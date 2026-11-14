"""Download the bronze layer of the latest R2 run into data/bronze, so `run_etl.py --offline`
can rebuild silver and gold on a machine that has no local cache.

Every object is verified against the sha256 in the run manifest; files that are already present
and identical are skipped, so re-running is cheap.

Usage (from pipeline/, R2 keys in .env):
    python pull_bronze.py --dry-run     # what would be downloaded (count, size)
    python pull_bronze.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from src.extractors.appeears_client import load_dotenv
from src.lake import r2
from src.lake.layout import BRONZE_SOURCES

ROOT = Path(__file__).resolve().parent
LOCAL_FOLDER = {v: k for k, v in BRONZE_SOURCES.items()}     # nasa_power -> power


def local_path(data_dir: Path, key: str) -> Path:
    """bronze/<source>/<rest> (bucket) -> data/bronze/<local folder>/<rest>."""
    parts = key.split("/")
    if parts[0] != "bronze" or len(parts) < 3 or parts[1] not in LOCAL_FOLDER:
        raise ValueError(f"not a bronze object of a known source: {key}")
    return data_dir / "bronze" / LOCAL_FOLDER[parts[1]] / Path(*parts[2:])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args(argv)

    load_dotenv(ROOT / ".env")
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    data_dir = ROOT / cfg.get("data_dir", "data")
    client, bucket = r2.make_client(), r2.bucket_name(cfg)

    def get(key: str) -> bytes:
        return client.get_object(Bucket=bucket, Key=key)["Body"].read()

    latest = json.loads(get("_meta/latest.json"))
    manifest = json.loads(get(latest["manifest_key"]))
    files = [f for f in manifest["files"] if f["layer"] == "bronze"]
    todo = []
    for f in files:
        dest = local_path(data_dir, f["key"])
        if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() == f["sha256"]:
            continue
        todo.append((f, dest))
    size = sum(f["size"] for f, _ in todo) if todo and "size" in todo[0][0] else 0
    print(f"run {manifest['run_id']}: {len(files)} bronze objects, {len(todo)} to download"
          + (f" ({size / 1e6:.1f} MB)" if size else ""))
    if args.dry_run or not todo:
        return 0

    def one(item):
        f, dest = item
        body = get(f["key"])
        if hashlib.sha256(body).hexdigest() != f["sha256"]:
            return f"sha256 mismatch: {f['key']}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        return None

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        errors = [e for e in pool.map(one, todo) if e]
    for e in errors:
        print("  FAILED", e)
    print(f"downloaded {len(todo) - len(errors)}/{len(todo)} into {data_dir / 'bronze'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
