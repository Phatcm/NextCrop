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
    ddl, views = dryrun.translate(stmts, pg.LOAD_ORDER)
    assert sum(s.startswith("CREATE TABLE") for s in ddl) == 13 and len(views) == 2
    assert not any(" ~ " in s for s in ddl)


def test_valid_data_passes_and_views_compile(tmp_path):
    res = run(tmp_path, dim_region=REGION, dim_crop=CROP,
              gaez_suitability=GAEZ_HEAD + "r1,RCW,HRLM,HP0120,AGERA5,HIST,144,144,8500\n")
    assert res["errors"] == [] and res["warnings"] == []
    assert res["counts"]["gaez_suitability"] == 1
    top = res["connection"].execute("SELECT crop_code, rank FROM v_crop_ranking").fetchall()
    assert top == [("RCW", 1)]


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
