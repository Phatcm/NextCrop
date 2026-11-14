import os
from pathlib import Path

import pytest

from src.db import dryrun
from src.db import postgres as pg

MIG = Path(__file__).resolve().parents[1] / "db" / "migrations"
SQL = "\n".join(p.read_text(encoding="utf-8") for p in sorted(MIG.glob("*.sql")))

REGION = ("region_id,name,status,lon_min,lat_min,lon_max,lat_max,center_lat,center_lon\n"
          "r1,R1,sample,100,19,100.1,19.1,19.05,100.05\n")
CROP = "crop_code,name_vi,name_verified\nRCW,Lúa nước,True\n"
GAEZ_HEAD = "region_id,crop_code,input_mode,period,climate,ssp,n_px,n_valid,value_mean\n"


def silver(tmp_path, **tables):
    for table, text in tables.items():
        d = tmp_path / table / "region_id=r1"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{table}.csv").write_text(text, encoding="utf-8-sig")
    return tmp_path


def run(tmp_path, **tables):
    return dryrun.dry_run(silver(tmp_path, **tables), SQL, log=lambda *_: None)


def test_ddl_types_and_translation_cover_every_table():
    stmts = pg.split_sql(SQL)
    types = dryrun.ddl_types(stmts)
    assert set(pg.LOAD_ORDER) <= set(types)
    assert types["power_daily"]["t2m"] == "double precision" and types["power_daily"]["date"] == "date"
    assert types["dim_region"]["year_start"] == "smallint" and types["dim_region"]["mcd12q1_is_cropland"] == "boolean"
    assert types["power_daily"]["prectotcorr_qa"] == "text"          # added by ALTER in 002
    assert types["gaez_grid"]["hrlm"] == "smallint" and types["gaez_grid"]["lat"] == "double precision"
    ddl, views = dryrun.translate(stmts, pg.LOAD_ORDER)
    assert sum(s.startswith("CREATE TABLE") for s in ddl) == 25 and len(views) == 2
    assert not any(" ~ " in s for s in ddl)


def test_valid_data_passes_and_views_compile(tmp_path):
    res = run(tmp_path, dim_region=REGION, dim_crop=CROP,
              gaez_suitability=GAEZ_HEAD + "r1,RCW,HRLM,HP0120,AGERA5,HIST,144,144,8500\n")
    assert res["errors"] == [] and res["warnings"] == []
    assert res["counts"]["gaez_suitability"] == 1
    top = res["connection"].execute("SELECT crop_code, rank FROM v_crop_ranking").fetchall()
    assert top == [("RCW", 1)]


def test_create_or_replace_view_replaces_the_earlier_definition_of_the_same_view():
    stmts = ["CREATE VIEW v AS SELECT 1 AS a", "CREATE VIEW w AS SELECT 5 AS z",
             "CREATE OR REPLACE VIEW v AS SELECT 2 AS a, 3 AS b"]
    _, views = dryrun.translate(stmts, [])
    assert views == ["CREATE VIEW v AS SELECT 2 AS a, 3 AS b", "CREATE VIEW w AS SELECT 5 AS z"]


def test_crop_ranking_view_has_traits_and_ranks_annual_crops_separately(tmp_path):
    crops = ("crop_code,name_vi,name_verified,life_cycle,gaez_group,water_regime\n"
             "RCW,Lúa nước,True,annual,Cereals,wetland\n"
             "CON,Dừa,True,perennial,Fruits,upland\n"
             "SOY,Đậu tương,True,annual,Oil crops,upland\n")
    gaez = (GAEZ_HEAD + "r1,RCW,HRLM,HP0120,AGERA5,HIST,4,4,8000\n" + "r1,CON,HRLM,HP0120,AGERA5,HIST,4,4,9000\n"
            + "r1,SOY,HRLM,HP0120,AGERA5,HIST,4,4,7000\n")
    res = run(tmp_path, dim_region=REGION, dim_crop=crops, gaez_suitability=gaez)
    assert res["errors"] == [] and res["warnings"] == []
    rows = res["connection"].execute(
        "SELECT crop_code, rank, rank_annual, life_cycle, gaez_group, water_regime FROM v_crop_ranking "
        "ORDER BY rank").fetchall()
    assert rows == [("CON", 1, None, "perennial", "Fruits", "upland"),        # coconut is first overall, not annual
                    ("RCW", 2, 1, "annual", "Cereals", "wetland"),
                    ("SOY", 3, 2, "annual", "Oil crops", "upland")]


@pytest.mark.parametrize("name,tables,needle", [
    ("float in integer column", {"dim_region": REGION, "dim_crop": CROP,
        "gaez_suitability": GAEZ_HEAD + "r1,RCW,HRLM,HP0120,AGERA5,HIST,144.0,144,8500\n"}, "not an integer"),
    ("NaN in double column", {"dim_region": REGION, "dim_crop": CROP,
        "gaez_suitability": GAEZ_HEAD + "r1,RCW,HRLM,HP0120,AGERA5,HIST,144,144,nan\n"}, "non-finite"),
    ("CHECK range", {"dim_region": REGION, "dim_crop": CROP,
        "gaez_suitability": GAEZ_HEAD + "r1,RCW,HRLM,HP0120,AGERA5,HIST,144,144,12000\n"}, "CHECK"),
    ("CHECK enum", {"dim_region": REGION, "dim_crop": CROP,
        "gaez_suitability": GAEZ_HEAD + "r1,RCW,XXXX,HP0120,AGERA5,HIST,144,144,100\n"}, "CHECK"),
    ("foreign key (unknown crop)", {"dim_region": REGION, "dim_crop": CROP,
        "gaez_suitability": GAEZ_HEAD + "r1,ZZZ,HRLM,HP0120,AGERA5,HIST,144,144,100\n"}, "FOREIGN KEY"),
    ("duplicate primary key", {"dim_region": REGION, "dim_crop": CROP,
        "gaez_suitability": GAEZ_HEAD + "r1,RCW,HRLM,HP0120,AGERA5,HIST,1,1,1\nr1,RCW,HRLM,HP0120,AGERA5,HIST,1,1,2\n"},
        "UNIQUE"),
    ("bad boolean", {"dim_region": REGION, "dim_crop": "crop_code,name_vi,name_verified\nRCW,Lua,maybe\n"},
        "not a boolean"),
    ("bad date", {"dim_region": REGION, "power_daily": "region_id,date,t2m\nr1,2015-13-40,1\n"}, "must be in"),
    ("bad month format", {"dim_region": REGION, "power_monthly": "region_id,month\nr1,2015-13\n"}, "month format"),
    ("column missing from the table", {"dim_region": REGION + "", "dim_crop": "crop_code,name_vi,extra\nRCW,x,y\n"},
        "not in table"),
])
def test_dry_run_catches_what_postgres_would_reject(tmp_path, name, tables, needle):
    res = run(tmp_path, **tables)
    assert any(needle in e for e in res["errors"]), f"{name}: expected an error containing {needle!r}, got {res['errors']}"


# ---- needs a disposable Postgres (CI sets TEST_DATABASE_URL)
@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")
def test_server_report_on_a_real_server():
    conn = pg.connect(os.environ["TEST_DATABASE_URL"])
    try:
        rep = {name: status for name, status, _ in pg.server_report(conn)}
        assert rep["PostgreSQL >= 14"] == "PASS"
        assert any(k.startswith("database encoding") and v == "PASS" for k, v in rep.items())
        assert not [k for k, v in rep.items() if v == "FAIL"]
    finally:
        conn.close()


POWER_HEAD = "region_id,date,t2m,prectotcorr,prectotcorr_qa\n"


def test_rain_qa_rows_load_and_flag_requires_null_rain(tmp_path):
    ok = run(tmp_path, dim_region=REGION,
             power_daily=POWER_HEAD + "r1,2020-06-13,27.1,12.3,\nr1,2020-06-14,27.5,,removed: 691.0 mm/day > 250 mm/day\n")
    assert ok["errors"] == [] and ok["counts"]["power_daily"] == 2
    bad = run(tmp_path / "x", dim_region=REGION,
              power_daily=POWER_HEAD + "r1,2020-06-14,27.5,691.0,removed: 691.0 mm/day > 250 mm/day\n")
    assert any("CHECK" in e or "constraint" in e.lower() for e in bad["errors"])


def test_gaez_grid_rows_validate(tmp_path):
    head = "lat,lon,crop_code,hilm,hrlm,lilm,lrlm\n"
    ok = run(tmp_path, dim_crop=CROP, gaez_grid=head + "10.45,105.35,RCW,8000,7600,5000,\n")
    assert ok["errors"] == [] and ok["counts"]["gaez_grid"] == 1
    out_of_range = run(tmp_path / "y", dim_crop=CROP, gaez_grid=head + "10.45,105.35,RCW,10001,,,\n")
    assert out_of_range["errors"]
    unknown_crop = run(tmp_path / "z", dim_crop=CROP, gaez_grid=head + "10.45,105.35,XXX,1,,,\n")
    assert unknown_crop["errors"]


def test_rain_validation_tables_validate(tmp_path):
    val = "region_id,year,power_mm,chirps_mm,ratio,status\n"
    best = "region_id,month,power_mm,chirps_mm,best_mm,best_source\n"
    ok = run(tmp_path, dim_region=REGION, rain_validation=val + "r1,2020,2031.0,896.0,2.266,power_high\n",
             rain_monthly_best=best + "r1,2020-01,50.0,40.0,40.0,chirps\nr1,2020-02,30.0,,30.0,power_fallback\n")
    assert ok["errors"] == [] and ok["counts"]["rain_monthly_best"] == 2
    bad_status = run(tmp_path / "a", dim_region=REGION, rain_validation=val + "r1,2020,1.0,1.0,1.0,maybe\n")
    assert bad_status["errors"]
    wrong_best = run(tmp_path / "b", dim_region=REGION, rain_monthly_best=best + "r1,2020-01,50.0,40.0,50.0,chirps\n")
    assert wrong_best["errors"]          # best_mm must equal chirps_mm when best_source = chirps
    negative = run(tmp_path / "c", dim_region=REGION, rain_monthly_best=best + "r1,2020-01,,-1.0,-1.0,chirps\n")
    assert negative["errors"]
