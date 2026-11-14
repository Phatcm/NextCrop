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
    rows, removed = clean_daily(daily(spike=(14, 691.0)), 250)
    bad = next(r for r in rows if r["date"] == "2020-06-14")
    assert bad[PARAM] is None and "691.0" in bad[FLAG_COL] and "250" in bad[FLAG_COL]
    assert removed == [{"date": "2020-06-14", "value_mm": 691.0, "rule": "> 250 mm/day"}]
    assert all(r[FLAG_COL] is None for r in rows if r["date"] != "2020-06-14")   # every row has the column


def test_value_equal_to_limit_is_kept():
    _, removed = clean_daily(daily(spike=(14, 250.0)), 250)
    assert removed == []


def test_month_and_year_recomputed_from_remaining_days():
    p = power(daily(spike=(14, 691.0)), monthly_rain=(29 * 10 + 691) / 30, annual_rain=99.0)
    out, removed = apply_rain_qa(p, 250)
    june = next(m for m in out["monthly"]["rows"] if m["month"] == "2020-06")
    july = next(m for m in out["monthly"]["rows"] if m["month"] == "2020-07")
    assert june[PARAM] == 10.0                         # mean of the 29 remaining days
    assert july[PARAM] == 4.0                          # untouched month stays as POWER delivered it
    assert out["monthly"]["annual"]["2020"][PARAM] == round((29 * 10 + 4) / 30, 3)
    assert len(removed) == 1
    assert p["monthly"]["rows"][0][PARAM] != 10.0      # input not mutated


def test_untouched_when_nothing_exceeds_the_limit():
    p = power(daily(), monthly_rain=9.8, annual_rain=9.7)
    out, removed = apply_rain_qa(p, 250)
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
    assert apply_rain_qa(p) == (p, [])
