"""Moisture check of the rotation options for the six demo areas.

This is an ANNOTATION: it reads the options that `options.generate()` already produced and returns a separate dict.
It never changes an option, never reorders them and never adds a score, so the ranking is exactly what it was.

What it asks, per option: can the crops of this option grow one after another on rain alone, in this area?
- Moist season (FAO AEZ growing-period criterion): the months in which rain is at least half of the reference
  evapotranspiration (ET0). Rain is CHIRPS v3 (not NASA); ET0 is computed from NASA POWER with the FAO-56
  Penman-Monteith equation and calibrated to the independent GAEZ ET0 layer (silver water_balance_monthly).
- Days available: the longest run of consecutive moist months (circular over the year), counted in days.
- Days needed by an option: the shortest cycle of every season (GAEZ `cycle_days_min`, same as the generator) plus the
  rest days between two crops that follow each other (`gap_rice` / `gap_other` of the result).
  The rest after the last crop falls outside the moist season, so it is not counted.
- enough: needed <= available. short: needed > available, so irrigation or fewer seasons are needed; the shortfall is
  given in days.

What it does NOT check (said in `not_checked`): temperature (GAEZ `min_temp_c` has an unverified meaning, so there is
no per-crop cold or heat threshold), and which month a season really starts (the generator does not schedule seasons).
The criterion does not depend on the crop, and paddy rice needs more water than half of ET0, so for rice the real
limit is stricter. It applies to rain-fed modes only (hrlm, lrlm); an irrigated mode is not limited by rain.
"""
from __future__ import annotations

import calendar

MOIST_RATIO = 0.5                         # FAO AEZ: moisture supply (rain) above half of potential evapotranspiration
RAINFED_MODES = ("hrlm", "lrlm")
NEAR_LIMIT_DAYS = 31                      # the data are monthly: a difference below one month is inside their resolution
MONTH_DAYS = [calendar.monthrange(2023, m)[1] for m in range(1, 13)]      # a common (non-leap) year
RICE_CODES = {"RCW"}                      # same rule as options.py: the gap source covers paddy rice only
LANGS = ("vi", "en")

_VI = {
    "criterion": "Tháng đủ ẩm: mưa tháng ≥ 0,5 × ET0 (tiêu chí thời kỳ sinh trưởng của FAO AEZ).",
    "method": "So số ngày mà mỗi phương án cần (độ dài vụ ngắn nhất cộng khoảng nghỉ giữa các vụ) với số ngày liên tục "
              "đủ ẩm của vùng. Chỉ là sàng lọc, không đổi thứ hạng.",
    "sources": "ET0: tính từ NASA POWER theo FAO-56, hiệu chỉnh theo lớp ET0 của GAEZ. Mưa: CHIRPS v3 (không phải dữ liệu "
               "NASA). Trung bình nhiều năm, không phải dự báo.",
    "enough": "Đủ ẩm nếu chỉ nhờ mưa: cần {need} ngày liên tục cho {n} vụ (gồm khoảng nghỉ giữa vụ), mùa đủ ẩm của vùng "
              "có {avail} ngày.",
    "short": "Thiếu ẩm nếu chỉ nhờ mưa: cần {need} ngày liên tục cho {n} vụ (gồm khoảng nghỉ giữa vụ), mùa đủ ẩm của "
             "vùng chỉ có {avail} ngày (thiếu {short} ngày). Cần tưới bổ sung hoặc bớt vụ.",
    "short_single": " Riêng một vụ đã dài hơn mùa đủ ẩm.",
    "near": " Sát ngưỡng: chênh dưới một tháng, nằm trong sai số của số liệu theo tháng, nên chưa kết luận chắc.",
    "unknown": "Không kiểm tra được: có cây chưa có độ dài vụ trong dữ liệu.",
    "nc_temp": "Nhiệt độ: chưa có ngưỡng lạnh hoặc nóng của từng cây có nguồn đã xác minh (cột min_temp_c của GAEZ chưa "
               "rõ nghĩa), nên không kiểm tra.",
    "nc_calendar": "Tháng bắt đầu của từng vụ: bộ sinh phương án không xếp lịch, nên chỉ so tổng số ngày với mùa đủ ẩm.",
    "cav_rice": "Tiêu chí của FAO không phụ thuộc loại cây; lúa nước cần nhiều nước hơn một nửa ET0 nên giới hạn thực tế "
                "chặt hơn kết quả ở đây.",
    "cav_monthly": "Tính theo trung bình tháng của các năm có dữ liệu: năm khô hoặc năm mưa nhiều có thể khác, và tháng sát "
                   "ngưỡng có thể thuộc mùa đủ ẩm hoặc không tùy năm.",
    "cav_scope": "Chỉ áp dụng cho 6 vùng demo (điểm phải nằm trong {km} km quanh một vùng) và cho chế độ nhờ mưa.",
    "na_irrigated": "Chế độ có tưới: mưa không phải giới hạn, nên không áp dụng kiểm tra độ ẩm.",
    "na_no_area": "Kiểm tra khí hậu chỉ có cho 6 vùng demo; điểm này không nằm trong {km} km quanh vùng nào.",
    "na_no_data": "Chưa có dữ liệu cân bằng nước của vùng này.",
}
_EN = {
    "criterion": "Moist month: monthly rain ≥ 0.5 × ET0 (the FAO AEZ growing-period criterion).",
    "method": "Compares the days each option needs (shortest cycle length plus the rest between crops) with the number of "
              "consecutive moist days of the area. A screening only: it does not change the ranking.",
    "sources": "ET0: computed from NASA POWER with FAO-56, calibrated to the GAEZ ET0 layer. Rain: CHIRPS v3 (not NASA "
               "data). Multi-year averages, not a forecast.",
    "enough": "Enough moisture on rain alone: needs {need} consecutive days for {n} season(s) (including the rest between "
              "crops); the moist season of the area has {avail} days.",
    "short": "Not enough moisture on rain alone: needs {need} consecutive days for {n} season(s) (including the rest "
             "between crops); the moist season of the area has only {avail} days ({short} short). Needs extra "
             "irrigation or fewer seasons.",
    "short_single": " A single season alone is already longer than the moist season.",
    "near": " Close to the limit: the difference is under one month, within the error of monthly data, so no firm "
            "conclusion.",
    "unknown": "Cannot be checked: a crop has no cycle length in the data.",
    "nc_temp": "Temperature: there is no verified cold or heat threshold per crop (the GAEZ min_temp_c column has an "
               "unclear meaning), so it is not checked.",
    "nc_calendar": "Start month of each season: the generator does not schedule seasons, so only the total days are "
                   "compared with the moist season.",
    "cav_rice": "The FAO criterion does not depend on the crop; paddy rice needs more water than half of ET0, so its real "
                "limit is stricter than this result.",
    "cav_monthly": "Based on monthly averages of the years with data: a dry or a wet year can differ, and a month close to "
                   "the threshold may or may not belong to the moist season.",
    "cav_scope": "Only for the 6 demo areas (the point must be within {km} km of one) and for rain-fed modes.",
    "na_irrigated": "Irrigated mode: rain is not the limit, so the moisture check does not apply.",
    "na_no_area": "The climate check exists only for the 6 demo areas; this point is not within {km} km of any.",
    "na_no_data": "No water-balance data for this area yet.",
}
STRINGS = {"vi": _VI, "en": _EN}


def _s(lang: str) -> dict:
    if lang not in STRINGS:
        raise ValueError(f"lang must be one of {', '.join(LANGS)}, got {lang!r}")
    return STRINGS[lang]


def moist_months(clim: list[tuple]) -> list[int]:
    """clim = [(month, rain_mm, et0_mm, years)]. Months (1-12) with rain >= MOIST_RATIO x ET0 (ET0 must be positive)."""
    return sorted(m for m, rain, et0, _n in clim if et0 and et0 > 0 and rain >= MOIST_RATIO * et0)


def longest_run(months: list[int]) -> tuple[list[int], int]:
    """Longest run of consecutive moist months, circular over the year; returns (months in the run, days)."""
    have = set(months)
    if not have:
        return [], 0
    if len(have) == 12:
        return list(range(1, 13)), sum(MONTH_DAYS)
    best: list[int] = []
    for start in range(1, 13):
        if (start - 2) % 12 + 1 in have:           # not the start of a run: the month before is moist too
            continue
        run, m = [], start
        while m in have and len(run) < 12:
            run.append(m)
            m = m % 12 + 1
        if len(run) > len(best):
            best = run
    return best, sum(MONTH_DAYS[m - 1] for m in best)


def _gap(a: str, b: str, gaps: dict) -> int:
    return gaps["rice"] if a in RICE_CODES and b in RICE_CODES else gaps["other"]


def not_applicable(reason: str, lang: str = "vi", **fmt) -> dict:
    """reason: irrigated_mode | no_demo_area | no_data."""
    s = _s(lang)
    key = {"irrigated_mode": "na_irrigated", "no_demo_area": "na_no_area", "no_data": "na_no_data"}[reason]
    return {"applies": False, "reason": reason, "message": s[key].format(**fmt)}


def check_options(res: dict, clim: list[tuple], area: dict, mode: str, lang: str = "vi", *, max_km: int = 60) -> dict:
    """Moisture check of every option in `res` (the dict returned by options.generate). `res` is not modified."""
    s = _s(lang)
    if mode not in RAINFED_MODES:
        return not_applicable("irrigated_mode", lang)
    if len({m for m, *_ in clim}) < 12:
        return not_applicable("no_data", lang)
    months = moist_months(clim)
    run, avail = longest_run(months)
    a = res.get("assumptions", {})
    gaps = {"rice": a.get("gap_rice", {}).get("days", 7), "other": a.get("gap_other", {}).get("days", 15)}
    out = {}
    for o in res.get("options", []):
        seq = o["sequence"]
        cycles = [e.get("cycle_days_min") for e in o["evidence"]]
        if any(c is None for c in cycles):
            out[o["id"]] = {"status": "unknown", "days_needed": None, "days_available": avail, "shortfall_days": None,
                            "margin_days": None, "near_limit": None, "single_season_fits": None, "message": s["unknown"]}
            continue
        need = sum(cycles) + sum(_gap(seq[i], seq[i + 1], gaps) for i in range(len(seq) - 1))
        short = max(0, need - avail)
        single_ok = max(cycles) <= avail
        margin = avail - need                                       # > 0: days to spare, < 0: days short
        near = abs(margin) < NEAR_LIMIT_DAYS
        msg = s["enough" if not short else "short"].format(need=need, n=len(seq), avail=avail, short=short)
        if short and not single_ok:
            msg += s["short_single"]
        if near:
            msg += s["near"]
        out[o["id"]] = {"status": "short" if short else "enough", "days_needed": need, "days_available": avail,
                        "shortfall_days": short, "margin_days": margin, "near_limit": near,
                        "single_season_fits": single_ok, "message": msg}
    return {
        "applies": True, "mode": mode, "lang": lang, "area": area,
        "years": min((n for *_x, n in clim), default=0),
        "method": s["method"], "sources": s["sources"],
        "moist_season": {"criterion": s["criterion"], "ratio": MOIST_RATIO, "months": run, "days": avail,
                         "all_moist_months": months},
        "monthly": [{"m": m, "rain_mm": round(r, 1), "et0_mm": round(e, 1),
                     "ratio": round(r / e, 2) if e and e > 0 else None, "moist": m in months}
                    for m, r, e, _n in sorted(clim)],
        "options": out,
        "not_checked": [s["nc_temp"], s["nc_calendar"]],
        "caveats": [s["cav_rice"], s["cav_monthly"], s["cav_scope"].format(km=max_km)],
    }
