"""Write silver CSVs and gold JSON (the data contract the web app reads)."""
from __future__ import annotations

import csv
import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

from src.models import NdviPoint, Region
from src.transformers.climate import annual_anomalies, grid_cells, monthly_normals, ndvi_profile

SCHEMA_VERSION = "0.3"   # 0.3: + suitability (GAEZ); silver ndvi tables unified with a source_key column
# additive changes since 0.3 (no bump): climate.rain_qa in gold, prectotcorr_qa in silver power_daily


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow({k: ("|".join(v) if isinstance(v, list) else v) for k, v in r.items()})


def write_json(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path


def _summary(series: list[NdviPoint]) -> dict:
    return {"n_dates": len(series),
            "n_measured": sum(p.source == "measured" for p in series),
            "n_interpolated": sum(p.source == "interpolated" for p in series),
            "n_missing": sum(p.source == "missing" for p in series),
            "first": series[0].date if series else None,
            "last": series[-1].date if series else None}


def landcover_check(lc: dict | None, min_cropland: float = 0.5) -> dict | None:
    """Latest-year MCD12Q1 verdict: is this bbox really cropland?"""
    if not lc:
        return None
    year = max(lc)
    v = lc[year]
    return {"year": int(year), "cropland_frac": v["cropland_frac"], "dominant": v["dominant"],
            "is_cropland": v["cropland_frac"] >= min_cropland}


def build_region_gold(region: Region, start_year: int, end_year: int, *, power: dict | None,
                      ndvi: dict[str, dict], smap: dict | None, landcover: dict | None,
                      elevation: dict | None, power_cfg: dict, suitability: dict | None = None,
                      rain_removed: list[dict] | None = None) -> dict:
    """ndvi = {source_key: {"description", "qa", "series": [NdviPoint]}}; suitability = gaez.gold_block()."""
    lat, lon = region.center
    lc_check = landcover_check(landcover)
    caveats = [
        "NASA POWER là dữ liệu mô hình/tái phân tích (MERRA-2, CERES) ~0.5 độ: không phân biệt từng thửa ruộng.",
        "GWETROOT/GWETTOP (độ ẩm đất POWER) là đầu ra mô hình MERRA-2, không phải đo vệ tinh; SMAP là đo vệ tinh (9 km).",
        "Ngày có source=interpolated là giá trị nội suy, không phải đo được.",
    ]
    if "gibs" in ndvi:
        caveats.append("NDVI 'gibs' lấy từ ảnh tô màu (làm tròn theo mức màu, không có QA gốc); chỉ dùng đối chiếu.")
    if region.status != "sample":
        if lc_check is None:
            caveats.append("Vùng ứng viên: chưa có lớp phủ đất để xác nhận.")
        elif not lc_check["is_cropland"]:
            caveats.append(f"CẢNH BÁO: MCD12Q1 {lc_check['year']} cho thấy chỉ {lc_check['cropland_frac']:.0%} "
                           f"điểm là đất trồng trọt (chủ yếu: {lc_check['dominant']}). Cần xem lại bbox.")
    primary = next((k for k in ("modis_qa", "gibs")
                    if k in ndvi and _summary(ndvi[k]["series"])["n_measured"] > 0), None)
    gold: dict = {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "region_id": region.id, "name": region.name, "status": region.status,
            "province_2025": region.province_2025, "zone": region.zone,
            "bbox": list(region.bbox), "center": {"lat": lat, "lon": lon},
            "years": [start_year, end_year], "generated_at": _now(),
            "landcover_check": lc_check, "caveats": caveats,
        },
        "terrain": elevation,
        "landcover": {"source": "MODIS MCD12Q1.061 LC_Type1 (IGBP), lưới 5x5 điểm, 500 m",
                      "by_year": landcover} if landcover else None,
        "climate": None,
        "ndvi": None,
        "soil_moisture": smap,
        "suitability": suitability,
    }
    if suitability:
        gold["metadata"]["caveats"].append(
            "GAEZ: chỉ số thích hợp là tiềm năng trung bình 20 năm; mô hình có thể lệch thực tế "
            "(ví dụ cà phê quanh Buôn Ma Thuột ra thấp); nhiều cây có thể trùng giá trị tại một điểm.")
    if power:
        params = list(power["daily"]["units"])
        gold["climate"] = {
            "source": f"NASA POWER (community={power_cfg.get('community', 'AG')})",
            "time_standard": power_cfg.get("time_standard", "LST"),
            "units": power["daily"]["units"],
            "daily_file": f"{region.id}_climate_daily.json",
            "monthly": power["monthly"]["rows"],
            "normals": monthly_normals(power["monthly"]["rows"], params),
            "annual_by_year": annual_anomalies(power["monthly"]["annual"], params),
            "missing_days": {p: sum(r[p] is None for r in power["daily"]["rows"]) for p in params},
        }
        if rain_removed is not None:
            qa = power_cfg.get("rain_qa") or {}
            gold["climate"]["rain_qa"] = {
                "rule": f"PRECTOTCORR ngày > {qa.get('max_daily_mm', 180.0):g} mm bị đặt NULL; tháng/năm có ngày đó "
                        "được tính lại từ các ngày còn lại (mm/ngày)",
                "removed_days": rain_removed}
            if rain_removed:
                gold["metadata"]["caveats"].append(
                    f"Mưa: đã loại {len(rain_removed)} ngày POWER có giá trị phi lý (" + ", ".join(
                        f"{d['date']} = {d['value_mm']:.0f} mm" for d in rain_removed) + ").")
    if ndvi:
        gold["ndvi"] = {"primary": primary, "sources": {}}
        for key, src in ndvi.items():
            pts = [asdict(p) for p in src["series"]]
            gold["ndvi"]["sources"][key] = {
                "description": src["description"], "qa": src["qa"],
                "summary": _summary(src["series"]), "profile": ndvi_profile(pts), "series": pts,
            }
    return gold


def write_region(gold_dir: Path, silver_dir: Path, gold: dict, power: dict | None,
                 raw_obs: dict[str, list], gaez_rows: list[dict] | None = None) -> Path:
    rid = gold["metadata"]["region_id"]

    def tbl(rows: list[dict]) -> list[dict]:
        """Silver tables are flat and self-describing: region_id is a real column, not only a path."""
        return [{"region_id": rid, **r} for r in rows]

    if power:
        write_csv(silver_dir / "power_daily.csv", tbl(power["daily"]["rows"]))
        write_csv(silver_dir / "power_monthly.csv", tbl(power["monthly"]["rows"]))
        write_json(gold_dir / f"{rid}_climate_daily.json",
                   {"region_id": rid, "units": power["daily"]["units"], "rows": power["daily"]["rows"]})
    # one NDVI table for all sources (source_key = modis_qa | gibs): the app/DB filters instead of joining
    if raw_obs:
        write_csv(silver_dir / "ndvi_raw.csv", tbl([{"source_key": key, **asdict(o)}
                                                    for key, obs in raw_obs.items() for o in obs]))
    if gold.get("ndvi"):
        write_csv(silver_dir / "ndvi_series.csv", tbl([{"source_key": key, **row}
                                                       for key, src in gold["ndvi"]["sources"].items()
                                                       for row in src["series"]]))
    if gaez_rows:
        write_csv(silver_dir / "gaez_suitability.csv", gaez_rows)  # rows already carry region_id
    if gold.get("soil_moisture"):
        write_csv(silver_dir / "smap_daily.csv", tbl(gold["soil_moisture"]["daily"]))
    lc = (gold.get("landcover") or {}).get("by_year") or {}
    if lc:
        write_csv(silver_dir / "landcover_by_year.csv", tbl(
            [{"year": int(y), "n_points": v["n"], "cropland_frac": v["cropland_frac"], "dominant": v["dominant"]}
             for y, v in sorted(lc.items())]))
        write_csv(silver_dir / "landcover_classes.csv", tbl(
            [{"year": int(y), "class_name": name, "frac": frac}
             for y, v in sorted(lc.items()) for name, frac in v["classes"].items()]))
    if gold.get("terrain"):
        t = gold["terrain"]
        write_csv(silver_dir / "terrain.csv", tbl([{"median_m": t["median_m"], "min_m": t["min_m"],
                                                    "max_m": t["max_m"], "n_points": t["n"]}]))
    return write_json(gold_dir / f"{rid}.json", gold)


def write_dim_crop(silver_dir: Path, rows: list[dict]) -> Path:
    path = silver_dir / "dim_crop.csv"
    write_csv(path, rows)
    return path


def write_dim_region(silver_dir: Path, gold_dir: Path, regions: list[Region]) -> Path:
    """silver/dim_region.csv: one row per region, rebuilt from every existing gold file
    (so a partial --regions run never truncates it)."""
    rows = []
    for r in regions:
        p = gold_dir / f"{r.id}.json"
        if not p.exists():
            continue
        g = json.loads(p.read_text(encoding="utf-8"))
        m, b = g["metadata"], g["metadata"]["bbox"]
        lc, c30 = m.get("landcover_check") or {}, g.get("cropland_30m") or {}
        rows.append({
            "region_id": m["region_id"], "name": m["name"], "status": m["status"],
            "province_2025": m.get("province_2025"), "zone": m.get("zone"),
            "lon_min": b[0], "lat_min": b[1], "lon_max": b[2], "lat_max": b[3],
            "center_lat": m["center"]["lat"], "center_lon": m["center"]["lon"],
            "year_start": m["years"][0], "year_end": m["years"][1],
            "ndvi_primary": (g.get("ndvi") or {}).get("primary"),
            "mcd12q1_cropland_frac": lc.get("cropland_frac"), "mcd12q1_dominant": lc.get("dominant"),
            "mcd12q1_is_cropland": lc.get("is_cropland"), "gfsad_bbox_crop_frac": c30.get("bbox_crop_frac"),
        })
    path = silver_dir / "dim_region.csv"
    write_csv(path, rows)
    return path


def write_grid(gold_dir: Path, silver_dir: Path, grid: dict, start_year: int, end_year: int) -> Path:
    cells = grid_cells(grid)
    long_rows = [{"lat": lat, "lon": lon, "param": p, "yyyymm": k, "value": v}
                 for (lat, lon), c in sorted(grid["cells"].items())
                 for p, series in c["params"].items() for k, v in sorted(series.items())]
    write_csv(silver_dir / "vn_grid_monthly.csv", long_rows)
    return write_json(gold_dir / "vn_climate_grid.json", {
        "schema_version": SCHEMA_VERSION, "generated_at": _now(),
        "source": "NASA POWER monthly/regional (MERRA-2 0.5 x 0.625 độ)",
        "years": [start_year, end_year], "units": grid["units"],
        "note": ("Lưới chữ nhật gồm cả ô trên biển/nước láng giềng; normals = trung bình tháng qua các năm. "
                 "ALLSKY_SFC_SW_DWN (CERES ~1 độ) được gán từ ô gần nhất vào lưới MERRA-2."),
        "cells": cells,
    })


def write_index(gold_dir: Path, regions: list[Region]) -> Path:
    """index.json: every region with a gold file + the VN grid, so the web app can discover data."""
    entries = []
    for r in regions:
        p = gold_dir / f"{r.id}.json"
        if not p.exists():
            continue
        g = json.loads(p.read_text(encoding="utf-8"))
        m = g["metadata"]
        entries.append({"file": p.name, "region_id": r.id, "name": m["name"], "status": m["status"],
                        "province_2025": m.get("province_2025"), "zone": m.get("zone"),
                        "center": m["center"], "bbox": m["bbox"], "years": m["years"],
                        "ndvi_primary": (g.get("ndvi") or {}).get("primary"),
                        "landcover_check": m.get("landcover_check")})
    grid = gold_dir / "vn_climate_grid.json"
    return write_json(gold_dir / "index.json", {
        "schema_version": SCHEMA_VERSION, "generated_at": _now(), "regions": entries,
        "vn_grid_file": grid.name if grid.exists() else None})
