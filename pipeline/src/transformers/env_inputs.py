"""Region-level environment inputs from GAEZ windows (slope, soil, crop water deficit) and a relative erosion context (DATA-03).

Rules
- Nodata is never 0: pixels without a value are excluded and counted.
- Slope shares come from the 10 LR-SLC classes (percent of land area per pixel, averaged over the window).
  mean slope = share-weighted class midpoint; the open class > 45 % uses 55 % (an assumption).
- Soil quality classes 1-10 are rating bins 0.0-0.1 .. 0.9-1.0 and are turned into the bin midpoint; classes 11-13
  (permafrost, not evaluated, water) are not ratings and are excluded and counted in n_px - n_rated.
- Erosion context is a RELATIVE flag, not t/ha: rain erosivity (Modified Fournier Index, from CHIRPS monthly rain) and
  slope. No soil erodibility (K) and no crop cover (C) is available here: the app multiplies by the crop protection class
  in crop_profile. Class thresholds are config values (`water.erosion`), they are not calibrated for Viet Nam.
"""
from __future__ import annotations

from src.extractors import gaez_env as ge
from src.models import Region

NOT_RATING = {11, 12, 13}


def _valid(win: dict, lo: float | None = 0.0) -> list[float]:
    nd = win.get("nodata")
    return [v for row in win["values"] for v in row if (nd is None or v != nd) and (lo is None or v >= lo)]


def slope_row(windows: dict, region: Region) -> dict | None:
    """One terrain_slope row from the 10 class windows, or None if any class window is missing or empty."""
    shares = []
    n_px = 0
    for cls in ge.SLOPE_CLASSES:
        win = windows.get(("slope", cls), {}).get(region.id)
        if not win:
            return None
        vals = _valid(win)
        if not vals:
            return None
        n_px = len(vals)
        shares.append(sum(vals) / len(vals) / 100.0)                 # raster 0-10000 -> percent of land area
    total = sum(shares)
    if total <= 0:
        return None
    shares = [s * 100.0 / total for s in shares]                      # renormalise: classes must add up to 100 %
    row = {"region_id": region.id}
    row.update({f"sc{i + 1:02d}_pct": round(s, 2) for i, s in enumerate(shares)})
    row["slope_mean_pct"] = round(sum(s * m for s, m in zip(shares, ge.SLOPE_MID)) / 100.0, 1)
    row["share_gt12_pct"] = round(sum(shares[5:]), 1)
    row["share_gt24_pct"] = round(sum(shares[7:]), 1)
    row["n_px"] = n_px
    return row


def soil_rows(windows: dict, region: Region) -> list[dict]:
    rows = []
    for f, name in ge.SOIL_FACTORS.items():
        for lv in ge.SOIL_LEVELS:
            win = windows.get(("soil", f"{f}.{lv}"), {}).get(region.id)
            if not win:
                continue
            vals = [int(v) for v in _valid(win)]
            rated = [v for v in vals if v not in NOT_RATING and 1 <= v <= 10]
            if not rated:
                continue
            ratings = [(v - 0.5) / 10 for v in rated]
            rows.append({"region_id": region.id, "factor": f, "factor_name": name, "input_level": lv,
                         "rating_mean": round(sum(ratings) / len(ratings), 3),
                         "rating_min": round(min(ratings), 2), "rating_max": round(max(ratings), 2),
                         "n_px": len(vals), "n_rated": len(rated)})
    return rows


def wdc_rows(windows: dict, region: Region, crops: list[str], modes: list[str]) -> list[dict]:
    rows = []
    for c in crops:
        for m in modes:
            win = windows.get(("wdc", f"{c}.{m}"), {}).get(region.id)
            if not win:
                continue
            flat = [v for row in win["values"] for v in row]
            vals = sorted(_valid(win))
            n = len(vals)
            rows.append({"region_id": region.id, "crop_code": c, "input_mode": m, "n_px": len(flat), "n_valid": n,
                         "mm_mean": round(sum(vals) / n, 1) if n else None,
                         "mm_median": (vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2) if n else None,
                         "mm_max": vals[-1] if n else None})
    return rows


def mfi_by_year(rain_best: list[dict]) -> dict[str, float]:
    """Modified Fournier Index per year = sum(monthly rain^2) / annual rain, years with 12 months only."""
    by: dict[str, list[float]] = {}
    for r in rain_best:
        by.setdefault(r["month"][:4], []).append(r["best_mm"])
    return {y: sum(p * p for p in v) / sum(v) for y, v in by.items() if len(v) == 12 and sum(v) > 0}


def mfi_class(mfi: float, bounds: list[float]) -> str:
    """bounds = [b1..b4]: below b1 very_low, then low, moderate, high, above b4 very_high."""
    names = ["very_low", "low", "moderate", "high", "very_high"]
    return names[sum(mfi >= b for b in bounds)]


def erosion_row(region: Region, slope: dict | None, rain_best: list[dict], cfg: dict) -> dict | None:
    """erosion_context row, or None when slope or rain is missing (no guess)."""
    years = mfi_by_year(rain_best)
    if slope is None or not years:
        return None
    mfi = sum(years.values()) / len(years)
    cls = mfi_class(mfi, cfg.get("mfi_bounds", [60, 90, 120, 160]))
    gt12 = slope["share_gt12_pct"]
    s_cls = "high" if gt12 >= cfg.get("slope_high_share_gt12", 40) else (
        "moderate" if gt12 >= cfg.get("slope_moderate_share_gt12", 10) else "low")
    rain_rank = ["very_low", "low", "moderate", "high", "very_high"].index(cls)
    if s_cls == "low":
        hazard = "low"
    elif s_cls == "high":
        hazard = "high" if rain_rank >= 2 else "moderate"
    else:
        hazard = "moderate" if rain_rank >= 3 else "low"
    return {"region_id": region.id, "mfi": round(mfi, 1), "mfi_class": cls, "n_years": len(years),
            "slope_mean_pct": slope["slope_mean_pct"], "share_gt12_pct": gt12, "slope_class": s_cls,
            "base_hazard": hazard}
