"""FAO GAEZ v5 slope, soil quality and crop water deficit over the whole nationwide grid box (DATA-17).

Same layers as `gaez_env.py` (which reads only a window around each demo region) but the full 102-110E, 8-24N box, so
any clicked point has the same five inputs as the demo regions. Each layer is read once and cached as a compressed
array in bronze/gaez_env_grid, so `--offline` reproduces the same rows. 30 arc-second layers (slope, soil) are 1920 x 960
pixels, 5 arc-minute layers (water deficit) are 192 x 96: exactly 10 x 10 pixels per 5 arc-minute grid cell.
"""
from __future__ import annotations

import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from src.extractors import gaez_env as ge
from src.geotiff import GeoTiff


def jobs(cfg: dict) -> list[tuple[str, str, str]]:
    """[(group, key, url)] for slope (all classes), the configured soil factors and the water-deficit layers."""
    out = [("slope", c, ge.slope_url(c)) for c in ge.SLOPE_CLASSES]
    out += [("soil", f"{f}.{lv}", ge.soil_url(f, lv)) for f in cfg["soil_factors"] for lv in ge.SOIL_LEVELS]
    w = cfg["water_deficit"]
    out += [("wdc", f"{c}.{m}", ge.wdc_url(w, c, m)) for c in w["crops"] for m in w["modes"]]
    return out


def _paths(bronze_dir: Path, group: str, key: str) -> tuple[Path, Path]:
    return bronze_dir / f"{group}__{key}.npz", bronze_dir / f"{group}__{key}.json"


def load_layer(bronze_dir: Path, group: str, key: str) -> tuple[np.ndarray, dict] | None:
    npz, meta = _paths(bronze_dir, group, key)
    if not (npz.exists() and meta.exists()):
        return None
    with np.load(npz) as z:
        return z["values"], json.loads(meta.read_text(encoding="utf-8"))


def _read_one(job, bbox, bronze_dir: Path):
    group, key, url = job
    gt = GeoTiff(url)
    arr, bounds = gt.window_with_bounds(*bbox)
    npz, meta = _paths(bronze_dir, group, key)
    npz.parent.mkdir(parents=True, exist_ok=True)
    tmp = npz.with_name(npz.stem + ".part.npz")
    np.savez_compressed(tmp, values=arr)
    tmp.replace(npz)
    meta.write_text(json.dumps({
        "url": url, "source": "FAO GAEZ v5", "bbox": list(bbox), "bounds": list(bounds), "shape": list(arr.shape),
        "nodata": None if gt.nodata is None else float(gt.nodata),
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}), encoding="utf-8")


def fetch_layers(cfg: dict, bbox: list[float], bronze_dir: Path, *, offline: bool = False, workers: int = 4,
                 log=print) -> tuple[dict, list[str]]:
    """({(group, key): (array, meta)}, problems). A layer cached for another bbox is fetched again; offline never fetches."""
    todo = jobs(cfg)
    problems: list[str] = []

    def one(job):
        group, key, _u = job
        have = load_layer(bronze_dir, group, key)
        if have and [round(v, 6) for v in have[1]["bbox"]] == [round(v, 6) for v in bbox]:
            return job, have, None
        if offline:
            return job, None, f"{group}/{key}: offline and not cached"
        try:
            _read_one(job, bbox, bronze_dir)
            return job, load_layer(bronze_dir, group, key), None
        except (OSError, ValueError, KeyError) as e:
            return job, None, f"{group}/{key}: {type(e).__name__}: {str(e)[:160]}"

    out: dict = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for (group, key, _u), layer, err in pool.map(one, todo):
            if err:
                problems.append(err)
            elif layer:
                out[(group, key)] = layer
    log(f"  [gaez-grid-env] {len(todo)} layers, {len(out)} read, {len(problems)} problem(s)")
    return out, problems
