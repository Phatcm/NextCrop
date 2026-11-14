"""ERA5 daily precipitation (Copernicus/ECMWF reanalysis) via the Open-Meteo archive API, no key.

Used ONLY as an independent reference to judge suspicious NASA POWER rain days (see
transformers/rain_qa.py). It is never stored as product data. Each region's series is cached in
bronze/era5, so `run_etl.py --offline` reproduces the same decisions.
Open-Meteo serves ERA5 under CC BY 4.0 (attribution required, free tier is non-commercial).
"""
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

from src.http_client import HttpError, fetch_cached


def build_url(cfg: dict, lat: float, lon: float, start_year: int, end_year: int) -> str:
    q = {"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}",
         "start_date": f"{start_year}-01-01", "end_date": f"{end_year}-12-31",
         "daily": "precipitation_sum", "timezone": cfg.get("timezone", "Asia/Bangkok")}
    return f"{cfg['url']}?{urllib.parse.urlencode(q)}"


def parse(payload: dict) -> dict[str, float]:
    """{YYYY-MM-DD: mm}; null days are left out (a gap is not 0)."""
    d = payload["daily"]
    return {t: float(v) for t, v in zip(d["time"], d["precipitation_sum"]) if v is not None}


def fetch_daily(cfg: dict, lat: float, lon: float, start_year: int, end_year: int,
                cache_dir: Path, offline: bool = False) -> dict[str, float] | None:
    """Daily ERA5 rain at (lat, lon), or None when it is neither cached nor reachable
    (the caller then falls back to the fixed limit)."""
    path = cache_dir / f"era5_openmeteo_{lat:.4f}_{lon:.4f}_{start_year}-{end_year}.json"
    try:
        raw = fetch_cached(build_url(cfg, lat, lon, start_year, end_year), path, offline=offline,
                           timeout=cfg.get("timeout_s", 60), retries=cfg.get("retries", 3))
        return parse(json.loads(raw.decode("utf-8")))
    except (HttpError, KeyError, ValueError):
        return None
