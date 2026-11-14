from src.extractors import era5_rain
from src.transformers.rain_qa import FLAG_COL, PARAM, apply_rain_qa, clean_daily, fix_monthly


def daily(days_in_june=30, spike=None):
    rows = []
    for d in range(1, days_in_june + 1):
        v = 10.0
        if spike and d == spike[0]:
            v = spike[1]
        rows.append({"date": f"2020-06-{d:02d}", PARAM: v, "T2M": 27.0})
    rows.append({"date": "2020-07-01", PARAM: 4.0, "T2M": 27.0})
    return rows


def power(rows, monthly_rain, annual_rain):
    return {"daily": {"units": {PARAM: "mm/day", "T2M": "C"}, "rows": rows},
            "monthly": {"units": {PARAM: "mm/day"},
                        "rows": [{"month": "2020-06", PARAM: monthly_rain}, {"month": "2020-07", PARAM: 4.0}],
                        "annual": {"2020": {PARAM: annual_rain}}}}


def test_spike_is_nulled_not_zeroed_and_labelled():
    rows, removed, _ = clean_daily(daily(spike=(14, 691.0)), 250)
    bad = next(r for r in rows if r["date"] == "2020-06-14")
    assert bad[PARAM] is None and "691.0" in bad[FLAG_COL] and "250" in bad[FLAG_COL]
    assert removed == [{"date": "2020-06-14", "value_mm": 691.0, "method": "fixed", "era5_mm": None, "rule": "> 250 mm/day"}]
    assert all(r[FLAG_COL] is None for r in rows if r["date"] != "2020-06-14")   # every row has the column


def test_value_equal_to_limit_is_kept():
    _, removed, _ = clean_daily(daily(spike=(14, 250.0)), 250)
    assert removed == []


def test_month_and_year_recomputed_from_remaining_days():
    p = power(daily(spike=(14, 691.0)), monthly_rain=(29 * 10 + 691) / 30, annual_rain=99.0)
    out, removed, _ = apply_rain_qa(p, 250)
    june = next(m for m in out["monthly"]["rows"] if m["month"] == "2020-06")
    july = next(m for m in out["monthly"]["rows"] if m["month"] == "2020-07")
    assert june[PARAM] == 10.0                         # mean of the 29 remaining days
    assert july[PARAM] == 4.0                          # untouched month stays as POWER delivered it
    assert out["monthly"]["annual"]["2020"][PARAM] == round((29 * 10 + 4) / 30, 3)
    assert len(removed) == 1
    assert p["monthly"]["rows"][0][PARAM] != 10.0      # input not mutated


def test_untouched_when_nothing_exceeds_the_limit():
    p = power(daily(), monthly_rain=9.8, annual_rain=9.7)
    out, removed, _ = apply_rain_qa(p, 250)
    assert removed == []
    assert out["monthly"]["rows"] == p["monthly"]["rows"] and out["monthly"]["annual"] == p["monthly"]["annual"]
    assert FLAG_COL in out["daily"]["rows"][0]


def test_month_with_too_many_gaps_becomes_null_not_a_biased_mean():
    rows = daily()
    for r in rows[:10]:                                # 10 of 30 days already missing, plus one spike
        r[PARAM] = None
    rows[20][PARAM] = 900.0
    monthly, _ = fix_monthly([{"month": "2020-06", PARAM: 5.0}], {}, clean_daily(rows, 250)[0],
                             [{"date": "2020-06-21"}], min_frac=0.8)
    assert monthly[0][PARAM] is None


def test_power_without_rain_parameter_is_returned_unchanged():
    p = {"daily": {"units": {"T2M": "C"}, "rows": []}, "monthly": {"rows": [], "annual": {}}}
    assert apply_rain_qa(p) == (p, [], [])


CROSS = {"candidate_mm": 100, "min_ratio": 0.5, "window_days": 1}


def two_days(a, b):
    return [{"date": "2024-09-07", PARAM: a, "T2M": 27.0}, {"date": "2020-06-14", PARAM: b, "T2M": 27.0}]


def test_cross_check_keeps_a_real_storm_and_drops_a_spike():
    # the same ERA5 reference decides: 155 mm (ERA5 144) is real, 691 mm (ERA5 22) is not
    ref = {"2024-09-07": 144.2, "2020-06-14": 22.2}
    rows, removed, kept = clean_daily(two_days(155.0, 691.0), 180, ref, CROSS)
    assert [d["date"] for d in removed] == ["2020-06-14"] and removed[0]["method"] == "era5"
    assert removed[0]["era5_mm"] == 22.2
    assert [d["date"] for d in kept] == ["2024-09-07"] and kept[0]["era5_mm"] == 144.2
    assert rows[0][PARAM] == 155.0 and rows[1][PARAM] is None
    assert "ERA5 only 22.2" in rows[1][FLAG_COL]


def test_cross_check_beats_the_fixed_limit_in_both_directions():
    ref = {"2024-09-07": 400.0, "2020-06-14": 5.0}
    rows, removed, _ = clean_daily(two_days(500.0, 120.0), 180, ref, CROSS)
    assert rows[0][PARAM] == 500.0                     # above the fixed limit but ERA5 agrees: kept
    assert rows[1][PARAM] is None                      # below the fixed limit but ERA5 disagrees: removed
    assert len(removed) == 1


def test_cross_check_window_tolerates_a_one_day_shift_between_products():
    ref = {"2024-09-06": 150.0, "2024-09-07": 3.0}     # the storm is on the previous day in ERA5
    _, removed, kept = clean_daily(two_days(155.0, 0.0), 180, ref, CROSS)
    assert removed == [] and len(kept) == 1


def test_cross_check_falls_back_to_the_fixed_limit_when_era5_has_no_value():
    rows, removed, _ = clean_daily(two_days(205.0, 120.0), 180, {"2000-01-01": 1.0}, CROSS)
    assert rows[0][PARAM] is None and removed[0]["method"] == "fixed"   # 205 > 180
    assert rows[1][PARAM] == 120.0                                      # 120 < 180 and no reference: kept


def test_without_a_reference_the_fixed_limit_applies():
    rows, removed, kept = clean_daily(two_days(155.0, 691.0), 180, None, CROSS)
    assert [d["date"] for d in removed] == ["2020-06-14"] and kept == [] and rows[0][PARAM] == 155.0


def test_era5_parse_drops_null_days_not_zero_them():
    got = era5_rain.parse({"daily": {"time": ["2020-01-01", "2020-01-02", "2020-01-03"],
                                     "precipitation_sum": [1.5, None, 0.0]}})
    assert got == {"2020-01-01": 1.5, "2020-01-03": 0.0}
