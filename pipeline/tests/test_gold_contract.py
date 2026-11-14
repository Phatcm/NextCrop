"""The gold JSON and the silver CSVs are the contract the web app reads. These tests pin that contract:
required keys, units, the rule that a gap is never 0, caveats that must travel with the data, and the files written.
"""
import csv
import json

import pytest

from src.models import NdviPoint, Region
from src.transformers import silver_to_gold as sg

REGION = Region("r1", "Vung 1", (106.25, 20.40, 106.35, 20.50), status="sample", province_2025="P", zone="Z")
UNITS = {"T2M": "C", "PRECTOTCORR": "mm/day"}


def power():
    rows = [{"date": f"2020-01-{d:02d}", "T2M": 20.0 + d / 10, "PRECTOTCORR": None if d == 3 else 1.0} for d in range(1, 6)]
    monthly = [{"month": f"2020-{m:02d}", "T2M": 20.0 + m, "PRECTOTCORR": 2.0} for m in range(1, 13)]
    annual = {"2020": {"T2M": 26.5, "PRECTOTCORR": 2.0}}
    return {"daily": {"units": UNITS, "rows": rows}, "monthly": {"rows": monthly, "annual": annual}}


def ndvi():
    pts = [NdviPoint("2020-01-01", 0.30, 0.30, "measured", False, [], 1.0, 0.0, 0.3),
           NdviPoint("2020-01-17", 0.05, 0.40, "interpolated", True, ["cloud"], 0.5, 0.9, 0.4),
           NdviPoint("2020-02-02", None, None, "missing", True, ["no data"], 0.0, 0.0, None)]
    return {"modis_qa": {"description": "MODIS", "qa": {"accept_reliability": [0, 1]}, "series": pts}}


def gold(**kw):
    args = dict(power=power(), ndvi=ndvi(), smap=None, landcover=None, elevation=None, power_cfg={"community": "AG"})
    args.update(kw)
    return sg.build_region_gold(REGION, 2015, 2025, **args)


def test_top_level_contract_keys_and_metadata():
    g = gold()
    assert set(g) >= {"schema_version", "metadata", "terrain", "landcover", "climate", "ndvi", "soil_moisture",
                      "suitability"}
    m = g["metadata"]
    assert m["region_id"] == "r1" and m["years"] == [2015, 2025] and m["center"] == {"lat": 20.45, "lon": 106.3}
    assert m["bbox"] == [106.25, 20.4, 106.35, 20.5] and m["generated_at"].endswith("+00:00")
    assert any("mô hình" in c for c in m["caveats"]), "the POWER-is-a-model caveat must always be present"
    assert any("nội suy" in c for c in m["caveats"]), "the interpolation caveat must always be present"


def test_climate_block_keeps_units_and_gaps():
    c = gold()["climate"]
    assert c["units"] == UNITS and len(c["monthly"]) == 12
    assert c["missing_days"]["PRECTOTCORR"] == 1 and c["missing_days"]["T2M"] == 0     # a gap is counted, not 0
    assert len(c["normals"]["T2M"]) == 12 and c["normals"]["T2M"][0] == 21.0
    assert "2020" in c["annual_by_year"] and "T2M_anom" in c["annual_by_year"]["2020"]


def test_ndvi_block_rows_follow_the_contract_and_missing_stays_null():
    n = gold()["ndvi"]
    assert n["primary"] == "modis_qa"
    s = n["sources"]["modis_qa"]
    assert s["summary"] == {"n_dates": 3, "n_measured": 1, "n_interpolated": 1, "n_missing": 1,
                            "first": "2020-01-01", "last": "2020-02-02"}
    row = s["series"][0]
    assert set(row) == {"date", "median_raw", "median_final", "source", "flag_bad", "reasons", "valid_frac",
                        "cloud_frac", "smoothed"}
    assert s["series"][2]["median_final"] is None and s["series"][2]["source"] == "missing"
    assert len(s["profile"]) == 23


def test_no_primary_ndvi_when_nothing_was_measured():
    only_missing = {"modis_qa": {"description": "d", "qa": {}, "series": [NdviPoint("2020-01-01", None, None, "missing", True)]}}
    assert gold(ndvi=only_missing)["ndvi"]["primary"] is None


def test_candidate_region_without_landcover_or_with_non_cropland_gets_a_warning():
    cand = Region("c1", "Ung vien", (106.0, 20.0, 106.1, 20.1), status="candidate")
    base = dict(power=None, ndvi={}, smap=None, elevation=None, power_cfg={})
    none = sg.build_region_gold(cand, 2015, 2025, landcover=None, **base)["metadata"]["caveats"]
    assert any("chưa có lớp phủ đất" in c for c in none)
    bad = sg.build_region_gold(cand, 2015, 2025, landcover={"2025": {"cropland_frac": 0.1, "dominant": "Rừng", "n": 25,
                                                                    "classes": {"Rừng": 1.0}}}, **base)["metadata"]["caveats"]
    assert any("CẢNH BÁO" in c and "10%" in c for c in bad)
    sample = sg.build_region_gold(REGION, 2015, 2025, landcover=None, **base)["metadata"]["caveats"]
    assert not any("Vùng ứng viên" in c for c in sample)          # a 'sample' region needs no candidate warning


def test_landcover_check_uses_the_latest_year():
    lc = {"2019": {"cropland_frac": 0.2, "dominant": "x"}, "2024": {"cropland_frac": 0.8, "dominant": "Đất trồng trọt"}}
    chk = sg.landcover_check(lc)
    assert chk == {"year": 2024, "cropland_frac": 0.8, "dominant": "Đất trồng trọt", "is_cropland": True}
    assert sg.landcover_check({"2024": {"cropland_frac": 0.4, "dominant": "x"}})["is_cropland"] is False
    assert sg.landcover_check(None) is None


def test_rain_validation_and_environment_blocks_travel_into_gold_with_caveats():
    months = [{"month": f"2020-{m:02d}", "power_mm": 60.0, "chirps_mm": 30.0, "best_mm": 30.0, "best_source": "chirps"}
              for m in range(1, 13)]
    from src.transformers import rain_validation as rv
    val = rv.validate({m["month"]: 60.0 for m in months}, {m["month"]: 30.0 for m in months}, {"min_years": 1})
    env = {"slope": {"region_id": "r1", "slope_mean_pct": 30.0, "share_gt12_pct": 80.0}, "soil": [], "wdc": [],
           "balance": [], "et0": {"factor": 1.0, "applied": False},
           "erosion": {"slope_mean_pct": 30.0, "share_gt12_pct": 80.0, "mfi": 200.0, "mfi_class": "very_high",
                       "base_hazard": "high"}}
    g = gold(rain_val=val, environment=env)
    assert g["climate"]["rain_best"]["summary"]["verdict"] == "power_biased"
    assert g["environment"]["erosion_context"]["base_hazard"] == "high" and "note" in g["environment"]
    joined = " ".join(g["metadata"]["caveats"])
    assert "climate.rain_best" in joined and "Xói mòn" in joined and "chưa hiệu chuẩn" in joined


def test_smap_l4_block_is_labelled_as_model_not_measurement():
    l4 = [{"date": "2020-01-01", "sm_surface": 0.3, "sm_rootzone": 0.4, "sm_rootzone_pctl": 50.0}] if hasattr(sg, "monthly_mean_l4") else None
    if l4 is None:
        pytest.skip("SMAP L4 is not merged yet")
    g = gold(smap_l4=l4)
    assert "KHÔNG phải đo trực tiếp" in g["soil_moisture_l4"]["note"]


# ---------------------------------------------------------------- files

def read(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_write_csv_empty_list_cells_and_bom(tmp_path):
    sg.write_csv(tmp_path / "a" / "x.csv", [{"a": 1, "b": ["p", "q"], "c": None}])
    assert (tmp_path / "a" / "x.csv").read_bytes().startswith(b"\xef\xbb\xbf")        # utf-8-sig: Excel opens Vietnamese text
    assert read(tmp_path / "a" / "x.csv") == [{"a": "1", "b": "p|q", "c": ""}]          # None is an empty cell, not 0
    sg.write_csv(tmp_path / "empty.csv", [])
    assert (tmp_path / "empty.csv").read_bytes() == "".encode("utf-8-sig")


def test_write_region_writes_flat_silver_tables_with_region_id_and_valid_gold(tmp_path):
    g = gold()
    silver, gold_dir = tmp_path / "silver" / "r1", tmp_path / "gold"
    p = sg.write_region(gold_dir, silver, g, power(), {})
    assert p == gold_dir / "r1.json"
    back = json.loads(p.read_text(encoding="utf-8"))
    assert back["metadata"]["region_id"] == "r1" and back["schema_version"] == sg.SCHEMA_VERSION
    daily = read(silver / "power_daily.csv")
    assert len(daily) == 5 and all(r["region_id"] == "r1" for r in daily)
    assert [r["PRECTOTCORR"] for r in daily][2] == ""                                  # the NULL day stays empty
    assert len(read(silver / "power_monthly.csv")) == 12
    series = read(silver / "ndvi_series.csv")
    assert {r["source_key"] for r in series} == {"modis_qa"} and [r["source"] for r in series] == [
        "measured", "interpolated", "missing"]
    assert (gold_dir / "r1_climate_daily.json").exists()


def test_write_dim_region_and_index_skip_regions_without_gold(tmp_path):
    other = Region("r2", "Vung 2", (106.0, 20.0, 106.1, 20.1))
    silver, gold_dir = tmp_path / "silver", tmp_path / "gold"
    sg.write_region(gold_dir, silver / "r1", gold(), power(), {})
    dim = read(sg.write_dim_region(silver, gold_dir, [REGION, other]))
    assert [r["region_id"] for r in dim] == ["r1"]                                       # r2 has no gold: no invented row
    assert float(dim[0]["center_lat"]) == 20.45 and dim[0]["status"] == "sample"
    idx = json.loads(sg.write_index(gold_dir, [REGION, other]).read_text(encoding="utf-8"))
    assert [r["region_id"] for r in idx["regions"]] == ["r1"] and idx["vn_grid_file"] is None
    assert idx["regions"][0]["ndvi_primary"] == "modis_qa"
