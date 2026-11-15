"""PgRepo against a real PostgreSQL (CI sets TEST_DATABASE_URL to a disposable database)."""
import os
from pathlib import Path

import pytest

DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL not set")

MIGRATIONS = Path(__file__).resolve().parents[3] / "pipeline" / "db" / "migrations"


@pytest.fixture(scope="module")
def repo():
    from fieldshift_api.repo import PgRepo
    from src.db import postgres as pg
    conn = pg.connect(DSN)
    conn.run("DROP SCHEMA IF EXISTS field_shift CASCADE")
    pg.migrate(conn, MIGRATIONS, log=lambda *_: None)
    conn.run("SET search_path TO field_shift")
    conn.run("INSERT INTO dim_crop (crop_code, name_vi, name_verified, life_cycle, gaez_group, water_regime, is_legume, "
             "family, cycle_days_min, cycle_days_max) VALUES "
             "('RCW','Lúa nước',true,'annual','Cereals','wetland',false,'Poaceae',105,150), "
             "('SOY','Đậu tương',true,'annual','Oil crops','upland',true,'Fabaceae',80,110)")
    conn.run("INSERT INTO gaez_grid (lat, lon, crop_code, hilm, hrlm, lilm, lrlm) VALUES "
             "(10.4583, 105.375, 'RCW', 8200, 8504, 5000, NULL), (10.4583, 105.375, 'SOY', 6500, 6800, NULL, NULL), "
             "(10.375, 105.375, 'RCW', NULL, 7000, NULL, NULL)")
    conn.run("INSERT INTO dim_region (region_id, name, status, lon_min, lat_min, lon_max, lat_max, center_lat, center_lon, ndvi_primary) "
             "VALUES ('r1', 'Region 1', 'candidate', 105.3, 10.4, 105.4, 10.5, 10.45, 105.35, 'modis_qa')")
    conn.run("INSERT INTO vn_grid_monthly (lat, lon, param, yyyymm, value) VALUES "
             "(10.5, 105.5, 'T2M', 201501, 26.0), (10.5, 105.5, 'T2M', 201601, 28.0), (10.5, 105.5, 'T2M', 201502, 27.0), "
             "(10.5, 105.5, 'T2M', 201513, 26.5), (10.5, 105.5, 'T2M', 201503, -999.0), "
             "(10.5, 105.5, 'T2M_MIN', 201501, 20.0), (10.5, 105.5, 'T2M_MAX', 201501, 33.0), (12.0, 108.0, 'T2M', 201501, 22.0)")
    conn.run("INSERT INTO rain_monthly_best (region_id, month, power_mm, chirps_mm, best_mm, best_source) VALUES "
             "('r1', '2015-01', 5.0, 1.0, 1.0, 'chirps'), ('r1', '2016-01', 5.0, 3.0, 3.0, 'chirps')")
    conn.run("INSERT INTO water_balance_monthly (region_id, month, rain_mm, et0_raw_mm, et0_mm, balance_mm, rain_source) VALUES "
             "('r1', '2015-01', 10.0, 100.0, 150.0, -140.0, 'chirps'), ('r1', '2016-01', 30.0, 100.0, 150.0, -120.0, 'chirps'), "
             "('r1', '2015-07', 200.0, 90.0, 120.0, 80.0, 'chirps')")
    conn.run("INSERT INTO ndvi_series (region_id, source_key, date, median_raw, median_final, source, flag_bad, valid_frac, cloud_frac, smoothed) VALUES "
             "('r1', 'modis_qa', '2015-01-01', 0.6, 0.6, 'measured', false, 1.0, 0.0, 0.6), "
             "('r1', 'modis_qa', '2016-01-17', 0.8, 0.8, 'measured', false, 1.0, 0.0, 0.8), "
             "('r1', 'modis_qa', '2015-01-17', 0.9, 0.9, 'interpolated', false, 0.0, 1.0, 0.9), "
             "('r1', 'modis_qa', '2015-02-01', 0.1, 0.1, 'measured', true, 0.2, 0.8, 0.1)")
    conn.close()
    return PgRepo(DSN)


def test_ping_crops_and_cell_values(repo):
    assert repo.ping() is True
    assert repo.crops()["RCW"]["water_regime"] == "wetland" and repo.crops()["SOY"]["is_legume"] is True
    cell = repo.cell_values(10.4583, 105.375)
    assert cell["RCW"] == {"hilm": 8200, "hrlm": 8504, "lilm": 5000, "lrlm": None} and set(cell) == {"RCW", "SOY"}
    assert repo.cell_values(11.0, 106.0) == {}


def test_cells_in_bbox_skip_empty_values_and_respect_the_limit(repo):
    rows = repo.cells_in_bbox(105, 10, 106, 11, "RCW", "hrlm", 10)
    assert rows == [(10.4583, 105.375, 8504), (10.375, 105.375, 7000)]
    assert repo.cells_in_bbox(105, 10, 106, 11, "RCW", "hilm", 10) == [(10.4583, 105.375, 8200)]   # NULL hilm skipped
    assert len(repo.cells_in_bbox(105, 10, 106, 11, "RCW", "hrlm", 1)) == 2                        # limit + 1 signals overflow


def test_mode_is_whitelisted(repo):
    with pytest.raises(ValueError):
        repo.cells_in_bbox(105, 10, 106, 11, "RCW", "hrlm; DROP TABLE x", 5)


def test_the_connection_is_read_only_even_for_the_owner(repo):
    with repo._tx() as c:
        with pytest.raises(Exception, match="read-only"):
            c.run("DELETE FROM field_shift.gaez_grid")
    assert repo.cell_values(10.4583, 105.375)["RCW"]["hrlm"] == 8504        # nothing was deleted, repo still usable


def test_repo_recovers_after_the_connection_dies(repo):
    repo._conn.close()
    assert repo.ping() is True


def test_nasa_power_climatology_ignores_the_annual_value_and_the_fill_value(repo):
    assert sorted(repo.power_cells()) == [(10.5, 105.5), (12.0, 108.0)]
    clim = repo.power_climatology(10.5, 105.5)
    assert clim["years"] == (2015, 2016)
    assert clim["months"][1]["T2M"] == 27.0                          # mean of 26 and 28; the annual 26.5 (month 13) is out
    assert clim["months"][1]["T2M_MIN"] == 20.0 and clim["months"][1]["T2M_MAX"] == 33.0
    assert clim["months"][2]["T2M"] == 27.0 and 3 not in clim["months"]       # March only had POWER's -999 fill value
    assert repo.power_climatology(0.0, 0.0) == {"months": {}, "years": None}


def test_water_balance_climatology_averages_rain_and_et0_per_calendar_month(repo):
    # (month, mean rain, mean ET0, years with data): January has two years (10 and 30 mm rain, ET0 150), July has one
    assert repo.water_balance_climatology("r1") == [(1, 20.0, 150.0, 2), (7, 200.0, 120.0, 1)]
    assert repo.water_balance_climatology("nope") == []


def test_nasa_regions_rain_and_ndvi(repo):
    assert [(r["region_id"], r["ndvi_primary"]) for r in repo.regions()] == [("r1", "modis_qa")]
    assert repo.rain_climatology("r1") == [(1, 2.0, 2)]
    rows = repo.ndvi_climatology("r1", "modis_qa")                    # interpolated and flagged rows are not measurements
    assert len(rows) == 1 and rows[0][0] == 1 and abs(rows[0][1] - 0.7) < 1e-9 and (rows[0][2], rows[0][3], rows[0][4]) == (0.6, 0.8, 2)
    assert repo.ndvi_climatology("r1", "gibs") == [] and repo.rain_climatology("nope") == []
