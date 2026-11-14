"""In-memory stand-in for PgRepo, shaped like the real tables."""
from __future__ import annotations


def crop(code, name, life="annual", group="Cereals", water="upland", legume=False, family="Poaceae", cmin=100, cmax=130):
    return {"crop_code": code, "name_vi": name, "name_verified": True, "life_cycle": life, "gaez_group": group,
            "water_regime": water, "is_legume": legume, "family": family,
            "cycle_days_min": None if life == "perennial" else cmin, "cycle_days_max": None if life == "perennial" else cmax}


CROPS = {c["crop_code"]: c for c in [
    crop("RCW", "Lúa nước", water="wetland", cmin=105, cmax=150),
    crop("RCD", "Lúa cạn", cmin=90, cmax=120),
    crop("MZE", "Ngô", family="Poaceae", cmin=90, cmax=130),
    crop("CSV", "Sắn", group="Roots and tubers", family="Euphorbiaceae", cmin=240, cmax=330),
    crop("SOY", "Đậu tương", group="Oil crops", legume=True, family="Fabaceae", cmin=80, cmax=110),
    crop("GRD", "Lạc", group="Oil crops", legume=True, family="Fabaceae", cmin=90, cmax=120),
    crop("COF", "Cà phê", life="perennial", group="Narcotics and stimulants", family="Rubiaceae"),
]}

# the cell that contains (10.45 N, 105.35 E): centre (10.4583, 105.375)
CELL = (10.4583, 105.375)
VALUES = {"RCW": dict(hilm=8200, hrlm=8504, lilm=5000, lrlm=None), "RCD": dict(hilm=9000, hrlm=9468, lilm=6000, lrlm=None),
          "MZE": dict(hilm=7000, hrlm=7200, lilm=4000, lrlm=None), "CSV": dict(hilm=8000, hrlm=8144, lilm=5000, lrlm=None),
          "SOY": dict(hilm=6500, hrlm=6800, lilm=3000, lrlm=None), "GRD": dict(hilm=6900, hrlm=7000, lilm=3500, lrlm=None),
          "COF": dict(hilm=8300, hrlm=8307, lilm=4000, lrlm=None)}


class FakeRepo:
    def __init__(self, ok=True, cells=None):
        self.ok, self.cells, self.calls = ok, cells if cells is not None else {CELL: VALUES}, []

    def ping(self):
        return self.ok

    def crops(self):
        self.calls.append("crops")
        return CROPS

    def cell_values(self, lat, lon):
        self.calls.append(("cell_values", lat, lon))
        return self.cells.get((round(lat, 4), round(lon, 4)), {})

    def cells_in_bbox(self, west, south, east, north, crop, mode, limit):
        rows = [(la, lo, v[crop][mode]) for (la, lo), v in self.cells.items()
                if west <= lo <= east and south <= la <= north and crop in v and v[crop][mode] is not None]
        return rows[:limit + 1]
