from pathlib import Path

import pytest
import yaml

from src.extractors import gaez
from src.rotation import options as ro
from src.transformers.crop_traits import load_traits, merge_into_dim_crop

ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
CROPS = {r["crop_code"]: r for r in merge_into_dim_crop(gaez.crop_dim_rows(CFG["gaez"]),
                                                       load_traits(ROOT / "crop_traits.csv"))}

# GAEZ index at the An Giang cell (10.45N 105.35E), rain-fed + high inputs, printed from data/silver/gaez_grid.csv
AN_GIANG = {"RCD": 9410, "RCW": 8460, "CSV": 7705, "SPO": 7273, "COW": 7272, "GRD": 7182, "SOY": 6277,
            "TOM": 5781, "ONI": 5110, "MZE": 5056, "WPO": 0, "CAB": 0}


def ids(res):
    return [o["id"] for o in res["options"]]


def seq(res, opt_id):
    return next(o["sequence"] for o in res["options"] if o["id"] == opt_id)


def test_an_giang_rice_gets_the_four_templates():
    res = ro.generate("RCW", CROPS, AN_GIANG, priorities=["yield"])
    assert res["seasons"] == 3 and res["options"][0]["id"] == "keep"
    assert seq(res, "keep") == ["RCW"] * 3
    assert seq(res, "legume") == ["RCW", "RCW", "COW"]                  # best legume that fits the year
    assert seq(res, "other_family") == ["RCW", "RCW", "TOM"]            # sweet potato (120 d) does not fit twice with rice
    # canonical order, not a schedule: kept crops first, then replacements by GAEZ index (SPO 7273 > COW 7272)
    assert seq(res, "diverse") == ["RCW", "SPO", "COW"]
    assert len(res["options"]) >= 3                                   # the challenge needs >= 3 incl. current
    assert all(o["components"]["fits_year"] for o in res["options"])


def test_components_are_reported_not_collapsed_into_one_score():
    res = ro.generate("RCW", CROPS, AN_GIANG)
    keep = res["options"][0]["components"]
    assert keep["same_family_adjacent"] == 3 and keep["has_legume"] is False and keep["gaez_mean"] == 8460
    assert keep["days_with_buffer"] == 336 and keep["slack_days"] == 29          # 3 x 105 + 3 x 7 (paddy rice gap)
    assert not any("score" in o or "total" in o for o in res["options"])
    div = next(o for o in res["options"] if o["id"] == "diverse")["components"]
    assert div["same_family_adjacent"] == 0 and div["has_legume"] is True and div["days_with_buffer"] == 350


def test_priority_changes_the_order_but_current_stays_first():
    by_yield = ro.generate("RCW", CROPS, AN_GIANG, priorities=["yield"])
    assert ids(by_yield) == ["keep", "legume", "diverse", "other_family"]
    by_pest = ro.generate("RCW", CROPS, AN_GIANG, priorities=["pest_cycle", "yield"])
    assert ids(by_pest)[0] == "keep" and ids(by_pest)[-1] == "other_family"     # still 1 same-family pair
    by_n = ro.generate("RCW", CROPS, AN_GIANG, priorities=["nitrogen"])
    assert ids(by_n)[-1] == "other_family"                                       # the only one without a legume


def test_unsupported_priorities_are_declared_not_ignored_silently():
    res = ro.generate("RCW", CROPS, AN_GIANG, priorities=["income", "erosion", "yield"])
    assert {u["priority"] for u in res["unsupported_priorities"]} == {"income", "erosion"}
    assert [r["priority"] for r in res["ranked_by"]] == ["yield"]
    assert any("giá" in m for m in res["missing"])


def test_wetland_rice_to_upland_crop_warns_about_drainage():
    legume = next(o for o in ro.generate("RCW", CROPS, AN_GIANG)["options"] if o["id"] == "legume")
    assert any("thoát nước" in r for r in legume["risks"])
    assert any("họ đậu" in b for b in legume["benefits"])


def test_upland_field_never_gets_a_flooded_crop():
    suit = {"MZE": 7000, "RCW": 9500, "TAROW": 9000, "SOY": 6500, "GRD": 6800, "SPO": 6000}
    res = ro.generate("MZE", CROPS, suit)
    used = {c for o in res["options"] for c in o["sequence"]}
    assert used and "RCW" not in used and "TAROW" not in used


def test_legume_current_skips_the_legume_template():
    res = ro.generate("SOY", CROPS, {"SOY": 6277, "RCW": 8460, "MZE": 7000, "SPO": 7273, "TOM": 5781})
    assert "legume" not in ids(res)
    assert any(s["id"] == "legume" and "họ đậu" in s["reason"] for s in res["skipped"])


def test_perennial_crop_has_no_options_and_says_why():
    res = ro.generate("COF", CROPS, {"COF": 8129, "RCW": 8460})
    assert res["options"] == [] and "lâu năm" in res["message"]


def test_no_candidates_leaves_only_the_current_option_with_reasons():
    res = ro.generate("RCW", CROPS, {"RCW": 8460})
    assert ids(res) == ["keep"]
    assert {s["id"] for s in res["skipped"]} == {"legume", "other_family", "diverse"}


def test_candidates_must_reach_the_fao_moderately_suitable_floor():
    suit = {"RCW": 8000, "COW": 3999, "GRD": 4000, "SOY": 4801}        # FAO: 4000 = lower bound of "moderately suitable"
    assert ro.eligible("RCW", CROPS, suit) == ["SOY", "GRD"]
    assert ro.eligible("RCW", CROPS, suit, min_index=2000) == ["SOY", "GRD", "COW"]


def test_gaez_class_labels_follow_the_fao_table():
    assert ro.gaez_class(8460) == "Rất phù hợp" and ro.gaez_class(8000) == "Rất phù hợp"
    assert ro.gaez_class(7999) == "Phù hợp" and ro.gaez_class(4000) == "Trung bình"
    assert ro.gaez_class(3999).startswith("Biên") and ro.gaez_class(1500).startswith("Rất biên")
    assert ro.gaez_class(0).startswith("Không phù hợp") and ro.gaez_class(None).startswith("Không phù hợp")
    ev = ro.generate("RCW", CROPS, AN_GIANG)["options"][1]["evidence"]
    assert {e["crop_code"]: e["gaez_class"] for e in ev}["COW"] == "Phù hợp"      # 7272


def test_current_crop_below_the_floor_is_flagged_and_alternatives_stay_above_it():
    suit = {"RCW": 3981, "COW": 4991, "CSV": 5433, "SPO": 4664, "GRD": 3595}      # Dak Lak style: rice itself is "Biên"
    res = ro.generate("RCW", CROPS, suit)
    assert res["current_gaez"]["class"].startswith("Biên") and any("dưới ngưỡng" in w for w in res["warnings"])
    assert all(suit[c] >= 4000 for o in res["options"][1:] for c in o["sequence"] if c != "RCW")


def test_gap_is_7_days_between_paddy_rice_crops_and_15_otherwise_and_both_are_echoed():
    res = ro.generate("RCW", CROPS, AN_GIANG)
    a = res["assumptions"]
    assert a["gap_rice"]["days"] == 7 and a["gap_other"]["days"] == 15 and a["min_index"]["value"] == 4000
    assert not any(v["custom"] for v in (a["gap_rice"], a["gap_other"], a["min_index"]))
    assert "PMC7059783" in a["gap_rice"]["source"] and "chưa có nguồn" in a["gap_other"]["source"]
    gaps = {"rice": 7, "other": 15}
    assert ro.gap_total(["RCW", "RCW", "RCW"], gaps) == 21
    assert ro.gap_total(["RCW", "RCW", "COW"], gaps) == 7 + 15 + 15           # only RCW->RCW is the cheap pair
    assert ro.gap_total(["COW"], gaps) == 15


def test_user_can_change_both_gaps_and_the_result_says_so():
    res = ro.generate("RCW", CROPS, AN_GIANG, gap_rice=10, gap_other=5, min_index=5000)
    a = res["assumptions"]
    assert a["gap_rice"] == {**a["gap_rice"], "days": 10, "custom": True}
    assert a["gap_other"]["days"] == 5 and a["gap_other"]["custom"] is True
    assert a["min_index"]["value"] == 5000 and a["min_index"]["custom"] is True
    assert res["options"][0]["components"]["days_with_buffer"] == 315 + 30


def test_changing_the_gap_can_change_the_number_of_seasons_and_warns():
    res = ro.generate("RCW", CROPS, AN_GIANG, gap_rice=30)                    # 3 x 105 + 3 x 30 = 405 > 365
    assert res["seasons"] == 2
    assert any("2 thay vì 3" in w for w in res["warnings"])
    explicit = ro.generate("RCW", CROPS, AN_GIANG, gap_rice=30, seasons=3)
    assert explicit["message"].startswith("3 vụ")                             # explicit seasons: refused, not silently changed


@pytest.mark.parametrize("kwargs", [{"gap_rice": -1}, {"gap_other": 61}, {"min_index": 10001}, {"gap_rice": "7"},
                                    {"gap_other": True}])
def test_out_of_range_parameters_are_rejected(kwargs):
    with pytest.raises(ValueError):
        ro.generate("RCW", CROPS, AN_GIANG, **kwargs)


def test_options_close_to_the_edge_say_how_little_room_is_left():
    suit = {"RCW": 8460, "TOM": 5781}
    res = ro.generate("RCW", CROPS, suit, gap_other=15)
    tom = next(o for o in res["options"] if o["id"] == "other_family")
    assert tom["components"]["slack_days"] == 365 - (105 + 105 + 105 + 7 + 15 + 15) == 13
    tight = ro.generate("RCW", CROPS, suit, gap_other=19)                     # 315 + 7 + 19 + 19 = 360, 5 days left
    t2 = next(o for o in tight["options"] if o["id"] == "other_family")
    assert t2["components"]["slack_days"] == 5 and any("Sát mép" in r for r in t2["risks"])
    over = ro.generate("RCW", CROPS, suit, gap_other=22)                      # 366 > 365: no longer fits, so it is dropped
    assert "other_family" not in [o["id"] for o in over["options"]]
    assert any(s["id"] == "other_family" for s in over["skipped"])


def test_long_cycle_crop_gets_one_season_and_no_diverse_option():
    res = ro.generate("CSV", CROPS, {"CSV": 7705, "SOY": 6277, "SPO": 7273, "RCW": 8460, "GRD": 7182})
    assert res["seasons"] == 1 and "diverse" not in ids(res)
    assert any(s["id"] == "diverse" for s in res["skipped"])


def test_too_many_seasons_for_the_year_is_refused():
    res = ro.generate("CSV", CROPS, {"CSV": 7705}, seasons=2)        # 2 x 210 d + buffer > 365
    assert res["options"] == [] and "không vừa" in res["message"]


def test_unknown_crop_raises():
    with pytest.raises(ValueError):
        ro.generate("NOPE", CROPS, AN_GIANG)


def test_assumptions_are_part_of_every_result():
    res = ro.generate("RCW", CROPS, AN_GIANG)
    assert "chưa được xếp lịch" in res["assumptions"]["season_order"]
    assert res["options"][1]["evidence_source"].startswith("FAO GAEZ v5")


def test_main_crop_stays_in_at_least_one_season_whenever_there_are_two_or_more():
    for kwargs in ({}, {"gap_rice": 30}, {"seasons": 2}, {"gap_other": 40}):
        res = ro.generate("RCW", CROPS, AN_GIANG, priorities=["nitrogen", "yield"], **kwargs)
        assert res["seasons"] >= 2
        assert all("RCW" in o["sequence"] for o in res["options"]), (kwargs, [o["sequence"] for o in res["options"]])
        assert "ít nhất 1 vụ cây hiện tại" in res["principle"]


def test_with_two_seasons_diverse_is_dropped_as_a_twin_not_replaced_by_a_full_change():
    res = ro.generate("RCW", CROPS, AN_GIANG, gap_rice=30)                      # 2 seasons
    assert res["seasons"] == 2
    assert ids(res) == ["keep", "legume", "other_family"] or set(ids(res)) == {"keep", "legume", "other_family"}
    assert seq(res, "legume") == ["RCW", "COW"]
    skipped = next(s for s in res["skipped"] if s["id"] == "diverse")
    assert "Trùng với phương án" in skipped["reason"] and "giữ 1 vụ cây hiện tại" in skipped["reason"]
    assert len(res["options"]) >= 3                                             # the challenge still gets >= 3


def test_single_season_crop_says_alternatives_are_next_year_crops():
    res = ro.generate("CSV", CROPS, {"CSV": 7705, "SOY": 6277, "SPO": 7273, "GRD": 7182})
    assert res["seasons"] == 1 and "năm kế tiếp" in res["principle"]


# GAEZ index at the Son La cell (21.15N 104.05E), rain-fed + high inputs, printed from data/silver/gaez_grid.csv:
# every annual crop is far below the FAO floor of 4000 (very marginal)
SON_LA = {"MZE": 452, "RCW": 988, "RCD": 981, "CSV": 675, "SPO": 643, "ONI": 635, "COW": 621, "GRD": 620,
          "TOM": 537, "WPO": 495, "CAB": 465, "SOY": 461}


def test_result_always_carries_the_fao_class_table_for_the_interface():
    tbl = ro.generate("RCW", CROPS, AN_GIANG)["index_classes"]
    assert [r["min_index"] for r in tbl] == [8000, 6000, 4000, 2000, 1]
    assert tbl[0]["class"] == "Rất phù hợp" and tbl[2]["class"] == "Trung bình" and tbl[3]["fao_yield_pct"] == "20–40"
    assert all({"min_index", "max_index", "class", "fao_yield_pct", "meaning"} <= set(r) for r in tbl)
    assert ro.generate("COF", CROPS, AN_GIANG)["index_classes"] == tbl            # also when there are no options


def test_son_la_gives_only_keep_by_default_and_hints_how_far_to_lower_the_floor():
    res = ro.generate("MZE", CROPS, SON_LA)
    assert ids(res) == ["keep"]
    hint = res["floor_hint"]
    assert hint["min_index"] is not None and hint["min_index"] < 4000 and hint["below_fao_floor"] is True
    assert hint["options_if_lowered"] >= 3 and "Hạ ngưỡng xuống" in hint["message"]
    assert all(c.startswith("Rất biên") for c in hint["classes"])                  # every Son La crop is "very marginal"
    lowered = ro.generate("MZE", CROPS, SON_LA, min_index=hint["min_index"])      # the hint really delivers >= 3 options
    assert len(lowered["options"]) >= 3 and lowered["floor_hint"] is None


def test_lowering_the_floor_warns_and_marks_every_crop_under_the_fao_floor():
    res = ro.generate("MZE", CROPS, SON_LA, min_index=500)
    assert any("thấp hơn 4000" in w for w in res["warnings"])
    for o in res["options"]:
        assert any("dưới ngưỡng 4000 của FAO" in r for r in o["risks"]), o["id"]
        assert all(e["gaez_class"].startswith("Rất biên") for e in o["evidence"])
    assert res["assumptions"]["min_index"]["custom"] is True and res["assumptions"]["min_index"]["value"] == 500


def test_no_hint_when_there_are_enough_options_and_no_floor_warning_at_default():
    res = ro.generate("RCW", CROPS, AN_GIANG)
    assert res["floor_hint"] is None and len(res["options"]) >= 3
    assert not any("thấp hơn 4000" in w for w in res["warnings"])


def test_hint_says_so_when_even_the_lowest_floor_cannot_give_three_options():
    res = ro.generate("RCW", CROPS, {"RCW": 8460})                             # nothing else to rotate with
    assert res["floor_hint"]["min_index"] is None and "không đủ 3 phương án" in res["floor_hint"]["message"]


def test_hint_search_does_not_recurse_forever_and_uses_the_same_settings():
    res = ro.generate("MZE", CROPS, SON_LA, gap_other=20, priorities=["nitrogen"])
    assert res["floor_hint"] is not None
    lowered = ro.generate("MZE", CROPS, SON_LA, gap_other=20, priorities=["nitrogen"],
                          min_index=res["floor_hint"]["min_index"])
    assert len(lowered["options"]) == res["floor_hint"]["options_if_lowered"]
