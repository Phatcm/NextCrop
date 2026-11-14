"""Use cases of the API: crops, rotation options for a point, grid cells for the map."""
from __future__ import annotations

import time

from . import config  # noqa: F401  (puts pipeline/ on sys.path)
from src.rotation import options as ro
from src.rotation.crop_names import NAMES_EN

from .grid import OutsideGrid, cell_for
from .repo import MODES, Repo

CROPS_TTL_SECONDS = 300
CELL_TTL_SECONDS = 300
CELL_CACHE_MAX = 512
MAX_CELLS = 20000


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
        self._cells: dict[tuple[float, float], tuple[float, dict]] = {}

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
