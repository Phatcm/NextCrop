"""Read-only access to the field_shift schema.

Every request runs in `BEGIN READ ONLY ... ROLLBACK`, so even the owner role cannot change data through the API.
Tables are schema-qualified, because a pooled connection (Neon PgBouncer, transaction mode) forgets `SET search_path`.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Protocol

from . import config  # noqa: F401  (puts pipeline/ on sys.path)
from .grid import QUERY_TOLERANCE

SCHEMA = "field_shift"
MODES = ("hilm", "hrlm", "lilm", "lrlm")
CROP_COLUMNS = ("crop_code", "name_vi", "name_verified", "life_cycle", "gaez_group", "water_regime", "is_legume",
                "family", "cycle_days_min", "cycle_days_max")


class Repo(Protocol):
    def ping(self) -> bool: ...
    def crops(self) -> dict[str, dict]: ...
    def cell_values(self, lat: float, lon: float) -> dict[str, dict[str, int | None]]: ...
    def cells_in_bbox(self, west: float, south: float, east: float, north: float, crop: str, mode: str,
                      limit: int) -> list[tuple[float, float, int]]: ...
    def power_cells(self) -> list[tuple[float, float]]: ...
    def power_climatology(self, lat: float, lon: float) -> dict: ...
    def regions(self) -> list[dict]: ...
    def rain_climatology(self, region_id: str) -> list[tuple[int, float, int]]: ...
    def ndvi_climatology(self, region_id: str, source_key: str) -> list[tuple[int, float, float, float, int]]: ...
    def water_balance_climatology(self, region_id: str) -> list[tuple[int, float, float, int]]: ...


class PgRepo:
    """One connection guarded by a lock: queries are a few milliseconds, so serialising them is fine here."""

    def __init__(self, dsn: str):
        self._dsn = dsn
        self._conn = None
        self._lock = threading.Lock()

    def _connect(self):
        import pg8000.native
        from src.db.postgres import parse_dsn
        self._conn = pg8000.native.Connection(**parse_dsn(self._dsn))

    def _close(self):
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        self._conn = None

    @contextmanager
    def _tx(self):
        with self._lock:
            for attempt in (1, 2):
                try:
                    if self._conn is None:
                        self._connect()
                    self._conn.run("BEGIN READ ONLY")
                    break
                except Exception:
                    self._close()
                    if attempt == 2:
                        raise
            try:
                yield self._conn
            finally:
                try:
                    self._conn.run("ROLLBACK")
                except Exception:
                    self._close()

    def ping(self) -> bool:
        try:
            with self._tx() as c:
                return c.run("SELECT 1")[0][0] == 1
        except Exception:
            return False

    def crops(self) -> dict[str, dict]:
        with self._tx() as c:
            rows = c.run(f"SELECT {', '.join(CROP_COLUMNS)} FROM {SCHEMA}.dim_crop ORDER BY crop_code")
        return {r[0]: dict(zip(CROP_COLUMNS, r)) for r in rows}

    def cell_values(self, lat: float, lon: float) -> dict[str, dict[str, int | None]]:
        t = QUERY_TOLERANCE
        with self._tx() as c:
            rows = c.run(f"SELECT crop_code, {', '.join(MODES)} FROM {SCHEMA}.gaez_grid "
                         "WHERE lat BETWEEN :la AND :lb AND lon BETWEEN :oa AND :ob",
                         la=lat - t, lb=lat + t, oa=lon - t, ob=lon + t)
        return {r[0]: dict(zip(MODES, r[1:])) for r in rows}

    # ---- NASA card: monthly climatology (mean over the years of the series), nothing is aggregated beyond that
    def power_cells(self) -> list[tuple[float, float]]:
        """Centres of the nationwide NASA POWER grid (0.5 degree cells)."""
        with self._tx() as c:
            rows = c.run(f"SELECT DISTINCT lat, lon FROM {SCHEMA}.vn_grid_monthly WHERE param = 'T2M'")
        return [(float(a), float(b)) for a, b in rows]

    def power_climatology(self, lat: float, lon: float) -> dict:
        """{"months": {1: {"T2M": mean, "T2M_MIN": .., "T2M_MAX": ..}, ...}, "years": (first, last)}.
        yyyymm = YYYY13 is POWER's annual value and is left out; -999 is POWER's fill value."""
        with self._tx() as c:
            rows = c.run(f"SELECT yyyymm % 100, param, avg(value) FROM {SCHEMA}.vn_grid_monthly "
                         "WHERE lat = :la AND lon = :lo AND param IN ('T2M', 'T2M_MIN', 'T2M_MAX') "
                         "AND yyyymm % 100 BETWEEN 1 AND 12 AND value IS NOT NULL AND value > -900 GROUP BY 1, 2",
                         la=lat, lo=lon)
            span = c.run(f"SELECT min(yyyymm / 100), max(yyyymm / 100) FROM {SCHEMA}.vn_grid_monthly "
                         "WHERE lat = :la AND lon = :lo AND param = 'T2M' AND yyyymm % 100 BETWEEN 1 AND 12",
                         la=lat, lo=lon)[0]
        months: dict[int, dict[str, float]] = {}
        for m, param, mean in rows:
            months.setdefault(int(m), {})[param] = float(mean)
        return {"months": months, "years": (int(span[0]), int(span[1])) if span[0] is not None else None}

    def regions(self) -> list[dict]:
        with self._tx() as c:
            rows = c.run(f"SELECT region_id, name, center_lat, center_lon, ndvi_primary FROM {SCHEMA}.dim_region "
                         "ORDER BY region_id")
        return [{"region_id": r[0], "name": r[1], "center_lat": float(r[2]), "center_lon": float(r[3]),
                 "ndvi_primary": r[4]} for r in rows]

    def rain_climatology(self, region_id: str) -> list[tuple[int, float, int]]:
        """(month, mean mm, years) from rain_monthly_best (CHIRPS v3, bias-corrected)."""
        with self._tx() as c:
            rows = c.run(f"SELECT substring(month, 6, 2)::int, avg(best_mm), count(*) FROM {SCHEMA}.rain_monthly_best "
                         "WHERE region_id = :r GROUP BY 1 ORDER BY 1", r=region_id)
        return [(int(m), float(v), int(n)) for m, v, n in rows]

    def water_balance_climatology(self, region_id: str) -> list[tuple[int, float, float, int]]:
        """(month, mean rain mm, mean ET0 mm, years) from water_balance_monthly: rain is CHIRPS, ET0 is computed from
        NASA POWER (FAO-56) and calibrated to the GAEZ ET0 layer. Months with a NULL value are left out of the mean."""
        with self._tx() as c:
            rows = c.run(f"SELECT substring(month, 6, 2)::int, avg(rain_mm), avg(et0_mm), count(*) "
                         f"FROM {SCHEMA}.water_balance_monthly WHERE region_id = :r AND rain_mm IS NOT NULL "
                         "AND et0_mm IS NOT NULL GROUP BY 1 ORDER BY 1", r=region_id)
        return [(int(m), float(rain), float(et0), int(n)) for m, rain, et0, n in rows]

    def ndvi_climatology(self, region_id: str, source_key: str) -> list[tuple[int, float, float, float, int]]:
        """(month, mean, min, max, n) over MEASURED composites that passed QA. Interpolated rows are not
        measurements (see the table comment) and are left out."""
        with self._tx() as c:
            rows = c.run(f"SELECT EXTRACT(MONTH FROM date)::int, avg(median_final), min(median_final), "
                         f"max(median_final), count(*) FROM {SCHEMA}.ndvi_series WHERE region_id = :r AND "
                         "source_key = :k AND source = 'measured' AND NOT flag_bad AND median_final IS NOT NULL "
                         "GROUP BY 1 ORDER BY 1", r=region_id, k=source_key)
        return [(int(m), float(a), float(lo), float(hi), int(n)) for m, a, lo, hi, n in rows]

    def cells_in_bbox(self, west: float, south: float, east: float, north: float, crop: str, mode: str,
                      limit: int) -> list[tuple[float, float, int]]:
        if mode not in MODES:                              # the column name is built into the SQL: whitelist it
            raise ValueError(f"unknown mode {mode!r}")
        with self._tx() as c:
            rows = c.run(f"SELECT lat, lon, {mode} FROM {SCHEMA}.gaez_grid "
                         f"WHERE crop_code = :crop AND {mode} IS NOT NULL "
                         "AND lat BETWEEN :s AND :n AND lon BETWEEN :w AND :e ORDER BY lat DESC, lon LIMIT :lim",
                         crop=crop, s=south, n=north, w=west, e=east, lim=limit + 1)
        return [(float(r[0]), float(r[1]), int(r[2])) for r in rows]
