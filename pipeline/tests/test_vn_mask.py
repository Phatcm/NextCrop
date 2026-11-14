"""DATA-14: the Viet Nam mask of the grid. Synthetic polygons, so no download is needed."""
import json

import numpy as np
import pytest

from src.extractors import boundary
from src.transformers import vn_mask as m

CELL = 0.1


def square(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


def feature(*polygons):
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {
        "type": "MultiPolygon", "coordinates": list(polygons)}}]}


def share(cells, geo, **kw):
    return {(r["lat"], r["lon"]): r for r in m.build_rows(cells, geo, CELL, **kw)}


def test_cell_fully_inside_fully_outside_and_half_on_the_border():
    geo = feature([square(100.0, 10.0, 101.0, 11.0)])
    rows = share([(10.5, 100.5), (10.5, 102.0), (10.5, 101.0)], geo, n=10)
    assert rows[(10.5, 100.5)]["vn_share"] == 1.0 and rows[(10.5, 100.5)]["in_vietnam"] is True
    assert rows[(10.5, 102.0)]["vn_share"] == 0.0 and rows[(10.5, 102.0)]["in_vietnam"] is False
    half = rows[(10.5, 101.0)]                       # centre exactly on the border: half the cell is inside
    assert half["vn_share"] == pytest.approx(0.5, abs=0.1)


def test_threshold_decides_in_vietnam_not_the_cell_centre():
    geo = feature([square(100.0, 10.0, 101.02, 11.0)])
    cell = [(10.5, 101.05)]                           # spans x 101.00..101.10: only the 0.02 strip is inside
    low = share(cell, geo, n=10, min_share=0.5)[(10.5, 101.05)]
    assert 0 < low["vn_share"] < 0.5 and low["in_vietnam"] is False
    lenient = share(cell, geo, n=10, min_share=0.1)[(10.5, 101.05)]
    assert lenient["in_vietnam"] is True and lenient["vn_share"] == low["vn_share"]


def test_a_hole_is_outside_and_islands_are_inside():
    outer = square(100.0, 10.0, 101.0, 11.0)
    hole = square(100.3, 10.3, 100.7, 10.7)
    island = square(105.0, 15.0, 105.5, 15.5)
    geo = feature([outer, hole], [island])
    rows = share([(10.5, 100.5), (10.9, 100.1), (15.25, 105.25), (10.5, 103.0)], geo, n=6)
    assert rows[(10.5, 100.5)]["in_vietnam"] is False        # inside the hole (a lake or an enclave)
    assert rows[(10.9, 100.1)]["in_vietnam"] is True
    assert rows[(15.25, 105.25)]["in_vietnam"] is True       # second polygon of the MultiPolygon
    assert rows[(10.5, 103.0)]["in_vietnam"] is False


def test_rows_are_unique_sorted_rounded_and_inputs_are_deduplicated():
    geo = feature([square(100.0, 10.0, 101.0, 11.0)])
    rows = m.build_rows([(10.5, 100.5), (10.2, 100.2), (10.5, 100.5)], geo, CELL)
    assert [(r["lat"], r["lon"]) for r in rows] == [(10.2, 100.2), (10.5, 100.5)]
    assert all(set(r) == {"lat", "lon", "vn_share", "in_vietnam"} and 0 <= r["vn_share"] <= 1 for r in rows)


def test_polygon_and_feature_inputs_and_bad_inputs():
    plain = {"type": "Polygon", "coordinates": [square(0, 0, 1, 1)]}
    assert len(m.rings(plain)) == 1
    with pytest.raises(ValueError, match="no polygon"):
        m.rings({"type": "FeatureCollection", "features": []})
    with pytest.raises(ValueError, match="min_share"):
        m.build_rows([(0.5, 0.5)], plain, CELL, min_share=0)


def test_inside_handles_many_points_in_chunks():
    e = m.edges(m.rings({"type": "Polygon", "coordinates": [square(0, 0, 1, 1)]}))
    x = np.linspace(-0.5, 1.5, 9001) + 1e-7                   # no point exactly on the border (ambiguous by definition)
    got = m.inside(x, np.full_like(x, 0.5), e, chunk=1000)
    assert got.sum() == ((x > 0) & (x < 1)).sum()


def test_boundary_fetch_reads_and_caches_the_geojson(monkeypatch, tmp_path):
    body = json.dumps(feature([square(0, 0, 1, 1)])).encode()
    calls = []

    def fake(url, path, **kw):
        calls.append(kw.get("offline"))
        return body

    monkeypatch.setattr(boundary, "fetch_cached", fake)
    geo = boundary.fetch({}, tmp_path, offline=True)
    assert geo["features"] and calls == [True]
    assert "CC BY 4.0" in boundary.ATTRIBUTION


def test_real_boundary_in_the_cache_puts_known_places_on_the_right_side(tmp_path):
    cached = list(__import__("pathlib").Path(__file__).resolve().parents[1].glob("data/bronze/boundary/*.geojson"))
    if not cached:
        pytest.skip("boundary not downloaded yet (run run_etl.py once)")
    geo = json.loads(cached[0].read_text(encoding="utf-8"))
    inside_pts = {"Ha Noi": (21.03, 105.85), "Thai Binh": (20.45, 106.33), "An Giang": (10.5, 105.2),
                  "Dak Lak": (12.7, 108.05), "Son La": (21.3, 103.9), "Ninh Thuan": (11.6, 108.9)}
    outside_pts = {"Vientiane": (17.97, 102.6), "Phnom Penh": (11.55, 104.92), "Kunming": (25.0, 102.7),
                   "Gulf of Thailand": (9.0, 102.5), "Bangkok": (13.75, 100.5)}
    pts = list(inside_pts.values()) + list(outside_pts.values())
    rows = m.build_rows(pts, geo, 0.0833333, n=4)
    res = {(r["lat"], r["lon"]): r["in_vietnam"] for r in rows}
    assert all(res[p] for p in inside_pts.values())
    assert not any(res[p] for p in outside_pts.values())
