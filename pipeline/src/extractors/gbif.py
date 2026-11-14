"""Botanical family of each crop from the GBIF Backbone Taxonomy (species match API, no key).

Used to give the family column of crop_traits.csv a citable source (DATA-01). Each answer is cached in
bronze/gbif so `run_etl.py --offline` reproduces the same rows.
"""
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

from src.http_client import HttpError, fetch_cached

URL = "https://api.gbif.org/v1/species/match"


def match_url(name: str) -> str:
    return f"{URL}?{urllib.parse.urlencode({'kingdom': 'Plantae', 'name': name})}"


def parse(payload: dict) -> dict | None:
    """{"family", "usage_key", "status", "match_type", "confidence"} or None when GBIF did not find the name."""
    if not payload.get("family") or payload.get("matchType") == "NONE":
        return None
    return {"family": payload["family"], "usage_key": payload.get("usageKey"), "status": payload.get("status"),
            "match_type": payload.get("matchType"), "confidence": payload.get("confidence")}


def fetch_family(name: str, cache_dir: Path, *, offline: bool = False) -> dict | None:
    path = cache_dir / ("gbif_match_" + name.lower().replace(" ", "_") + ".json")
    try:
        raw = fetch_cached(match_url(name), path, offline=offline, timeout=30, retries=3)
        return parse(json.loads(raw.decode("utf-8")))
    except (HttpError, ValueError):
        return None
