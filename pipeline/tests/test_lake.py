import hashlib
import json

import pytest

pytest.importorskip("boto3")
from botocore.exceptions import ClientError

from src.lake import r2
from src.lake.layout import map_key
from src.lake.profile import describe_dataset


class FakeS3:
    def __init__(self):
        self.objs = {}

    def list_objects_v2(self, Bucket, Prefix="", ContinuationToken=None):
        c = [{"Key": k, "Size": len(v["body"]), "ETag": f'"{hashlib.md5(v["body"]).hexdigest()}"'}
             for k, v in sorted(self.objs.items()) if k.startswith(Prefix)]
        return {"Contents": c, "IsTruncated": False}

    def head_object(self, Bucket, Key):
        if Key not in self.objs:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"Metadata": self.objs[Key]["meta"]}

    def get_object(self, Bucket, Key):
        import io
        return {"Body": io.BytesIO(self.objs[Key]["body"])}

    def upload_file(self, Filename, Bucket, Key, ExtraArgs=None, Config=None):
        with open(Filename, "rb") as f:
            self.objs[Key] = {"body": f.read(), "meta": (ExtraArgs or {}).get("Metadata", {})}

    def put_object(self, Bucket, Key, Body, **kw):
        self.objs[Key] = {"body": Body, "meta": {}}


def test_map_key_layout():
    assert map_key("bronze/power/x.json", "0.2") == ("bronze", "nasa_power", "bronze/nasa_power/x.json")
    assert map_key("silver/thai_binh_rice/power_daily.csv", "0.2") == (
        "silver", "power_daily", "silver/power_daily/region_id=thai_binh_rice/power_daily.csv")
    assert map_key("silver/dim_region.csv", "0.2")[2] == "silver/dim_region/dim_region.csv"
    assert map_key("gold/index.json", "0.2")[2] == "gold/v0.2/index.json"
    with pytest.raises(ValueError):
        map_key("bronze/unknown/x", "0.2")
    with pytest.raises(ValueError):
        map_key("silver/a/b/c.csv", "0.2")


def _tree(tmp_path):
    d = tmp_path / "data"
    (d / "silver" / "r1").mkdir(parents=True)
    (d / "silver" / "r2").mkdir(parents=True)
    (d / "bronze" / "power").mkdir(parents=True)
    (d / "gold").mkdir()
    (d / "silver" / "r1" / "power_daily.csv").write_text("region_id,date,T2M\nr1,2015-01-01,1.5\nr1,2015-01-02,\n", "utf-8")
    (d / "silver" / "r2" / "power_daily.csv").write_text("region_id,date,T2M\nr2,2015-01-01,2\n", "utf-8")
    (d / "bronze" / "power" / "a.json").write_text("{}", "utf-8")
    (d / "gold" / "r1.json").write_text('{"a": 1}', "utf-8")
    return d


def test_profile_types_nulls_and_key():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as t:
        d = _tree(Path(t))
        e = describe_dataset(sorted((d / "silver").rglob("power_daily.csv")), ["region_id", "date"])
    assert e["rows"] == 3 and e["key_unique"] is True and not e["errors"]
    types = {c["name"]: (c["type"], c["null_count"]) for c in e["columns"]}
    assert types == {"region_id": ("text", 0), "date": ("date", 0), "T2M": ("real", 1)}


def test_profile_detects_duplicate_key_and_header_drift(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_text("region_id,date\nr1,2015-01-01\nr1,2015-01-01\n", "utf-8")
    b.write_text("region_id,day\nr2,2015-01-01\n", "utf-8")
    e = describe_dataset([a, b], ["region_id", "date"])
    assert e["key_unique"] is False
    assert any("duplicate keys" in x for x in e["errors"]) and any("header differs" in x for x in e["errors"])


def test_upload_is_idempotent_and_detects_changes(tmp_path):
    d = _tree(tmp_path)
    s3 = FakeS3()

    def run():
        items = r2.collect(d, ("bronze", "silver", "gold"), "0.2")
        r2.hash_all(items)
        datasets, errors = r2.quality_gate(items)
        assert not errors
        r2.sync(s3, "b", items, "run1", log=lambda *_: None)
        return items, datasets

    items, datasets = run()
    assert {i.action for i in items} == {"uploaded"}
    assert "silver/power_daily/region_id=r1/power_daily.csv" in s3.objs
    assert s3.objs["gold/v0.2/r1.json"]["meta"]["sha256"] == hashlib.sha256(b'{"a": 1}').hexdigest()

    items, datasets = run()
    assert {i.action for i in items} == {"skipped"}

    (d / "gold" / "r1.json").write_text('{"a": 2}', "utf-8")
    items, datasets = run()
    assert [i.key for i in items if i.action == "uploaded"] == ["gold/v0.2/r1.json"]

    m = r2.build_manifest(items, datasets, "run1", "0.2", ("bronze", "silver", "gold"))
    r2.publish_meta(s3, "b", m, datasets, "0.2", make_latest=True)
    assert json.loads(s3.objs["_meta/latest.json"]["body"])["manifest_key"] == "_meta/manifests/run_id=run1.json"
    assert r2.verify(s3, "b", log=lambda *_: None) == []
    s3.objs["silver/power_daily/region_id=r2/power_daily.csv"]["meta"]["sha256"] = "bad"
    assert any("sha256 mismatch" in p for p in r2.verify(s3, "b", log=lambda *_: None))


def test_quality_gate_blocks_bad_gold_json(tmp_path):
    d = _tree(tmp_path)
    (d / "gold" / "bad.json").write_text("{not json", "utf-8")
    items = r2.collect(d, ("silver", "gold"), "0.2")
    _, errors = r2.quality_gate(items)
    assert any("invalid JSON" in e for e in errors)
