import json

import numpy as np

from src.extractors import gaez_grid as gg


def test_clean_marks_nodata_and_negatives_but_keeps_a_real_zero():
    a = np.array([[7000, -9, 0], [-1, 10000, 5]], dtype=np.int16)
    assert gg.clean(a, -9).tolist() == [[7000, gg.NO_DATA, 0], [gg.NO_DATA, 10000, 5]]


def test_urls_and_cache_use_the_cropland_layer_and_do_not_collide_with_the_old_grid(tmp_path):
    gcfg = {"period": "HP0120", "climate": "AGERA5", "ssp": "HIST"}
    assert gg.file_url(gcfg, "RCW", "HRLM") == (
        "https://storage.googleapis.com/fao-gismgr-gaez-v5-data/DATA/GAEZ-V5/MAPSET/RES05-SUX/"
        "GAEZ-V5.RES05-SUX.HP0120.AGERA5.HIST.RCW.HRLM.tif")
    p = gg.cache_path(gcfg, {}, tmp_path, "RCW", "HRLM")
    assert "grid_sux_5arcmin" in p.parts and "grid_0.1deg" not in p.parts


def grid(values, cell=0.1):
    return {"layer": gg.LAYER, "bounds": [102.0, 10.0, 102.0 + cell * len(values[0]), 10.0 + cell * len(values)],
            "cell_deg": cell, "values": values}


def test_build_rows_is_wide_and_leaves_missing_modes_empty():
    gcfg = {"modes": ["HILM", "HRLM", "LILM", "LRLM"]}
    grids = {("RCW", "HRLM"): grid([[7000, gg.NO_DATA], [0, 5000]]),
             ("RCW", "LRLM"): grid([[3000, gg.NO_DATA], [gg.NO_DATA, 100]])}
    rows = gg.build_rows(gcfg, grids)
    by = {(r["lat"], r["lon"]): r for r in rows}
    assert set(by) == {(10.15, 102.05), (10.05, 102.05), (10.05, 102.15)}      # sea cell dropped
    assert by[(10.15, 102.05)] == {"lat": 10.15, "lon": 102.05, "crop_code": "RCW",
                                   "hilm": None, "hrlm": 7000, "lilm": None, "lrlm": 3000}
    assert by[(10.05, 102.05)]["hrlm"] == 0 and by[(10.05, 102.05)]["lrlm"] is None   # 0 stays 0, gap stays NULL
    assert rows[0]["lat"] >= rows[-1]["lat"]                                  # north to south


def test_build_rows_cell_centres_on_the_native_five_arcminute_grid():
    step = 1 / 12
    g = {"layer": gg.LAYER, "bounds": [102.0, 8.0, 102.0 + 2 * step, 8.0 + 2 * step], "cell_deg": step,
         "values": [[1, 2], [3, 4]]}
    rows = gg.build_rows({"modes": ["HRLM"]}, {("RCW", "HRLM"): g})
    assert {(r["lat"], r["lon"]): r["hrlm"] for r in rows} == {
        (8.125, 102.0417): 1, (8.125, 102.125): 2, (8.0417, 102.0417): 3, (8.0417, 102.125): 4}


def test_offline_run_uses_cache_and_reports_missing_files(tmp_path):
    gcfg = {"period": "HP0120", "climate": "AGERA5", "ssp": "HIST", "modes": ["HRLM"],
            "crops": [{"code": "RCW"}, {"code": "MZE"}]}
    gc = {"bbox": [102.0, 10.0, 102.2, 10.2]}
    entry = {**grid([[1, 2], [3, 4]]), "request_bbox": [102.0, 10.0, 102.2, 10.2]}
    path = gg.cache_path(gcfg, gc, tmp_path, "RCW", "HRLM")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(entry), encoding="utf-8")
    grids, problems = gg.fetch_grids(gcfg, gc, tmp_path, offline=True, log=lambda *_: None)
    assert list(grids) == [("RCW", "HRLM")]
    assert len(problems) == 1 and problems[0].startswith("MZE/HRLM: not cached")


def test_cache_for_another_bbox_or_another_layer_is_not_reused(tmp_path):
    gcfg = {"period": "HP0120", "climate": "AGERA5", "ssp": "HIST", "modes": ["HRLM"], "crops": [{"code": "RCW"}]}
    gc = {"bbox": [102.0, 8.0, 110.0, 24.0]}
    path = gg.cache_path(gcfg, gc, tmp_path, "RCW", "HRLM")
    path.parent.mkdir(parents=True)
    for stale in ({**grid([[1]]), "request_bbox": [102.0, 10.0, 102.2, 10.2]},                    # other bbox
                  {**grid([[1]]), "layer": "RES05-SXX30AS", "request_bbox": [102.0, 8.0, 110.0, 24.0]}):   # other layer
        path.write_text(json.dumps(stale), encoding="utf-8")
        grids, problems = gg.fetch_grids(gcfg, gc, tmp_path, offline=True, log=lambda *_: None)
        assert grids == {} and problems
