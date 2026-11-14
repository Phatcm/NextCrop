"""CHIRPS v3 monthly rainfall (UCSB Climate Hazards Center), read by HTTP range windows.

Why: NASA POWER rain (MERRA-2 model, ~0.5 deg) is wrong by a large factor in some regions (DATA-06/07):
Ninh Thuan ~2,000 mm/yr against ~800-900 mm for gauge-based data, Dak Lak 2015 = 423 mm against ~1,650 mm.
CHIRPS blends 0.05 deg satellite estimates with rain-gauge records, so it follows rain shadows.
Each global monthly GeoTIFF is ~21 MB; src.geotiff reads only the tile around the region, so a
region x 132 months costs a few MB. Series are cached per region in bronze/chirps.
Open data (CC0). Citation: Funk et al. 2015, Scientific Data 2:150066 (CHIRPS v2); v3 at data.chc.ucsb.edu.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.geotiff import GeoTiff
from src.models import Region

DEFAULT_URL = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/monthly/global/tifs/chirps-v3.0.{year}.{month:02d}.tif"


def month_url(cfg: dict, year: int, month: int) -> str:
    return cfg.get("url", DEFAULT_URL).format(year=year, month=month)


def window_mean(values, nodata) -> float | None:
    """Mean of the valid cells (CHIRPS marks nodata as -9999; rain is never negative)."""
    cells = [float(v) for row in values for v in row
             if v is not None and v >= 0 and (nodata is None or v != nodata)]
    return round(sum(cells) / len(cells), 1) if cells else None


def _one(cfg: dict, region: Region, year: int, month: int) -> float | None:
    gt = GeoTiff(month_url(cfg, year, month))
    lat, lon = region.center
    h = float(cfg.get("half_window_deg", 0.075))
    return window_mean(gt.window(lon - h, lat - h, lon + h, lat + h), gt.nodata)


def cache_path(cache_dir: Path, region: Region, start: int, end: int) -> Path:
    return cache_dir / f"chirps_v3_{region.id}_{start}-{end}.json"


def fetch_monthly(cfg: dict, region: Region, start: int, end: int, cache_dir: Path, *,
                  offline: bool = False, workers: int = 4) -> tuple[dict[str, float], list[str]]:
    """({YYYY-MM: mm/month}, problems). Months that cannot be read are left out (a gap is not 0)."""
    path = cache_path(cache_dir, region, start, end)
    if path.exists() and path.stat().st_size > 0:
        return json.loads(path.read_text(encoding="utf-8")), []
    if offline:
        return {}, [f"chirps {region.id}: offline mode and no cache at {path.name}"]
    keys = [(y, m) for y in range(start, end + 1) for m in range(1, 13)]
    out: dict[str, float] = {}
    problems: list[str] = []

    def job(ym):
        try:
            return ym, _one(cfg, region, *ym), None
        except Exception as e:  # network / HTTP / decode: report, never fabricate
            return ym, None, f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for (y, m), v, err in ex.map(job, keys):
            if v is not None:
                out[f"{y}-{m:02d}"] = v
            else:
                problems.append(f"chirps {region.id} {y}-{m:02d}: {err or 'no valid cell'}")
    if not problems:  # cache only a complete series, so a re-run retries the gaps
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, sort_keys=True), encoding="utf-8")
    return out, problems
