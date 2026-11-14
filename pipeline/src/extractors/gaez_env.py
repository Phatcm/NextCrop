"""FAO GAEZ v5 land-resource and water layers read as small windows around each region (DATA-03).

Same bucket and reader as `gaez.py`; three groups of layers, each cached in bronze/gaez_env:
- LR-SLC   share of land by slope class, 10 classes SC01..SC10, 30 arc-second (~1 km), derived from ALOS AW3D30.
           Raster value = percent x 100 of the cell area in that class (0-10000).
- SQX      soil quality ratings SQ0..SQ7 (HWSD-based, ~1 km) for high (HIM) and low (LIM) input management.
           Class 1-10 = rating 0.0-0.1 .. 0.9-1.0; 11 permafrost, 12 not evaluated, 13 water (not ratings).
- RES01-ET0 reference evapotranspiration, 20-year annual mean (mm), 5 arc-minute: the independent check of the ET0 that
           water.py computes from NASA POWER (see transformers/et0.py).
- RES05-WDC water deficit = net irrigation requirement during the crop cycle (mm) of CURRENT CROPLAND, 5 arc-minute,
           per crop and input level. 0 = no deficit modelled, -9 = no data.
Windows are tiny (a 0.1 deg box is 12 x 12 pixels at 30 arc-seconds), so no whole file is ever downloaded.
"""
from __future__ import annotations

import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.geotiff import GeoTiff
from src.models import Region

BUCKET = "https://storage.googleapis.com/fao-gismgr-gaez-v5-data/DATA/GAEZ-V5/MAPSET"
SLOPE_CLASSES = ["SC01", "SC02", "SC03", "SC04", "SC05", "SC06", "SC07", "SC08", "SC09", "SC10"]
# slope gradient classes (%) of LR-SLC, in the order SC01..SC10, and the class midpoint used for the mean slope
SLOPE_BOUNDS = [(0, 0.5), (0.5, 2), (2, 5), (5, 8), (8, 12), (12, 16), (16, 24), (24, 30), (30, 45), (45, None)]
SLOPE_MID = [0.25, 1.25, 3.5, 6.5, 10.0, 14.0, 20.0, 27.0, 37.5, 55.0]    # >45 % has no upper bound: 55 is an assumption
SOIL_FACTORS = {"SQ0": "Most limiting soil quality rating factor", "SQ1": "Nutrient availability",
                "SQ2": "Nutrient retention capacity", "SQ3": "Rooting conditions",
                "SQ4": "Oxygen availability to roots", "SQ5": "Presence of salinity and sodicity",
                "SQ6": "Presence of lime and gypsum", "SQ7": "Workability"}
SOIL_LEVELS = ["HIM", "LIM"]


def slope_url(cls: str) -> str:
    return f"{BUCKET}/LR-SLC/GAEZ-V5.LR-SLC.{cls}.tif"


def soil_url(factor: str, level: str) -> str:
    return f"{BUCKET}/SQX/GAEZ-V5.SQX.{factor}.{level}.tif"


def wdc_url(cfg: dict, crop: str, mode: str) -> str:
    return f"{BUCKET}/RES05-WDC/GAEZ-V5.RES05-WDC.{cfg['period']}.{cfg['climate']}.{cfg['ssp']}.{crop}.{mode}.tif"


def et0_url(cfg: dict) -> str:
    return f"{BUCKET}/RES01-ET0/GAEZ-V5.RES01-ET0.{cfg['period']}.{cfg['climate']}.{cfg['ssp']}.tif"


def jobs(cfg: dict) -> list[tuple[str, str, str]]:
    """[(group, key, url)] for everything configured: slope, soil, water-deficit windows."""
    out = [("slope", c, slope_url(c)) for c in SLOPE_CLASSES]
    out += [("soil", f"{f}.{lv}", soil_url(f, lv)) for f in SOIL_FACTORS for lv in SOIL_LEVELS]
    if cfg.get("et0_reference"):
        out.append(("et0", "annual", et0_url(cfg["et0_reference"])))
    w = cfg.get("water_deficit") or {}
    out += [("wdc", f"{c}.{m}", wdc_url(w, c, m)) for c in w.get("crops", []) for m in w.get("modes", [])]
    return out


def _cache_path(bronze_dir: Path, group: str, key: str) -> Path:
    return bronze_dir / group / f"{key}.json"


def _fresh(entry: dict | None, region: Region) -> bool:
    return bool(entry) and [round(v, 6) for v in entry["bbox"]] == [round(v, 6) for v in region.bbox]


def _read(url: str, regions: list[Region]) -> dict[str, dict]:
    gt = GeoTiff(url)
    out = {}
    for r in regions:
        arr, bounds = gt.window_with_bounds(*r.bbox)
        out[r.id] = {"bbox": list(r.bbox), "bounds": list(bounds), "shape": list(arr.shape),
                     "nodata": None if gt.nodata is None else float(gt.nodata),
                     "values": [[float(v) for v in row] for row in arr.tolist()]}
    return out


def fetch_windows(cfg: dict, regions: list[Region], bronze_dir: Path, *, offline: bool = False,
                  workers: int = 4, log=print) -> tuple[dict, list[str]]:
    """({(group, key): {region_id: window}}, problems). Missing windows are fetched and cached."""
    todo = jobs(cfg)

    def one(job):
        group, key, url = job
        path = _cache_path(bronze_dir, group, key)
        cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"windows": {}}
        need = [r for r in regions if not _fresh(cache["windows"].get(r.id), r)]
        if need and not offline:
            try:
                cache.update({"url": url, "source": "FAO GAEZ v5"})
                cache["windows"].update(_read(url, need))
                cache["fetched_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".part")
                tmp.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
                tmp.replace(path)
            except (OSError, ValueError, KeyError) as e:
                return job, cache, f"{group}/{key}: {type(e).__name__}: {str(e)[:160]}"
        elif need:
            return job, cache, f"{group}/{key}: offline and not cached for {', '.join(r.id for r in need)}"
        return job, cache, None

    results: dict = {}
    problems: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for (group, key, _u), cache, err in pool.map(one, todo):
            results[(group, key)] = cache["windows"]
            if err:
                problems.append(err)
    log(f"  [gaez-env] {len(todo)} windows processed, {len(problems)} problem(s)")
    return results, problems
