"""FAOSTAT producer prices (dataset PP) and crop yields (dataset QCL) for Viet Nam, from the public bulk files.

The API (fenixservices.fao.org) was down on 14/11/2026 (HTTP 521); the bulk zips are not: ~12 MB (prices) and
~34 MB (production). Only the Viet Nam rows are kept in bronze/faostat as small JSON files, with the source URL
and the HTTP Last-Modified of the zip, so the numbers can be traced and `--offline` works.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import urllib.request
import zipfile
from pathlib import Path

from src.http_client import USER_AGENT, HttpError

AREA = "Viet Nam"
PRICE_ELEMENTS = {"Producer Price (USD/tonne)": "usd_per_t", "Producer Price (LCU/tonne)": "lcu_per_t"}
YIELD_ELEMENT = "Yield"            # kg/ha


def _download(url: str, timeout: float) -> tuple[bytes, str | None]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), r.headers.get("Last-Modified")
    except Exception as e:
        raise HttpError(f"{type(e).__name__} for {url}: {e}") from e


def filter_zip(zip_bytes: bytes, kind: str, first_year: int) -> dict:
    """{item_code: {"item": name, "values": {metric: {year: value}}}} for Viet Nam rows of the normalized CSV."""
    out: dict[str, dict] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        name = next(n for n in z.namelist() if n.endswith("(Normalized).csv"))
        with z.open(name) as f:
            for r in csv.DictReader(io.TextIOWrapper(f, encoding="latin-1")):
                if r["Area"] != AREA or not r["Value"] or int(r["Year"]) < first_year:
                    continue
                metric = PRICE_ELEMENTS.get(r["Element"]) if kind == "price" else (
                    "yield_kg_ha" if r["Element"] == YIELD_ELEMENT else None)
                if metric is None:
                    continue
                item = out.setdefault(r["Item Code"], {"item": r["Item"], "values": {}})
                item["values"].setdefault(metric, {})[r["Year"]] = float(r["Value"])
    return out


def fetch_vn(cfg: dict, cache_dir: Path, *, offline: bool = False, log=print) -> tuple[dict | None, dict | None]:
    """(prices, yields), each {"source": {...}, "items": {...}} or None when neither cached nor reachable."""
    first = int(cfg.get("first_year", 2015))
    out = []
    for kind, key in (("price", "prices_zip_url"), ("yield", "production_zip_url")):
        path = cache_dir / f"faostat_vn_{kind}.json"
        if path.exists() and path.stat().st_size > 0:
            out.append(json.loads(path.read_text(encoding="utf-8")))
            continue
        if offline:
            log(f"  [faostat] offline: no cache at {path.name}")
            out.append(None)
            continue
        try:
            raw, modified = _download(cfg[key], cfg.get("timeout_s", 300))
            payload = {"source": {"url": cfg[key], "last_modified": modified,
                                  "retrieved": dt.date.today().isoformat(), "area": AREA},
                       "items": filter_zip(raw, kind, first)}
        except (HttpError, StopIteration, zipfile.BadZipFile, KeyError, ValueError) as e:
            log(f"  [faostat] {kind}: {e}")
            out.append(None)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        out.append(payload)
    return out[0], out[1]
