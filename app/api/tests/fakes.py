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


# NASA card: a coarse POWER grid, two demo areas, and their rain and NDVI
POWER_CELLS = [(10.5, 105.5), (12.5, 108.0), (21.0, 104.0)]
REGIONS = [{"region_id": "an_giang_rice", "name": "An Giang - lúa 3 vụ", "center_lat": 10.45, "center_lon": 105.35, "ndvi_primary": "modis_qa"},
           {"region_id": "son_la_maize", "name": "Sơn La (Mai Sơn) - ngô", "center_lat": 21.15, "center_lon": 104.1, "ndvi_primary": "modis_qa"}]


# (month, mean rain mm CHIRPS, mean ET0 mm, years) of An Giang, 2015-2025: moist months (rain >= 0.5 ET0) are May to Dec
AN_GIANG_WB = list(zip(range(1, 13), [19.0, 12, 20, 64, 185, 150, 200, 185, 244, 300, 180, 64],
                       [120.0, 143, 188, 176, 144, 116, 111, 114, 104, 103, 99, 105], [11] * 12))
FAR_CELL = (21.0417, 105.875)          # Ha Noi: about 185 km from the Son La demo area, 300+ km from An Giang


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

    def power_cells(self):
        return POWER_CELLS

    def power_climatology(self, lat, lon):
        if (lat, lon) not in POWER_CELLS:
            return {"months": {}, "years": None}
        return {"months": {m: {"T2M": 24.0 + m, "T2M_MIN": 19.0 + m, "T2M_MAX": 30.0 + m} for m in range(1, 13)}, "years": (2015, 2025)}

    def regions(self):
        return REGIONS

    def rain_climatology(self, region_id):
        return [(m, 10.0 * m, 11) for m in range(1, 13)] if region_id == "an_giang_rice" else []

    def ndvi_climatology(self, region_id, source_key):
        self.calls.append(("ndvi", region_id, source_key))
        return [(m, 0.5 + m / 100, 0.3, 0.8, 22) for m in range(1, 13)] if region_id == "an_giang_rice" else []

    def water_balance_climatology(self, region_id):
        self.calls.append(("water_balance", region_id))
        return list(AN_GIANG_WB) if region_id == "an_giang_rice" else []

    def cells_in_bbox(self, west, south, east, north, crop, mode, limit):
        rows = [(la, lo, v[crop][mode]) for (la, lo), v in self.cells.items()
                if west <= lo <= east and south <= la <= north and crop in v and v[crop][mode] is not None]
        return rows[:limit + 1]
