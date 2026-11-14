"""How much of each grid cell lies inside Viet Nam (DATA-14).

For every cell of gaez_grid we test an n x n lattice of points inside the cell against the national polygon
(even-odd rule, holes handled). `vn_share` is the fraction of lattice points inside; `in_vietnam` is share >= min_share.
A cell is judged by its area, not by its centre, so a coastal or border cell that is mostly Vietnamese stays in and a
cell that is mostly Laos or sea stays out. Pure numpy, no GIS library.
"""
from __future__ import annotations

import numpy as np


def rings(geojson: dict) -> list[np.ndarray]:
    """All linear rings (outer rings and holes alike: with the even-odd rule both just toggle) as (k, 2) lon/lat arrays."""
    out: list[np.ndarray] = []

    def polygon(coords):
        for ring in coords:
            a = np.asarray(ring, dtype=float)[:, :2]
            if len(a) >= 3:
                out.append(a)

    for f in geojson.get("features", [geojson]):
        g = f.get("geometry", f)
        if g["type"] == "Polygon":
            polygon(g["coordinates"])
        elif g["type"] == "MultiPolygon":
            for p in g["coordinates"]:
                polygon(p)
    if not out:
        raise ValueError("boundary has no polygon")
    return out


def edges(ring_list: list[np.ndarray]) -> np.ndarray:
    """(m, 4) array of x1, y1, x2, y2 for every ring edge (rings are closed implicitly)."""
    parts = []
    for r in ring_list:
        nxt = np.roll(r, -1, axis=0)
        parts.append(np.hstack([r, nxt]))
    return np.vstack(parts)


def inside(px: np.ndarray, py: np.ndarray, e: np.ndarray, chunk: int = 4000) -> np.ndarray:
    """Even-odd point-in-polygon for many points against all edges (ray to +x)."""
    res = np.zeros(len(px), dtype=bool)
    x1, y1, x2, y2 = e[:, 0], e[:, 1], e[:, 2], e[:, 3]
    for s in range(0, len(px), chunk):
        x, y = px[s:s + chunk, None], py[s:s + chunk, None]
        cond = (y1 > y) != (y2 > y)
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        res[s:s + chunk] = (np.sum(cond & (x < xint), axis=1) % 2) == 1
    return res


def cell_shares(cells: list[tuple[float, float]], e: np.ndarray, cell_deg: float, n: int = 8) -> np.ndarray:
    """Fraction (0..1) of an n x n lattice inside the polygon for each (lat, lon) cell centre."""
    off = (np.arange(n) + 0.5) / n - 0.5            # lattice offsets inside the cell, centred
    ox, oy = np.meshgrid(off * cell_deg, off * cell_deg)
    ox, oy = ox.ravel(), oy.ravel()
    lat = np.array([c[0] for c in cells])
    lon = np.array([c[1] for c in cells])
    px = (lon[:, None] + ox[None, :]).ravel()
    py = (lat[:, None] + oy[None, :]).ravel()
    return inside(px, py, e).reshape(len(cells), n * n).mean(axis=1)


def build_rows(cells: list[tuple[float, float]], geojson: dict, cell_deg: float, *, n: int = 8,
               min_share: float = 0.5) -> list[dict]:
    """silver/grid_vietnam rows: lat, lon, vn_share, in_vietnam, one per cell, sorted."""
    if not 0 < min_share <= 1:
        raise ValueError("min_share must be in (0, 1]")
    cells = sorted(set(cells))
    e = edges(rings(geojson))
    shares = cell_shares(cells, e, cell_deg, n)
    return [{"lat": la, "lon": lo, "vn_share": round(float(s), 4), "in_vietnam": bool(s >= min_share)}
            for (la, lo), s in zip(cells, shares)]
