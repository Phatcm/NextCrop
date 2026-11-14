"""FAO GAEZ v5 crop suitability for the demo regions (continuous index 0-10000, int16, nodata -9).

The layer is chosen by `gaez.layer` in config.yaml:
- RES05-SUX (current): average suitability index of CURRENT CROPLAND, 5 arc-minute cells (~9 km), the better part of
  the cell in proportion to its cropland share. Same layer as the nationwide gaez_grid, so the two tables agree.
  A 0.1 deg region bbox covers only 2-3 cells per side, so n_px is small (4-9).
- RES05-SXX30AS (default when `layer` is absent): average of the TOTAL cell, ~0.9 km pixels, so n_px is 144.
  It includes forest and steep land and understates hilly regions (Son La maize 282-1185 against 1728-2485).

Public Google Cloud Storage bucket, one global GeoTIFF (~150 MB) per crop x input level. We never
download whole files: each file is read with HTTP range requests, only the pixels that cover each
region's bbox (a few KB). The raw pixel windows are stored in bronze so the run can be replayed offline.

Notes from docs/gaez-notes.md that shape the code:
- the index is potential suitability averaged over 20 years, not a yearly value;
- neighbouring pixels can jump a lot, so we summarize the whole bbox window (mean/median), not one pixel;
- several crops can share a value at one point: never identify a crop by its number.
"""
from __future__ import annotations

import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.geotiff import GeoTiff
from src.models import Region

BUCKET_URL = "https://storage.googleapis.com/fao-gismgr-gaez-v5-data/DATA/GAEZ-V5/MAPSET"
DEFAULT_LAYER = "RES05-SXX30AS"
BASE_URL = f"{BUCKET_URL}/{DEFAULT_LAYER}"
DEFAULT_NODATA = -9
LAYER_LABEL = {"RES05-SUX": "đất canh tác, phần tốt nhất của ô 5 phút cung (~9 km)",
               "RES05-SXX30AS": "trung bình cả ô, pixel ~0,9 km"}


def layer_of(cfg: dict) -> str:
    return cfg.get("layer", DEFAULT_LAYER)


def file_name(period: str, climate: str, ssp: str, crop: str, mode: str, layer: str = DEFAULT_LAYER) -> str:
    return f"GAEZ-V5.{layer}.{period}.{climate}.{ssp}.{crop}.{mode}.tif"


def file_url(cfg: dict, crop: str, mode: str) -> str:
    layer = layer_of(cfg)
    return f"{cfg.get('base_url', f'{BUCKET_URL}/{layer}').rstrip('/')}/" + file_name(
        cfg["period"], cfg["climate"], cfg["ssp"], crop, mode, layer)


def _cache_path(cfg: dict, bronze_dir: Path, crop: str, mode: str) -> Path:
    """Legacy layer keeps its old folder; any other layer gets its own, so two layers never share a cache."""
    root = bronze_dir if layer_of(cfg) == DEFAULT_LAYER else bronze_dir / layer_of(cfg)
    return root / f"{cfg['period']}.{cfg['climate']}.{cfg['ssp']}" / f"{crop}_{mode}.json"


def _fresh(entry: dict | None, region: Region) -> bool:
    return bool(entry) and [round(v, 6) for v in entry["bbox"]] == [round(v, 6) for v in region.bbox]


def _read_windows(url: str, regions: list[Region]) -> dict[str, dict]:
    gt = GeoTiff(url)
    out = {}
    for r in regions:
        arr, bounds = gt.window_with_bounds(*r.bbox)
        out[r.id] = {"bbox": list(r.bbox), "bounds": list(bounds), "shape": list(arr.shape),
                     "nodata": gt.nodata if gt.nodata is not None else DEFAULT_NODATA,
                     "values": arr.astype(int).tolist()}
    return out


def fetch_windows(cfg: dict, regions: list[Region], bronze_dir: Path, *, offline: bool = False,
                  workers: int = 4, log=print) -> tuple[dict, list[str]]:
    """Return ({(crop, mode): {region_id: window}}, problems). Missing windows are fetched and cached."""
    jobs = [(c["code"], m) for c in cfg["crops"] for m in cfg["modes"]]

    def one(job):
        crop, mode = job
        path = _cache_path(cfg, bronze_dir, crop, mode)
        cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"windows": {}}
        need = [r for r in regions if not _fresh(cache["windows"].get(r.id), r)]
        if need and not offline:
            try:
                url = file_url(cfg, crop, mode)
                cache.update({"source": f"FAO GAEZ v5 {layer_of(cfg)}", "url": url})
                cache["windows"].update(_read_windows(url, need))
                cache["fetched_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".part")
                tmp.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
                tmp.replace(path)
            except (OSError, ValueError, KeyError) as e:
                return job, cache, f"{crop}/{mode}: {type(e).__name__}: {str(e)[:160]}"
        return job, cache, None

    results, problems = {}, []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for job, cache, err in pool.map(one, jobs):
            results[job] = cache["windows"]
            if err:
                problems.append(err)
    log(f"  [gaez] {len(jobs)} crop x mode files processed, {len(problems)} failed")
    return results, problems


def window_stats(win: dict, region: Region) -> dict:
    """Summary of one cached window. Nodata (-9) pixels are excluded, never counted as 0."""
    nodata = win.get("nodata", DEFAULT_NODATA)
    flat = [v for row in win["values"] for v in row]
    valid = sorted(v for v in flat if v != nodata and v >= 0)
    h, w = win["shape"]
    x0, y0, x1, y1 = win["bounds"]
    center = None
    if h and w:
        lat, lon = region.center
        c = min(w - 1, max(0, int((lon - x0) / ((x1 - x0) / w))))
        r = min(h - 1, max(0, int((y1 - lat) / ((y1 - y0) / h))))
        v = win["values"][r][c]
        center = None if (v == nodata or v < 0) else v
    n = len(valid)
    return {
        "n_px": len(flat), "n_valid": n,
        "value_mean": round(sum(valid) / n, 1) if n else None,
        "value_median": (valid[n // 2] if n % 2 else (valid[n // 2 - 1] + valid[n // 2]) / 2) if n else None,
        "value_min": valid[0] if n else None, "value_max": valid[-1] if n else None,
        "value_center": center,
    }


def build_rows(cfg: dict, regions: list[Region], windows: dict) -> list[dict]:
    rows = []
    for r in regions:
        for c in cfg["crops"]:
            for m in cfg["modes"]:
                win = windows.get((c["code"], m), {}).get(r.id)
                if not win:
                    continue
                rows.append({"region_id": r.id, "crop_code": c["code"], "input_mode": m,
                             "period": cfg["period"], "climate": cfg["climate"], "ssp": cfg["ssp"],
                             **window_stats(win, r)})
    return rows


def crop_dim_rows(cfg: dict) -> list[dict]:
    return [{"crop_code": c["code"], "name_vi": c["name_vi"],
             "name_verified": bool(c.get("name_verified", True))} for c in cfg["crops"]]


def gold_block(cfg: dict, rows: list[dict]) -> dict | None:
    """suitability block for a region's gold JSON; values[crop][mode] = window mean (0-10000)."""
    if not rows:
        return None
    values: dict[str, dict] = {}
    detail: dict[str, dict] = {}
    for r in rows:
        values.setdefault(r["crop_code"], {})[r["input_mode"]] = r["value_mean"]
        detail.setdefault(r["crop_code"], {})[r["input_mode"]] = {
            k: r[k] for k in ("value_median", "value_min", "value_max", "value_center", "n_valid", "n_px")}
    return {
        "source": f"FAO GAEZ v5 {layer_of(cfg)}, {cfg['period']} ({cfg['climate']}, {cfg['ssp']})",
        "layer": layer_of(cfg), "layer_note": LAYER_LABEL.get(layer_of(cfg)),
        "note": "0-10000, cao = hợp hơn; trung bình các ô/pixel phủ vùng bbox; mức đầu vào ảnh hưởng rất mạnh; "
                "là tiềm năng trung bình 20 năm, không phải từng năm",
        "modes": {"HILM": "tưới + đầu vào cao", "HRLM": "mưa + đầu vào cao",
                  "LILM": "tưới + đầu vào thấp", "LRLM": "mưa + đầu vào thấp"},
        "values": values, "detail": detail,
    }
