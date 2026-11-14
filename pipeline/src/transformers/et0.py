"""Reference evapotranspiration ET0 (FAO-56 Penman-Monteith) from the NASA POWER daily series, and a monthly water balance.

NASA POWER has no PET (the API answers HTTP 422 for it), but it has every input of the FAO-56 daily equation:
T2M_MAX / T2M_MIN / T2M (C), RH2M (%), WS2M (m/s at 2 m) and ALLSKY_SFC_SW_DWN (MJ/m2/day). No new download.

Equation (FAO-56 eq. 6, daily, G = 0):
    ET0 = (0.408 D (Rn - G) + g 900/(T+273) u2 (es - ea)) / (D + g (1 + 0.34 u2))
with the standard auxiliary equations: es from Tmax/Tmin (eq. 12), ea from mean relative humidity (eq. 19, the less
accurate form because POWER gives RH2M mean only), Rn = Rns - Rnl (eq. 38-39), Ra from latitude and day of year
(eq. 21), clear-sky Rso = (0.75 + 2e-5 z) Ra (eq. 37), pressure from elevation (eq. 7).
Because ea uses mean RH (not RHmax/RHmin) the result is slightly less exact than the full method: it is checked against
the independent GAEZ v5 ET0 layer in run_etl (config `water.et0_check_tolerance`).

The monthly water balance is rain - ET0 (mm/month), with rain from rain_monthly_best (CHIRPS), not from POWER.
"""
from __future__ import annotations

import calendar
import datetime as dt
import math

SIGMA = 4.903e-9          # Stefan-Boltzmann, MJ K-4 m-2 day-1
GSC = 0.0820              # solar constant, MJ m-2 min-1
ALBEDO = 0.23
MIN_VALID_FRAC = 0.8


def sat_vp(t: float) -> float:
    """Saturation vapour pressure (kPa) at air temperature t (C), FAO-56 eq. 11."""
    return 0.6108 * math.exp(17.27 * t / (t + 237.3))


def slope_svp(t: float) -> float:
    """Slope of the saturation vapour pressure curve (kPa/C), FAO-56 eq. 13."""
    return 4098 * sat_vp(t) / (t + 237.3) ** 2


def pressure(z: float) -> float:
    return 101.3 * ((293 - 0.0065 * z) / 293) ** 5.26


def extraterrestrial(lat_deg: float, doy: int) -> float:
    """Ra, MJ m-2 day-1 (FAO-56 eq. 21)."""
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi * doy / 365)
    delta = 0.409 * math.sin(2 * math.pi * doy / 365 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(delta))))
    return (24 * 60 / math.pi) * GSC * dr * (ws * math.sin(phi) * math.sin(delta)
                                             + math.cos(phi) * math.cos(delta) * math.sin(ws))


def et0_day(tmax: float, tmin: float, tmean: float, rh: float, u2: float, rs: float, lat: float, z: float,
            doy: int) -> float:
    """ET0 in mm/day for one day. Raises ValueError for physically impossible inputs."""
    if tmax < tmin or not 0 <= rh <= 100 or u2 < 0 or rs < 0:
        raise ValueError("impossible input")
    es = (sat_vp(tmax) + sat_vp(tmin)) / 2
    ea = rh / 100 * sat_vp(tmean)
    ra = extraterrestrial(lat, doy)
    rso = (0.75 + 2e-5 * z) * ra
    rns = (1 - ALBEDO) * rs
    ratio = min(1.0, rs / rso) if rso > 0 else 0.0
    rnl = SIGMA * (((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2) * (0.34 - 0.14 * math.sqrt(max(ea, 0))) \
        * (1.35 * ratio - 0.35)
    rn = rns - rnl
    gamma = 0.000665 * pressure(z)
    d = slope_svp(tmean)
    et = (0.408 * d * rn + gamma * 900 / (tmean + 273) * u2 * (es - ea)) / (d + gamma * (1 + 0.34 * u2))
    return max(0.0, et)


def daily_et0(rows: list[dict], lat: float, z: float) -> dict[str, float]:
    """{YYYY-MM-DD: mm/day}. A day with any missing input is left out (a gap is not 0)."""
    out: dict[str, float] = {}
    for r in rows:
        v = [r.get(k) for k in ("T2M_MAX", "T2M_MIN", "T2M", "RH2M", "WS2M", "ALLSKY_SFC_SW_DWN")]
        if any(x is None for x in v):
            continue
        try:
            doy = dt.date.fromisoformat(r["date"]).timetuple().tm_yday
            out[r["date"]] = et0_day(*v, lat=lat, z=z, doy=doy)
        except ValueError:
            continue
    return out


def monthly_et0(daily: dict[str, float], min_valid_frac: float = MIN_VALID_FRAC) -> dict[str, float]:
    """{YYYY-MM: mm/month}: mean of the valid days x days in the month; None-free (a month with too few days is left out)."""
    acc: dict[str, list[float]] = {}
    for d, v in daily.items():
        acc.setdefault(d[:7], []).append(v)
    out = {}
    for m, vals in acc.items():
        n = calendar.monthrange(int(m[:4]), int(m[5:7]))[1]
        if len(vals) / n >= min_valid_frac:
            out[m] = round(sum(vals) / len(vals) * n, 1)
    return out


def calibration(pm_annual: dict[str, float], reference_mm: float | None, lo: float = 0.5, hi: float = 2.0,
                min_years: int = 5) -> dict:
    """Scale factor reference / POWER-ET0 (mean over full years). Applied only when it is plausible:
    {"factor", "applied", "pm_mean_mm", "reference_mm", "reason"}. Not applied (factor 1.0) when the reference is
    missing, there are too few full years, or the factor falls outside [lo, hi] (a sign of a data fault, not a bias)."""
    if not pm_annual or reference_mm is None or reference_mm <= 0:
        return {"factor": 1.0, "applied": False, "pm_mean_mm": None, "reference_mm": reference_mm,
                "reason": "no reference ET0"}
    mean = sum(pm_annual.values()) / len(pm_annual)
    f = reference_mm / mean
    if len(pm_annual) < min_years:
        return {"factor": 1.0, "applied": False, "pm_mean_mm": round(mean), "reference_mm": reference_mm,
                "reason": f"only {len(pm_annual)} full years"}
    if not lo <= f <= hi:
        return {"factor": 1.0, "applied": False, "pm_mean_mm": round(mean), "reference_mm": reference_mm,
                "reason": f"factor {f:.2f} outside [{lo}, {hi}]"}
    return {"factor": round(f, 3), "applied": True, "pm_mean_mm": round(mean), "reference_mm": reference_mm,
            "reason": "scaled so the 11-year mean matches the GAEZ reference (monthly shape kept from POWER)"}


def water_balance(rain_best: list[dict], et0_month: dict[str, float], factor: float = 1.0) -> list[dict]:
    """Rows {month, rain_mm, et0_raw_mm, et0_mm, balance_mm, rain_source}: only months present in both.
    rain_best = rain_monthly_best rows; et0_mm = et0_raw_mm x calibration factor; balance = rain - et0_mm."""
    rows = []
    for r in sorted(rain_best, key=lambda x: x["month"]):
        raw = et0_month.get(r["month"])
        if raw is None:
            continue
        et = round(raw * factor, 1)
        rows.append({"month": r["month"], "rain_mm": r["best_mm"], "et0_raw_mm": raw, "et0_mm": et,
                     "balance_mm": round(r["best_mm"] - et, 1), "rain_source": r["best_source"]})
    return rows


def annual_totals(monthly: dict[str, float]) -> dict[str, float]:
    """{year: mm} for years with all 12 months."""
    by: dict[str, list[float]] = {}
    for m, v in monthly.items():
        by.setdefault(m[:4], []).append(v)
    return {y: round(sum(v), 1) for y, v in by.items() if len(v) == 12}
