"""The GAEZ grid used by the pipeline (5 arc-minute cells over 102-110 E, 8-24 N).

Cell (i, j) has its centre at lat = 24 - (i + 0.5) / 12 and lon = 102 + (j + 0.5) / 12, rounded to 4 decimals,
exactly as pipeline/src/extractors/gaez_grid.py writes them to gaez_grid.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

LON_MIN, LON_MAX = 102.0, 110.0
LAT_MIN, LAT_MAX = 8.0, 24.0
STEP = 1 / 12
ROWS = round((LAT_MAX - LAT_MIN) / STEP)      # 192
COLS = round((LON_MAX - LON_MIN) / STEP)      # 96
EARTH_RADIUS_KM = 6371.0088
QUERY_TOLERANCE = 0.0002                       # centres are stored with 4 decimals; this only absorbs float noise


class OutsideGrid(ValueError):
    """The point is not inside the rectangle the pipeline covers."""


@dataclass(frozen=True)
class Cell:
    i: int
    j: int
    lat: float            # centre, as stored in gaez_grid
    lon: float
    west: float
    south: float
    east: float
    north: float
    area_km2: float

    def bounds(self) -> list[float]:
        return [round(self.west, 6), round(self.south, 6), round(self.east, 6), round(self.north, 6)]


def cell_for(lat: float, lon: float) -> Cell:
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise OutsideGrid("toạ độ không hợp lệ")
    if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
        raise OutsideGrid(f"điểm nằm ngoài vùng dữ liệu ({LON_MIN}-{LON_MAX}°E, {LAT_MIN}-{LAT_MAX}°N)")
    i = min(int((LAT_MAX - lat) / STEP), ROWS - 1)
    j = min(int((lon - LON_MIN) / STEP), COLS - 1)
    north, west = LAT_MAX - i * STEP, LON_MIN + j * STEP
    south, east = north - STEP, west + STEP
    area = EARTH_RADIUS_KM ** 2 * math.radians(STEP) * (math.sin(math.radians(north)) - math.sin(math.radians(south)))
    return Cell(i=i, j=j, lat=round(LAT_MAX - (i + 0.5) * STEP, 4), lon=round(LON_MIN + (j + 0.5) * STEP, 4),
                west=west, south=south, east=east, north=north, area_km2=round(area, 1))
