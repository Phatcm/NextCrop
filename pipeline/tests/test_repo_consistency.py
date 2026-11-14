"""Consistency of the repository as a system: the pieces that must agree, and that broke (or nearly broke) on 14/11.

Examples caught here: two people numbering a migration 003 or 006 at the same time, a table added to the schema
but not to LOAD_ORDER (it would never be loaded), a dataset without a primary key in the lake layout (it would
bypass the uniqueness gate), a config crop that has no row in the crop tables.
"""
import csv
import re
from pathlib import Path

import pytest
import yaml

from src.db import postgres as pg
from src.lake import layout
from src.models import Region
from src.transformers.crop_profile import load_map
from src.transformers.crop_traits import load_traits

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / "db" / "migrations"
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def migrations():
    return sorted(MIG.glob("*.sql"))


def test_migration_numbers_are_unique_and_names_follow_the_pattern():
    names = [p.name for p in migrations()]
    assert names, "no migrations"
    numbers = []
    for n in names:
        m = re.fullmatch(r"(\d{3})_[a-z0-9_]+\.sql", n)
        assert m, f"bad migration file name: {n}"
        numbers.append(m.group(1))
    assert len(numbers) == len(set(numbers)), f"duplicate migration number among {names}"
    assert numbers == sorted(numbers)


def test_every_migration_records_its_own_version():
    for p in migrations():
        text = p.read_text(encoding="utf-8")
        versions = re.findall(r"INSERT INTO schema_migrations \(version\) VALUES \('([^']+)'\)", text)
        assert versions == [p.stem], f"{p.name} must register exactly '{p.stem}', found {versions}"


def schema_tables():
    out = set()
    for p in migrations():
        for t in re.findall(r"CREATE TABLE (\w+)\s*\(", p.read_text(encoding="utf-8")):
            out.add(t)
    return out - {"schema_migrations", "pipeline_run"}


def test_every_data_table_is_loaded_and_has_a_lake_key():
    tables = schema_tables()
    assert set(pg.LOAD_ORDER) == tables, f"LOAD_ORDER and migrations differ: {set(pg.LOAD_ORDER) ^ tables}"
    assert len(pg.LOAD_ORDER) == len(set(pg.LOAD_ORDER))
    assert set(layout.DATASET_KEYS) == tables, f"lake keys and migrations differ: {set(layout.DATASET_KEYS) ^ tables}"


def test_parents_are_loaded_before_children():
    """A table that REFERENCES another one must come after it in LOAD_ORDER (foreign keys on COPY)."""
    order = {t: i for i, t in enumerate(pg.LOAD_ORDER)}
    for p in migrations():
        text = p.read_text(encoding="utf-8")
        for m in re.finditer(r"CREATE TABLE (\w+)\s*\((.*?)\n\);", text, re.S):
            child = m.group(1)
            if child not in order:
                continue
            for parent in re.findall(r"REFERENCES (\w+)", m.group(2)):
                assert order[parent] < order[child], f"{child} is loaded before its parent {parent}"


def test_lake_keys_name_real_columns_of_the_table():
    cols = {}
    for p in migrations():
        text = p.read_text(encoding="utf-8")
        for m in re.finditer(r"CREATE TABLE (\w+)\s*\((.*?)\n\);", text, re.S):
            cols.setdefault(m.group(1), set()).update(re.findall(r"^\s{2}(\w+)\s", m.group(2), re.M))
            cols[m.group(1)].update(re.findall(r",\s*(\w+)\s+(?:text|double|smallint|integer|date|boolean|bigint)", m.group(2)))
    for table, key in layout.DATASET_KEYS.items():
        missing = [k for k in key if k not in cols.get(table, set())]
        assert not missing, f"{table}: key column(s) {missing} not in the schema"


def test_config_regions_are_valid_and_unique():
    regions = [Region.from_dict(r) for r in CFG["regions"]]
    assert len(regions) >= 3
    ids = [r.id for r in regions]
    assert len(ids) == len(set(ids))
    for r in regions:
        lon_min, lat_min, lon_max, lat_max = r.bbox
        assert 102 <= lon_min < lon_max <= 110 and 8 <= lat_min < lat_max <= 24, f"{r.id} is outside Viet Nam"
        assert lon_max - lon_min <= 0.2 and lat_max - lat_min <= 0.2, f"{r.id} bbox is larger than ~0.2 deg"
    assert CFG["start_year"] <= CFG["end_year"]


def test_config_crops_match_the_crop_tables():
    codes = [c["code"] for c in CFG["gaez"]["crops"]]
    assert len(codes) == len(set(codes))
    traits = load_traits(ROOT / "crop_traits.csv")
    assert set(codes) == set(traits), f"gaez crops vs crop_traits.csv: {set(codes) ^ set(traits)}"
    assert set(load_map(ROOT / "crop_profile_map.csv", known_crops=set(traits))) == set(codes)


def test_crop_traits_are_internally_consistent():
    for code, t in load_traits(ROOT / "crop_traits.csv").items():
        assert t["family"] and t["traits_source"] and t["family_source"], code
        if t["life_cycle"] == "perennial":
            assert t["cycle_days_min"] is None, f"{code}: a perennial crop has no per-season cycle"
        assert t["water_regime"] in ("wetland", "upland"), code
    legumes = {c for c, t in load_traits(ROOT / "crop_traits.csv").items() if t["is_legume"]}
    assert legumes == {"SOY", "GRD", "COW"}, "legume flags changed: update the rotation tests and the nitrogen logic"


def test_appeears_tasks_are_unique_and_have_layers():
    tasks = CFG["appeears"]["tasks"]
    keys = [t["key"] for t in tasks]
    assert len(keys) == len(set(keys))
    for t in tasks:
        assert t["product"] and t["layers"] and t["points"] in ("grid", "center")


def test_no_secret_shaped_value_is_committed_in_config_or_examples():
    secret = re.compile(r"(?i)(password|secret|token|api[_-]?key)\s*[:=]\s*['\"]?(?!\s|<|\$|your|xxx|example|changeme|\{)[A-Za-z0-9/+_-]{16,}")
    for p in [ROOT / "config.yaml", ROOT / ".env.example"]:
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            assert not secret.search(line), f"{p.name}:{n} looks like a committed secret"


def test_env_example_lists_every_variable_the_code_reads():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    needed = {"R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET",
              "EARTHDATA_USERNAME", "EARTHDATA_PASSWORD", "DATABASE_URL"}
    missing = [v for v in needed if v not in text]
    assert not missing, f".env.example lacks {missing}"


@pytest.mark.parametrize("path", sorted((ROOT / "src").rglob("*.py")))
def test_every_source_file_compiles(path):
    compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_crop_csvs_have_no_ragged_rows():
    for name in ("crop_traits.csv", "crop_profile_map.csv"):
        with open(ROOT / name, encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        width = len(rows[0])
        assert all(len(r) == width for r in rows), f"{name}: a row has the wrong number of cells"
