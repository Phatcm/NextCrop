import os
import ssl
from pathlib import Path

import pytest

from src.db import postgres as pg

MIGRATIONS = Path(__file__).resolve().parents[1] / "db" / "migrations"


def test_split_sql_handles_comments_and_quoted_semicolons():
    sql = """
    -- a comment with 'a quote' and ; semicolon
    CREATE TABLE a (x int);   -- trailing
    COMMENT ON TABLE a IS 'one; two ''quoted'' -- not a comment';
    INSERT INTO a VALUES (1)
    """
    out = pg.split_sql(sql)
    assert out == ["CREATE TABLE a (x int)",
                   "COMMENT ON TABLE a IS 'one; two ''quoted'' -- not a comment'",
                   "INSERT INTO a VALUES (1)"]


def test_real_migration_splits_cleanly():
    stmts = pg.split_sql((MIGRATIONS / "001_init.sql").read_text(encoding="utf-8"))
    assert len(stmts) > 25
    assert all(not s.startswith("--") for s in stmts)
    assert sum(s.startswith("CREATE TABLE") for s in stmts) == 15   # 13 data tables + schema_migrations + pipeline_run
    assert not any("::" in s for s in stmts), "pg8000 treats ':name' as a parameter; use CAST() instead of ::"


def test_load_order_matches_migration_tables():
    created = {s.split()[2] for p in sorted(MIGRATIONS.glob("*.sql")) for s in pg.split_sql(p.read_text(encoding="utf-8"))
               if s.startswith("CREATE TABLE")}
    assert set(pg.LOAD_ORDER) == created - {"schema_migrations", "pipeline_run"}


def test_parse_dsn():
    kw = pg.parse_dsn("postgresql://app:p%40ss@db.example.com:6543/fs?sslmode=require")
    assert (kw["user"], kw["password"], kw["host"], kw["port"], kw["database"]) == (
        "app", "p@ss", "db.example.com", 6543, "fs")
    assert kw["ssl_context"].verify_mode == ssl.CERT_NONE
    kw = pg.parse_dsn("postgres://u@localhost/x")
    assert kw["port"] == 5432 and "ssl_context" not in kw and "password" not in kw
    assert pg.parse_dsn("postgresql://u@h/x?sslmode=verify-full")["ssl_context"].verify_mode == ssl.CERT_REQUIRED
    with pytest.raises(ValueError):
        pg.parse_dsn("mysql://u@h/x")


# ---- integration: needs a disposable database, e.g. TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/test
@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")
def test_migrate_copy_and_constraints(tmp_path):
    conn = pg.connect(os.environ["TEST_DATABASE_URL"])
    try:
        conn.run(f"DROP SCHEMA IF EXISTS {pg.SCHEMA} CASCADE")
        assert pg.migrate(conn, MIGRATIONS, log=lambda *_: None) == ["001_init"]
        assert pg.migrate(conn, MIGRATIONS, log=lambda *_: None) == []        # idempotent
        conn.run(f"SET search_path TO {pg.SCHEMA}")

        def csv(name, text):
            p = tmp_path / name
            p.write_text(text, encoding="utf-8-sig")  # silver CSVs carry a BOM
            return p

        pg.copy_csv(conn, "dim_region", csv("r.csv",
            "region_id,name,status,province_2025,zone,lon_min,lat_min,lon_max,lat_max,center_lat,center_lon,"
            "year_start,year_end,ndvi_primary,mcd12q1_cropland_frac,mcd12q1_dominant,mcd12q1_is_cropland,"
            "gfsad_bbox_crop_frac\nr1,R1,sample,,,100,19,100.1,19.1,19.05,100.05,2015,2025,modis_qa,0.6,Crop,True,\n"))
        pg.copy_csv(conn, "dim_crop", csv("c.csv", "crop_code,name_vi,name_verified\nRCW,Lúa nước,True\nMZE,Ngô,False\n"))
        pg.copy_csv(conn, "gaez_suitability", csv("g.csv",
            "region_id,crop_code,input_mode,period,climate,ssp,n_px,n_valid,value_mean,value_median,value_min,"
            "value_max,value_center\nr1,RCW,HRLM,HP0120,AGERA5,HIST,144,144,8500,8600,0,9300,8700\n"
            "r1,MZE,HRLM,HP0120,AGERA5,HIST,144,144,4000,4100,0,6000,\n"))
        pg.copy_csv(conn, "power_daily", csv("p.csv",
            "region_id,date,T2M,T2M_MAX,T2M_MIN,PRECTOTCORR,RH2M,WS2M,ALLSKY_SFC_SW_DWN,GWETROOT,GWETTOP\n"
            "r1,2015-01-01,15.2,21.4,10.1,0.0,73.6,2.9,16.1,0.68,\n"))
        top = conn.run("SELECT crop_code, rank FROM v_crop_ranking WHERE region_id='r1' ORDER BY rank")
        assert top == [["RCW", 1], ["MZE", 2]]
        assert conn.run("SELECT gwettop IS NULL, name_verified FROM power_daily, dim_crop WHERE crop_code='MZE'") == [[True, False]]
        with pytest.raises(Exception):   # unknown region -> foreign key
            pg.copy_csv(conn, "power_monthly", csv("m.csv", "region_id,month\nnope,2015-01\n"))
        with pytest.raises(Exception):   # out-of-range value -> CHECK
            pg.copy_csv(conn, "gaez_suitability", csv("g2.csv",
                "region_id,crop_code,input_mode,period,climate,ssp,n_px,n_valid,value_mean\n"
                "r1,RCW,LILM,HP0120,AGERA5,HIST,1,1,12000\n"))
    finally:
        conn.close()
