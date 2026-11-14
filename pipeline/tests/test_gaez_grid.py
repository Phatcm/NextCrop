import json

import numpy as np
import pytest

from src.extractors import gaez_grid as gg


def test_block_means_ignore_nodata_and_never_make_zero_from_nodata():
    a = np.full((4, 4), -9, dtype=np.int16)
    a[0:2, 0:2] = [[1000, 3000], [-9, 2000]]        # cell (0,0): mean of 1000, 3000, 2000
    a[2:4, 2:4] = 0                                 # cell (1,1): real zeros = unsuitable, not missing
    m = gg.block_means(a, -9, 2)
    assert m.tolist() == [[2000, gg.NO_DATA], [gg.NO_DATA, 0]]


def test_block_means_rejects_a_window_that_does_not_align():
    with pytest.raises(ValueError, match="multiple"):
        gg.block_means(np.zeros((5, 4), dtype=np.int16), -9, 2)


def grid(means, crop_mode):
    return {"bounds": [102.0, 10.0, 102.2, 10.2], "cell_deg": 0.1, "means": means}


def test_build_rows_is_wide_and_leaves_missing_modes_empty():
    gcfg = {"modes": ["HILM", "HRLM", "LILM", "LRLM"]}
    grids = {("RCW", "HRLM"): grid([[7000, gg.NO_DATA], [0, 5000]], None),
             ("RCW", "LRLM"): grid([[3000, gg.NO_DATA], [gg.NO_DATA, 100]], None)}
    rows = gg.build_rows(gcfg, grids)
    by = {(r["lat"], r["lon"]): r for r in rows}
    assert set(by) == {(10.15, 102.05), (10.05, 102.05), (10.05, 102.15)}      # sea cell dropped
    assert by[(10.15, 102.05)] == {"lat": 10.15, "lon": 102.05, "crop_code": "RCW",
                                   "hilm": None, "hrlm": 7000, "lilm": None, "lrlm": 3000}
    assert by[(10.05, 102.05)]["hrlm"] == 0 and by[(10.05, 102.05)]["lrlm"] is None   # 0 stays 0, gap stays NULL
    assert rows[0]["lat"] >= rows[-1]["lat"]                                  # north to south


def test_offline_run_uses_cache_and_reports_missing_files(tmp_path):
    gcfg = {"period": "HP0120", "climate": "AGERA5", "ssp": "HIST", "modes": ["HRLM"],
            "crops": [{"code": "RCW"}, {"code": "MZE"}]}
    gc = {"cell_deg": 0.1, "bbox": [102.0, 10.0, 102.2, 10.2]}
    entry = {**grid([[1, 2], [3, 4]], None), "request_bbox": [102.0, 10.0, 102.2, 10.2]}
    path = gg.cache_path(gcfg, gc, tmp_path, "RCW", "HRLM")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(entry), encoding="utf-8")
    grids, problems = gg.fetch_grids(gcfg, gc, tmp_path, offline=True, log=lambda *_: None)
    assert list(grids) == [("RCW", "HRLM")]
    assert len(problems) == 1 and problems[0].startswith("MZE/HRLM: not cached")


def test_cache_for_another_bbox_or_cell_size_is_not_reused(tmp_path):
    gcfg = {"period": "HP0120", "climate": "AGERA5", "ssp": "HIST", "modes": ["HRLM"], "crops": [{"code": "RCW"}]}
    gc = {"cell_deg": 0.1, "bbox": [102.0, 8.0, 110.0, 24.0]}
    stale = {**grid([[1]], None), "request_bbox": [102.0, 10.0, 102.2, 10.2]}
    path = gg.cache_path(gcfg, gc, tmp_path, "RCW", "HRLM")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(stale), encoding="utf-8")
    grids, problems = gg.fetch_grids(gcfg, gc, tmp_path, offline=True, log=lambda *_: None)
    assert grids == {} and problems
