"""NASA POWER API (no key needed): multi-year point series + Vietnam-wide monthly grid."""
from __future__ import annotations

import hashlib
import json
import urllib.parse
from pathlib import Path

from src.http_client import fetch_cached


def build_url(base_url: str, kind: str, lat: float, lon: float, start: str, end: str,
              parameters: list[str], community: str = "AG",
              time_standard: str | None = None) -> str:
    q = {
        "parameters": ",".join(parameters),
        "community": community,
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "start": start,
        "end": end,
        "format": "JSON",
    }
    if kind == "daily" and time_standard:
        q["time-standard"] = time_standard
    return f"{base_url.rstrip('/')}/{kind}/point?{urllib.parse.urlencode(q)}"


def build_regional_url(base_url: str, bbox: list[float], parameter: str, start_year: int,
                       end_year: int, community: str = "AG") -> str:
    lon_min, lat_min, lon_max, lat_max = bbox
    q = {
        "parameters": parameter, "community": community,
        "latitude-min": lat_min, "latitude-max": lat_max,
        "longitude-min": lon_min, "longitude-max": lon_max,
        "start": start_year, "end": end_year, "format": "JSON",
    }
    return f"{base_url.rstrip('/')}/monthly/regional?{urllib.parse.urlencode(q)}"


def _clean(v, fill):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f == fill or f <= -999 else f


def parse_response(payload: dict, kind: str) -> dict:
    """Return {"units": {...}, "rows": [...], "annual": {year: {...}}}.

    Fill values (-999) become None: a data gap is never treated as 0.
    Monthly key YYYY13 is the annual aggregate and goes to "annual".
    """
    params = payload["properties"]["parameter"]
    fill = payload.get("header", {}).get("fill_value", -999.0)
    meta = payload.get("parameters", {})
    units = {k: meta.get(k, {}).get("units") for k in params}
    keys = sorted({k for series in params.values() for k in series})
    rows: list[dict] = []
    annual: dict[str, dict] = {}
    for key in keys:
        values = {p: _clean(params[p].get(key), fill) for p in params}
        if kind == "daily":
            rows.append({"date": f"{key[:4]}-{key[4:6]}-{key[6:8]}", **values})
        elif key[4:6] == "13":
            annual[key[:4]] = values
        else:
            rows.append({"month": f"{key[:4]}-{key[4:6]}", **values})
    return {"units": units, "rows": rows, "annual": annual}


def parse_regional(payload: dict) -> tuple[dict, dict, dict]:
    """Return ({(lat, lon): {"elev": m, "values": {YYYYMM: v}}}, units, header) for one parameter."""
    fill = payload.get("header", {}).get("fill_value", -999.0)
    cells: dict[tuple[float, float], dict] = {}
    for f in payload["features"]:
        lon, lat, *rest = f["geometry"]["coordinates"]
        (param, series), = f["properties"]["parameter"].items()
        cells[(round(lat, 4), round(lon, 4))] = {
            "elev": rest[0] if rest else None,
            "param": param,
            "values": {k: _clean(v, fill) for k, v in series.items()},
        }
    units = {k: v.get("units") for k, v in payload.get("parameters", {}).items()}
    return cells, units, payload.get("header", {})


def fetch_power(cfg: dict, lat: float, lon: float, start_year: int, end_year: int,
                cache_dir: Path, offline: bool = False) -> dict:
    """Daily + monthly series for start_year..end_year in one request each."""
    out = {}
    for kind, start, end in (("daily", f"{start_year}0101", f"{end_year}1231"),
                             ("monthly", str(start_year), str(end_year))):
        url = build_url(cfg["base_url"], kind, lat, lon, start, end, cfg["parameters"],
                        cfg.get("community", "AG"), cfg.get("time_standard"))
        # stable across runs (built-in hash() of str is randomized per process)
        tag = hashlib.sha1(",".join(sorted(cfg["parameters"])).encode()).hexdigest()[:8]
        path = cache_dir / f"{kind}_{start_year}-{end_year}_{lat:.4f}_{lon:.4f}_{tag}.json"
        raw = fetch_cached(url, path, offline=offline, timeout=cfg.get("timeout_s", 180),
                           retries=cfg.get("retries", 3))
        out[kind] = parse_response(json.loads(raw.decode("utf-8")), kind)
        out[kind]["url"] = url
    return out


def fetch_vn_grid(power_cfg: dict, grid_cfg: dict, start_year: int, end_year: int,
                  cache_dir: Path, offline: bool = False, log=print) -> dict:
    """Merge regional responses into {(lat, lon): {"elev", "params": {P: {YYYYMM: v}}}}."""
    cells: dict[tuple[float, float], dict] = {}
    units: dict = {}
    for b, bbox in enumerate(grid_cfg["boxes"]):
        for p in grid_cfg["parameters"]:
            url = build_regional_url(power_cfg["base_url"], bbox, p, start_year, end_year,
                                     power_cfg.get("community", "AG"))
            path = cache_dir / f"regional_{p}_{start_year}-{end_year}_box{b}_{'_'.join(map(str, bbox))}.json"
            raw = fetch_cached(url, path, offline=offline, timeout=power_cfg.get("timeout_s", 180),
                               retries=power_cfg.get("retries", 3))
            got, u, _h = parse_regional(json.loads(raw.decode("utf-8")))
            units.update(u)
            for key, c in got.items():
                cell = cells.setdefault(key, {"elev": c["elev"], "params": {}})
                cell["params"][p] = c["values"]
            log(f"  [grid] {p} box{b}: {len(got)} cells")
    return {"cells": cells, "units": units}
