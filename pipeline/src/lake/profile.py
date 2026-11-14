"""Profile silver CSV datasets (columns, inferred types, row counts, key uniqueness)."""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path


def _kind(v: str) -> str | None:
    if v == "":
        return None
    if v in ("True", "False"):
        return "boolean"
    try:
        int(v)
        return "integer"
    except ValueError:
        pass
    try:
        float(v)
        return "real"
    except ValueError:
        pass
    if len(v) == 10 and v[4] == "-" and v[7] == "-":
        try:
            dt.date.fromisoformat(v)
            return "date"
        except ValueError:
            pass
    return "text"


def _final(kinds: set) -> str:
    kinds = {k for k in kinds if k}
    if not kinds:
        return "text"
    if kinds == {"integer"}:
        return "integer"
    if kinds <= {"integer", "real"}:
        return "real"
    if kinds == {"boolean"}:
        return "boolean"
    if kinds == {"date"}:
        return "date"
    return "text"


def describe_dataset(paths: list[Path], key_cols: list[str] | None) -> dict:
    """One dataset = the same table in several region folders. Returns a catalog entry:
    {columns: [{name, type, null_count}], rows, key, key_unique, duplicate_keys, errors, warnings, files}.
    """
    errors: list[str] = []
    warnings: list[str] = []
    cols: list[str] | None = None
    kinds: list[set] = []
    nulls: list[int] = []
    rows = 0
    seen: set[tuple] = set()
    dups: list[list] = []
    per_file: dict[str, int] = {}
    for p in paths:
        with p.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                warnings.append(f"{p.parent.name}/{p.name}: empty file, skipped")
                continue
            if cols is None:
                cols = header
                kinds = [set() for _ in cols]
                nulls = [0] * len(cols)
            elif header != cols:
                errors.append(f"{p.parent.name}/{p.name}: header differs from the other files of this dataset")
                continue
            kidx = [cols.index(k) for k in key_cols] if key_cols and all(k in cols for k in key_cols) else None
            if key_cols and kidx is None:
                errors.append(f"key column(s) {key_cols} missing in {p.name} (has {cols})")
            n = 0
            for row in reader:
                n += 1
                if len(row) != len(cols):
                    errors.append(f"{p.parent.name}/{p.name}: row {n + 1} has {len(row)} cells, expected {len(cols)}")
                    break
                for i, v in enumerate(row):
                    k = _kind(v)
                    if k is None:
                        nulls[i] += 1
                    else:
                        kinds[i].add(k)
                if kidx is not None:
                    key = tuple(row[i] for i in kidx)
                    if key in seen:
                        if len(dups) < 5:
                            dups.append(list(key))
                    else:
                        seen.add(key)
            per_file[f"{p.parent.name}/{p.name}"] = n
            rows += n
    if rows == 0:
        errors.append("dataset has no data rows")
    if dups:
        errors.append(f"duplicate keys on {key_cols}, e.g. {dups[:3]}")
    return {
        "columns": [{"name": c, "type": _final(kinds[i]), "null_count": nulls[i]} for i, c in enumerate(cols or [])],
        "rows": rows,
        "key": key_cols,
        "key_unique": (not dups) if key_cols else None,
        "duplicate_keys": dups,
        "files": len(per_file),
        "errors": errors,
        "warnings": warnings,
    }
