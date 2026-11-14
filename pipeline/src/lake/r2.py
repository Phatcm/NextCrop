"""Idempotent upload of data/{bronze,silver,gold} to Cloudflare R2 (S3 API) + manifest + verification.

Credentials come from the environment / .env (R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY),
never from code. Re-running is safe: an object whose size and content hash already match is skipped.
Write order is bronze/silver -> gold -> _meta (manifest last, so _meta/latest.json is the commit marker).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from src.lake.layout import (DATASET_KEYS, LAYERS, LAYOUT_DOC, LAYOUT_VERSION, cache_control, content_type,
                             map_key)
from src.lake.profile import describe_dataset


@dataclass
class Item:
    path: Path
    rel: str
    layer: str
    dataset: str | None
    key: str
    size: int = 0
    sha256: str = ""
    md5: str = ""
    content_type: str = ""
    action: str = "pending"  # uploaded | skipped | would-upload


def make_client(env=os.environ):
    import boto3
    from botocore.config import Config
    # same variable names as pipeline/.env.example; R2_ENDPOINT is optional (derived from R2_ACCOUNT_ID)
    endpoint = env.get("R2_ENDPOINT") or (
        f"https://{env['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com" if env.get("R2_ACCOUNT_ID") else "")
    missing = [k for k in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY") if not env.get(k)]
    if not endpoint:
        missing.insert(0, "R2_ACCOUNT_ID")
    if missing:
        raise RuntimeError(f"missing in .env: {', '.join(missing)}")
    return boto3.client(
        "s3", endpoint_url=endpoint, aws_access_key_id=env["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=env["R2_SECRET_ACCESS_KEY"], region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"},
                      # R2 does not need the newer default CRC trailers
                      request_checksum_calculation="when_required",
                      response_checksum_validation="when_required"))


def bucket_name(cfg: dict, env=os.environ) -> str:
    """R2_BUCKET from .env wins over config.yaml (r2.bucket)."""
    name = env.get("R2_BUCKET") or cfg.get("r2", {}).get("bucket")
    if not name:
        raise RuntimeError("no bucket: set R2_BUCKET in .env or r2.bucket in config.yaml")
    return name


def prune(client, bucket: str, items: list["Item"], layers: tuple[str, ...], *, dry_run: bool = False,
          log=print) -> list[str]:
    """Delete silver/ and gold/ objects that the current local snapshot no longer produces
    (e.g. after a rename). bronze/ and _meta/ are never pruned."""
    keep = {i.key for i in items}
    stale = []
    for layer in ("silver", "gold"):
        if layer in layers:
            stale += [k for k in list_remote(client, bucket, f"{layer}/") if k not in keep]
    if stale and not dry_run:
        for i in range(0, len(stale), 1000):
            client.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": k} for k in stale[i:i + 1000]]})
    log(f"  [prune] {len(stale)} stale object(s) {'would be ' if dry_run else ''}deleted")
    return stale


def collect(data_dir: Path, layers: tuple[str, ...], schema_version: str) -> list[Item]:
    items = []
    for layer in layers:
        base = data_dir / layer
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix == ".part":
                continue
            rel = p.relative_to(data_dir).as_posix()
            lyr, dataset, key = map_key(rel, schema_version)
            items.append(Item(p, rel, lyr, dataset, key, content_type=content_type(p.name)))
    keys = [i.key for i in items]
    if len(keys) != len(set(keys)):
        raise ValueError("two local files map to the same object key")
    return items


def _digest(item: Item) -> Item:
    sha, md5 = hashlib.sha256(), hashlib.md5(usedforsecurity=False)
    with item.path.open("rb") as f:
        while chunk := f.read(1 << 20):
            sha.update(chunk)
            md5.update(chunk)
    item.size, item.sha256, item.md5 = item.path.stat().st_size, sha.hexdigest(), md5.hexdigest()
    return item


def hash_all(items: list[Item], workers: int = 8) -> None:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(_digest, items))


def quality_gate(items: list[Item]) -> tuple[dict, list[str]]:
    """Profile every silver dataset; return (catalog datasets, blocking errors)."""
    by_ds: dict[str, list[Path]] = {}
    for i in items:
        if i.layer == "silver":
            by_ds.setdefault(i.dataset, []).append(i.path)  # type: ignore[arg-type]
    datasets, errors = {}, []
    for name, paths in sorted(by_ds.items()):
        entry = describe_dataset(paths, DATASET_KEYS.get(name))
        if name not in DATASET_KEYS:
            entry["warnings"].append("dataset has no declared key in layout.DATASET_KEYS")
        datasets[name] = entry
        errors += [f"silver/{name}: {e}" for e in entry["errors"]]
    for i in items:
        if i.layer == "gold":
            try:
                json.loads(i.path.read_text(encoding="utf-8"))
            except ValueError as e:
                errors.append(f"gold/{i.path.name}: invalid JSON ({e})")
    return datasets, errors


def _is_missing(e: Exception) -> bool:
    code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
    return code in ("404", "NoSuchKey", "NotFound")


def list_remote(client, bucket: str, prefix: str = "") -> dict[str, dict]:
    out, token = {}, None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        r = client.list_objects_v2(**kw)
        for o in r.get("Contents", []):
            out[o["Key"]] = {"size": o["Size"], "etag": o["ETag"].strip('"')}
        if not r.get("IsTruncated"):
            return out
        token = r["NextContinuationToken"]


def _unchanged(client, bucket: str, item: Item, remote: dict | None) -> bool:
    if not remote or remote["size"] != item.size:
        return False
    if remote["etag"] == item.md5:
        return True
    try:
        meta = client.head_object(Bucket=bucket, Key=item.key).get("Metadata", {})
    except Exception as e:  # noqa: BLE001
        if _is_missing(e):
            return False
        raise
    return meta.get("sha256") == item.sha256


def _put(client, bucket: str, item: Item, run_id: str) -> None:
    from boto3.s3.transfer import TransferConfig
    extra = {"ContentType": item.content_type, "Metadata": {"sha256": item.sha256, "run-id": run_id}}
    cc = cache_control(item.layer)
    if cc:
        extra["CacheControl"] = cc
    client.upload_file(str(item.path), bucket, item.key, ExtraArgs=extra,
                       Config=TransferConfig(multipart_threshold=64 * 1024 * 1024, max_concurrency=4))


def sync(client, bucket: str, items: list[Item], run_id: str, *, dry_run: bool = False,
         workers: int = 8, log=print) -> None:
    remote = list_remote(client, bucket)

    def one(item: Item) -> Item:
        if _unchanged(client, bucket, item, remote.get(item.key)):
            item.action = "skipped"
        elif dry_run:
            item.action = "would-upload"
        else:
            _put(client, bucket, item, run_id)
            item.action = "uploaded"
        return item

    for group in (("bronze", "silver"), ("gold",)):  # gold last: readers never see new gold before its inputs
        batch = [i for i in items if i.layer in group]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, batch))
        n_up = sum(i.action in ("uploaded", "would-upload") for i in batch)
        log(f"  [{'+'.join(group)}] {len(batch)} objects: {n_up} to upload, {len(batch) - n_up} unchanged")


def build_manifest(items: list[Item], datasets: dict, run_id: str, schema_version: str,
                   layers: tuple[str, ...]) -> dict:
    rows = {n: d["rows"] for n, d in datasets.items()}
    return {
        "run_id": run_id,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "layout_version": LAYOUT_VERSION,
        "gold_schema_version": schema_version,
        "layers": list(layers),
        "totals": {lyr: {"objects": sum(i.layer == lyr for i in items),
                         "bytes": sum(i.size for i in items if i.layer == lyr)} for lyr in layers},
        "silver_rows": rows,
        "files": [{"key": i.key, "layer": i.layer, "dataset": i.dataset, "size": i.size, "sha256": i.sha256,
                   "content_type": i.content_type, "action": i.action} for i in items],
    }


def _put_json(client, bucket: str, key: str, obj, cache: str | None = None) -> None:
    kw = {"CacheControl": cache} if cache else {}
    client.put_object(Bucket=bucket, Key=key, Body=json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8"),
                      ContentType="application/json", **kw)


def read_catalog(client, bucket: str) -> dict | None:
    """Catalog of the latest published run, or None when the bucket has none yet."""
    try:
        return json.loads(client.get_object(Bucket=bucket, Key="_meta/catalog.json")["Body"].read())
    except client.exceptions.NoSuchKey:
        return None


def publish_meta(client, bucket: str, manifest: dict, datasets: dict, schema_version: str,
                 *, make_latest: bool) -> None:
    run_id = manifest["run_id"]
    mkey = f"_meta/manifests/run_id={run_id}.json"
    _put_json(client, bucket, mkey, manifest)
    if make_latest:
        _put_json(client, bucket, "_meta/catalog.json",
                  {"layout_version": LAYOUT_VERSION, "gold_schema_version": schema_version, "run_id": run_id,
                   "datasets": datasets})
        client.put_object(Bucket=bucket, Key="_meta/LAYOUT.md", Body=LAYOUT_DOC.encode("utf-8"),
                          ContentType="text/markdown; charset=utf-8")
        _put_json(client, bucket, "_meta/latest.json",
                  {"run_id": run_id, "manifest_key": mkey, "generated_at": manifest["generated_at"]})


def init_bucket(client, bucket: str, log=print) -> None:
    """Bucket-level hygiene: abort stale multipart uploads (they are billed but invisible)."""
    client.put_bucket_lifecycle_configuration(Bucket=bucket, LifecycleConfiguration={"Rules": [{
        "ID": "abort-incomplete-multipart-7d", "Status": "Enabled", "Filter": {"Prefix": ""},
        "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7}}]})
    log("  [init] lifecycle: abort incomplete multipart uploads after 7 days")


def verify(client, bucket: str, log=print) -> list[str]:
    """Compare the latest manifest with what is really in the bucket. Returns problems."""
    latest = json.loads(client.get_object(Bucket=bucket, Key="_meta/latest.json")["Body"].read())
    manifest = json.loads(client.get_object(Bucket=bucket, Key=latest["manifest_key"])["Body"].read())
    remote = list_remote(client, bucket)
    problems = []

    def check(f: dict) -> str | None:
        r = remote.get(f["key"])
        if r is None:
            return f"missing in bucket: {f['key']}"
        if r["size"] != f["size"]:
            return f"size mismatch {f['key']}: bucket {r['size']} vs manifest {f['size']}"
        meta = client.head_object(Bucket=bucket, Key=f["key"]).get("Metadata", {})
        if meta.get("sha256") != f["sha256"]:
            return f"sha256 mismatch: {f['key']}"
        return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        problems = [p for p in pool.map(check, manifest["files"]) if p]
    log(f"  [verify] run {manifest['run_id']}: {len(manifest['files'])} objects checked, {len(problems)} problems")
    return problems
