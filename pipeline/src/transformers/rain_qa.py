"""QA for daily rain from NASA POWER (DATA-05).

POWER daily PRECTOTCORR comes from the MERRA-2 model and sometimes contains single-day spikes that
are physically implausible (An Giang 2020-06-14 = 691 mm; an independent ERA5 check gives 22 mm).
Because monthly sums, annual totals and monthly normals are all derived from the daily series,
one bad day poisons every table. Rule: a day above `max_daily_mm` is set to NULL (never to 0) and
labelled; the months and years that contained it are then recomputed from the remaining days.

Months/years without a removed day are left exactly as POWER delivered them.
"""
from __future__ import annotations

PARAM = "PRECTOTCORR"
FLAG_COL = "PRECTOTCORR_QA"          # silver column prectotcorr_qa: empty = untouched
DEFAULT_MAX_MM = 250.0
DEFAULT_MIN_VALID_FRAC = 0.8          # a month/year needs >= 80% valid days to be recomputed


def flag_text(value: float, limit: float) -> str:
    return f"removed: {value:.1f} mm/day > {limit:g} mm/day"


def clean_daily(rows: list[dict], max_mm: float = DEFAULT_MAX_MM) -> tuple[list[dict], list[dict]]:
    """Return (new_rows, removed). Every row gets FLAG_COL (None when untouched), so all regions
    share one CSV header. `removed` = [{"date", "value_mm", "rule"}] for the gold metadata."""
    out, removed = [], []
    for r in rows:
        v = r.get(PARAM)
        row = dict(r)
        row[FLAG_COL] = None
        if v is not None and v > max_mm:
            row[PARAM] = None
            row[FLAG_COL] = flag_text(v, max_mm)
            removed.append({"date": r["date"], "value_mm": round(v, 1), "rule": f"> {max_mm:g} mm/day"})
        out.append(row)
    return out, removed


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


def apply_rain_qa(power: dict, max_mm: float = DEFAULT_MAX_MM,
                  min_frac: float = DEFAULT_MIN_VALID_FRAC) -> tuple[dict, list[dict]]:
    """power = power_client.fetch_power() result. Returns (new_power, removed); a no-op copy when nothing is removed
    (rows still get the empty FLAG_COL so the schema is identical for every region)."""
    if PARAM not in power["daily"]["units"]:
        return power, []
    daily, removed = clean_daily(power["daily"]["rows"], max_mm)
    monthly, annual = fix_monthly(power["monthly"]["rows"], power["monthly"]["annual"], daily, removed, min_frac)
    return ({**power,
             "daily": {**power["daily"], "rows": daily},
             "monthly": {**power["monthly"], "rows": monthly, "annual": annual}}, removed)
