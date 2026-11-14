"""Crop traits for dim_crop (DATA-01), read from pipeline/crop_traits.csv.

The CSV is hand-maintained and committed: GAEZ v5 Appendix 4-6 (A4-6.1) gives life cycle, legume flag,
candidate cycle length and minimum temperature; Appendix 4-1 gives the GAEZ crop group; the botanical family
comes from standard classification. Every row says where each group of columns comes from. An empty
cell means "no source found", never a guess: the app must show it as missing.
"""
from __future__ import annotations

import csv
from pathlib import Path

LIFE_CYCLES = ("annual", "perennial")
TRAIT_COLUMNS = ["res02_code", "gaez_group", "life_cycle", "is_legume", "family", "cycle_days_min",
                 "cycle_days_max", "min_temp_c", "traits_source", "family_source", "notes"]


def _num(text: str, cast, where: str):
    text = (text or "").strip()
    if not text:
        return None
    try:
        return cast(text)
    except ValueError:
        raise ValueError(f"{where}: {text!r} is not a number") from None


def load_traits(path: Path) -> dict[str, dict]:
    """{crop_code: traits}. Raises ValueError on a malformed row (bad enum, min > max, duplicate code)."""
    out: dict[str, dict] = {}
    with open(path, encoding="utf-8", newline="") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            code = (row.get("crop_code") or "").strip()
            where = f"{path.name} line {n} ({code or '?'})"
            # DictReader silently drops extra cells and fills missing ones with None: an unquoted comma
            # inside a text field would shift the row without any error, so reject it explicitly.
            if None in row or None in row.values():
                raise ValueError(f"{where}: wrong number of cells (quote text that contains a comma)")
            if not code:
                raise ValueError(f"{where}: empty crop_code")
            if code in out:
                raise ValueError(f"{where}: duplicate crop_code")
            life = (row.get("life_cycle") or "").strip() or None
            if life is not None and life not in LIFE_CYCLES:
                raise ValueError(f"{where}: life_cycle must be one of {LIFE_CYCLES}, got {life!r}")
            legume = (row.get("is_legume") or "").strip().lower()
            if legume not in ("true", "false", ""):
                raise ValueError(f"{where}: is_legume must be true or false, got {legume!r}")
            lo = _num(row.get("cycle_days_min"), int, where)
            hi = _num(row.get("cycle_days_max"), int, where)
            if (lo is None) != (hi is None) or (lo is not None and lo > hi):
                raise ValueError(f"{where}: cycle_days_min/max must both be set with min <= max")
            if life == "perennial" and lo is not None:
                raise ValueError(f"{where}: a perennial crop has no per-season cycle length")
            out[code] = {
                "res02_code": (row.get("res02_code") or "").strip() or None,
                "gaez_group": (row.get("gaez_group") or "").strip() or None,
                "life_cycle": life,
                "is_legume": None if legume == "" else legume == "true",
                "family": (row.get("family") or "").strip() or None,
                "cycle_days_min": lo, "cycle_days_max": hi,
                "min_temp_c": _num(row.get("min_temp_c"), float, where),
                "traits_source": (row.get("traits_source") or "").strip() or None,
                "family_source": (row.get("family_source") or "").strip() or None,
                "notes": (row.get("notes") or "").strip() or None,
            }
    return out


def merge_into_dim_crop(rows: list[dict], traits: dict[str, dict]) -> list[dict]:
    """Add the trait columns to dim_crop rows. Every crop must have a traits row and vice versa, so a
    crop added to config.yaml without traits (or a stale traits row) fails loudly."""
    codes = {r["crop_code"] for r in rows}
    missing, extra = sorted(codes - set(traits)), sorted(set(traits) - codes)
    if missing or extra:
        raise ValueError(f"crop_traits.csv does not match config crops: missing {missing}, unknown {extra}")
    return [{**r, **traits[r["crop_code"]]} for r in rows]
