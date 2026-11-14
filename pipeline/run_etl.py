"""Field Shift ETL: NASA data -> bronze (cache) -> silver (CSV) -> gold (JSON for the web app).

Sources: NASA POWER (point + VN grid), AppEEARS (MOD13Q1 NDVI+QA, SMAP, MCD12Q1, NASADEM),
GFSAD30SEACE (cropland mask), FAO GAEZ v5 (crop suitability), GIBS NDVI (fallback, no account).

Usage (from pipeline/):
    python run_etl.py                          # everything in config.yaml
    python run_etl.py --regions thai_binh_rice an_giang_rice
    python run_etl.py --start 2020 --end 2025  # override year range
    python run_etl.py --no-wait                # submit AppEEARS tasks, don't wait; re-run later
    python run_etl.py --offline                # rebuild gold from cache only
    python run_etl.py --skip-appeears --skip-gibs --skip-grid
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from src.extractors import appeears_client, gaez, gfsad, gibs_ndvi, power_client
from src.http_client import HttpError
from src.models import Region
from src.transformers import appeears_transform as at
from src.transformers.ndvi_qa import build_series
from src.transformers.silver_to_gold import (build_region_gold, write_csv, write_dim_crop, write_dim_region,
                                             write_grid, write_index, write_region)

ROOT = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--regions", nargs="*", help="region ids (default: all)")
    ap.add_argument("--start", type=int, help="first year (default: config start_year)")
    ap.add_argument("--end", type=int, help="last year (default: config end_year)")
    ap.add_argument("--skip-power", action="store_true")
    ap.add_argument("--skip-grid", action="store_true", help="skip the Vietnam-wide POWER grid")
    ap.add_argument("--skip-gibs", action="store_true")
    ap.add_argument("--skip-appeears", action="store_true")
    ap.add_argument("--skip-gfsad", action="store_true")
    ap.add_argument("--skip-gaez", action="store_true", help="skip FAO GAEZ crop suitability")
    ap.add_argument("--no-wait", action="store_true", help="don't wait for AppEEARS tasks to finish")
    ap.add_argument("--offline", action="store_true", help="use cached downloads only")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    data = ROOT / cfg.get("data_dir", "data")
    bronze, silver, gold_dir = data / "bronze", data / "silver", data / "gold"
    all_regions = [Region.from_dict(r) for r in cfg["regions"]]
    regions = all_regions
    if args.regions:
        unknown = set(args.regions) - {r.id for r in all_regions}
        if unknown:
            ap.error(f"unknown region(s): {', '.join(sorted(unknown))}")
        regions = [r for r in all_regions if r.id in args.regions]
    start, end = args.start or cfg["start_year"], args.end or cfg["end_year"]
    if start > end:
        ap.error("--start must be <= --end")
    problems: list[str] = []

    # 1) AppEEARS first: submit so the server processes while we fetch the rest.
    #    Tasks always cover ALL config regions so a --regions run reuses the same tasks.
    ae_csv: dict[str, Path] = {}
    if not args.skip_appeears:
        print("== AppEEARS: submit / resume")
        try:
            appeears_client.run_tasks(cfg["appeears"], all_regions, start, end, bronze,
                                      offline=args.offline, wait=False)
        except HttpError as e:
            problems.append(f"appeears submit: {e}")
            print(f"  [appeears] FAILED: {e}")

    # 2) Vietnam-wide climate grid
    if not args.skip_grid and "vn_grid" in cfg:
        print(f"== VN climate grid {start}-{end}")
        try:
            grid = power_client.fetch_vn_grid(cfg["power"], cfg["vn_grid"], start, end,
                                              bronze / "power", args.offline)
            print(f"  [grid] {write_grid(gold_dir, silver, grid, start, end).relative_to(ROOT)} "
                  f"({len(grid['cells'])} cells)")
        except HttpError as e:
            problems.append(f"grid: {e}")
            print(f"  [grid] FAILED: {e}")

    # 3) per-region POWER + GIBS
    power_by: dict[str, dict] = {}
    gibs_by: dict[str, list] = {}
    for region in regions:
        print(f"== {region.id} ({region.name})")
        if not args.skip_power:
            lat, lon = region.center
            try:
                power_by[region.id] = power_client.fetch_power(cfg["power"], lat, lon, start, end,
                                                               bronze / "power", args.offline)
                p = power_by[region.id]
                print(f"  [power] {len(p['daily']['rows'])} days, {len(p['monthly']['rows'])} months")
            except HttpError as e:
                problems.append(f"power {region.id}: {e}")
                print(f"  [power] FAILED: {e}")
        if not args.skip_gibs:
            years = [y for y in cfg["gibs"].get("years", []) if start <= y <= end]
            obs = []
            try:
                for y in years:
                    obs += gibs_ndvi.fetch_series(cfg["gibs"], region, y, bronze / "gibs",
                                                  cfg["gibs"]["qa"], args.offline, log=lambda *_: None)
            except HttpError as e:
                problems.append(f"gibs colormap: {e}")
            if obs:
                gibs_by[region.id] = obs
                ok = sum(o.median is not None for o in obs)
                print(f"  [gibs] {ok}/{len(obs)} dates with data ({', '.join(map(str, years))})")
                if ok == 0:
                    problems.append(f"gibs {region.id}: no usable images")

    # 4) AppEEARS: wait (unless --no-wait) and parse
    ae_rows: dict[str, list[dict]] = {}
    if not args.skip_appeears:
        print("== AppEEARS: wait / download")
        try:
            ae_csv = appeears_client.run_tasks(cfg["appeears"], all_regions, start, end, bronze,
                                               offline=args.offline, wait=not args.no_wait)
        except HttpError as e:
            problems.append(f"appeears: {e}")
            print(f"  [appeears] FAILED: {e}")
        tasks = {t["key"]: t for t in cfg["appeears"]["tasks"]}
        for key, path in ae_csv.items():
            ae_rows[key] = appeears_client.read_results(path, tasks[key]["product"], tasks[key]["layers"])
            print(f"  [appeears] {key}: {len(ae_rows[key])} rows from {path.name}")
        missing = [k for k in tasks if k not in ae_csv]
        if missing:
            problems.append(f"appeears not ready: {', '.join(missing)}")

    # 4b) GFSAD 30 m cropland -> keep only pure-cropland MODIS points
    gf_stats: dict[str, dict] = {}
    allowed: dict[str, set[str]] = {}
    if not args.skip_gfsad and "gfsad" in cfg:
        print("== GFSAD30SEACE cropland mask")
        gcfg = cfg["gfsad"]
        tiles, missing = gfsad.ensure_tiles(regions, bronze / "gfsad", args.offline)
        for region in regions:
            s = gfsad.region_stats(tiles, region, cfg["appeears"].get("grid_n", 5), gcfg["crop_values"],
                                   gcfg.get("footprint_m", 250))
            if s is None:
                continue
            good = {p["point"] for p in s["points"]
                    if p["crop_frac"] is not None and p["crop_frac"] >= gcfg["min_point_crop_frac"]}
            s["n_points_kept"] = len(good)
            s["filter_applied"] = len(good) >= gcfg.get("min_points", 5)
            if s["filter_applied"]:
                allowed[region.id] = good
            gf_stats[region.id] = s
            write_csv(silver / region.id / "gfsad_points.csv",
                      [{"region_id": region.id, **p} for p in s["points"]])
            print(f"  [gfsad] {region.id}: bbox cropland {s['bbox_crop_frac']:.0%}, "
                  f"{len(good)}/{len(s['points'])} points kept, classes={s['classes']}")
        if missing:
            problems.append(f"gfsad: {len(missing)} tile(s) missing -> download manually into "
                            f"data/bronze/gfsad/: " + " ".join(missing))

    # 4c) FAO GAEZ crop suitability: windows read over HTTP (cached in bronze/gaez)
    gaez_rows: dict[str, list[dict]] = {}
    if not args.skip_gaez and "gaez" in cfg:
        print("== FAO GAEZ v5 crop suitability")
        gcfg = cfg["gaez"]
        windows, gproblems = gaez.fetch_windows(gcfg, regions, bronze / "gaez", offline=args.offline,
                                                workers=gcfg.get("workers", 4))
        problems += [f"gaez: {p}" for p in gproblems]
        for region, rows in ((r, gaez.build_rows(gcfg, [r], windows)) for r in regions):
            gaez_rows[region.id] = rows
            expected = len(gcfg["crops"]) * len(gcfg["modes"])
            print(f"  [gaez] {region.id}: {len(rows)}/{expected} crop x mode values")
            if len(rows) < expected:
                problems.append(f"gaez {region.id}: only {len(rows)}/{expected} values")
        write_dim_crop(silver, gaez.crop_dim_rows(gcfg))

    modis = at.modis_ndvi_observations(ae_rows["ndvi"], cfg["appeears"]["ndvi_qa"]["accept_reliability"],
                                       allowed) if "ndvi" in ae_rows else {}
    smap = at.smap_daily(ae_rows["smap"]) if "smap" in ae_rows else {}
    lc = at.landcover_by_year(ae_rows["landcover"]) if "landcover" in ae_rows else {}
    dem = at.elevation(ae_rows["dem"]) if "dem" in ae_rows else {}

    # 5) gold per region
    print("== gold")
    for region in regions:
        ndvi, raw = {}, {}
        if region.id in modis:
            raw["modis_qa"] = modis[region.id]
            pts_note = (f"; chỉ {len(allowed[region.id])} điểm >= {cfg['gfsad']['min_point_crop_frac']:.0%} "
                        f"đất canh tác theo GFSAD30 2015") if region.id in allowed else "; tất cả điểm lưới (chưa lọc GFSAD)"
            ndvi["modis_qa"] = {
                "description": "MODIS Terra MOD13Q1.061 250 m qua AppEEARS; median các điểm có "
                               "pixel_reliability chấp nhận được" + pts_note,
                "qa": cfg["appeears"]["ndvi_qa"],
                "series": build_series(modis[region.id], cfg["appeears"]["ndvi_qa"])}
        if region.id in gibs_by:
            raw["gibs"] = gibs_by[region.id]
            ndvi["gibs"] = {"description": f"NASA GIBS {cfg['gibs']['layer']} (ảnh màu -> bảng màu), dự phòng",
                            "qa": cfg["gibs"]["qa"], "series": build_series(gibs_by[region.id], cfg["gibs"]["qa"])}
        sm = None
        if smap.get(region.id):
            sm = {"source": "SMAP L3 Enhanced SPL3SMP_E.006, AM (6h sáng), 9 km, m3/m3",
                  "note": "sm_recommended = cờ chất lượng khuyến nghị; thảm thực vật dày (lúa) thường làm mất cờ này",
                  "daily": smap[region.id],
                  "monthly": at.monthly_mean(smap[region.id], ["sm_recommended", "sm_all"])}
        if region.id not in power_by and not ndvi:
            print(f"  [gold] {region.id}: no data, skipped")
            continue
        g = build_region_gold(region, start, end, power=power_by.get(region.id), ndvi=ndvi, smap=sm,
                              landcover=lc.get(region.id), elevation=dem.get(region.id),
                              power_cfg=cfg["power"],
                              suitability=gaez.gold_block(cfg["gaez"], gaez_rows.get(region.id, [])) if "gaez" in cfg else None)
        if region.id in gf_stats:
            s = gf_stats[region.id]
            g["cropland_30m"] = {"source": "GFSAD30SEACE v001 (2015, 30 m)", **s}
            if not s["filter_applied"]:
                g["metadata"]["caveats"].append(
                    f"GFSAD30: chỉ {s['n_points_kept']} điểm MODIS đủ 'thuần ruộng'; NDVI dùng tất cả điểm.")
        path = write_region(gold_dir, silver / region.id, g, power_by.get(region.id), raw,
                            gaez_rows.get(region.id))
        chk = g["metadata"]["landcover_check"]
        lc_txt = f", cropland {chk['cropland_frac']:.0%} ({chk['dominant']})" if chk else ""
        print(f"  [gold] {path.relative_to(ROOT)}  ndvi={g['ndvi']['primary'] if g['ndvi'] else None}{lc_txt}")
    print(f"[index] {write_index(gold_dir, all_regions).relative_to(ROOT)}")
    print(f"[silver] {write_dim_region(silver, gold_dir, all_regions).relative_to(ROOT)}")

    if problems:
        print("\nCHƯA ĐỦ / LỖI:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nOK: tất cả nguồn dữ liệu đã đủ.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
