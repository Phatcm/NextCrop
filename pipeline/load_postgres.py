"""Load the silver layer into PostgreSQL (the app's database).

Reads silver from R2 (verifying every sha256 against the manifest) or from local data/, applies
db/migrations, then replaces the table contents in ONE transaction: it is validated and only then
committed, so the app never sees a half-loaded database. Re-running is safe (full refresh).

Usage (from pipeline/):
    python load_postgres.py                  # R2 -> PostgreSQL   (DATABASE_URL in .env)
    python load_postgres.py --local          # data/silver -> PostgreSQL
    python load_postgres.py --migrate-only   # just create/upgrade the schema
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import yaml

from src.db import postgres as pg
from src.extractors.appeears_client import load_dotenv
from src.lake import r2
from src.lake.layout import map_key
from src.transformers.silver_to_gold import SCHEMA_VERSION

ROOT = Path(__file__).resolve().parent


def pull_silver(client, bucket: str, workdir: Path, log=print) -> tuple[dict, dict]:
    def get(key: str) -> bytes:
        return client.get_object(Bucket=bucket, Key=key)["Body"].read()

    latest = json.loads(get("_meta/latest.json"))
    manifest = json.loads(get(latest["manifest_key"]))
    catalog = json.loads(get("_meta/catalog.json"))
    if catalog["run_id"] != manifest["run_id"]:
        raise RuntimeError("catalog and manifest are from different runs: an upload was interrupted, re-run upload_r2.py")
    files = [f for f in manifest["files"] if f["layer"] == "silver"]
    t0, nbytes = time.time(), 0
    for f in files:
        body = get(f["key"])
        if hashlib.sha256(body).hexdigest() != f["sha256"]:
            raise RuntimeError(f"sha256 mismatch after download: {f['key']}")
        dest = workdir / f["key"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        nbytes += len(body)
    log(f"pulled {len(files)} silver objects ({nbytes / 1e6:.1f} MB) from run {manifest['run_id']} "
        f"in {time.time() - t0:.1f}s, all sha256 OK")
    return manifest, catalog


def local_silver(data_dir: Path, workdir: Path) -> tuple[dict, dict]:
    """Reshape data/silver into the bucket layout and profile it like the uploader does."""
    items = r2.collect(data_dir, ("silver",), SCHEMA_VERSION)
    for i in items:
        dest = workdir / i.key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(i.path.read_bytes())
    datasets, errors = r2.quality_gate(items)
    if errors:
        raise RuntimeError("local silver fails the quality gate: " + "; ".join(errors[:3]))
    return {"run_id": "local", "files": []}, {"datasets": datasets}


class Report:
    def __init__(self):
        self.failed = 0
        self.total = 0

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.total += 1
        self.failed += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def scalar(conn, sql: str):
    return conn.run(sql)[0][0]


def validate(conn, counts: dict, catalog: dict, start: int, end: int, cfg: dict | None = None) -> Report:
    rep = Report()
    for t, n in counts.items():
        exp = catalog["datasets"].get(t, {}).get("rows")
        if exp is not None:
            rep.check(f"{t}: rows loaded == catalog", n == exp, f"{n:,} vs {exp:,}")
    import datetime as dt
    days = (dt.date(end, 12, 31) - dt.date(start, 1, 1)).days + 1
    bad = conn.run(f"SELECT region_id, count(*) FROM power_daily GROUP BY 1 HAVING count(*) <> {days}")
    rep.check(f"power_daily: every region has {days} days", not bad, str(bad) if bad else "")
    rep.check("power_daily: no NULL t2m, and NULL rain only where the rain QA rule removed the day (never 0)",
              scalar(conn, "SELECT count(*) FROM power_daily WHERE t2m IS NULL "
                           "OR (prectotcorr IS NULL AND prectotcorr_qa IS NULL)") == 0)
    limit = float(((cfg or {}).get("power", {}).get("rain_qa") or {}).get("max_daily_mm", 150))
    rep.check(f"power_daily: no rain above the QA limit survives ({limit:g} mm/day)",
              scalar(conn, f"SELECT count(*) FROM power_daily WHERE prectotcorr > {limit}") == 0)
    rep.check("power_daily: t2m in [-10, 45] C", scalar(conn, "SELECT count(*) FROM power_daily WHERE t2m NOT BETWEEN -10 AND 45") == 0)
    rep.check("every region has NDVI from its primary source",
              scalar(conn, "SELECT count(*) FROM dim_region r WHERE r.ndvi_primary IS NOT NULL AND NOT EXISTS "
                           "(SELECT 1 FROM ndvi_series n WHERE n.region_id = r.region_id AND n.source_key = r.ndvi_primary)") == 0)
    if counts.get("gaez_suitability"):
        per = conn.run("SELECT region_id, count(*) FROM gaez_suitability GROUP BY 1")
        full = scalar(conn, "SELECT count(*) * 4 FROM dim_crop")
        rep.check("gaez: every region has every crop x 4 modes",
                  all(c == full for _, c in per) and len(per) == counts["dim_region"], f"expected {full} per region")
        # NOTE: no "high inputs >= low inputs" check on purpose: the GAEZ index is not monotonic in input
        # level (22 of 144 region x crop cases have LRLM > HRLM), so that is not a valid invariant.
        if counts.get("gaez_grid"):
            rep.check("gaez_grid: every crop of dim_crop appears in the grid",
                      scalar(conn, "SELECT count(DISTINCT crop_code) FROM gaez_grid") == scalar(conn, "SELECT count(*) FROM dim_crop"))
            rep.check("gaez_grid: every demo region centre has a grid cell within 0.1 deg",
                      scalar(conn, "SELECT count(*) FROM dim_region r WHERE NOT EXISTS (SELECT 1 FROM gaez_grid g "
                                   "WHERE abs(g.lat - r.center_lat) <= 0.1 AND abs(g.lon - r.center_lon) <= 0.1)") == 0)
        rep.check("gaez: rows with n_valid = 0 have no value",
                  scalar(conn, "SELECT count(*) FROM gaez_suitability WHERE n_valid = 0 AND value_mean IS NOT NULL") == 0)
    return rep


def report_queries(conn) -> None:
    print("\nApp-style queries")
    print("  1) v_region_overview")
    print(f"     {'region':<24}{'cropland(MCD12)':>16}{'cropland(30m)':>14}{'ndvi':>6}{'measured':>9}{'smap':>6}{'sm_ok%':>7}")
    for r in conn.run("SELECT region_id, mcd12q1_cropland_frac, gfsad_bbox_crop_frac, ndvi_dates, ndvi_measured, "
                      "smap_days, smap_recommended_pct FROM v_region_overview ORDER BY region_id"):
        f = lambda v: "n/a" if v is None else f"{float(v):.0%}"
        print(f"     {r[0]:<24}{f(r[1]):>16}{f(r[2]):>14}{r[3]:>6}{r[4]:>9}{r[5]:>6}{(r[6] or 0):>6.0f}%")
    print("  2) v_crop_ranking: top 5 crops, An Giang, rain-fed + high inputs (HRLM)")
    for r in conn.run("SELECT rank, crop_code, name_vi, value_mean FROM v_crop_ranking WHERE region_id = 'an_giang_rice' "
                      "AND input_mode = 'HRLM' ORDER BY rank LIMIT 5"):
        print(f"     {r[0]:>2}. {r[1]:<6} {r[2]:<22} {r[3]:.0f}")
    print("  3) rainfall x NDVI by month (join of two sources), An Giang 2023")
    rows = conn.run("SELECT p.month, round(CAST(p.prectotcorr * 30 AS numeric), 0), "
                    "round(CAST(avg(n.median_final) AS numeric), 2) "
                    "FROM power_monthly p JOIN ndvi_series n ON n.region_id = p.region_id AND n.source_key = 'modis_qa' "
                    "AND to_char(n.date, 'YYYY-MM') = p.month WHERE p.region_id = 'an_giang_rice' "
                    "AND p.month LIKE '2023-%' GROUP BY p.month, p.prectotcorr ORDER BY p.month")
    print("     " + "  ".join(f"{m[5:]}:{float(r):.0f}mm/{float(v)}" for m, r, v in rows))


def run_dry_run(silver_root: Path, manifest: dict, catalog: dict) -> int:
    from src.db import dryrun
    sql = "\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "db" / "migrations").glob("*.sql")))
    res = dryrun.dry_run(silver_root, sql)
    print("\nrows loaded into the DDL proxy (vs rows in the catalog):")
    mismatch = 0
    for t, n in res["counts"].items():
        exp = catalog["datasets"].get(t, {}).get("rows")
        flag = "" if exp in (None, n) else f"   <-- catalog has {exp:,}"
        mismatch += bool(flag)
        print(f"  {t:<22}{n:>10,}{flag}")
    for w in res["warnings"]:
        print("  [warn]", w)
    for e in res["errors"]:
        print("  [FAIL]", e)
    ok = not res["errors"] and not mismatch
    print("\nRESULT: " + ("every row passes PK / FK / CHECK / type rules; a real COPY should succeed on this data."
                          if ok else "the data would NOT load cleanly, see the lines above."))
    print("(proxy only: server settings are not covered, run --check-server against the real server)")
    return 0 if ok else 1


def print_server_report(conn) -> int:
    print("\nServer check")
    rows = pg.server_report(conn)
    for name, status, detail in rows:
        print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))
    failed = [r for r in rows if r[1] == "FAIL"]
    print("\nRESULT: " + ("server is fit for the load." if not failed else f"{len(failed)} blocking problem(s)."))
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local", action="store_true", help="read data/silver instead of pulling from R2")
    ap.add_argument("--migrate-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="no server: load silver into a DDL-faithful SQLite proxy with Postgres-strict cell checks")
    ap.add_argument("--check-server", action="store_true",
                    help="only report whether the target server is fit for the load (version, encoding, rights, TLS)")
    ap.add_argument("--dsn", help="override DATABASE_URL")
    ap.add_argument("--workdir", help="where to download R2 objects (default: new temp dir)")
    args = ap.parse_args(argv)

    load_dotenv(ROOT / ".env")
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    def open_silver():
        work = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="fs_silver_"))
        work.mkdir(parents=True, exist_ok=True)
        if args.local:
            manifest, catalog = local_silver(ROOT / cfg.get("data_dir", "data"), work)
        else:
            manifest, catalog = pull_silver(r2.make_client(), r2.bucket_name(cfg), work)
        return work / "silver", manifest, catalog

    if args.dry_run:                     # no server needed
        return run_dry_run(*open_silver())

    dsn = args.dsn or os.environ.get("DATABASE_URL")
    if not dsn:
        ap.error("no database: set DATABASE_URL in .env (postgresql://user:pass@host:5432/db) or pass --dsn")
    conn = pg.connect(dsn)
    try:
        print(f"connected: {conn.run('SELECT current_database(), version()')[0][1].split(',')[0]}")
        if args.check_server:
            return print_server_report(conn)
        pg.migrate(conn, ROOT / "db" / "migrations")
        if args.migrate_only:
            return 0
        conn.run(f"SET search_path TO {pg.SCHEMA}, public")

        silver_root, manifest, catalog = open_silver()
        t0 = time.time()
        counts: dict[str, int] = {}
        conn.run("START TRANSACTION")
        try:
            conn.run(f"TRUNCATE {', '.join(f'{pg.SCHEMA}.{t}' for t in pg.LOAD_ORDER)}")
            for table in pg.LOAD_ORDER:
                for p in sorted((silver_root / table).rglob("*.csv")):
                    pg.copy_csv(conn, table, p)
                counts[table] = scalar(conn, f"SELECT count(*) FROM {pg.SCHEMA}.{table}")
            print(f"loaded {sum(counts.values()):,} rows into {len(counts)} tables in {time.time() - t0:.1f}s")
            for t, n in counts.items():
                print(f"  {t:<22}{n:>10,}")
            print("\nChecks")
            rep = validate(conn, counts, catalog, cfg["start_year"], cfg["end_year"], cfg)
            if rep.failed:
                conn.run("ROLLBACK")
                print(f"\n{rep.failed}/{rep.total} checks FAILED: rolled back, database unchanged.")
                return 1
            conn.run("INSERT INTO pipeline_run (run_id, manifest_key, gold_schema_version, row_counts) "
                     "VALUES (:r, :m, :g, CAST(:c AS jsonb)) ON CONFLICT (run_id) DO UPDATE SET loaded_at = now(), "
                     "row_counts = EXCLUDED.row_counts",
                     r=manifest["run_id"], m=f"_meta/manifests/run_id={manifest['run_id']}.json",
                     g=SCHEMA_VERSION, c=json.dumps(counts))
            conn.run("COMMIT")
        except Exception:
            conn.run("ROLLBACK")
            raise
        conn.run("ANALYZE")
        report_queries(conn)
        print(f"\n{rep.total}/{rep.total} checks passed; committed (run {manifest['run_id']})")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
