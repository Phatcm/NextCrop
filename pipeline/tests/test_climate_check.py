"""Moisture check of the options (annotation only). Real crops from the config, real monthly climate of three demo areas."""
import copy
import re

import pytest

from src.rotation import climate_check as cc
from src.rotation import options as ro
from test_rotation import AN_GIANG, CROPS

# monthly means 2015-2025 of the demo areas (silver water_balance_monthly): (rain mm CHIRPS, ET0 mm), months 1-12
AN_GIANG_CLIM = list(zip(range(1, 13), [19, 12, 20, 64, 185, 150, 200, 185, 244, 300, 180, 64],
                         [120, 143, 188, 176, 144, 116, 111, 114, 104, 103, 99, 105], [11] * 12))
THAI_BINH_CLIM = list(zip(range(1, 13), [36, 39, 54, 86, 170, 162, 273, 350, 390, 257, 45, 24],
                          [65, 68, 86, 104, 132, 134, 134, 120, 110, 99, 80, 70], [11] * 12))
NINH_THUAN_CLIM = list(zip(range(1, 13), [19, 10, 8, 17, 59, 61, 50, 60, 138, 159, 173, 107],
                           [131, 140, 174, 173, 164, 145, 140, 148, 133, 124, 108, 112], [11] * 12))
AREA = {"region_id": "an_giang_rice", "name": "An Giang", "distance_km": 3}


def an_giang_result(**kw):
    return ro.generate("RCW", CROPS, AN_GIANG, **kw)


# ---------------------------------------------------------------- the moist season

def test_moist_season_of_the_three_areas_matches_the_data():
    ag = cc.moist_months(AN_GIANG_CLIM)
    assert ag == [5, 6, 7, 8, 9, 10, 11, 12] and cc.longest_run(ag) == (ag, 245)
    tb = cc.moist_months(THAI_BINH_CLIM)
    assert tb == list(range(1, 12)) and cc.longest_run(tb)[1] == 334            # December (0.34) is the only dry month
    nt = cc.moist_months(NINH_THUAN_CLIM)
    assert nt == [9, 10, 11, 12] and cc.longest_run(nt)[1] == 122


def test_the_threshold_is_half_of_et0_and_needs_a_positive_et0():
    assert cc.moist_months([(1, 50, 100, 5)]) == [1]                            # exactly half counts
    assert cc.moist_months([(1, 49.9, 100, 5)]) == []
    assert cc.moist_months([(1, 5, 0, 5), (2, 5, None, 5)]) == []              # no ET0: not claimed as moist


def test_longest_run_wraps_around_the_year_and_handles_the_extremes():
    run, days = cc.longest_run([11, 12, 1, 2])                                  # Nov-Feb is ONE run, not two
    assert run == [11, 12, 1, 2] and days == 30 + 31 + 31 + 28
    assert cc.longest_run([]) == ([], 0)
    assert cc.longest_run(list(range(1, 13))) == (list(range(1, 13)), 365)
    run, days = cc.longest_run([1, 2, 6, 7, 8])                                 # the longest of two runs
    assert run == [6, 7, 8] and days == 30 + 31 + 31


# ---------------------------------------------------------------- the check per option

def test_three_rice_crops_do_not_fit_the_rain_in_an_giang():
    res = an_giang_result()
    out = cc.check_options(res, AN_GIANG_CLIM, AREA, "hrlm")
    assert out["applies"] is True and out["moist_season"]["days"] == 245 and out["area"] == AREA
    keep = out["options"]["keep"]
    assert keep["days_needed"] == 105 * 3 + 7 * 2 and keep["shortfall_days"] == 84 and keep["status"] == "short"
    assert keep["single_season_fits"] is True
    assert "thiếu 84 ngày" in keep["message"] and "Thiếu ẩm" in keep["message"]
    legume = out["options"]["legume"]                                          # rice, rice, cowpea: 105+105+80 + 7 + 15
    assert legume["days_needed"] == 312 and legume["shortfall_days"] == 67
    assert set(out["options"]) == {o["id"] for o in res["options"]}            # every option gets an answer


def test_a_shorter_plan_fits_and_a_crop_longer_than_the_season_is_called_out():
    res = ro.generate("RCW", CROPS, AN_GIANG, seasons=2)
    out = cc.check_options(res, AN_GIANG_CLIM, AREA, "hrlm")
    assert out["options"]["keep"]["status"] == "enough" and out["options"]["keep"]["days_needed"] == 217
    assert out["options"]["keep"]["shortfall_days"] == 0 and "Đủ ẩm" in out["options"]["keep"]["message"]
    nt = cc.check_options(ro.generate("RCW", CROPS, AN_GIANG, seasons=1), NINH_THUAN_CLIM, AREA, "hrlm")
    assert nt["options"]["keep"]["status"] == "enough"                         # 105 days in a 122-day moist season
    cassava = ro.generate("RCW", CROPS, {**AN_GIANG, "CSV": 9000}, seasons=1)
    cassava["options"][0]["evidence"][0]["cycle_days_min"] = 210                # a crop that needs 210 days, in a 122-day season
    r = cc.check_options(cassava, NINH_THUAN_CLIM, AREA, "hrlm")["options"]["keep"]
    assert r["status"] == "short" and r["single_season_fits"] is False and "Riêng một vụ" in r["message"]


def test_a_difference_below_one_month_is_flagged_as_near_the_limit_not_decided():
    res = an_giang_result()                                                     # 3 rice crops need 329 days
    tb = cc.check_options(res, THAI_BINH_CLIM, AREA, "hrlm")["options"]["keep"]          # Thai Binh: 334 moist days
    assert tb["status"] == "enough" and tb["margin_days"] == 5 and tb["near_limit"] is True
    assert "Sát ngưỡng" in tb["message"]
    ag = cc.check_options(res, AN_GIANG_CLIM, AREA, "hrlm")["options"]["keep"]           # An Giang: 84 days short
    assert ag["near_limit"] is False and ag["margin_days"] == -84 and "Sát ngưỡng" not in ag["message"]
    en = cc.check_options(res, THAI_BINH_CLIM, AREA, "hrlm", "en")["options"]["keep"]
    assert "close to the limit" in en["message"].lower()
    edge = [cc.check_options(res, [(m, r, e, n) for m, r, e, n in AN_GIANG_CLIM], AREA, "hrlm")]   # sanity: still the same dict shape
    assert {"margin_days", "near_limit"} <= set(edge[0]["options"]["keep"])


def test_user_gaps_are_used_for_the_days_needed():
    # the generator counts a rest after EVERY crop for the year (3 x 105 + 3 x 15 = 360 fits), but the moisture check
    # only counts the rests BETWEEN crops: the last one falls outside the moist season (3 x 105 + 2 x 15 = 345)
    res = an_giang_result(gap_rice=15)
    assert res["seasons"] == 3
    assert cc.check_options(res, AN_GIANG_CLIM, AREA, "hrlm")["options"]["keep"]["days_needed"] == 105 * 3 + 15 * 2
    res = an_giang_result(gap_rice=30)                                          # the generator itself drops to 2 seasons
    assert res["seasons"] == 2
    assert cc.check_options(res, AN_GIANG_CLIM, AREA, "hrlm")["options"]["keep"]["days_needed"] == 105 * 2 + 30


def test_irrigated_modes_and_missing_data_do_not_apply():
    res = an_giang_result()
    for mode in ("hilm", "lilm"):
        out = cc.check_options(res, AN_GIANG_CLIM, AREA, mode)
        assert out == {"applies": False, "reason": "irrigated_mode", "message": cc.STRINGS["vi"]["na_irrigated"]}
    out = cc.check_options(res, AN_GIANG_CLIM[:8], AREA, "hrlm")               # fewer than 12 months of data
    assert out["applies"] is False and out["reason"] == "no_data"
    assert cc.not_applicable("no_demo_area", "en", km=60)["message"].endswith("within 60 km of any.")
    with pytest.raises(ValueError):
        cc.check_options(res, AN_GIANG_CLIM, AREA, "hrlm", lang="fr")


def test_an_option_with_an_unknown_cycle_is_unknown_not_guessed():
    res = an_giang_result()
    res["options"][1]["evidence"][0]["cycle_days_min"] = None
    out = cc.check_options(res, AN_GIANG_CLIM, AREA, "hrlm")["options"]
    assert out[res["options"][1]["id"]]["status"] == "unknown" and out[res["options"][1]["id"]]["days_needed"] is None


# ---------------------------------------------------------------- it must NOT touch the ranking

def test_the_check_never_changes_the_options_or_their_order():
    res = an_giang_result(priorities=["nitrogen", "yield"])
    before = copy.deepcopy(res)
    cc.check_options(res, AN_GIANG_CLIM, AREA, "hrlm")
    cc.check_options(res, AN_GIANG_CLIM, AREA, "hrlm", lang="en")
    assert res == before                                                       # the result dict is not modified at all
    assert [o["id"] for o in res["options"]] == [o["id"] for o in before["options"]]


def test_the_check_adds_no_score_and_names_what_it_does_not_check():
    out = cc.check_options(an_giang_result(), AN_GIANG_CLIM, AREA, "hrlm")
    assert not ({"score", "rank", "total"} & set(out)) and not any(
        {"score", "rank", "total"} & set(o) for o in out["options"].values())
    text = " ".join(out["not_checked"] + out["caveats"])
    assert "min_temp_c" in text and "không xếp lịch" in text and "lúa nước" in text
    assert "CHIRPS" in out["sources"] and "không phải dữ liệu NASA" in out["sources"]


# ---------------------------------------------------------------- the two languages

def test_vi_and_en_tables_have_the_same_keys_and_placeholders():
    vi, en = cc.STRINGS["vi"], cc.STRINGS["en"]
    assert set(vi) == set(en)
    holders = lambda s: sorted(re.findall(r"\{(\w+)\}", s))                    # noqa: E731
    assert all(holders(vi[k]) == holders(en[k]) for k in vi), [k for k in vi if holders(vi[k]) != holders(en[k])]


def test_english_text_has_no_vietnamese_and_the_language_changes_only_words():
    assert not [k for k, v in cc.STRINGS["en"].items() if re.search(r"[àáảãạăâđêéèẻẽẹôơưíìỉĩịúùủũụýỳỷỹỵ]", v.lower())]
    res = an_giang_result()
    vi = cc.check_options(res, AN_GIANG_CLIM, AREA, "hrlm", "vi")
    en = cc.check_options(res, AN_GIANG_CLIM, AREA, "hrlm", "en")
    strip = lambda d: {i: {k: v for k, v in o.items() if k != "message"} for i, o in d["options"].items()}   # noqa: E731
    assert strip(vi) == strip(en) and vi["moist_season"]["months"] == en["moist_season"]["months"]
    assert "not enough moisture" in en["options"]["keep"]["message"].lower()
