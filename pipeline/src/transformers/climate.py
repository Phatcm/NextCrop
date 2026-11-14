"""Multi-year climate summaries: monthly normals, per-year annual values, VN grid."""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from src.extractors.gibs_ndvi import _percentile


def _mean(v: list[float]) -> float | None:
    return round(sum(v) / len(v), 3) if v else None


def monthly_normals(monthly_rows: list[dict], params: list[str]) -> dict[str, list[float | None]]:
    """{param: [Jan..Dec mean over all years]} from rows {"month": "YYYY-MM", P: v}."""
    acc: dict[str, list[list[float]]] = {p: [[] for _ in range(12)] for p in params}
    for r in monthly_rows:
        m = int(r["month"][5:7]) - 1
        for p in params:
            if r.get(p) is not None:
                acc[p][m].append(r[p])
    return {p: [_mean(v) for v in acc[p]] for p in params}


def annual_anomalies(annual: dict[str, dict], params: list[str]) -> dict[str, dict]:
    """{year: {P: value, P_anom: value - multi-year mean}} for spotting dry/hot years."""
    means = {p: _mean([a[p] for a in annual.values() if a.get(p) is not None]) for p in params}
    out = {}
    for y in sorted(annual):
        row = {}
        for p in params:
            v = annual[y].get(p)
            row[p] = v
            row[f"{p}_anom"] = round(v - means[p], 3) if (v is not None and means[p] is not None) else None
        out[y] = row
    return out


def _harmonize(raw: dict) -> tuple[dict, dict]:
    """POWER params live on different grids (MERRA-2 0.5x0.625 vs CERES 1 deg for solar).

    Keep only cells of the densest grid; fill a param missing there from the nearest cell
    that has it. Returns (cells, {param: "nearest-neighbor"} for params that were filled).
    """
    params = {p for c in raw.values() for p in c["params"]}
    count = {p: sum(p in c["params"] for c in raw.values()) for p in params}
    if not count:
        return {}, {}
    main = max(count, key=count.get)  # type: ignore[arg-type]
    base = {k: c for k, c in raw.items() if main in c["params"]}
    filled = {}
    for p in params:
        donors = [(k, c["params"][p]) for k, c in raw.items() if p in c["params"]]
        for (lat, lon), c in base.items():
            if p in c["params"]:
                continue
            _, series = min(donors, key=lambda d: (d[0][0] - lat) ** 2 + (d[0][1] - lon) ** 2)
            c["params"][p] = series
            filled[p] = "nearest-neighbor (lưới nguồn thô hơn)"
    return base, filled


def grid_cells(grid: dict) -> list[dict]:
    """VN grid -> [{"lat", "lon", "elev", "normals": {P: [12]}, "annual": {P: {year: v}}}]."""
    cells = []
    base, _ = _harmonize({k: {"elev": c.get("elev"), "params": dict(c["params"])}
                          for k, c in grid["cells"].items()})
    for (lat, lon), c in sorted(base.items()):
        normals, annual = {}, {}
        for p, series in c["params"].items():
            months: list[list[float]] = [[] for _ in range(12)]
            ann = {}
            for k, v in series.items():
                if v is None:
                    continue
                if k[4:6] == "13":
                    ann[k[:4]] = v
                else:
                    months[int(k[4:6]) - 1].append(v)
            normals[p] = [_mean(m) for m in months]
            annual[p] = ann
        cells.append({"lat": lat, "lon": lon, "elev": c.get("elev"), "normals": normals, "annual": annual})
    return cells


def ndvi_profile(points: list[dict]) -> list[dict]:
    """Typical season: per 16-day slot (DOY 1, 17, ...) median/p25/p75 of median_final across years."""
    slots: dict[int, list[float]] = defaultdict(list)
    for p in points:
        if p.get("median_final") is None:
            continue
        doy = dt.date.fromisoformat(p["date"]).timetuple().tm_yday
        slots[min((doy - 1) // 16, 22)].append(p["median_final"])
    out = []
    for k in range(23):
        v = sorted(slots.get(k, []))
        out.append({"slot": k, "doy_start": 1 + 16 * k,
                    "median": round(_percentile(v, 0.5), 4) if v else None,
                    "p25": round(_percentile(v, 0.25), 4) if v else None,
                    "p75": round(_percentile(v, 0.75), 4) if v else None,
                    "n_years": len(v)})
    return out
