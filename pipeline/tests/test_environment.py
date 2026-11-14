import math

import pytest

from src.extractors import gaez_env as ge
from src.models import Region
from src.transformers import env_inputs as ei
from src.transformers import et0

R = Region("r1", "R1", (100.0, 10.0, 100.1, 10.1))


# ---------------------------------------------------------------- ET0 (FAO-56 Penman-Monteith)

def test_fao56_reference_values():
    assert et0.sat_vp(20) == pytest.approx(2.338, abs=0.001)          # FAO-56 table 2.3
    assert et0.slope_svp(20) == pytest.approx(0.1447, abs=0.0005)     # FAO-56 table 2.4
    assert 0.000665 * et0.pressure(0) == pytest.approx(0.0674, abs=0.0002)
    assert et0.pressure(1000) < et0.pressure(0)


def test_extraterrestrial_radiation_is_physical():
    # FAO-56 example 8: latitude 20 S on 3 September (day 246) gives Ra = 32.2 MJ/m2/day
    assert et0.extraterrestrial(-20, 246) == pytest.approx(32.2, abs=0.1)
    # equator: roughly 34-38 MJ/m2/day all year; at 50 N it swings strongly between winter and summer
    assert all(33 < et0.extraterrestrial(0, d) < 38 for d in (15, 105, 196, 288))
    assert et0.extraterrestrial(50, 355) < 10 < 40 < et0.extraterrestrial(50, 172)


def test_et0_typical_tropical_day_and_monotonic_behaviour():
    day = dict(tmax=32, tmin=24, tmean=27.5, rh=75, u2=2.0, rs=18, lat=10.5, z=5, doy=120)
    e = et0.et0_day(**day)
    assert 3.5 < e < 5.5                                              # typical humid-tropics day
    assert et0.et0_day(**{**day, "rs": 24}) > e                       # more sun, more ET0
    assert et0.et0_day(**{**day, "rh": 50}) > e                       # drier air, more ET0
    assert et0.et0_day(**{**day, "u2": 4}) > e                        # more wind, more ET0
    assert et0.et0_day(**{**day, "tmax": 25, "tmin": 25, "tmean": 25, "rs": 0}) >= 0   # never negative


@pytest.mark.parametrize("bad", [dict(tmax=20, tmin=25), dict(rh=120), dict(u2=-1), dict(rs=-3)])
def test_et0_rejects_impossible_input(bad):
    day = dict(tmax=32, tmin=24, tmean=27.5, rh=75, u2=2.0, rs=18, lat=10.5, z=5, doy=120)
    with pytest.raises(ValueError):
        et0.et0_day(**{**day, **bad})


def rows_for(year_month_days):
    out = []
    for date in year_month_days:
        out.append({"date": date, "T2M_MAX": 32.0, "T2M_MIN": 24.0, "T2M": 27.5, "RH2M": 75.0, "WS2M": 2.0,
                    "ALLSKY_SFC_SW_DWN": 18.0})
    return out


def test_daily_skips_days_with_missing_inputs_and_monthly_needs_enough_days():
    days = [f"2020-01-{d:02d}" for d in range(1, 32)]
    rows = rows_for(days)
    rows[3]["WS2M"] = None                                           # a gap is not zero
    daily = et0.daily_et0(rows, 10.5, 5)
    assert len(daily) == 30 and "2020-01-04" not in daily
    assert et0.monthly_et0(daily)["2020-01"] > 0
    assert et0.monthly_et0({k: v for k, v in list(daily.items())[:10]}) == {}        # 10/31 days < 80%


def test_calibration_applies_only_when_plausible():
    pm = {str(y): 1000.0 for y in range(2015, 2021)}                 # 6 full years
    c = et0.calibration(pm, 1200.0)
    assert c["applied"] and c["factor"] == pytest.approx(1.2)
    assert not et0.calibration(pm, 3000.0)["applied"]                # factor 3 -> a data fault, not a bias
    assert et0.calibration(pm, 3000.0)["factor"] == 1.0
    assert not et0.calibration(pm, None)["applied"]
    assert not et0.calibration({"2020": 1000.0}, 1200.0)["applied"]  # too few years


def test_water_balance_uses_best_rain_and_calibrated_et0():
    rain = [{"month": "2020-01", "best_mm": 10.0, "best_source": "chirps"},
            {"month": "2020-02", "best_mm": 50.0, "best_source": "power_fallback"},
            {"month": "2020-03", "best_mm": 5.0, "best_source": "chirps"}]
    rows = et0.water_balance(rain, {"2020-01": 100.0, "2020-02": 80.0}, factor=1.5)      # 2020-03 has no ET0
    assert [r["month"] for r in rows] == ["2020-01", "2020-02"]
    assert rows[0] == {"month": "2020-01", "rain_mm": 10.0, "et0_raw_mm": 100.0, "et0_mm": 150.0,
                       "balance_mm": -140.0, "rain_source": "chirps"}
    assert rows[1]["rain_source"] == "power_fallback"


# ---------------------------------------------------------------- GAEZ windows -> rows

def win(values, nodata=None):
    return {"values": values, "nodata": nodata, "shape": [len(values), len(values[0])]}


def slope_windows(per_class):
    """per_class: list of 10 percent shares of land (0-100); raster = percent x 100."""
    return {("slope", c): {"r1": win([[p * 100, p * 100], [p * 100, p * 100]])}
            for c, p in zip(ge.SLOPE_CLASSES, per_class)}


def test_slope_row_shares_mean_and_thresholds():
    row = ei.slope_row(slope_windows([0, 0, 50, 0, 0, 0, 0, 0, 25, 25]), R)
    assert row["sc03_pct"] == 50 and row["sc10_pct"] == 25
    assert row["share_gt12_pct"] == 50 and row["share_gt24_pct"] == 50
    assert row["slope_mean_pct"] == pytest.approx(0.5 * 3.5 + 0.25 * 37.5 + 0.25 * 55, abs=0.1)
    # shares that do not add up to 100 are renormalised, never left inconsistent
    row2 = ei.slope_row(slope_windows([5] * 10), R)
    assert sum(row2[f"sc{i:02d}_pct"] for i in range(1, 11)) == pytest.approx(100, abs=0.1)


def test_slope_row_is_none_when_a_class_is_missing():
    w = slope_windows([10] * 10)
    del w[("slope", "SC05")]
    assert ei.slope_row(w, R) is None


def test_soil_rows_exclude_water_permafrost_and_not_evaluated():
    w = {("soil", "SQ1.LIM"): {"r1": win([[10, 10], [13, 12]])},      # two rated pixels (class 10), water, not evaluated
         ("soil", "SQ2.LIM"): {"r1": win([[13, 13], [13, 11]])}}      # nothing rated -> no row, not a rating of 0
    rows = ei.soil_rows(w, R)
    assert len(rows) == 1
    r = rows[0]
    assert (r["factor"], r["input_level"], r["rating_mean"], r["n_px"], r["n_rated"]) == ("SQ1", "LIM", 0.95, 4, 2)


def test_wdc_rows_nodata_is_null_and_zero_is_kept():
    w = {("wdc", "RCW.HILM"): {"r1": win([[0.0, 0.0], [0.0, 0.0]], nodata=-9.0)},      # modelled no deficit
         ("wdc", "MZE.HILM"): {"r1": win([[-9.0, -9.0], [-9.0, -9.0]], nodata=-9.0)},  # no data at all
         ("wdc", "SOY.HILM"): {"r1": win([[100.0, 200.0], [-9.0, 300.0]], nodata=-9.0)}}
    rows = {x["crop_code"]: x for x in ei.wdc_rows(w, R, ["RCW", "MZE", "SOY"], ["HILM"])}
    assert rows["RCW"]["mm_mean"] == 0.0 and rows["RCW"]["n_valid"] == 4
    assert rows["MZE"]["mm_mean"] is None and rows["MZE"]["n_valid"] == 0
    assert rows["SOY"]["mm_mean"] == 200.0 and rows["SOY"]["mm_median"] == 200.0 and rows["SOY"]["n_valid"] == 3


def test_mfi_and_erosion_rule():
    one_wet_month = [{"month": f"2020-{m:02d}", "best_mm": 120.0 if m == 7 else 10.0} for m in range(1, 13)]
    mfi = ei.mfi_by_year(one_wet_month)["2020"]
    assert mfi == pytest.approx((120 ** 2 + 11 * 10 ** 2) / (120 + 110))
    assert ei.mfi_by_year(one_wet_month[:11]) == {}                  # incomplete year: no value
    assert ei.mfi_class(30, [60, 90, 120, 160]) == "very_low" and ei.mfi_class(170, [60, 90, 120, 160]) == "very_high"
    steep = {"slope_mean_pct": 35.0, "share_gt12_pct": 80.0}
    flat = {"slope_mean_pct": 2.0, "share_gt12_pct": 0.0}
    wet = [{"month": f"2020-{m:02d}", "best_mm": 200.0} for m in range(1, 13)]      # MFI = 200 -> very_high
    assert ei.erosion_row(R, steep, wet, {})["base_hazard"] == "high"
    assert ei.erosion_row(R, flat, wet, {})["base_hazard"] == "low"          # flat land stays low even with erosive rain
    assert ei.erosion_row(R, None, wet, {}) is None and ei.erosion_row(R, steep, [], {}) is None


# ---------------------------------------------------------------- GAEZ environment extractor

def test_jobs_cover_slope_soil_et0_and_water_deficit():
    cfg = {"et0_reference": {"period": "HP0120", "climate": "AGERA5", "ssp": "HIST"},
           "water_deficit": {"period": "HP0120", "climate": "AGERA5", "ssp": "HIST", "modes": ["HILM"], "crops": ["RCW", "MZE"]}}
    j = ge.jobs(cfg)
    groups = [g for g, _k, _u in j]
    assert groups.count("slope") == 10 and groups.count("soil") == 16 and groups.count("wdc") == 2 and groups.count("et0") == 1
    urls = {k: u for _g, k, u in j}
    assert urls["RCW.HILM"].endswith("GAEZ-V5.RES05-WDC.HP0120.AGERA5.HIST.RCW.HILM.tif")
    assert urls["SQ1.LIM"].endswith("SQX/GAEZ-V5.SQX.SQ1.LIM.tif")
    assert urls["SC03"].endswith("LR-SLC/GAEZ-V5.LR-SLC.SC03.tif")


def test_fetch_windows_offline_without_cache_reports_every_gap(tmp_path):
    cfg = {"water_deficit": {"period": "HP0120", "climate": "AGERA5", "ssp": "HIST", "modes": ["HILM"], "crops": ["RCW"]}}
    res, problems = ge.fetch_windows(cfg, [R], tmp_path, offline=True, log=lambda *_: None)
    assert len(problems) == 27 and all("offline" in p for p in problems)      # 10 slope + 16 soil + 1 wdc
    assert all(not v for v in res.values())


def test_slope_midpoints_are_inside_their_class_bounds():
    for (lo, hi), mid in zip(ge.SLOPE_BOUNDS, ge.SLOPE_MID):
        assert lo < mid and (hi is None or mid < hi)
    assert math.isclose(sum(1 for _ in ge.SLOPE_CLASSES), 10)
