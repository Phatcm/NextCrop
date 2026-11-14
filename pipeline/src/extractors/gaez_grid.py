"""FAO GAEZ v5 suitability on a nationwide grid (DATA-04).

The per-region extractor (gaez.py) only covers the 6 demo bboxes. This one reads the same files
(RES05-SXX30AS, ~0.9 km) for ALL of Vietnam and averages them into square cells of `cell_deg`
degrees (default 0.1 deg ~ 11 km), so any clicked point has a suitability value for every crop and
input level. Each cell = mean of the valid ~0.9 km pixels inside it (nodata -9 excluded, never 0).

Only the bbox window of each file is read (HTTP range requests); the per-file result is a small
2-D grid cached in bronze/gaez/grid_<cell>/..., so the run can be replayed offline.
"""
from __future__ import annotations

import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.extractors.gaez import DEFAULT_NODATA, file_url
from src.geotiff import GeoTiff

NO_DATA = -1   # marker in the cached grid: the cell has no valid pixel (sea, nodata)


def cache_path(gcfg: dict, grid_cfg: dict, bronze_dir: Path, crop: str, mode: str) -> Path:
    cell = f"{grid_cfg['cell_deg']:g}"
    return (bronze_dir / f"grid_{cell}deg" / f"{gcfg['period']}.{gcfg['climate']}.{gcfg['ssp']}" /
            f"{crop}_{mode}.json")


def block_means(arr, nodata: int, block: int):
    """Mean of valid pixels per block x block cell, rounded to int; NO_DATA where no valid pixel."""
    import numpy as np
    h, w = arr.shape
    if h % block or w % block:
        raise ValueError(f"window {h}x{w} px is not a multiple of {block} px: bbox must align to cell_deg")
    a = arr.astype(np.int64)
    valid = (a != nodata) & (a >= 0)
    shape = (h // block, block, w // block, block)
    total = np.where(valid, a, 0).reshape(shape).sum(axis=(1, 3))
    count = valid.reshape(shape).sum(axis=(1, 3))
    return np.where(count > 0, np.rint(total / np.maximum(count, 1)), NO_DATA).astype(int)


def read_grid(url: str, grid_cfg: dict) -> dict:
    gt = GeoTiff(url)
    cell = float(grid_cfg["cell_deg"])
    block = round(cell / gt.dx)
    if abs(block * gt.dx - cell) > 1e-6:
        raise ValueError(f"cell_deg {cell} is not a whole number of {gt.dx:.6f} deg pixels")
    arr, bounds = gt.window_with_bounds(*grid_cfg["bbox"])
    nodata = gt.nodata if gt.nodata is not None else DEFAULT_NODATA
    return {"bounds": [round(b, 6) for b in bounds], "cell_deg": cell, "block_px": block,
            "shape": list(arr.shape), "nodata": nodata,
            "means": block_means(arr, nodata, block).tolist()}


def _fresh(entry: dict | None, grid_cfg: dict) -> bool:
    return bool(entry) and entry.get("cell_deg") == float(grid_cfg["cell_deg"]) and \
        entry.get("request_bbox") == [round(float(v), 6) for v in grid_cfg["bbox"]]


def fetch_grids(gcfg: dict, grid_cfg: dict, bronze_dir: Path, *, offline: bool = False,
                workers: int = 4, local_dir: Path | None = None, log=print) -> tuple[dict, list[str]]:
    """{(crop, mode): cached_grid}. Missing grids are read from the bucket and cached.

    local_dir: folder with already downloaded GAEZ GeoTIFFs (same file names, covering the bbox).
    Used instead of the network when the file is there: ~0.1 s per file instead of ~2 min."""
    jobs = [(c["code"], m) for c in gcfg["crops"] for m in gcfg["modes"]]

    def one(job):
        crop, mode = job
        path = cache_path(gcfg, grid_cfg, bronze_dir, crop, mode)
        entry = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if not _fresh(entry, grid_cfg):
            url = file_url(gcfg, crop, mode)
            local = local_dir / url.rsplit("/", 1)[-1] if local_dir else None
            local = local if local and local.exists() else None
            if offline and not local:                      # a local file needs no network, so it is allowed offline
                return job, None, f"{crop}/{mode}: not cached (offline)"
            try:
                entry = read_grid(str(local) if local else url, grid_cfg)
                entry.update({"source": "FAO GAEZ v5 RES05-SXX30AS", "url": url,
                              "request_bbox": [round(float(v), 6) for v in grid_cfg["bbox"]],
                              "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".part")
                tmp.write_text(json.dumps(entry, separators=(",", ":")), encoding="utf-8")
                tmp.replace(path)
            except (OSError, ValueError, KeyError) as e:
                return job, None, f"{crop}/{mode}: {type(e).__name__}: {str(e)[:160]}"
        return job, entry, None

    grids, problems = {}, []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for job, entry, err in pool.map(one, jobs):
            if entry:
                grids[job] = entry
            if err:
                problems.append(err)
    log(f"  [gaez-grid] {len(jobs)} crop x mode files processed, {len(problems)} failed")
    return grids, problems


def build_rows(gcfg: dict, grids: dict) -> list[dict]:
    """Wide rows {lat, lon, crop_code, hilm, hrlm, lilm, lrlm}: one per cell x crop that has at least
    one valid mode. A mode without data is empty (NULL), never 0."""
    cells: dict[tuple[float, float, str], dict] = {}
    for (crop, mode), g in sorted(grids.items()):
        x0, _y0, _x1, y1 = g["bounds"]
        step = g["cell_deg"]
        for i, row in enumerate(g["means"]):
            lat = round(y1 - (i + 0.5) * step, 4)
            for j, v in enumerate(row):
                if v == NO_DATA:
                    continue
                lon = round(x0 + (j + 0.5) * step, 4)
                cells.setdefault((lat, lon, crop), {})[mode.lower()] = v
    modes = [m.lower() for m in gcfg["modes"]]
    return [{"lat": lat, "lon": lon, "crop_code": crop, **{m: vals.get(m) for m in modes}}
            for (lat, lon, crop), vals in sorted(cells.items(), key=lambda kv: (-kv[0][0], kv[0][1], kv[0][2]))]
