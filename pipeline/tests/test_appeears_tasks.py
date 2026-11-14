import csv

import pytest

from src.extractors import appeears_client as ac
from src.models import Region

R1 = Region("r1", "R1", (100.0, 10.0, 100.1, 10.1))
R2 = Region("r2", "R2", (101.0, 11.0, 101.1, 11.1))
TASK = {"key": "ndvi", "product": "MOD13Q1.061", "layers": ["_250m_16_days_NDVI", "_250m_16_days_pixel_reliability"],
        "points": "grid", "start": "01-01-{start_year}", "end": "12-31-{end_year}"}


def test_build_task_grid_and_center_points_carry_the_region_as_category():
    grid = ac.build_task(TASK, [R1, R2], 5, 2015, 2025)
    pts = grid["params"]["coordinates"]
    assert len(pts) == 50 and {p["category"] for p in pts} == {"r1", "r2"}
    assert pts[0]["id"] == "r1__00" and all(100.0 < p["longitude"] < 100.1 for p in pts if p["category"] == "r1")
    assert grid["params"]["dates"] == [{"startDate": "01-01-2015", "endDate": "12-31-2025"}]
    assert [l["layer"] for l in grid["params"]["layers"]] == TASK["layers"]
    center = ac.build_task({**TASK, "points": "center"}, [R1, R2], 5, 2015, 2025)
    assert len(center["params"]["coordinates"]) == 2


def test_task_hash_is_stable_and_changes_with_any_input():
    a = ac.task_hash(ac.build_task(TASK, [R1], 5, 2015, 2025))
    assert a == ac.task_hash(ac.build_task(TASK, [R1], 5, 2015, 2025))
    assert a != ac.task_hash(ac.build_task(TASK, [R1, R2], 5, 2015, 2025))      # another region set is another task
    assert a != ac.task_hash(ac.build_task(TASK, [R1], 5, 2015, 2024))
    assert a != ac.task_hash(ac.build_task({**TASK, "layers": ["_250m_16_days_NDVI"]}, [R1], 5, 2015, 2025))


def write_results(path, header, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def test_read_results_maps_layers_and_treats_blank_as_none(tmp_path):
    p = tmp_path / "x-results.csv"
    write_results(p, ["ID", "Category", "Latitude", "Longitude", "Date", "MOD13Q1_061__250m_16_days_NDVI",
                      "MOD13Q1_061__250m_16_days_pixel_reliability"],
                  [["r1__00", "r1", "10.0", "100.0", "2020-01-01", "0.5", "0"],
                   ["r1__01", "r1", "10.1", "100.1", "2020-01-01", "", "2"]])
    rows = ac.read_results(p, "MOD13Q1.061", TASK["layers"])
    assert rows[0]["_250m_16_days_NDVI"] == 0.5 and rows[0]["region"] == "r1" and rows[0]["date"] == "2020-01-01"
    assert rows[1]["_250m_16_days_NDVI"] is None and rows[1]["_250m_16_days_pixel_reliability"] == 2.0   # blank is not 0


def test_read_results_fails_loudly_when_a_layer_column_is_missing(tmp_path):
    p = tmp_path / "x-results.csv"
    write_results(p, ["ID", "Category", "Latitude", "Longitude", "Date", "other"], [["r1__00", "r1", "1", "2", "2020-01-01", "1"]])
    with pytest.raises(ValueError, match="no column for layer"):
        ac.read_results(p, "MOD13Q1.061", TASK["layers"])


def test_read_results_derives_region_from_the_point_id_when_category_is_empty(tmp_path):
    p = tmp_path / "x-results.csv"
    write_results(p, ["ID", "Category", "Latitude", "Longitude", "Date", "SPL4SMGP_008_Geophysical_Data_sm_surface"],
                  [["an_giang__00", "", "10", "105", "2020-01-01", "0.31"]])
    rows = ac.read_results(p, "SPL4SMGP.008", ["Geophysical_Data_sm_surface"])
    assert rows[0]["region"] == "an_giang" and rows[0]["Geophysical_Data_sm_surface"] == 0.31


def test_results_csv_finds_the_results_file_or_none(tmp_path):
    assert ac.results_csv(tmp_path / "missing") is None
    (tmp_path / "t").mkdir()
    assert ac.results_csv(tmp_path / "t") is None
    (tmp_path / "t" / "MOD13Q1-061-results.csv").write_text("x", encoding="utf-8")
    assert ac.results_csv(tmp_path / "t").name == "MOD13Q1-061-results.csv"


def test_run_tasks_offline_returns_cached_results_and_never_logs_in(tmp_path, monkeypatch):
    cfg = {"base_url": "http://x", "grid_n": 5, "tasks": [TASK]}
    task = ac.build_task(TASK, [R1], 5, 2015, 2025)
    d = tmp_path / "appeears" / f"ndvi_{ac.task_hash(task)}"
    d.mkdir(parents=True)
    (d / "a-results.csv").write_text("x", encoding="utf-8")
    monkeypatch.setattr(ac.AppEEARS, "login", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not log in")))
    msgs = []
    out = ac.run_tasks(cfg, [R1], 2015, 2025, tmp_path, offline=True, log=msgs.append)
    assert list(out) == ["ndvi"] and out["ndvi"].name == "a-results.csv"
    # nothing cached and offline: no result, no network, a log line saying so
    out2 = ac.run_tasks(cfg, [R2], 2015, 2025, tmp_path, offline=True, log=msgs.append)
    assert out2 == {} and any("offline" in m for m in msgs)


def test_run_tasks_without_credentials_skips_instead_of_failing(tmp_path, monkeypatch):
    monkeypatch.delenv("EARTHDATA_USERNAME", raising=False)
    monkeypatch.delenv("EARTHDATA_PASSWORD", raising=False)
    monkeypatch.setattr(ac, "load_dotenv", lambda *a, **k: None)
    msgs = []
    out = ac.run_tasks({"base_url": "http://x", "tasks": [TASK]}, [R1], 2015, 2025, tmp_path, log=msgs.append)
    assert out == {} and any("EARTHDATA_USERNAME" in m for m in msgs)
