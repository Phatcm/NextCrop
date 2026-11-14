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


def test_candidates_must_reach_the_ratio_of_the_current_index():
    suit = {"RCW": 8000, "COW": 4000, "GRD": 4799, "SOY": 4801}        # floor = 0.6 * 8000 = 4800
    assert ro.eligible("RCW", CROPS, suit) == ["SOY"]
    assert ro.eligible("RCW", CROPS, suit, min_ratio=0.4) == ["SOY", "GRD", "COW"]


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
