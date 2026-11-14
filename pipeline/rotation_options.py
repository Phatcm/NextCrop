"""Rotation options for a point and a current crop (DATA-02): the four season-level templates.

Reads dim_crop and the GAEZ grid from data/silver (default) and prints JSON. Nearest grid cell within 0.1 deg
of the point is used; outside that range there is no answer (the point is not on the Vietnam grid).

Usage (from pipeline/):
    python rotation_options.py --lat 10.45 --lon 105.35 --crop RCW
    python rotation_options.py --lat 10.45 --lon 105.35 --crop RCW --mode hilm --seasons 2 --priorities nitrogen yield
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import yaml

from src.rotation import options as ro

ROOT = Path(__file__).resolve().parent
MODES = ("hilm", "hrlm", "lilm", "lrlm")


def _to_crop(row: dict) -> dict:
    def i(v):
        return int(v) if v not in (None, "") else None
    return {"crop_code": row["crop_code"], "name_vi": row["name_vi"], "life_cycle": row["life_cycle"] or None,
            "is_legume": row["is_legume"] == "True", "family": row["family"] or None,
            "cycle_days_min": i(row["cycle_days_min"]), "cycle_days_max": i(row["cycle_days_max"]),
            "water_regime": row["water_regime"] or None}


def load_silver(silver: Path) -> dict[str, dict]:
    with open(silver / "dim_crop.csv", encoding="utf-8-sig", newline="") as f:
        return {r["crop_code"]: _to_crop(r) for r in csv.DictReader(f)}


def nearest_cell(silver: Path, lat: float, lon: float, mode: str, max_deg: float = 0.1) -> tuple[dict, tuple[float, float]] | None:
    """({crop_code: index}, (cell_lat, cell_lon)) of the nearest grid cell, or None if farther than max_deg."""
    best, best_d, cells = None, None, {}
    with open(silver / "gaez_grid.csv", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            la, lo = float(r["lat"]), float(r["lon"])
            d = max(abs(la - lat), abs(lo - lon))
            if d > max_deg:
                continue
            cells.setdefault((la, lo), {})[r["crop_code"]] = int(r[mode]) if r[mode] != "" else None
            if best_d is None or d < best_d:
                best, best_d = (la, lo), d
    return (cells[best], best) if best else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--crop", required=True, help="current crop code, e.g. RCW")
    ap.add_argument("--mode", choices=MODES, default="hrlm", help="GAEZ input level (default: rain-fed, high inputs)")
    ap.add_argument("--seasons", type=int, help="crops per year (default: as many as fit, up to 3)")
    ap.add_argument("--priorities", nargs="*", default=["yield"])
    ap.add_argument("--silver", default=None, help="silver folder (default: data/silver)")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    silver = Path(args.silver) if args.silver else ROOT / cfg.get("data_dir", "data") / "silver"
    crops = load_silver(silver)
    if args.crop not in crops:
        print(f"unknown crop {args.crop!r}; known: {', '.join(sorted(crops))}", file=sys.stderr)
        return 2
    cell = nearest_cell(silver, args.lat, args.lon, args.mode)
    if cell is None:
        print("no GAEZ grid cell within 0.1 deg: the point is outside the Vietnam grid", file=sys.stderr)
        return 3
    suit, (la, lo) = cell
    res = ro.generate(args.crop, crops, suit, mode=args.mode, seasons=args.seasons, priorities=args.priorities)
    res["location"] = {"lat": args.lat, "lon": args.lon, "cell_lat": la, "cell_lon": lo}
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
