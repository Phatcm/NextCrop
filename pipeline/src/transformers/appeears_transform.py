"""Turn AppEEARS point rows into per-region series (NDVI, SMAP, land cover, elevation)."""
from __future__ import annotations

from collections import defaultdict

from src.extractors.gibs_ndvi import _percentile
from src.models import NdviObservation

NDVI = "_250m_16_days_NDVI"
REL = "_250m_16_days_pixel_reliability"
SM = "Soil_Moisture_Retrieval_Data_AM_soil_moisture"
SM_QF = "Soil_Moisture_Retrieval_Data_AM_retrieval_qual_flag"

# MCD12Q1 LC_Type1 = IGBP classes
IGBP = {
    1: "Rừng lá kim thường xanh", 2: "Rừng lá rộng thường xanh", 3: "Rừng lá kim rụng lá",
    4: "Rừng lá rộng rụng lá", 5: "Rừng hỗn giao", 6: "Cây bụi rậm", 7: "Cây bụi thưa",
    8: "Savan có cây gỗ", 9: "Savan", 10: "Đồng cỏ", 11: "Đất ngập nước thường xuyên",
    12: "Đất trồng trọt", 13: "Đô thị", 14: "Khảm trồng trọt/tự nhiên", 15: "Băng tuyết",
    16: "Đất trống", 17: "Mặt nước",
}
CROPLAND = {12, 14}


def _ndvi_value(v: float | None) -> float | None:
    """AppEEARS CSVs are normally already scaled; also accept raw ints (scale 1e-4)."""
    if v is None:
        return None
    if abs(v) > 1.5:
        v = v * 1e-4
    return None if v < -0.2 or v > 1.0 else round(v, 4)  # -0.3 / -3000 = fill


def _by_region(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        out[r["region"]].append(r)
    return out


def modis_ndvi_observations(rows: list[dict], accept_rel: list[int],
                            allowed_points: dict[str, set[str]] | None = None) -> dict[str, list[NdviObservation]]:
    """Per region/date: median NDVI over grid points whose pixel_reliability is acceptable.

    allowed_points: optional {region: {point ids}} (e.g. pure-cropland points from GFSAD);
    regions not in the dict use all points.
    valid_frac = share of points that are good; cloud_frac = share flagged cloudy (reliability 3).
    """
    acc = set(accept_rel)
    out: dict[str, list[NdviObservation]] = {}
    for region, rs in _by_region(rows).items():
        keep = (allowed_points or {}).get(region)
        by_date: dict[str, list[dict]] = defaultdict(list)
        for r in rs:
            if keep is None or r["point"] in keep:
                by_date[r["date"]].append(r)
        series = []
        for date in sorted(by_date):
            pts = by_date[date]
            n = len(pts)
            good = sorted(v for p in pts
                          if (rel := p.get(REL)) is not None and int(rel) in acc
                          and (v := _ndvi_value(p.get(NDVI))) is not None)
            cloudy = sum(1 for p in pts if p.get(REL) is not None and int(p[REL]) == 3)
            if not good:
                series.append(NdviObservation(date=date, valid_frac=0.0, cloud_frac=round(cloudy / n, 4),
                                              median=None))
                continue
            series.append(NdviObservation(
                date=date, valid_frac=round(len(good) / n, 4), cloud_frac=round(cloudy / n, 4),
                median=round(_percentile(good, 0.5), 4), mean=round(sum(good) / len(good), 4),
                p80=round(_percentile(good, 0.8), 4), min=good[0], max=good[-1],
                frac_below_030=round(sum(v < 0.30 for v in good) / len(good), 4)))
        out[region] = series
    return out


def smap_daily(rows: list[dict]) -> dict[str, list[dict]]:
    """Per region/date soil moisture (m3/m3). 'recommended' = retrieval_qual_flag bit 0 == 0.

    Dense vegetation (e.g. rice) often makes SMAP flag retrievals as not recommended;
    both values are kept so the app can show the difference honestly.
    """
    out: dict[str, list[dict]] = {}
    for region, rs in _by_region(rows).items():
        by_date: dict[str, list[tuple[float, bool]]] = defaultdict(list)
        for r in rs:
            sm, qf = r.get(SM), r.get(SM_QF)
            if sm is None or sm < 0 or sm > 1:
                continue
            rec = qf is not None and qf < 65534 and (int(qf) & 1) == 0
            by_date[r["date"]].append((sm, rec))
        series = []
        for date in sorted(by_date):
            vals = by_date[date]
            all_v = sorted(v for v, _ in vals)
            rec_v = sorted(v for v, ok in vals if ok)
            series.append({"date": date,
                           "sm_recommended": round(_percentile(rec_v, 0.5), 4) if rec_v else None,
                           "sm_all": round(_percentile(all_v, 0.5), 4)})
        out[region] = series
    return out


def monthly_mean(daily: list[dict], fields: list[str]) -> list[dict]:
    acc: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for d in daily:
        for f in fields:
            if d.get(f) is not None:
                acc[d["date"][:7]][f].append(d[f])
    out = []
    for month in sorted(acc):
        row = {"month": month}
        for f in fields:
            v = acc[month][f]
            row[f] = round(sum(v) / len(v), 4) if v else None
            row[f"n_{f}"] = len(v)
        out.append(row)
    return out


def landcover_by_year(rows: list[dict]) -> dict[str, dict[str, dict]]:
    """{region: {year: {"cropland_frac", "dominant", "classes": {label: frac}, "n"}}}"""
    out: dict[str, dict[str, dict]] = {}
    for region, rs in _by_region(rows).items():
        years: dict[str, list[int]] = defaultdict(list)
        for r in rs:
            v = r.get("LC_Type1")
            if v is not None and int(v) in IGBP:
                years[r["date"][:4]].append(int(v))
        res = {}
        for y in sorted(years):
            cls = years[y]
            n = len(cls)
            counts: dict[int, int] = defaultdict(int)
            for c in cls:
                counts[c] += 1
            dom = max(counts, key=counts.get)  # type: ignore[arg-type]
            res[y] = {"n": n, "cropland_frac": round(sum(counts[c] for c in CROPLAND) / n, 3),
                      "dominant": IGBP[dom],
                      "classes": {IGBP[c]: round(k / n, 3) for c, k in sorted(counts.items(), key=lambda kv: -kv[1])}}
        out[region] = res
    return out


def elevation(rows: list[dict]) -> dict[str, dict]:
    out = {}
    for region, rs in _by_region(rows).items():
        v = sorted(r["NASADEM_HGT"] for r in rs if r.get("NASADEM_HGT") is not None and r["NASADEM_HGT"] > -1000)
        if v:
            out[region] = {"median_m": round(_percentile(v, 0.5), 1), "min_m": v[0], "max_m": v[-1], "n": len(v)}
    return out
