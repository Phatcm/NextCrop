import math

import pytest

from fieldshift_api.grid import OutsideGrid, cell_for


def test_cell_containing_a_point_uses_the_pipeline_centre_convention():
    c = cell_for(10.45, 105.35)
    assert (c.i, c.j) == (162, 40)
    assert (c.lat, c.lon) == (10.4583, 105.375)                       # 24 - 162.5/12, 102 + 40.5/12
    assert c.bounds() == [105.333333, 10.416667, 105.416667, 10.5]
    assert c.west <= 105.35 < c.east and c.south <= 10.45 < c.north


def test_centre_matches_what_the_extractor_writes_for_every_cell():
    step = 1 / 12
    for i, j in [(0, 0), (191, 95), (100, 50), (162, 40)]:
        c = cell_for(24 - (i + 0.5) * step, 102 + (j + 0.5) * step)
        assert (c.i, c.j) == (i, j)
        assert c.lat == round(24 - (i + 0.5) * step, 4) and c.lon == round(102 + (j + 0.5) * step, 4)


def test_area_is_about_80_to_85_km2_and_shrinks_towards_the_north():
    south, north = cell_for(9.6, 105.95).area_km2, cell_for(21.3, 103.9).area_km2
    assert 83 < south < 87 and 78 < north < 83 and north < south
    assert math.isclose(cell_for(10.45, 105.35).area_km2, 84.4, abs_tol=0.2)


@pytest.mark.parametrize("lat,lon", [(7.99, 105), (24.01, 105), (15, 101.9), (15, 110.1)])
def test_points_outside_the_rectangle_are_rejected(lat, lon):
    with pytest.raises(OutsideGrid):
        cell_for(lat, lon)


@pytest.mark.parametrize("lat,lon", [(float("nan"), 105), (15, float("inf"))])
def test_non_finite_coordinates_are_rejected(lat, lon):
    with pytest.raises(OutsideGrid):
        cell_for(lat, lon)


def test_the_rectangle_edges_belong_to_the_edge_cells():
    assert cell_for(24, 102).i == 0 and cell_for(24, 102).j == 0
    assert cell_for(8, 110).i == 191 and cell_for(8, 110).j == 95
