"""Crop profile (DATA-01, part 2): verified family, Viet Nam price and yield, erosion protection class.

Inputs
- pipeline/crop_profile_map.csv (hand-maintained, committed): scientific name, which FAOSTAT item stands for the crop
  (direct / proxy / none) and the erosion protection class with the basis for it.
- GBIF match API: the botanical family, with the GBIF key so it can be looked up.
- FAOSTAT bulk files: Viet Nam producer price (USD/tonne) and yield (kg/ha), national averages.

Rules
- A value without a source stays empty: no Viet Nam item means no price, never an estimate.
- Gross revenue = mean price x mean yield over the years where BOTH exist inside the window (>= min_years). It is
  revenue per hectare per harvest (annual crops) or per year (perennials), NOT profit: costs are not in the data.
- FAOSTAT values are national averages. They say nothing about a given province.
"""
from __future__ import annotations

import csv
from pathlib import Path

MATCHES = ("direct", "proxy", "none")
PROTECTION = ("high", "medium", "low")
CONFIDENCE = ("documented_secondary", "assumed")
MAP_COLUMNS = ["crop_code", "scientific_name", "faostat_item_code", "faostat_match", "erosion_protection",
               "cover_confidence", "cover_basis"]


def load_map(path: Path, known_crops: set[str] | None = None) -> dict[str, dict]:
    """{crop_code: row}. Raises ValueError on a malformed row (bad enum, duplicate, unknown crop, shifted cells)."""
    out: dict[str, dict] = {}
    with open(path, encoding="utf-8", newline="") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            code = (row.get("crop_code") or "").strip()
            where = f"{path.name} line {n} ({code or '?'})"
            if None in row or None in row.values():
                raise ValueError(f"{where}: wrong number of cells (quote text that contains a comma)")
            if not code or code in out:
                raise ValueError(f"{where}: empty or duplicate crop_code")
            if known_crops is not None and code not in known_crops:
                raise ValueError(f"{where}: crop_code is not in dim_crop")
            for col, allowed in (("faostat_match", MATCHES), ("erosion_protection", PROTECTION),
                                 ("cover_confidence", CONFIDENCE)):
                if (row.get(col) or "").strip() not in allowed:
                    raise ValueError(f"{where}: {col} must be one of {allowed}, got {row.get(col)!r}")
            item = (row.get("faostat_item_code") or "").strip()
            if (row["faostat_match"] == "none") != (item == ""):
                raise ValueError(f"{where}: faostat_item_code must be empty exactly when faostat_match is none")
            if not (row.get("scientific_name") or "").strip() or not (row.get("cover_basis") or "").strip():
                raise ValueError(f"{where}: scientific_name and cover_basis are required")
            out[code] = {k: (row[k] or "").strip() for k in MAP_COLUMNS}
    return out


def economics(prices: dict | None, yields: dict | None, item_code: str, first: int, last: int,
              min_years: int) -> dict | None:
    """{price_usd_per_t, yield_kg_ha, years, gross_revenue_usd_ha, item} or None when there is not enough data."""
    if not prices or not yields or not item_code:
        return None
    p = (prices["items"].get(item_code) or {}).get("values", {}).get("usd_per_t", {})
    y = (yields["items"].get(item_code) or {}).get("values", {}).get("yield_kg_ha", {})
    years = sorted(int(k) for k in set(p) & set(y) if first <= int(k) <= last)
    if len(years) < min_years:
        return None
    mp = sum(p[str(k)] for k in years) / len(years)
    my = sum(y[str(k)] for k in years) / len(years)
    return {"item": prices["items"][item_code]["item"], "price_usd_per_t": round(mp, 1), "yield_kg_ha": round(my),
            "year_from": years[0], "year_to": years[-1], "n_years": len(years),
            "gross_revenue_usd_ha": round(mp * my / 1000)}


def build_rows(cmap: dict[str, dict], gbif: dict[str, dict | None], prices: dict | None, yields: dict | None,
               traits_family: dict[str, str | None], cfg: dict | None = None) -> list[dict]:
    cfg = cfg or {}
    first, last = cfg.get("econ_years", [2020, 2024])
    min_years = int(cfg.get("min_years", 3))
    rows = []
    for code, m in sorted(cmap.items()):
        g = gbif.get(m["scientific_name"])
        fam = traits_family.get(code)
        if g is None:
            check = "unverified"
        else:
            check = "match" if fam == g["family"] else "mismatch"
        e = economics(prices, yields, m["faostat_item_code"], first, last, min_years)
        rows.append({
            "crop_code": code, "scientific_name": m["scientific_name"],
            "gbif_usage_key": g["usage_key"] if g else None, "gbif_family": g["family"] if g else None,
            "family_check": check,
            "faostat_item_code": int(m["faostat_item_code"]) if m["faostat_item_code"] else None,
            "faostat_item": e["item"] if e else None, "faostat_match": m["faostat_match"],
            "price_usd_per_t": e["price_usd_per_t"] if e else None,
            "yield_kg_ha": e["yield_kg_ha"] if e else None,
            "econ_year_from": e["year_from"] if e else None, "econ_year_to": e["year_to"] if e else None,
            "gross_revenue_usd_ha": e["gross_revenue_usd_ha"] if e else None,
            "erosion_protection": m["erosion_protection"], "cover_confidence": m["cover_confidence"],
            "cover_basis": m["cover_basis"],
        })
    return rows
