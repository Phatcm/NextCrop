"""Use cases of the API: crops, rotation options for a point, grid cells for the map."""
from __future__ import annotations

import time

from . import config  # noqa: F401  (puts pipeline/ on sys.path)
from src.rotation import options as ro
from src.rotation.crop_names import NAMES_EN

from .grid import OutsideGrid, cell_for, distance_km
from .repo import MODES, Repo

CROPS_TTL_SECONDS = 300
CELL_TTL_SECONDS = 300
CELL_CACHE_MAX = 512
MAX_CELLS = 20000
POWER_MAX_KM = 110          # the nearest NASA POWER cell (0.5 deg) must be this close
DEMO_AREA_KM = 60           # rain and NDVI exist only for the six demo areas: use one this close or none


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _for_generator(c: dict) -> dict:
    """dim_crop row -> the dict the rotation generator reads (same shape as pipeline/rotation_options.py)."""
    return {"crop_code": c["crop_code"], "name_vi": c["name_vi"], "name_en": NAMES_EN.get(c["crop_code"]),
            "life_cycle": c["life_cycle"] or None,
            "is_legume": bool(c["is_legume"]), "family": c["family"] or None,
            "cycle_days_min": c["cycle_days_min"], "cycle_days_max": c["cycle_days_max"],
            "water_regime": c["water_regime"] or None}


def _check_lang(lang: str) -> None:
    if lang not in ro.LANGS:
        raise ApiError(422, "invalid_lang", f"lang phải là một trong {', '.join(ro.LANGS)} / lang must be one of {', '.join(ro.LANGS)}")


class Service:
    def __init__(self, repo: Repo, clock=time.monotonic):
        self.repo, self._clock = repo, clock
        self._crops: dict[str, dict] | None = None
        self._crops_at = 0.0
        self._cells: dict[tuple, tuple[float, dict]] = {}
        self._power_cells: list[tuple[float, float]] | None = None

    def crops(self) -> dict[str, dict]:
        """dim_crop is tiny and changes only when the pipeline reloads: cache it for a few minutes."""
        now = self._clock()
        if self._crops is None or now - self._crops_at > CROPS_TTL_SECONDS:
            self._crops, self._crops_at = self.repo.crops(), now
        return self._crops

    def cell_values(self, lat: float, lon: float) -> dict:
        """One grid cell's values. Cached briefly: the UI re-asks for the same cell whenever a slider moves, and the
        data only changes when the pipeline reloads."""
        key, now = (lat, lon), self._clock()
        hit = self._cells.get(key)
        if hit and now - hit[0] <= CELL_TTL_SECONDS:
            return hit[1]
        values = self.repo.cell_values(lat, lon)
        if len(self._cells) >= CELL_CACHE_MAX:
            self._cells.pop(next(iter(self._cells)))          # drop the oldest entry
        self._cells[key] = (now, values)
        return values

    def nasa(self, lat: float, lon: float) -> dict:
        """NASA context of a point: monthly temperature everywhere (NASA POWER grid, 2015-2025); rain (CHIRPS) and NDVI
        (NASA MODIS) only when one of the six demo areas is within DEMO_AREA_KM. All values are monthly means over the
        years of the series, not forecasts. Distances use the centre of the data cell, so a cell has one answer."""
        try:
            cell = cell_for(lat, lon)
        except OutsideGrid as e:
            raise ApiError(422, "outside_grid", str(e))
        key, now = ("nasa", cell.lat, cell.lon), self._clock()
        hit = self._cells.get(key)
        if hit and now - hit[0] <= CELL_TTL_SECONDS:
            return {**hit[1], "location": {"lat": lat, "lon": lon, "cell_lat": cell.lat, "cell_lon": cell.lon}}
        if self._power_cells is None:
            self._power_cells = self.repo.power_cells()
        if not self._power_cells:
            raise ApiError(404, "no_data", "Chưa có dữ liệu NASA POWER.")
        pc = min(self._power_cells, key=lambda p: distance_km(cell.lat, cell.lon, p[0], p[1]))
        dist = distance_km(cell.lat, cell.lon, pc[0], pc[1])
        clim = self.repo.power_climatology(*pc) if dist <= POWER_MAX_KM else {"months": {}}
        if not clim["months"]:
            raise ApiError(404, "no_data", "Không có dữ liệu NASA POWER gần điểm này.")
        nan = float("nan")
        temperature = {
            "source": "NASA POWER (MERRA-2) T2M, T2M_MIN, T2M_MAX", "grid_cell": {"lat": pc[0], "lon": pc[1]},
            "years": list(clim["years"]) if clim.get("years") else None,
            "months": [{"m": m, "mean": round(v.get("T2M", nan), 1), "min": round(v.get("T2M_MIN", nan), 1),
                        "max": round(v.get("T2M_MAX", nan), 1)} for m, v in sorted(clim["months"].items())]}
        area = None
        regions = [(distance_km(cell.lat, cell.lon, r["center_lat"], r["center_lon"]), r) for r in self.repo.regions()]
        if regions:
            d, r = min(regions, key=lambda x: x[0])
            if d <= DEMO_AREA_KM:
                rain = self.repo.rain_climatology(r["region_id"])
                ndvi = self.repo.ndvi_climatology(r["region_id"], r["ndvi_primary"] or "modis_qa")
                area = {"region_id": r["region_id"], "name": r["name"], "distance_km": round(d),
                        "rain": {"source": "CHIRPS v3 (bias-corrected rainfall, not NASA)",
                                 "months": [{"m": m, "mm": round(v, 1)} for m, v, _ in rain],
                                 "years": max((n for _, _, n in rain), default=0)},
                        "ndvi": {"source": "NASA MODIS MOD13Q1 (measured, quality-checked 16-day composites)",
                                 "months": [{"m": m, "mean": round(a, 3), "min": round(lo, 3), "max": round(hi, 3), "n": n}
                                            for m, a, lo, hi, n in ndvi]}}
        res = {"temperature": temperature, "demo_area": area}
        if len(self._cells) >= CELL_CACHE_MAX:
            self._cells.pop(next(iter(self._cells)))
        self._cells[key] = (now, res)
        return {**res, "location": {"lat": lat, "lon": lon, "cell_lat": cell.lat, "cell_lon": cell.lon}}

    def crop_list(self, lang: str = "vi") -> list[dict]:
        """`name` is the display name in `lang`; name_vi and name_en are both returned."""
        _check_lang(lang)
        out = []
        for c in self.crops().values():
            en = NAMES_EN.get(c["crop_code"])
            out.append({**c, "name_en": en, "name": (en if lang == "en" and en else c["name_vi"]),
                        "rotatable": ro._usable(_for_generator(c))})
        return out

    def options(self, lat: float, lon: float, crop: str, *, mode: str = "hrlm", seasons: int | None = None,
                priorities: list[str] | None = None, min_index: int | None = None,
                gap_rice: int | None = None, gap_other: int | None = None, lang: str = "vi") -> dict:
        _check_lang(lang)
        if mode not in MODES:
            raise ApiError(422, "invalid_mode", f"mode phải là một trong {', '.join(MODES)}")
        try:
            cell = cell_for(lat, lon)
        except OutsideGrid as e:
            raise ApiError(422, "outside_grid", str(e))
        crops = self.crops()
        if crop not in crops:
            raise ApiError(422, "unknown_crop", f"cây {crop!r} không có trong dữ liệu; mã hợp lệ: {', '.join(sorted(crops))}")
        values = self.cell_values(cell.lat, cell.lon)
        if not values:
            raise ApiError(404, "no_data", "Ô này không có dữ liệu GAEZ (biển, hoặc không có đất canh tác).")
        suit = {code: values.get(code, {}).get(mode) for code in crops}
        try:
            res = ro.generate(crop, {k: _for_generator(v) for k, v in crops.items()}, suit, mode=mode,
                              seasons=seasons, priorities=priorities, min_index=min_index,
                              gap_rice=gap_rice, gap_other=gap_other, lang=lang)
        except ValueError as e:
            raise ApiError(422, "invalid_argument", str(e))
        res["location"] = {"lat": lat, "lon": lon, "cell_lat": cell.lat, "cell_lon": cell.lon,
                           "cell_bounds": cell.bounds(), "cell_area_km2": cell.area_km2}
        res["cell_indices"] = suit
        return res

    def cells(self, west: float, south: float, east: float, north: float, crop: str, mode: str = "hrlm",
              limit: int = 6000) -> dict:
        if mode not in MODES:
            raise ApiError(422, "invalid_mode", f"mode phải là một trong {', '.join(MODES)}")
        if not (west < east and south < north):
            raise ApiError(422, "invalid_bbox", "bbox phải có west < east và south < north")
        if crop not in self.crops():
            raise ApiError(422, "unknown_crop", f"cây {crop!r} không có trong dữ liệu")
        limit = max(1, min(limit, MAX_CELLS))
        rows = self.repo.cells_in_bbox(west, south, east, north, crop, mode, limit)
        if len(rows) > limit:
            raise ApiError(413, "too_many_cells", f"vùng chọn có hơn {limit} ô; hãy thu nhỏ bbox")
        return {"crop": crop, "mode": mode, "cell_deg": 1 / 12, "count": len(rows),
                "cells": [{"lat": la, "lon": lo, "index": v} for la, lo, v in rows]}
