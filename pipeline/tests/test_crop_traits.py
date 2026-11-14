from pathlib import Path

import pytest
import yaml

from src.extractors import gaez
from src.transformers.crop_traits import load_traits, merge_into_dim_crop

ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
TRAITS = load_traits(ROOT / "crop_traits.csv")

HEADER = ("crop_code,res02_code,gaez_group,life_cycle,is_legume,family,cycle_days_min,cycle_days_max,"
          "min_temp_c,traits_source,family_source,notes\n")


def csv_file(tmp_path, body):
    p = tmp_path / "t.csv"
    p.write_text(HEADER + body, encoding="utf-8")
    return p


def test_every_config_crop_has_traits_and_nothing_else():
    rows = merge_into_dim_crop(gaez.crop_dim_rows(CFG["gaez"]), TRAITS)
    assert len(rows) == len(CFG["gaez"]["crops"]) == 24
    assert {r["crop_code"] for r in rows} == set(TRAITS)


def test_legumes_are_the_three_gaez_flags():
    assert {c for c, t in TRAITS.items() if t["is_legume"]} == {"SOY", "GRD", "COW"}
    assert all(t["is_legume"] is not None for t in TRAITS.values())      # no crop left undecided


def test_perennials_have_no_season_cycle_and_annuals_with_gaez_row_have_one():
    for code, t in TRAITS.items():
        if t["life_cycle"] == "perennial":
            assert t["cycle_days_min"] is None, code
        elif "Appendix 4-6 (A4-6.1" in (t["traits_source"] or ""):
            assert t["cycle_days_min"] is not None and t["cycle_days_min"] <= t["cycle_days_max"], code


def test_notes_survive_with_commas_and_diacritics():
    assert "kiến thức chung, chưa kiểm chứng" in TRAITS["CSH"]["notes"]
    assert "chè Trung Quốc 5" in TRAITS["TEA"]["notes"]
    assert "min temp 5 for China tea, 10 for hybrid" in TRAITS["TEA"]["traits_source"]


def test_every_crop_has_family_life_cycle_and_sources():
    for code, t in TRAITS.items():
        assert t["family"] and t["life_cycle"] and t["traits_source"] and t["family_source"], code


def test_solanaceae_and_cacao_coconut_codes_are_right():
    assert TRAITS["WPO"]["family"] == TRAITS["TOM"]["family"] == "Solanaceae"   # same family: not in a row
    assert TRAITS["CON"]["res02_code"] == "COCN"                                # COCO is cacao
    assert len({t["res02_code"] for t in TRAITS.values()}) == len(TRAITS)       # RES02 codes are unique


def test_crops_without_a_gaez_parameter_row_are_declared_not_guessed():
    for code in ("TAROW", "SES", "CSH", "WMEL"):
        t = TRAITS[code]
        assert t["cycle_days_min"] is None and t["min_temp_c"] is None
        assert "no row found" in t["traits_source"]


@pytest.mark.parametrize("body,msg", [
    ("X,XX,G,monthly,false,F,,,,s,s,\n", "life_cycle"),
    ("X,XX,G,annual,maybe,F,,,,s,s,\n", "is_legume"),
    ("X,XX,G,annual,false,F,200,100,,s,s,\n", "min <= max"),
    ("X,XX,G,annual,false,F,100,,,s,s,\n", "both be set"),
    ("X,XX,G,perennial,false,F,300,300,,s,s,\n", "perennial"),
    ("X,XX,G,annual,false,F,abc,100,,s,s,\n", "not a number"),
    ("X,XX,G,annual,false,F,,,,s,s,\nX,XX,G,annual,false,F,,,,s,s,\n", "duplicate"),
    ("X,XX,G,annual,false,F,,,,s,s,cay lau nam, kien thuc chung\n", "wrong number of cells"),   # unquoted comma
    ("X,XX,G,annual,false,F,,,,s\n", "wrong number of cells"),                                    # too few cells
])
def test_malformed_rows_are_rejected(tmp_path, body, msg):
    with pytest.raises(ValueError, match=msg):
        load_traits(csv_file(tmp_path, body))


def test_missing_or_stale_traits_fail_the_merge():
    rows = gaez.crop_dim_rows({"crops": [{"code": "RCW", "name_vi": "Lúa"}, {"code": "NEW", "name_vi": "Mới"}]})
    with pytest.raises(ValueError, match="missing \\['NEW'\\]"):
        merge_into_dim_crop(rows, {"RCW": TRAITS["RCW"]})
    with pytest.raises(ValueError, match="unknown \\['MZE'\\]"):
        merge_into_dim_crop(rows[:1], {"RCW": TRAITS["RCW"], "MZE": TRAITS["MZE"]})
