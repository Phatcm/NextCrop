"""Viet Nam national boundary (DATA-14), from geoBoundaries gbOpen ADM0 (CC BY 4.0, generalised polygon).

Why it exists: gaez_grid is the rectangle 102-110E, 8-24N, so it also holds Laos, Cambodia and southern China.
The generalised polygon is accurate to roughly a kilometre, far below the ~9 km grid cell, so it is enough to say
how much of a cell is inside Viet Nam. The raw GeoJSON is cached in bronze/boundary so `--offline` reproduces it.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.http_client import fetch_cached

URL = "https://github.com/wmgeolab/geoBoundaries/raw/main/releaseData/gbOpen/VNM/ADM0/geoBoundaries-VNM-ADM0_simplified.geojson"
ATTRIBUTION = "geoBoundaries gbOpen VNM ADM0 (Runfola et al. 2020, CC BY 4.0)"


def fetch(cfg: dict, cache_dir: Path, *, offline: bool = False) -> dict:
    """The boundary as a GeoJSON dict. Raises HttpError when it is neither cached nor reachable."""
    url = cfg.get("url", URL)
    path = cache_dir / url.rsplit("/", 1)[-1]
    return json.loads(fetch_cached(url, path, offline=offline, timeout=60, retries=3).decode("utf-8"))
