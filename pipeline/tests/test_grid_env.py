"""DATA-17: slope, soil and water deficit per grid cell. Synthetic rasters on a tiny box (2 x 2 cells), no network."""
import numpy as np
import pytest

from src.extractors import gaez_env as ge
from src.extractors import gaez_grid_env as gge
from src.transformers import grid_env as g

BBOX = [100.0, 10.0, 100.1666667, 10.1666667]     # 2 x 2 cells of 5 arc-minutes
CFG = {"soil_factors": ["SQ0", "SQ1"], "water_deficit": {"crops": ["RCW"], "modes": ["HILM"], "period": "HP0120",
                                                         "climate": "AGERA5", "ssp": "HIST"}}
# cell centres: lat 10.125 / 10.0417, lon 100.0417 / 100.125 (row 0 is the northern one)
N0, N1 = 10.125, 10.0417
W0, W1 = 100.0417, 100.125


def layer(arr):
    return arr, {"bbox": BBOX}


def slope_layers(pixel_classes, f=10):
    """pixel_classes[(row, col)] = class index 0..9 holding 100 % of that cell's pixels; None = no land (all zeros)."""
    layers = {}
    for k, cls in enumerate(ge.SLOPE_CLASSES):
        a = np.zeros((2 * f, 2 * f), dtype=np.int16)
        for (i, j), c in pixel_classes.items():
            if c == k:
                a[i * f:(i + 1) * f, j * f:(j + 1) * f] = 10000
        layers[("slope", cls)] = layer(a)
    return layers


def test_geometry_and_cell_index_follow_the_documented_cell_centres():
    full = [102.0, 8.0, 110.0, 24.0]
    assert g.geometry(full) == (192, 96)
    assert g.cell_ij(23.9583333, 102.0416667, full) == (0, 0)
    assert g.cell_ij(8.0416667, 109.9583333, full) == (191, 95)


def test_slope_cells_share_weighted_mean_gt12_and_no_land_is_none():
    layers = slope_layers({(0, 0): 0, (0, 1): 9, (1, 0): 5})        # flat, steep (>45 %), 12-16 %; (1,1) has no land
    s = g.slope_grid(layers, BBOX)
    assert s["mean"][0, 0] == pytest.approx(0.25) and s["gt12"][0, 0] == 0
    assert s["mean"][0, 1] == pytest.approx(55.0) and s["gt12"][0, 1] == pytest.approx(100) and s["gt24"][0, 1] == pytest.approx(100)
    assert s["gt12"][1, 0] == pytest.approx(100) and s["gt24"][1, 0] == 0
    assert np.isnan(s["mean"][1, 1]) and s["n_px"][1, 1] == 0           # sea: nothing to average, not a 0 % slope


def test_slope_shares_are_renormalised_when_pixels_carry_less_than_100_percent():
    layers = slope_layers({(0, 0): 0})
    a, m = layers[("slope", "SC01")]
    a = a.copy()
    a[:10, :10] = 5000                                                    # the cell's pixels carry only 50 % of land in total
    layers[("slope", "SC01")] = (a, m)
    s = g.slope_grid(layers, BBOX)
    assert s["mean"][0, 0] == pytest.approx(0.25)                         # 100 % of the remaining mass is class 1


def test_slope_grid_is_none_when_a_class_layer_is_missing():
    layers = slope_layers({(0, 0): 0})
    del layers[("slope", "SC04")]
    assert g.slope_grid(layers, BBOX) is None


def test_soil_cells_exclude_non_rating_classes_and_empty_is_nan():
    a = np.zeros((20, 20), dtype=np.uint8)
    a[:10, :10] = 10                                   # cell (0,0): rating bin 10 -> 0.95
    a[:10, 10:] = 13                                   # cell (0,1): water, not a rating -> no rating
    blk = np.full((10, 10), 2, dtype=np.uint8)
    blk[:5] = 12                                       # half not evaluated: only the rated half counts
    a[10:, :10] = blk                                  # cell (1,0): rating bin 2 -> 0.15
    s = g.soil_grid({("soil", "SQ0.HIM"): layer(a)}, BBOX, "SQ0", "HIM")
    assert s[0, 0] == pytest.approx(0.95) and np.isnan(s[0, 1]) and s[1, 0] == pytest.approx(0.15) and np.isnan(s[1, 1])


def test_water_deficit_keeps_a_real_zero_and_drops_nodata():
    a = np.array([[120.5, -9.0], [0.0, -9.0]], dtype=np.float32)
    w = g.wdc_grid({("wdc", "RCW.HILM"): layer(a)}, BBOX, "RCW", "HILM")
    assert w[0, 0] == pytest.approx(120.5) and w[1, 0] == 0.0 and np.isnan(w[0, 1]) and np.isnan(w[1, 1])


def test_build_rows_assembles_cells_and_never_writes_nodata_as_zero():
    layers = slope_layers({(0, 0): 0, (0, 1): 9, (1, 0): 5})
    for f in CFG["soil_factors"]:
        for lv in ge.SOIL_LEVELS:
            a = np.zeros((20, 20), dtype=np.uint8)
            a[:10, :10] = 8
            layers[("soil", f"{f}.{lv}")] = layer(a)
    layers[("wdc", "RCW.HILM")] = layer(np.array([[100.0, -9.0], [0.0, -9.0]], dtype=np.float32))
    env, wd, problems = g.build_rows(layers, [(N0, W0), (N0, W1), (N1, W0), (N1, W1)], BBOX,
                                     {**CFG, "slope_high_share_gt12": 40, "slope_moderate_share_gt12": 10})
    assert problems == []
    by = {(r["lat"], r["lon"]): r for r in env}
    assert len(env) == 3                                  # the sea cell (no slope, no soil, no water deficit) has no row
    flat, steep = by[(N0, W0)], by[(N0, W1)]
    assert flat["slope_class"] == "low" and flat["soil_limiting_him"] == 0.75 and flat["soil_nutrient_lim"] == 0.75
    assert steep["slope_class"] == "high" and steep["soil_limiting_him"] is None     # no rated soil pixel: None, not 0
    assert by[(N1, W0)]["slope_class"] == "high" and by[(N1, W0)]["soil_limiting_him"] is None
    assert "soil_salinity_him" not in flat                                # only the configured soil factors become columns
    assert {(r["lat"], r["lon"], r["wdc_mm"]) for r in wd} == {(N0, W0, 100.0), (N1, W0, 0.0)}
    assert all(set(r) == {"lat", "lon", "crop_code", "input_mode", "wdc_mm"} for r in wd)


def test_build_rows_reports_missing_layers_and_rejects_an_unknown_soil_factor():
    layers = slope_layers({(0, 0): 0})
    env, wd, problems = g.build_rows(layers, [(N0, W0)], BBOX, CFG)
    assert any("soil SQ0.HIM missing" in p for p in problems) and any("water deficit RCW.HILM missing" in p for p in problems)
    assert env[0]["soil_limiting_him"] is None and wd == []
    with pytest.raises(ValueError, match="no column name"):
        g.build_rows(layers, [(N0, W0)], BBOX, {**CFG, "soil_factors": ["SQ9"]})
    out_env, _w, probs = g.build_rows(layers, [(50.0, 50.0)], BBOX, CFG)
    assert out_env == [] and any("outside the bbox" in p for p in probs)


def test_array_that_does_not_tile_into_cells_is_rejected():
    with pytest.raises(ValueError, match="does not tile"):
        g._blocks(np.zeros((25, 20)), BBOX)


def test_slope_class_rule_matches_the_erosion_thresholds():
    cfg = {"slope_high_share_gt12": 40, "slope_moderate_share_gt12": 10}
    assert [g.slope_class(x, cfg) for x in (0, 9.9, 10, 39.9, 40, 100)] == ["low", "low", "moderate", "moderate", "high", "high"]
    assert g.slope_class(None, cfg) is None


def test_jobs_list_every_layer_and_fetch_uses_the_cache_offline(tmp_path, monkeypatch):
    j = gge.jobs(CFG)
    assert len([x for x in j if x[0] == "slope"]) == 10 and len([x for x in j if x[0] == "soil"]) == 4
    assert [x[1] for x in j if x[0] == "wdc"] == ["RCW.HILM"]
    off, probs = gge.fetch_layers(CFG, BBOX, tmp_path, offline=True, log=lambda *_: None)
    assert off == {} and len(probs) == len(j) and all("offline" in p for p in probs)
    monkeypatch.setattr(gge, "_read_one", lambda job, bbox, d: _fake_read(job, bbox, d))
    got, probs = gge.fetch_layers(CFG, BBOX, tmp_path, workers=2, log=lambda *_: None)
    assert probs == [] and len(got) == len(j)
    monkeypatch.setattr(gge, "_read_one", lambda *a: (_ for _ in ()).throw(AssertionError("must use the cache")))
    again, probs = gge.fetch_layers(CFG, BBOX, tmp_path, log=lambda *_: None)
    assert probs == [] and len(again) == len(j)
    other, probs = gge.fetch_layers(CFG, [100.0, 10.0, 100.3333334, 10.3333334], tmp_path, offline=True, log=lambda *_: None)
    assert other == {} and probs                                          # cached for another bbox = not a cache hit


def _fake_read(job, bbox, bronze_dir):
    import json
    group, key, url = job
    npz, meta = gge._paths(bronze_dir, group, key)
    np.savez_compressed(npz, values=np.zeros((2, 2), dtype=np.int16))
    meta.write_text(json.dumps({"bbox": list(bbox), "bounds": list(bbox), "shape": [2, 2], "nodata": None}), encoding="utf-8")
