"""FAO GAEZ v5 suitability on a nationwide grid, current-cropland version (DATA-04).

Layer RES05-SUX: average suitability index of CURRENT CROPLAND for each 5 arc-minute cell (~9 km). Following the
GAEZ v5 documentation (Module V), the cropland maps assume farmers use the better part of the suitability
distribution of a cell, in proportion to the cropland share. It is read as delivered: no aggregation.

It replaces the earlier version, the total-cell average of RES05-SXX30AS aggregated into 0.1 deg cells. That one
includes forest and steep land, which pulls hilly cells far down (Son La maize 282-1185 instead of 1728-2485,
and 55% of the cells had no annual crop at 4000 or more against 9% now); flat deltas barely differ. The per-region
extractor (gaez.py) still uses RES05-SXX30AS for the 6 demo bboxes.

The SUX index can reach 10000 in good cells, so crops can tie at the top: do not read small differences there.
The per-file result is a small 2-D grid cached in bronze/gaez/grid_sux_5arcmin/..., so the run can be replayed
offline.
"""
from __future__ import annotations

import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.extractors.gaez import DEFAULT_NODATA
from src.geotiff import GeoTiff

LAYER = "RES05-SUX"
BASE_URL = f"https://storage.googleapis.com/fao-gismgr-gaez-v5-data/DATA/GAEZ-V5/MAPSET/{LAYER}"
NO_DATA = -1   # marker in the cached grid: the cell has no valid value (sea, nodata)


def file_name(gcfg: dict, crop: str, mode: str) -> str:
    return f"GAEZ-V5.{LAYER}.{gcfg['period']}.{gcfg['climate']}.{gcfg['ssp']}.{crop}.{mode}.tif"


def file_url(gcfg: dict, crop: str, mode: str) -> str:
    return f"{BASE_URL}/{file_name(gcfg, crop, mode)}"


def cache_path(gcfg: dict, grid_cfg: dict, bronze_dir: Path, crop: str, mode: str) -> Path:
    return (bronze_dir / "grid_sux_5arcmin" / f"{gcfg['period']}.{gcfg['climate']}.{gcfg['ssp']}" /
            f"{crop}_{mode}.json")


def clean(arr, nodata: int):
    """Integer grid with NO_DATA wherever the value is the file's nodata or negative. A real 0 stays 0
    (unsuitable), it is never confused with missing."""
    import numpy as np
    a = arr.astype(np.int64)
    return np.where((a == nodata) | (a < 0), NO_DATA, a).astype(int)


def read_grid(url: str, grid_cfg: dict) -> dict:
    gt = GeoTiff(url)
    arr, bounds = gt.window_with_bounds(*grid_cfg["bbox"])
    nodata = gt.nodata if gt.nodata is not None else DEFAULT_NODATA
    return {"layer": LAYER, "bounds": [round(b, 6) for b in bounds], "cell_deg": gt.dx,
            "shape": list(arr.shape), "nodata": nodata, "values": clean(arr, nodata).tolist()}


def _fresh(entry: dict | None, grid_cfg: dict) -> bool:
    return bool(entry) and entry.get("layer") == LAYER and \
        entry.get("request_bbox") == [round(float(v), 6) for v in grid_cfg["bbox"]]


def fetch_grids(gcfg: dict, grid_cfg: dict, bronze_dir: Path, *, offline: bool = False,
                workers: int = 4, local_dir: Path | None = None, log=print) -> tuple[dict, list[str]]:
    """{(crop, mode): cached_grid}. Missing grids are read from the bucket and cached.

    local_dir: folder with already downloaded RES05-SUX GeoTIFFs (same file names, covering the bbox).
    Used instead of the network when the file is there."""
    jobs = [(c["code"], m) for c in gcfg["crops"] for m in gcfg["modes"]]

    def one(job):
        crop, mode = job
        path = cache_path(gcfg, grid_cfg, bronze_dir, crop, mode)
        entry = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if not _fresh(entry, grid_cfg):
            url = file_url(gcfg, crop, mode)
            local = local_dir / file_name(gcfg, crop, mode) if local_dir else None
            local = local if local and local.exists() else None
            if offline and not local:                      # a local file needs no network, so it is allowed offline
                return job, None, f"{crop}/{mode}: not cached (offline)"
            try:
                entry = read_grid(str(local) if local else url, grid_cfg)
                entry.update({"source": f"FAO GAEZ v5 {LAYER} (average suitability index of current cropland)",
                              "url": url, "request_bbox": [round(float(v), 6) for v in grid_cfg["bbox"]],
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
    one valid mode. A mode without data is empty (NULL), never 0. lat/lon are cell centres (4 decimals)."""
    cells: dict[tuple[float, float, str], dict] = {}
    for (crop, mode), g in sorted(grids.items()):
        x0, _y0, _x1, y1 = g["bounds"]
        step = g["cell_deg"]
        for i, row in enumerate(g["values"]):
            lat = round(y1 - (i + 0.5) * step, 4)
            for j, v in enumerate(row):
                if v == NO_DATA:
                    continue
                lon = round(x0 + (j + 0.5) * step, 4)
                cells.setdefault((lat, lon, crop), {})[mode.lower()] = v
    modes = [m.lower() for m in gcfg["modes"]]
    return [{"lat": lat, "lon": lon, "crop_code": crop, **{m: vals.get(m) for m in modes}}
            for (lat, lon, crop), vals in sorted(cells.items(), key=lambda kv: (-kv[0][0], kv[0][1], kv[0][2]))]
