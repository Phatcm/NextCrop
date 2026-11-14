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
