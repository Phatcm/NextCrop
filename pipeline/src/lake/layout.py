"""Bucket layout (data-lake conventions) shared by the uploader, the verifier and the DB loader.

    bronze/<source>/...                          raw, as downloaded. Append-only, never rewritten.
    silver/<dataset>/region_id=<id>/<dataset>.csv  cleaned flat tables, one folder per dataset,
    silver/<dataset>/<dataset>.csv                 Hive-style partition for per-region tables.
    gold/v<schema>/<name>.json                   app-ready JSON, versioned by data-contract schema.
    _meta/manifests/run_id=<UTC>.json            immutable log of every upload run (sizes, sha256, rows).
    _meta/catalog.json                           latest data dictionary: columns, types, keys per dataset.
    _meta/latest.json                            pointer to the newest complete run (written last = commit).
"""
from __future__ import annotations

LAYOUT_VERSION = "1"

BRONZE_SOURCES = {
    "power": "nasa_power",
    "gibs": "nasa_gibs",
    "appeears": "nasa_appeears",
    "gfsad": "usgs_gfsad30seace",
    "gaez": "fao_gaez_v5",
    "era5": "open_meteo_era5",
    "chirps": "chc_chirps_v3",
    "gbif": "gbif_backbone",
    "faostat": "fao_faostat",
}

# Natural (primary) key of every silver dataset. Uploads are blocked if a key is not unique.
DATASET_KEYS: dict[str, list[str]] = {
    "dim_region": ["region_id"],
    "dim_crop": ["crop_code"],
    "crop_profile": ["crop_code"],
    "power_daily": ["region_id", "date"],
    "power_monthly": ["region_id", "month"],
    "rain_validation": ["region_id", "year"],
    "rain_monthly_best": ["region_id", "month"],
    "ndvi_series": ["region_id", "source_key", "date"],
    "ndvi_raw": ["region_id", "source_key", "date"],
    "gaez_suitability": ["region_id", "crop_code", "input_mode", "period", "ssp"],
    "gaez_grid": ["lat", "lon", "crop_code"],
    "smap_daily": ["region_id", "date"],
    "gfsad_points": ["point"],
    "landcover_by_year": ["region_id", "year"],
    "landcover_classes": ["region_id", "year", "class_name"],
    "terrain": ["region_id"],
    "vn_grid_monthly": ["lat", "lon", "param", "yyyymm"],
}

CONTENT_TYPES = {
    ".csv": "text/csv; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".xml": "application/xml",
    ".md": "text/markdown; charset=utf-8",
}

LAYERS = ("bronze", "silver", "gold")


def content_type(name: str) -> str:
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return CONTENT_TYPES.get(suffix, "application/octet-stream")


def cache_control(layer: str) -> str | None:
    # gold is what the web app reads: short cache so a new run shows up within minutes
    return "public, max-age=300" if layer == "gold" else None


def map_key(rel: str, schema_version: str) -> tuple[str, str | None, str]:
    """Local path under data/ (posix, e.g. 'silver/thai_binh_rice/power_daily.csv')
    -> (layer, dataset_or_source, object key)."""
    parts = rel.split("/")
    layer = parts[0]
    if layer == "bronze" and len(parts) >= 3:
        src = BRONZE_SOURCES.get(parts[1])
        if src is None:
            raise ValueError(f"unknown bronze source folder: {parts[1]}")
        return "bronze", src, "/".join(["bronze", src, *parts[2:]])
    if layer == "silver" and len(parts) == 2 and parts[1].endswith(".csv"):
        name = parts[1][:-4]
        return "silver", name, f"silver/{name}/{parts[1]}"
    if layer == "silver" and len(parts) == 3 and parts[2].endswith(".csv"):
        region, fname = parts[1], parts[2]
        name = fname[:-4]
        return "silver", name, f"silver/{name}/region_id={region}/{fname}"
    if layer == "gold" and len(parts) == 2 and parts[1].endswith(".json"):
        return "gold", None, f"gold/v{schema_version}/{parts[1]}"
    raise ValueError(f"path does not fit the layout: {rel}")


LAYOUT_DOC = f"""# field-shift-nasa: bucket layout (v{LAYOUT_VERSION})

{__doc__.split(chr(10), 1)[1].strip()}

Rules
- Object keys are lowercase snake_case; per-region tables are partitioned as `region_id=<id>`.
- Every silver table has a natural key (see `_meta/catalog.json`); uploads fail if it is not unique.
- Every object carries `x-amz-meta-sha256`; `_meta/manifests` records size and sha256 of the whole snapshot.
- bronze is the source of truth: silver and gold can always be rebuilt from it with `run_etl.py --offline`.
- Missing values are empty cells in CSV and `null` in JSON, never 0.
"""
