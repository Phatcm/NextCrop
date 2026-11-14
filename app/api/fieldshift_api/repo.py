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
