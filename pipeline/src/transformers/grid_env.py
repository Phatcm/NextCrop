"""Slope, soil quality and crop water deficit for every grid cell inside Viet Nam (DATA-17).

Turns the full-box GAEZ arrays (gaez_grid_env) into one row per 5 arc-minute cell, with the same rules as the
region-level tables (env_inputs.py): nodata is never 0, soil classes 11-13 are not ratings, mean slope is the
share-weighted class midpoint (the open class > 45 % uses 55 %), and shares are renormalised to 100 %.
Erosion is NOT computed here: it needs rain erosivity per cell and the only nationwide rain is the biased POWER grid.
Only the slope part of the erosion rule is given (`slope_class`), so the app can show terrain risk without rain.
"""
from __future__ import annotations

import numpy as np

from src.extractors import gaez_env as ge

SOIL_COLS = {"SQ0": "limiting", "SQ1": "nutrient", "SQ5": "salinity"}   # factor -> column stem
CELL_PER_DEG = 12                                                          # 5 arc-minute cells


def geometry(bbox: list[float]) -> tuple[int, int]:
    """(rows, cols) of cells in the bbox."""
    return round((bbox[3] - bbox[1]) * CELL_PER_DEG), round((bbox[2] - bbox[0]) * CELL_PER_DEG)


def cell_ij(lat: float, lon: float, bbox: list[float]) -> tuple[int, int]:
    """Row (from the top) and column of the cell whose centre is (lat, lon)."""
    return round((bbox[3] - lat) * CELL_PER_DEG - 0.5), round((lon - bbox[0]) * CELL_PER_DEG - 0.5)


def _blocks(arr: np.ndarray, bbox: list[float]) -> np.ndarray:
    """(rows, cols, f, f) view: the f x f pixels of every cell (f = 10 for 30 arc-second, 1 for 5 arc-minute rasters)."""
    r, c = geometry(bbox)
    if arr.shape[0] % r or arr.shape[1] % c or arr.shape[0] // r != arr.shape[1] // c:
        raise ValueError(f"array {arr.shape} does not tile into {r} x {c} cells")
    f = arr.shape[0] // r
    return arr.reshape(r, f, c, f).swapaxes(1, 2)


def slope_grid(layers: dict, bbox: list[float]) -> dict[str, np.ndarray] | None:
    """Per-cell slope arrays (NaN where a cell has no land pixel), or None when a class layer is missing."""
    sums, land = [], None
    for cls in ge.SLOPE_CLASSES:
        have = layers.get(("slope", cls))
        if have is None:
            return None
        b = _blocks(have[0].astype(np.float64), bbox)
        sums.append(b.sum(axis=(2, 3)))                                          # (rows, cols)
        land = b if land is None else land + b                                   # per pixel: sum of the class shares
    sums = np.stack(sums)                                                        # (10, rows, cols)
    npx = (land > 0).sum(axis=(2, 3))                                            # pixels that carry any land share
    total = sums.sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        shares = np.where(total > 0, sums * 100.0 / total, np.nan)
    mid = np.array(ge.SLOPE_MID)[:, None, None]
    return {"mean": (shares * mid).sum(axis=0) / 100.0, "gt12": shares[5:].sum(axis=0), "gt24": shares[7:].sum(axis=0),
            "n_px": npx}


def soil_grid(layers: dict, bbox: list[float], factor: str, level: str) -> np.ndarray | None:
    """Mean soil quality rating (0-1) per cell over rated pixels only; NaN where a cell has no rated pixel."""
    have = layers.get(("soil", f"{factor}.{level}"))
    if have is None:
        return None
    b = _blocks(have[0].astype(np.float64), bbox)
    rated = (b >= 1) & (b <= 10)
    n = rated.sum(axis=(2, 3))
    s = np.where(rated, (b - 0.5) / 10.0, 0.0).sum(axis=(2, 3))
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(n > 0, s / n, np.nan)


def wdc_grid(layers: dict, bbox: list[float], crop: str, mode: str) -> np.ndarray | None:
    """Water deficit (mm) per cell: the mean of valid pixels (>= 0); NaN where none. -9 / negative is nodata, 0 is a real 0."""
    have = layers.get(("wdc", f"{crop}.{mode}"))
    if have is None:
        return None
    b = _blocks(have[0].astype(np.float64), bbox)
    ok = b >= 0
    n = ok.sum(axis=(2, 3))
    s = np.where(ok, b, 0.0).sum(axis=(2, 3))
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(n > 0, s / n, np.nan)


def _num(x, nd):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def slope_class(share_gt12: float | None, cfg: dict) -> str | None:
    """Slope part of the erosion rule (same thresholds as erosion_context): low / moderate / high."""
    if share_gt12 is None:
        return None
    if share_gt12 >= cfg.get("slope_high_share_gt12", 40):
        return "high"
    return "moderate" if share_gt12 >= cfg.get("slope_moderate_share_gt12", 10) else "low"


def build_rows(layers: dict, cells: list[tuple[float, float]], bbox: list[float], cfg: dict,
               ) -> tuple[list[dict], list[dict], list[str]]:
    """(grid_environment rows, grid_water_demand rows, problems) for the given cell centres.

    A cell with no slope, no soil rating and no water deficit at all gets no environment row.
    """
    problems: list[str] = []
    slope = slope_grid(layers, bbox)
    if slope is None:
        problems.append("slope layers missing: no slope columns")
    soils = {}
    for f in cfg["soil_factors"]:
        if f not in SOIL_COLS:
            raise ValueError(f"soil factor {f} has no column name in grid_env.SOIL_COLS")
        for lv in ge.SOIL_LEVELS:
            g = soil_grid(layers, bbox, f, lv)
            if g is None:
                problems.append(f"soil {f}.{lv} missing")
            soils[(f, lv)] = g
    w = cfg["water_deficit"]
    wd = {(c, m): wdc_grid(layers, bbox, c, m) for c in w["crops"] for m in w["modes"]}
    for (c, m), g in wd.items():
        if g is None:
            problems.append(f"water deficit {c}.{m} missing")

    env_rows, wd_rows = [], []
    rows_n, cols_n = geometry(bbox)
    for lat, lon in sorted(cells):
        i, j = cell_ij(lat, lon, bbox)
        if not (0 <= i < rows_n and 0 <= j < cols_n):
            problems.append(f"cell {lat},{lon} is outside the bbox")
            continue
        row = {"lat": lat, "lon": lon, "slope_mean_pct": None, "share_gt12_pct": None, "share_gt24_pct": None,
               "slope_class": None, "n_px_slope": None}
        if slope is not None and np.isfinite(slope["mean"][i, j]):
            row.update(slope_mean_pct=_num(slope["mean"][i, j], 1), share_gt12_pct=_num(slope["gt12"][i, j], 1),
                       share_gt24_pct=_num(slope["gt24"][i, j], 1), n_px_slope=int(slope["n_px"][i, j]))
            row["slope_class"] = slope_class(row["share_gt12_pct"], cfg)
        for f in cfg["soil_factors"]:
            for lv in ge.SOIL_LEVELS:
                g = soils[(f, lv)]
                row[f"soil_{SOIL_COLS[f]}_{lv.lower()}"] = None if g is None else _num(g[i, j], 3)
        got_wd = False
        for (c, m), g in wd.items():
            v = None if g is None else _num(g[i, j], 1)
            if v is not None:
                got_wd = True
                wd_rows.append({"lat": lat, "lon": lon, "crop_code": c, "input_mode": m, "wdc_mm": v})
        has_env = row["slope_mean_pct"] is not None or any(
            v is not None for k, v in row.items() if k.startswith("soil_"))
        if has_env or got_wd:
            env_rows.append(row)
    return env_rows, wd_rows, problems
