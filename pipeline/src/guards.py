"""Regression guard shared by upload_r2.py and load_postgres.py.

Why: on 14/11/2026 a run built on a machine without the nationwide GAEZ silver was uploaded and loaded; the load
is a full refresh, so `gaez_grid` went from 222,720 rows to 0 on the database and nothing complained (the
existing check on that table only ran when it had rows). A table that had data in the previous run and has none
in this one is almost always a missing input, not an intended change.
"""
from __future__ import annotations


def dropped_to_zero(new_rows: dict[str, int], previous_rows: dict[str, int],
                    allow: tuple[str, ...] | list[str] = ()) -> list[str]:
    """Tables with rows in the previous run but none (or absent) now, except the ones deliberately allowed."""
    return sorted(t for t, n in previous_rows.items()
                  if n and not new_rows.get(t, 0) and t not in set(allow))


def rows_from_catalog(catalog: dict | None) -> dict[str, int]:
    """{dataset: rows} from _meta/catalog.json; empty when there is no previous run."""
    return {name: int(d.get("rows") or 0) for name, d in ((catalog or {}).get("datasets") or {}).items()}


def message(tables: list[str], previous_rows: dict[str, int], where: str) -> str:
    detail = ", ".join(f"{t} ({previous_rows[t]:,} rows before)" for t in tables)
    return (f"{where}: no rows for {detail}. They had data in the previous run, so an input is probably missing "
            "on this machine (run pull_bronze.py and run_etl.py --offline). If the table is meant to be empty, "
            "pass --allow-empty TABLE.")
