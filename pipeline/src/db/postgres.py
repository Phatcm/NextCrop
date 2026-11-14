"""PostgreSQL helpers on top of pg8000 (pure Python, no libpq/DLL): connect, migrate, COPY silver CSVs."""
from __future__ import annotations

import ssl
import urllib.parse
from pathlib import Path

SCHEMA = "field_shift"

# Parents before children (foreign keys). dim_* first; vn_grid_monthly has no parent.
LOAD_ORDER = ["dim_region", "dim_crop", "power_daily", "power_monthly", "ndvi_series", "ndvi_raw", "smap_daily",
              "gfsad_points", "landcover_by_year", "landcover_classes", "terrain", "gaez_suitability",
              "vn_grid_monthly"]


def parse_dsn(dsn: str) -> dict:
    """postgresql://user:pass@host:5432/db?sslmode=require -> pg8000 kwargs."""
    u = urllib.parse.urlparse(dsn)
    if u.scheme not in ("postgres", "postgresql"):
        raise ValueError("DATABASE_URL must start with postgresql://")
    kw: dict = {"user": urllib.parse.unquote(u.username or "postgres"), "host": u.hostname or "localhost",
                "port": u.port or 5432, "database": (u.path or "/postgres").lstrip("/") or "postgres"}
    if u.password:
        kw["password"] = urllib.parse.unquote(u.password)
    mode = urllib.parse.parse_qs(u.query).get("sslmode", ["prefer"])[0]
    if mode in ("require", "verify-ca", "verify-full"):
        ctx = ssl.create_default_context()
        if mode == "require":  # like libpq: encrypt but do not verify the certificate
            ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        kw["ssl_context"] = ctx
    return kw


def connect(dsn: str):
    import pg8000.native
    return pg8000.native.Connection(**parse_dsn(dsn))


def split_sql(text: str) -> list[str]:
    """Split a migration file into statements. Handles -- comments and '...' strings; no $$ bodies."""
    out, buf, in_str, i = [], [], False, 0
    while i < len(text):
        ch = text[i]
        if not in_str and text.startswith("--", i):
            j = text.find("\n", i)
            i = len(text) if j < 0 else j
            continue
        if ch == "'":
            if in_str and text.startswith("''", i):
                buf.append("''")
                i += 2
                continue
            in_str = not in_str
        if ch == ";" and not in_str:
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def applied_versions(conn) -> set[str]:
    exists = conn.run("SELECT to_regclass(:t)", t=f"{SCHEMA}.schema_migrations")[0][0]
    return {r[0] for r in conn.run(f"SELECT version FROM {SCHEMA}.schema_migrations")} if exists else set()


def migrate(conn, migrations_dir: Path, log=print) -> list[str]:
    """Apply migrations/*.sql that are not recorded yet; each file in its own transaction."""
    done = applied_versions(conn)
    applied = []
    for path in sorted(migrations_dir.glob("*.sql")):
        if path.stem in done:
            continue
        conn.run("START TRANSACTION")
        try:
            for stmt in split_sql(path.read_text(encoding="utf-8")):
                conn.run(stmt)
            conn.run("COMMIT")
        except Exception:
            conn.run("ROLLBACK")
            raise
        applied.append(path.stem)
        log(f"  [db] applied migration {path.stem}")
    return applied


def server_report(conn) -> list[tuple[str, str, str]]:
    """Pre-flight facts about the target server: [(check, PASS|WARN|FAIL, detail)].
    Nothing here writes to the database."""
    import time
    out: list[tuple[str, str, str]] = []
    ver_num = int(conn.run("SHOW server_version_num")[0][0])
    ver = conn.run("SHOW server_version")[0][0]
    out.append(("PostgreSQL >= 14", "PASS" if ver_num >= 140000 else "FAIL", ver))
    enc = conn.run("SHOW server_encoding")[0][0]
    out.append(("database encoding is UTF8 (Vietnamese names, COPY ... ENCODING 'UTF8')",
                "PASS" if enc == "UTF8" else "FAIL", enc))
    user, db = conn.run("SELECT current_user, current_database()")[0]
    exists = conn.run("SELECT 1 FROM pg_namespace WHERE nspname = :s", s=SCHEMA)
    if exists:
        can = conn.run("SELECT has_schema_privilege(current_user, :s, 'CREATE')", s=SCHEMA)[0][0]
        out.append((f"role {user} can create tables in schema {SCHEMA}", "PASS" if can else "FAIL",
                    "schema exists" + ("" if can else ": grant CREATE or run as the owner")))
    else:
        can = conn.run("SELECT has_database_privilege(current_user, current_database(), 'CREATE')")[0][0]
        out.append((f"role {user} can create schema {SCHEMA} in {db}", "PASS" if can else "FAIL",
                    "" if can else f"GRANT CREATE ON DATABASE {db} TO {user}"))
    ssl_db = conn.run("SELECT coalesce((SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()), false)")[0][0]
    # A proxy in front of the database (e.g. Neon) ends TLS itself, so the database reports ssl = false
    # even though the client link is encrypted. Check the client socket too (pg8000 internals; may be absent).
    ssl_client = isinstance(getattr(conn, "_usock", None), ssl.SSLSocket)
    out.append(("connection is encrypted (TLS)", "PASS" if (ssl_db or ssl_client) else "WARN",
                ("yes (database sees TLS)" if ssl_db else "yes (client link is TLS; a proxy ends it before the database)")
                if (ssl_db or ssl_client) else "no: add ?sslmode=require to DATABASE_URL and enable ssl on the server"))
    t = []
    for _ in range(5):
        t0 = time.perf_counter()
        conn.run("SELECT 1")
        t.append((time.perf_counter() - t0) * 1000)
    ms = sorted(t)[len(t) // 2]
    out.append(("round-trip latency", "PASS" if ms < 200 else "WARN", f"{ms:.0f} ms median"))
    if exists:
        done = sorted(applied_versions(conn))
        out.append(("existing schema", "PASS", f"migrations applied: {done or 'none'}"))
    return out


def table_columns(conn, table: str) -> list[str]:
    rows = conn.run("SELECT column_name FROM information_schema.columns WHERE table_schema = :s AND table_name = :t "
                    "ORDER BY ordinal_position", s=SCHEMA, t=table)
    return [r[0] for r in rows]


def copy_csv(conn, table: str, path: Path) -> None:
    """COPY one silver CSV (with header) into field_shift.<table>.
    Columns come from the CSV header and must all exist in the table."""
    import csv
    with path.open(newline="", encoding="utf-8-sig") as f:
        header = next(csv.reader(f), None)
    if not header:
        return
    cols = [c.lower() for c in header]
    missing = set(cols) - set(table_columns(conn, table))
    if missing:
        raise ValueError(f"{path.name}: columns not in {SCHEMA}.{table}: {sorted(missing)}")
    sql = (f"COPY {SCHEMA}.{table} ({', '.join(cols)}) FROM STDIN "
           f"WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')")
    with path.open("rb") as f:  # a UTF-8 BOM only affects the header line, which COPY skips
        conn.run(sql, stream=f)
