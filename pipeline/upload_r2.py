"""Upload the ETL output to Cloudflare R2 (bronze/silver/gold + manifest + catalog).

Usage (from pipeline/):
    python upload_r2.py --dry-run            # show what would be uploaded, write nothing
    python upload_r2.py --init               # one-time bucket setup (lifecycle rule), then upload
    python upload_r2.py                      # upload everything that changed
    python upload_r2.py --prune              # also delete silver/gold objects the pipeline no longer produces
    python upload_r2.py --layers silver gold
    python upload_r2.py --verify             # check the bucket against the latest manifest
Credentials in .env: R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import yaml

from src.extractors.appeears_client import load_dotenv
from src.lake import r2
from src.lake.layout import LAYERS
from src.transformers.silver_to_gold import SCHEMA_VERSION

ROOT = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--bucket", help="override R2_BUCKET / r2.bucket")
    ap.add_argument("--prune", action="store_true", help="delete stale silver/gold objects (never bronze or _meta)")
    ap.add_argument("--layers", nargs="*", choices=LAYERS, default=list(LAYERS))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--init", action="store_true", help="apply bucket-level settings first")
    ap.add_argument("--verify", action="store_true", help="only verify the bucket against the latest manifest")
    ap.add_argument("--force", action="store_true", help="upload even if the quality gate fails (not advised)")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    rcfg = cfg.get("r2", {})
    workers = rcfg.get("workers", 8)
    load_dotenv(ROOT / ".env")
    bucket = args.bucket or r2.bucket_name(cfg)
    client = r2.make_client()
    print(f"bucket: {bucket}")

    if args.verify:
        problems = r2.verify(client, bucket)
        for p in problems:
            print("  -", p)
        return 1 if problems else 0

    if args.init and not args.dry_run:
        r2.init_bucket(client, bucket)

    layers = tuple(args.layers)
    data = ROOT / cfg.get("data_dir", "data")
    items = r2.collect(data, layers, SCHEMA_VERSION)
    r2.hash_all(items, workers)
    print(f"local: {len(items)} files, {sum(i.size for i in items) / 1e6:.1f} MB")

    datasets, errors = r2.quality_gate(items)
    for name, d in datasets.items():
        for w in d["warnings"]:
            print(f"  [warn] silver/{name}: {w}")
    print(f"quality gate: {len(datasets)} silver datasets, {sum(d['rows'] for d in datasets.values()):,} rows")
    if errors:
        for e in errors:
            print("  [FAIL]", e)
        if not args.force:
            print("Upload blocked. Fix the data (or pass --force).")
            return 1

    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    r2.sync(client, bucket, items, run_id, dry_run=args.dry_run, workers=workers)
    if args.dry_run:
        if args.prune:
            r2.prune(client, bucket, items, layers, dry_run=True)
        n = sum(i.action == "would-upload" for i in items)
        print(f"dry run: {n} object(s) would be uploaded; nothing written.")
        return 0

    manifest = r2.build_manifest(items, datasets, run_id, SCHEMA_VERSION, layers)
    r2.publish_meta(client, bucket, manifest, datasets, SCHEMA_VERSION, make_latest=set(layers) == set(LAYERS))
    if args.prune:  # only after the new manifest is the committed state
        r2.prune(client, bucket, items, layers)
    up = sum(i.action == "uploaded" for i in items)
    print(f"done: run {run_id}, {up} uploaded, {len(items) - up} unchanged.")
    problems = r2.verify(client, bucket) if set(layers) == set(LAYERS) else []
    for p in problems:
        print("  -", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
