"""Server-less dry run of the PostgreSQL load.

Translates db/migrations/*.sql into SQLite (same tables, PKs, FKs and CHECKs), then loads the silver
CSVs with Postgres-strict cell checks (an integer column rejects "12.5", a double rejects "nan",
a boolean accepts only True/False, ...). It answers "will COPY succeed on these files?" without a server.

It is a PROXY, not PostgreSQL: it cannot see server settings (encoding, privileges, SSL) and the
month-format regex is checked in Python. Use `load_postgres.py --check-server` for the server side.
"""
from __future__ import annotations

import csv
import datetime as dt
import math
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

from src.db.postgres import LOAD_ORDER, split_sql

_TYPE_RE = re.compile(r"^(double precision|smallint|integer|bigint|text|boolean|date|timestamptz|jsonb|numeric)\b", re.I)
_SQLITE_TYPE = {"double precision": "REAL", "smallint": "INTEGER", "integer": "INTEGER", "bigint": "INTEGER",
                "boolean": "INTEGER", "text": "TEXT", "date": "TEXT", "numeric": "REAL"}
_NON_COLUMN = ("PRIMARY KEY", "CHECK", "FOREIGN KEY", "UNIQUE", "CONSTRAINT")
_MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


def _split_top_level(body: str) -> list[str]:
    parts, depth, buf, in_str = [], 0, [], False
    for ch in body:
        if ch == "'":
            in_str = not in_str
        if not in_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append("".join(buf).strip())
                buf = []
                continue
        buf.append(ch)
    if "".join(buf).strip():
        parts.append("".join(buf).strip())
    return parts


def _table_parts(stmt: str) -> tuple[str, list[str]] | None:
    m = re.match(r"CREATE TABLE (\w+)\s*\(", stmt, re.I)
    if not m:
        return None
    return m.group(1), _split_top_level(stmt[m.end():stmt.rindex(")")])


def ddl_types(statements: list[str]) -> dict[str, dict[str, str]]:
    """{table: {column: postgres type}} read from the CREATE TABLE statements."""
    out: dict[str, dict[str, str]] = {}
    for s in statements:
        tp = _table_parts(s)
        if not tp:
            continue
        table, parts = tp
        cols = {}
        for p in parts:
            if p.upper().startswith(_NON_COLUMN):
                continue
            name, _, rest = p.partition(" ")
            m = _TYPE_RE.match(rest.strip())
            cols[name.lower()] = m.group(1).lower() if m else "text"
        out[table] = cols
    return out


def _strip_regex_checks(part: str) -> str:
    """Drop CHECK (... ~ '<regex>') clauses (SQLite has no regex operator); other CHECKs stay."""
    while True:
        i = part.upper().find("CHECK")
        found = False
        while i >= 0:
            j = part.find("(", i)
            depth, k = 0, j
            while k < len(part):
                depth += part[k] == "("
                depth -= part[k] == ")"
                if depth == 0:
                    break
                k += 1
            clause = part[i:k + 1]
            if " ~ " in clause:
                part, found = part[:i] + part[k + 1:], True
                break
            i = part.upper().find("CHECK", k)
        if not found:
            return part.strip()


def translate(statements: list[str], tables: list[str]) -> tuple[list[str], list[str]]:
    """(tables+indexes, views) in SQLite dialect, restricted to `tables`."""
    ddl, views = [], []
    for s in statements:
        tp = _table_parts(s)
        if tp:
            table, parts = tp
            if table not in tables:
                continue
            new = []
            for p in parts:
                if p.upper().startswith(_NON_COLUMN):
                    new.append(_strip_regex_checks(p) if p.upper().startswith("CHECK") else p)
                    continue
                name, _, rest = p.partition(" ")
                m = _TYPE_RE.match(rest.strip())
                if m:
                    rest = _SQLITE_TYPE[m.group(1).lower()] + rest.strip()[m.end():]
                new.append(f"{name} {_strip_regex_checks(rest)}".strip())
            new = [x for x in new if x and x.upper() != "CHECK"]
            ddl.append(f"CREATE TABLE {table} (" + ", ".join(new) + ")")
        elif s.upper().startswith("CREATE INDEX"):
            m = re.search(r"\bON\s+(\w+)", s, re.I)
            if m and m.group(1) in tables:
                ddl.append(s)
        elif s.upper().startswith("CREATE VIEW"):
            views.append(s)
    return ddl, views


def strict_value(raw: str, pgtype: str):
    """Convert one CSV cell exactly as Postgres COPY would accept it, or raise ValueError."""
    if raw == "":
        return None                                    # csv format: unquoted empty -> NULL
    if "\x00" in raw:
        raise ValueError("NUL byte in text")
    if pgtype in ("integer", "smallint", "bigint"):
        if not re.fullmatch(r"-?\d+", raw):
            raise ValueError(f"not an integer: {raw!r}")
        v = int(raw)
        if pgtype == "smallint" and not -32768 <= v <= 32767:
            raise ValueError(f"smallint out of range: {raw}")
        return v
    if pgtype in ("double precision", "numeric"):
        v = float(raw)                                 # ValueError if not numeric
        if not math.isfinite(v):
            raise ValueError(f"non-finite number: {raw!r} (NaN fails every CHECK range)")
        return v
    if pgtype == "boolean":
        if raw.lower() not in ("true", "false", "t", "f"):
            raise ValueError(f"not a boolean: {raw!r}")
        return 1 if raw.lower() in ("true", "t") else 0
    if pgtype == "date":
        return dt.date.fromisoformat(raw).isoformat()
    return raw


def dry_run(silver_root: Path, migration_sql: str, log=print) -> dict:
    """Load every silver table into an in-memory SQLite built from the migration.
    Returns {"counts": {table: rows}, "errors": [...], "warnings": [...]}."""
    statements = split_sql(migration_sql)
    types = ddl_types(statements)
    ddl, views = translate(statements, LOAD_ORDER)
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys = ON")
    for s in ddl:
        con.execute(s)
    errors: list[str] = []
    warnings: list[str] = []
    counts: dict[str, int] = {}
    for table in LOAD_ORDER:
        counts[table] = 0
        bad_cells: dict[str, list[str]] = defaultdict(list)
        for path in sorted((silver_root / table).rglob("*.csv")):
            where = f"{table}/{path.parent.name}"
            with path.open(newline="", encoding="utf-8-sig") as f:
                rd = csv.reader(f)
                header = next(rd, None)
                if not header:
                    continue
                cols = [c.lower() for c in header]
                unknown = set(cols) - set(types[table])
                if unknown:
                    errors.append(f"{where}: columns not in table {table}: {sorted(unknown)}")
                    continue
                rows = []
                for n, row in enumerate(rd, start=2):
                    try:
                        vals = [strict_value(v, types[table][c]) for c, v in zip(cols, row)]
                    except ValueError as e:
                        bad_cells[where].append(f"line {n}: {e}")
                        continue
                    if table == "power_monthly" and not _MONTH_RE.match(row[cols.index("month")]):
                        bad_cells[where].append(f"line {n}: month {row[cols.index('month')]!r} violates the month format")
                        continue
                    rows.append(vals)
                try:
                    con.executemany(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", rows)
                    counts[table] += len(rows)
                except sqlite3.IntegrityError as e:
                    errors.append(f"{where}: {e} (PK / FK / CHECK / NOT NULL)")
                    con.rollback()
        for where, msgs in bad_cells.items():
            errors.append(f"{where}: {len(msgs)} cell(s) Postgres would reject, e.g. {msgs[0]}")
    errors += [f"foreign key violation: {r}" for r in con.execute("PRAGMA foreign_key_check").fetchall()[:5]]
    for v in views:                                    # views must at least compile against the tables
        try:
            con.execute(v)
        except sqlite3.Error as e:
            warnings.append(f"view not verified (SQLite dialect difference?): {str(e)[:100]}")
    log(f"dry run: {sum(counts.values()):,} rows, {len(errors)} error(s), {len(warnings)} warning(s)")
    return {"counts": counts, "errors": errors, "warnings": warnings, "connection": con}
