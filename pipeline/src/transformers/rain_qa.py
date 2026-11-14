"""QA for daily rain from NASA POWER (DATA-05).

POWER daily PRECTOTCORR comes from the MERRA-2 model and sometimes contains single-day spikes that
are physically implausible (An Giang 2020-06-14 = 691 mm; an independent ERA5 check gives 22 mm).
Because monthly sums, annual totals and monthly normals are all derived from the daily series,
one bad day poisons every table. A rejected day is set to NULL (never to 0) and labelled; the months
and years that contained it are then recomputed from the remaining days.

Two ways to decide, both automatic:
1. Cross-check (default): a day above `cross_check.candidate_mm` is compared with ERA5 at the same point
   and removed only if ERA5 does not support it (ERA5 < min_ratio x POWER). This keeps real typhoon rain
   (Yagi 2024-09-07: POWER 155, ERA5 144) and drops spikes (691 vs 22), with no hand-tuned limit.
2. Fixed limit `max_daily_mm`: used when ERA5 is not available (offline without cache, API down).

Months/years without a removed day are left exactly as POWER delivered them.
"""
from __future__ import annotations

import datetime as dt

PARAM = "PRECTOTCORR"
FLAG_COL = "PRECTOTCORR_QA"          # silver column prectotcorr_qa: empty = untouched
DEFAULT_MAX_MM = 180.0
DEFAULT_MIN_VALID_FRAC = 0.8          # a month/year needs >= 80% valid days to be recomputed


def flag_text(value: float, limit: float, era5: float | None = None) -> str:
    if era5 is not None:
        return f"removed: {value:.1f} mm/day, ERA5 only {era5:.1f} mm/day (cross-check)"
    return f"removed: {value:.1f} mm/day > {limit:g} mm/day"


def _ref_max(reference: dict[str, float], date: str, window: int) -> float | None:
    """Largest ERA5 value within +-window days (day boundaries differ between the two products)."""
    d0 = dt.date.fromisoformat(date)
    vals = [reference[k] for k in ((d0 + dt.timedelta(days=i)).isoformat() for i in range(-window, window + 1))
            if k in reference]
    return max(vals) if vals else None


def clean_daily(rows: list[dict], max_mm: float = DEFAULT_MAX_MM, reference: dict[str, float] | None = None,
                cross: dict | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (new_rows, removed, kept). Every row gets FLAG_COL (None when untouched), so all regions
    share one CSV header.

    Without `reference`: a day above `max_mm` is removed (fixed limit).
    With `reference` (ERA5 daily) and `cross`: a day above cross["candidate_mm"] is removed only when the
    reference does not support it, i.e. the largest reference value within +-window_days is below
    cross["min_ratio"] x POWER. Supported days are kept and listed in `kept`. A candidate day the reference
    has no data for falls back to the fixed limit.
    removed/kept = [{"date", "value_mm", "rule", "method", "era5_mm"}] for the gold metadata."""
    cross = cross or {}
    cand, ratio, window = cross.get("candidate_mm", 100.0), cross.get("min_ratio", 0.5), cross.get("window_days", 1)
    out, removed, kept = [], [], []
    for r in rows:
        v = r.get(PARAM)
        row = dict(r)
        row[FLAG_COL] = None
        if v is not None:
            ref = _ref_max(reference, r["date"], window) if (reference is not None and v > cand) else None
            if ref is not None:
                info = {"date": r["date"], "value_mm": round(v, 1), "method": "era5", "era5_mm": round(ref, 1),
                        "rule": f"ERA5 < {ratio:g} x POWER"}
                if ref < ratio * v:
                    row[PARAM], row[FLAG_COL] = None, flag_text(v, max_mm, ref)
                    removed.append(info)
                else:
                    kept.append(info)
            elif v > max_mm:
                row[PARAM], row[FLAG_COL] = None, flag_text(v, max_mm)
                removed.append({"date": r["date"], "value_mm": round(v, 1), "method": "fixed", "era5_mm": None,
                                "rule": f"> {max_mm:g} mm/day"})
        out.append(row)
    return out, removed, kept


def _mean_valid(values: list, min_frac: float) -> float | None:
    ok = [v for v in values if v is not None]
    if not values or len(ok) / len(values) < min_frac:
        return None
    return round(sum(ok) / len(ok), 3)


def fix_monthly(monthly_rows: list[dict], annual: dict[str, dict], daily_rows: list[dict],
                removed: list[dict], min_frac: float = DEFAULT_MIN_VALID_FRAC) -> tuple[list[dict], dict]:
    """Recompute PRECTOTCORR (mm/day mean) only for months and years that lost a day.

    monthly_rows: [{"month": "YYYY-MM", ...}], annual: {"YYYY": {...}}, daily_rows: output of clean_daily.
    Returns (new_monthly_rows, new_annual); inputs are not modified."""
    bad_months = {d["date"][:7] for d in removed}
    bad_years = {d["date"][:4] for d in removed}
    by_month: dict[str, list] = {}
    by_year: dict[str, list] = {}
    for r in daily_rows:
        if r["date"][:7] in bad_months:
            by_month.setdefault(r["date"][:7], []).append(r.get(PARAM))
        if r["date"][:4] in bad_years:
            by_year.setdefault(r["date"][:4], []).append(r.get(PARAM))
    new_monthly = [dict(m, **{PARAM: _mean_valid(by_month[m["month"]], min_frac)}) if m["month"] in by_month else dict(m)
                   for m in monthly_rows]
    new_annual = {y: (dict(a, **{PARAM: _mean_valid(by_year[y], min_frac)}) if y in by_year else dict(a))
                  for y, a in annual.items()}
    return new_monthly, new_annual


def apply_rain_qa(power: dict, max_mm: float = DEFAULT_MAX_MM, min_frac: float = DEFAULT_MIN_VALID_FRAC,
                  reference: dict[str, float] | None = None, cross: dict | None = None
                  ) -> tuple[dict, list[dict], list[dict]]:
    """power = power_client.fetch_power() result. Returns (new_power, removed, kept); a no-op copy when nothing
    is removed (rows still get the empty FLAG_COL so the schema is identical for every region)."""
    if PARAM not in power["daily"]["units"]:
        return power, [], []
    daily, removed, kept = clean_daily(power["daily"]["rows"], max_mm, reference, cross)
    monthly, annual = fix_monthly(power["monthly"]["rows"], power["monthly"]["annual"], daily, removed, min_frac)
    return ({**power,
             "daily": {**power["daily"], "rows": daily},
             "monthly": {**power["monthly"], "rows": monthly, "annual": annual}}, removed, kept)
