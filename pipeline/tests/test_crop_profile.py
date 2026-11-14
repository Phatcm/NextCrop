import io
import json
import zipfile
from pathlib import Path

import pytest

from src.extractors import faostat, gbif
from src.transformers import crop_profile as cp
from src.transformers.crop_traits import load_traits

MAP_HEAD = "crop_code,scientific_name,faostat_item_code,faostat_match,erosion_protection,cover_confidence,cover_basis\n"


def write_map(tmp_path, body):
    p = tmp_path / "map.csv"
    p.write_text(MAP_HEAD + body, encoding="utf-8")
    return p


def test_committed_map_is_valid_and_covers_every_crop():
    root = Path(__file__).resolve().parents[1]
    traits = load_traits(root / "crop_traits.csv")
    m = cp.load_map(root / "crop_profile_map.csv", known_crops=set(traits))
    assert set(m) == set(traits)                                       # all crops, none invented


@pytest.mark.parametrize("body,msg", [
    ("RCW,Oryza sativa,27,sometimes,high,assumed,x\n", "faostat_match"),
    ("RCW,Oryza sativa,27,direct,great,assumed,x\n", "erosion_protection"),
    ("RCW,Oryza sativa,27,direct,high,sure,x\n", "cover_confidence"),
    ("RCW,Oryza sativa,,direct,high,assumed,x\n", "faostat_item_code"),          # direct without an item
    ("RCW,Oryza sativa,27,none,high,assumed,x\n", "faostat_item_code"),          # none with an item
    ("RCW,Oryza sativa,27,direct,high,assumed,flooded, bunded\n", "cells"),      # unquoted comma shifts the row
    ("RCW,Oryza sativa,27,direct,high,assumed,x\nRCW,Oryza sativa,27,direct,high,assumed,y\n", "duplicate"),
    ("XXX,Oryza sativa,27,direct,high,assumed,x\n", "dim_crop"),
])
def test_load_map_rejects_bad_rows(tmp_path, body, msg):
    with pytest.raises(ValueError, match=msg):
        cp.load_map(write_map(tmp_path, body), known_crops={"RCW"})


PRICES = {"items": {"27": {"item": "Rice", "values": {"usd_per_t": {"2019": 100, "2020": 200, "2021": 300, "2022": 400}}}}}
YIELDS = {"items": {"27": {"item": "Rice", "values": {"yield_kg_ha": {"2020": 5000, "2021": 6000, "2022": 7000, "2023": 8000}}}}}


def test_economics_uses_only_years_present_in_both_and_inside_window():
    e = cp.economics(PRICES, YIELDS, "27", 2020, 2024, 3)
    assert (e["year_from"], e["year_to"], e["n_years"]) == (2020, 2022, 3)          # 2019 no yield, 2023 no price
    assert e["price_usd_per_t"] == 300.0 and e["yield_kg_ha"] == 6000
    assert e["gross_revenue_usd_ha"] == 1800                                          # 300 USD/t x 6 t/ha
    assert cp.economics(PRICES, YIELDS, "27", 2020, 2024, 4) is None                   # too few years: no number
    assert cp.economics(PRICES, YIELDS, "99", 2020, 2024, 3) is None                   # item absent: no number
    assert cp.economics(None, YIELDS, "27", 2020, 2024, 3) is None
    assert cp.economics(PRICES, YIELDS, "", 2020, 2024, 3) is None


def test_build_rows_family_check_and_missing_values_stay_null(tmp_path):
    body = ("RCW,Oryza sativa,27,direct,high,assumed,paddy\n"
            "TOM,Solanum lycopersicum,,none,low,assumed,no item\n"
            "SES,Sesamum indicum,27,direct,low,assumed,x\n")
    cmap = cp.load_map(write_map(tmp_path, body))
    g = {"Oryza sativa": {"family": "Poaceae", "usage_key": 1}, "Solanum lycopersicum": None,
         "Sesamum indicum": {"family": "Pedaliaceae", "usage_key": 2}}
    rows = {r["crop_code"]: r for r in cp.build_rows(
        cmap, g, PRICES, YIELDS, {"RCW": "Poaceae", "TOM": "Solanaceae", "SES": "Lamiaceae"},
        {"econ_years": [2020, 2024], "min_years": 3})}
    assert rows["RCW"]["family_check"] == "match" and rows["RCW"]["gross_revenue_usd_ha"] == 1800
    assert rows["TOM"]["family_check"] == "unverified" and rows["TOM"]["gbif_family"] is None
    assert rows["TOM"]["price_usd_per_t"] is None and rows["TOM"]["gross_revenue_usd_ha"] is None   # none -> NULL, not 0
    assert rows["SES"]["family_check"] == "mismatch"                                  # surfaced, not hidden


def test_faostat_filter_zip_keeps_only_viet_nam_and_needed_elements():
    head = "Area Code,Area,Item Code,Item,Element Code,Element,Year Code,Year,Unit,Value,Flag\n"
    csv_text = head + "\n".join([
        "237,Viet Nam,27,Rice,5532,Producer Price (USD/tonne),2020,2020,USD,310.5,A",
        "237,Viet Nam,27,Rice,5530,Producer Price (LCU/tonne),2020,2020,LCU,7000000,A",
        "237,Viet Nam,27,Rice,5530,Producer Price Index (2014-2016 = 100),2020,2020,index,120,A",
        "237,Viet Nam,27,Rice,5532,Producer Price (USD/tonne),2010,2010,USD,100,A",       # before first_year
        "4,Afghanistan,27,Rice,5532,Producer Price (USD/tonne),2020,2020,USD,999,A",
        "237,Viet Nam,56,Maize,5532,Producer Price (USD/tonne),2020,2020,USD,,A",          # empty value
    ])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Prices_E_All_Data_(Normalized).csv", csv_text.encode("latin-1"))
    out = faostat.filter_zip(buf.getvalue(), "price", 2015)
    assert list(out) == ["27"]
    assert out["27"]["values"] == {"usd_per_t": {"2020": 310.5}, "lcu_per_t": {"2020": 7000000.0}}


def test_faostat_offline_without_cache_returns_none(tmp_path):
    cfg = {"prices_zip_url": "x", "production_zip_url": "y"}
    assert faostat.fetch_vn(cfg, tmp_path, offline=True, log=lambda *_: None) == (None, None)
    (tmp_path / "faostat_vn_price.json").write_text(json.dumps({"source": {}, "items": {}}), encoding="utf-8")
    p, y = faostat.fetch_vn(cfg, tmp_path, offline=True, log=lambda *_: None)
    assert p == {"source": {}, "items": {}} and y is None


def test_gbif_parse():
    assert gbif.parse({"matchType": "NONE"}) is None
    assert gbif.parse({"family": "Poaceae", "usageKey": 7, "status": "ACCEPTED", "matchType": "EXACT",
                       "confidence": 99}) == {"family": "Poaceae", "usage_key": 7, "status": "ACCEPTED",
                                              "match_type": "EXACT", "confidence": 99}
