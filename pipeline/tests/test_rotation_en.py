"""English output of the rotation generator (lang="en") and the guarantee that Vietnamese stays as it was."""
import csv
import re
from pathlib import Path
from string import Formatter

import pytest

from src.rotation import options as ro
from src.rotation.crop_names import NAMES_EN

VIETNAMESE = re.compile("[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)


def crop(code, vi, life="annual", legume=False, family="Poaceae", water="upland", cmin=100):
    return {"crop_code": code, "name_vi": vi, "name_en": NAMES_EN[code], "life_cycle": life, "is_legume": legume,
            "family": family, "cycle_days_min": None if life == "perennial" else cmin, "water_regime": water}


CROPS = {c["crop_code"]: c for c in [
    crop("RCW", "Lúa nước", water="wetland", cmin=105), crop("MZE", "Ngô", cmin=100),
    crop("COW", "Đậu đũa", legume=True, family="Fabaceae", cmin=80),
    crop("SPO", "Khoai lang", family="Convolvulaceae", cmin=120), crop("TOM", "Cà chua", family="Solanaceae", cmin=100),
    crop("COF", "Cà phê", life="perennial", family="Rubiaceae")]}
GOOD = {"RCW": 9200, "MZE": 7000, "COW": 7778, "SPO": 7778, "TOM": 7778, "COF": 8000}
WEAK = {"RCW": 1800, "MZE": 1500, "COW": 1200, "SPO": 3000, "TOM": 2600, "COF": 8000}


def vietnamese_strings(obj, path="$"):
    """Every string in the result that contains Vietnamese letters, except the `name_vi` fields (which are data)."""
    if isinstance(obj, str):
        return [(path, obj)] if VIETNAMESE.search(obj) else []
    if isinstance(obj, dict):
        return [x for k, v in obj.items() if k != "name_vi" for x in vietnamese_strings(v, f"{path}.{k}")]
    if isinstance(obj, list):
        return [x for i, v in enumerate(obj) for x in vietnamese_strings(v, f"{path}[{i}]")]
    return []


def test_both_languages_have_the_same_keys_and_placeholders():
    assert set(ro.STRINGS["vi"]) == set(ro.STRINGS["en"])
    for key in ro.STRINGS["vi"]:
        vi = {f for _, f, _, _ in Formatter().parse(ro.STRINGS["vi"][key]) if f}
        en = {f for _, f, _, _ in Formatter().parse(ro.STRINGS["en"][key]) if f}
        assert vi == en, f"{key}: placeholders differ {vi} vs {en}"


def test_every_crop_of_the_project_has_an_english_name():
    with open(Path(__file__).resolve().parents[1] / "crop_traits.csv", encoding="utf-8-sig", newline="") as f:
        codes = {r["crop_code"] for r in csv.DictReader(f)}
    assert codes and codes <= set(NAMES_EN), f"missing English names: {sorted(codes - set(NAMES_EN))}"
    assert all(v and not VIETNAMESE.search(v) for v in NAMES_EN.values())


@pytest.mark.parametrize("cur,suit,kw", [
    ("RCW", GOOD, {}), ("RCW", GOOD, {"seasons": 2, "priorities": ["nitrogen"]}), ("MZE", GOOD, {"min_index": 2000}),
    ("RCW", WEAK, {}), ("RCW", GOOD, {"gap_other": 60}), ("RCW", GOOD, {"priorities": ["income", "water", "x"]}),
    ("COF", GOOD, {}), ("RCW", GOOD, {"min_index": 1000}),
])
def test_english_result_contains_no_vietnamese_sentence(cur, suit, kw):
    res = ro.generate(cur, CROPS, suit, lang="en", **kw)
    assert vietnamese_strings(res) == []


def test_english_result_uses_english_names_and_labels():
    res = ro.generate("RCW", CROPS, GOOD, lang="en", priorities=["nitrogen"])
    assert res["lang"] == "en"
    assert [o["label"] for o in res["options"]][0] == "Keep as is"
    assert res["options"][0]["names"] == ["Wetland rice"] * 3
    legume = next(o for o in res["options"] if o["id"] == "legume")
    assert "Cowpea" in legume["benefits"][0] and legume["evidence"][-1]["name"] == "Cowpea"
    assert legume["evidence"][-1]["name_vi"] == "Đậu đũa"                       # the Vietnamese name stays as data
    assert res["current_gaez"]["class"] == "Very suitable"
    assert res["ranked_by"] == [{"priority": "nitrogen", "meaning": "legumes first"}]
    assert [r["class"] for r in res["index_classes"]][:2] == ["Very suitable", "Suitable"]
    assert res["index_classes"][-1]["fao_yield_pct"] == "under 20"


def test_language_changes_the_words_not_the_options():
    for cur, suit, kw in [("RCW", GOOD, {}), ("RCW", GOOD, {"seasons": 2}), ("MZE", WEAK, {}), ("RCW", GOOD, {"gap_other": 60})]:
        vi, en = ro.generate(cur, CROPS, suit, lang="vi", **kw), ro.generate(cur, CROPS, suit, lang="en", **kw)
        assert [(o["id"], o["sequence"], o["components"]) for o in vi["options"]] == \
               [(o["id"], o["sequence"], o["components"]) for o in en["options"]]
        assert [s["id"] for s in vi["skipped"]] == [s["id"] for s in en["skipped"]]
        assert (vi["floor_hint"] or {}).get("min_index") == (en["floor_hint"] or {}).get("min_index")


def test_vietnamese_is_the_default_and_is_unchanged():
    assert ro.generate("RCW", CROPS, GOOD) == ro.generate("RCW", CROPS, GOOD, lang="vi")
    res = ro.generate("RCW", CROPS, GOOD)
    assert res["options"][0]["label"] == "Giữ nguyên" and res["current_gaez"]["class"] == "Rất phù hợp"
    assert ro.GAP_SOURCES["rice"].startswith("Giữa hai vụ lúa nước") and ro.INDEX_CLASS_TABLE[0]["class"] == "Rất phù hợp"


def test_english_messages_for_the_special_cases():
    assert "perennial" in ro.generate("COF", CROPS, GOOD, lang="en")["message"]
    weak = ro.generate("RCW", CROPS, WEAK, lang="en")
    assert weak["floor_hint"]["message"].startswith("Lower the floor to ") or weak["floor_hint"]["message"].startswith("Lowering the floor")
    assert any("below the floor" in w for w in weak["warnings"])
    assert ro.generate("RCW", CROPS, GOOD, lang="en", priorities=["income"])["unsupported_priorities"] == [
        {"priority": "income", "reason": "no crop prices"}]
    low = ro.generate("RCW", CROPS, GOOD, lang="en", min_index=1000)
    assert any(w.startswith("The floor is set to 1000") for w in low["warnings"])


def test_unknown_language_is_rejected():
    with pytest.raises(ValueError, match="lang"):
        ro.generate("RCW", CROPS, GOOD, lang="fr")
    with pytest.raises(ValueError, match="lang"):
        ro.gaez_class(5000, "de")


def test_a_crop_without_an_english_name_falls_back_to_vietnamese():
    crops = {k: dict(v) for k, v in CROPS.items()}
    crops["COW"].pop("name_en")
    res = ro.generate("RCW", crops, GOOD, lang="en", priorities=["nitrogen"])
    assert "Đậu đũa" in next(o for o in res["options"] if o["id"] == "legume")["benefits"][0]
