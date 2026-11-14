"""QA flags, time-based linear interpolation and 3-point smoothing for an NDVI series."""
from __future__ import annotations

import datetime as dt

from src.models import NdviObservation, NdviPoint


def flag_days(obs: list[NdviObservation], qa: dict) -> list[list[str]]:
    """Reasons each day is bad (empty list = good). Rules from FIELD-SHIFT-NOTES 3.3."""
    reasons: list[list[str]] = []
    for i, o in enumerate(obs):
        r: list[str] = []
        if o.error:
            r.append("không tải được ảnh")
        if o.median is None:
            if not o.error:
                r.append("không có pixel hợp lệ")
            reasons.append(r)
            continue
        # A threshold set to None (null in YAML) disables that rule.
        if qa.get("min_valid_frac") is not None and o.valid_frac < qa["min_valid_frac"]:
            r.append("ít pixel hợp lệ")
        if qa.get("max_cloud_frac") is not None and o.cloud_frac > qa["max_cloud_frac"]:
            r.append("nhiều pixel giống mây")
        if qa.get("min_median") is not None and o.median < qa["min_median"]:
            r.append("median quá thấp")
        drop = qa.get("max_drop_vs_neighbors")
        neigh = [obs[j].median for j in (i - 1, i + 1)
                 if 0 <= j < len(obs) and obs[j].median is not None]
        if drop is not None and neigh and o.median < drop * (sum(neigh) / len(neigh)):
            r.append("sụt mạnh so với ngày kề")
        reasons.append(r)
    return reasons


def _day_offsets(dates: list[str]) -> list[int]:
    d0 = dt.date.fromisoformat(dates[0][:4] + "-01-01")
    return [(dt.date.fromisoformat(d) - d0).days for d in dates]


def interpolate(dates: list[str], values: list[float | None], bad: list[bool]) -> list[float | None]:
    """Linear interpolation over real day distance from the 2 nearest good days.

    At the series edges the nearest good value is copied. None if no good day exists.
    """
    xs = _day_offsets(dates)
    good = [i for i, b in enumerate(bad) if not b and values[i] is not None]
    out: list[float | None] = []
    for i, v in enumerate(values):
        if i in good:
            out.append(v)
            continue
        left = max((j for j in good if j < i), default=None)
        right = min((j for j in good if j > i), default=None)
        if left is not None and right is not None:
            t = (xs[i] - xs[left]) / (xs[right] - xs[left])
            out.append(round(values[left] + t * (values[right] - values[left]), 4))  # type: ignore[operator]
        elif left is not None or right is not None:
            out.append(values[left if left is not None else right])  # type: ignore[index]
        else:
            out.append(None)
    return out


def moving_average(values: list[float | None], window: int = 3) -> list[float | None]:
    """Centered moving average for charts only (not for analysis)."""
    half = window // 2
    out: list[float | None] = []
    for i in range(len(values)):
        win = [v for v in values[max(0, i - half):i + half + 1] if v is not None]
        out.append(round(sum(win) / len(win), 4) if win else None)
    return out


def build_series(obs: list[NdviObservation], qa: dict) -> list[NdviPoint]:
    reasons = flag_days(obs, qa)
    bad = [bool(r) for r in reasons]
    dates = [o.date for o in obs]
    raw = [o.median for o in obs]
    final = interpolate(dates, raw, bad)
    smooth = moving_average(final)
    points = []
    for o, r, b, f, s in zip(obs, reasons, bad, final, smooth):
        source = "missing" if f is None else ("interpolated" if b else "measured")
        points.append(NdviPoint(date=o.date, median_raw=o.median, median_final=f, source=source,
                                flag_bad=b, reasons=r, valid_frac=o.valid_frac,
                                cloud_frac=o.cloud_frac, smoothed=s))
    return points
