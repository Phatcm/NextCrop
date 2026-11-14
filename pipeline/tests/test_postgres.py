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
        assert pg.migrate(conn, MIGRATIONS, log=lambda *_: None) == ["001_init", "002_gaez_grid_rain_qa",
                                                                         "003_crop_traits",
                                                                         "004_rain_validation",
                                                                         "005_crop_water_regime",
                                                                         "006_gaez_grid_cropland",
                                                                         "008_gaez_suitability_cropland"]
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
        # rain QA (migration 002): a removed day has NULL rain + a reason; a reason with a value is rejected
        pg.copy_csv(conn, "power_daily", csv("p2.csv",
            "region_id,date,T2M,PRECTOTCORR,PRECTOTCORR_QA\n"
            'r1,2015-01-02,15.0,,"removed: 691.0 mm/day, ERA5 only 22.2 mm/day (cross-check)"\n'))
        assert conn.run("SELECT prectotcorr IS NULL, prectotcorr_qa LIKE 'removed:%' FROM power_daily "
                        "WHERE date = '2015-01-02'") == [[True, True]]
        with pytest.raises(Exception):
            pg.copy_csv(conn, "power_daily", csv("p3.csv",
                "region_id,date,T2M,PRECTOTCORR,PRECTOTCORR_QA\nr1,2015-01-03,15.0,691.0,removed\n"))
        # nationwide GAEZ grid (migration 002)
        pg.copy_csv(conn, "gaez_grid", csv("gg.csv",
            "lat,lon,crop_code,hilm,hrlm,lilm,lrlm\n10.45,105.35,RCW,8000,7600,5000,\n"))
        assert conn.run("SELECT hrlm, lrlm FROM gaez_grid WHERE crop_code = 'RCW'") == [[7600, None]]
        with pytest.raises(Exception):   # out-of-range value -> CHECK
            pg.copy_csv(conn, "gaez_grid", csv("gg2.csv", "lat,lon,crop_code,hilm\n10.55,105.35,RCW,10001\n"))
        # crop traits (migration 003)
        pg.copy_csv(conn, "dim_crop", csv("c2.csv",
            "crop_code,name_vi,name_verified,life_cycle,is_legume,cycle_days_min,cycle_days_max\n"
            "SOY,Đậu tương,True,annual,True,105,135\nCOF,Cà phê,True,perennial,False,,\n"))
        assert conn.run("SELECT is_legume FROM dim_crop WHERE crop_code = 'SOY'") == [[True]]
        with pytest.raises(Exception):   # perennial crop with a per-season cycle -> CHECK
            pg.copy_csv(conn, "dim_crop", csv("c3.csv",
                "crop_code,name_vi,name_verified,life_cycle,cycle_days_min,cycle_days_max\n"
                "RUB,Cao su,True,perennial,300,300\n"))
        with pytest.raises(Exception):   # min > max -> CHECK
            pg.copy_csv(conn, "dim_crop", csv("c4.csv",
                "crop_code,name_vi,name_verified,life_cycle,cycle_days_min,cycle_days_max\n"
                "CSV,Sắn,True,annual,270,210\n"))
        # CHIRPS rain reference (migration 004)
        pg.copy_csv(conn, "rain_monthly_best", csv("rb.csv",
            "region_id,month,power_mm,chirps_mm,best_mm,best_source\nr1,2015-01,50.0,40.0,40.0,chirps\n"))
        with pytest.raises(Exception):   # best_mm must equal chirps_mm for best_source = chirps
            pg.copy_csv(conn, "rain_monthly_best", csv("rb2.csv",
                "region_id,month,power_mm,chirps_mm,best_mm,best_source\nr1,2015-02,50.0,40.0,50.0,chirps\n"))
        with pytest.raises(Exception):   # unknown region -> foreign key
            pg.copy_csv(conn, "power_monthly", csv("m.csv", "region_id,month\nnope,2015-01\n"))
        with pytest.raises(Exception):   # out-of-range value -> CHECK
            pg.copy_csv(conn, "gaez_suitability", csv("g2.csv",
                "region_id,crop_code,input_mode,period,climate,ssp,n_px,n_valid,value_mean\n"
                "r1,RCW,LILM,HP0120,AGERA5,HIST,1,1,12000\n"))
    finally:
        conn.close()
