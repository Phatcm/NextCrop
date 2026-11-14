"""Audit the R2 data lake against the Field Shift requirements. Reads ONLY what is in the bucket.

Pulls silver + gold from R2 (verifying sha256) and reports: integrity, coverage per region, NDVI
cross-source agreement, crop-cycle (phenology) check, location sanity, climate plausibility, rain
outliers, GAEZ coverage, and which data-contract fields exist. See docs/data-audit.md for the
interpretation of a past run.

Usage (from pipeline/):
    python audit_r2.py                 # downloads into a new temp dir
    python audit_r2.py <empty-dir>     # or into a directory you choose
"""
import collections
import csv
import hashlib
import json
import math
import statistics
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from src.extractors.appeears_client import load_dotenv  # noqa: E402
from src.lake import r2  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(ROOT / ".env")
cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
client, bucket = r2.make_client(), r2.bucket_name(cfg)
work = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="fs_audit_"))
work.mkdir(parents=True, exist_ok=True)


def get(key):
    return client.get_object(Bucket=bucket, Key=key)["Body"].read()


# ---------------------------------------------------------------- A. integrity
latest = json.loads(get("_meta/latest.json"))
manifest = json.loads(get(latest["manifest_key"]))
catalog = json.loads(get("_meta/catalog.json"))
print("== A. R2 integrity")
print(f"latest run {latest['run_id']}; catalog run {catalog['run_id']}; same run: {latest['run_id'] == catalog['run_id']}")
bad = 0
for f in manifest["files"]:
    if f["layer"] in ("silver", "gold"):
        body = get(f["key"])
        bad += hashlib.sha256(body).hexdigest() != f["sha256"]
        p = work / f["key"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
print(f"silver+gold downloaded and re-hashed: {sum(f['layer'] in ('silver', 'gold') for f in manifest['files'])} files, {bad} sha256 mismatches")
problems = r2.verify(client, bucket, log=lambda *_: None)
print(f"verify of all {len(manifest['files'])} manifest objects (incl. bronze): {len(problems)} problems")
remote = r2.list_remote(client, bucket)
extra = [k for k in remote if not k.startswith("_meta/") and k not in {f["key"] for f in manifest["files"]}]
print(f"objects in bucket not in manifest (excluding _meta): {len(extra)}")


def table(name):
    rows = []
    for p in sorted((work / "silver" / name).rglob("*.csv")):
        rows += [{k.lower(): v for k, v in r.items()} for r in csv.DictReader(p.open(encoding="utf-8-sig"))]
    return rows


def f(v):
    return None if v in ("", None) else float(v)


regions = {r["region_id"]: r for r in table("dim_region")}
power = collections.defaultdict(list)
for r in table("power_daily"):
    power[r["region_id"]].append(r)
ndvi = collections.defaultdict(lambda: collections.defaultdict(list))
for r in table("ndvi_series"):
    ndvi[r["region_id"]][r["source_key"]].append(r)
smap = collections.defaultdict(list)
for r in table("smap_daily"):
    smap[r["region_id"]].append(r)
lc = collections.defaultdict(dict)
for r in table("landcover_by_year"):
    lc[r["region_id"]][int(r["year"])] = r
terrain = {r["region_id"]: r for r in table("terrain")}
gaez = collections.defaultdict(list)
for r in table("gaez_suitability"):
    gaez[r["region_id"]].append(r)
crops = {r["crop_code"]: r for r in table("dim_crop")}

# ---------------------------------------------------------------- B. coverage
print("\n== B. Coverage per region (requirement: multi-year, gaps never 0)")
print(f"{'region':<24}{'power days':>11}{'power range':>24}{'nulls':>6} | {'ndvi dates':>10}{'measured':>9}{'worst yr':>9}{'range':>25}")
for rid in regions:
    p = power[rid]
    dates = sorted(x["date"] for x in p)
    nulls = sum(v == "" for x in p for k, v in x.items() if k != "gwettop")
    m = ndvi[rid]["modis_qa"]
    per_year = collections.defaultdict(lambda: [0, 0])
    for x in m:
        y = x["date"][:4]
        per_year[y][1] += 1
        per_year[y][0] += x["source"] == "measured"
    full = {y: a / b for y, (a, b) in per_year.items() if b >= 20}
    worst = min(full.items(), key=lambda kv: kv[1])
    ms = sum(x["source"] == "measured" for x in m)
    rng = sorted(x["date"] for x in m)
    print(f"{rid:<24}{len(p):>11}{dates[0] + ' .. ' + dates[-1]:>24}{nulls:>6} | {len(m):>10}{ms / len(m):>9.0%}{worst[1]:>7.0%}({worst[0][2:]}){rng[0] + '..' + rng[-1]:>25}")

print("\n   NDVI measured share by year (MODIS), % of 16-day dates actually measured:")
years = [str(y) for y in range(2015, 2026)]
print("   " + f"{'region':<24}" + "".join(f"{y[2:]:>5}" for y in years))
for rid in regions:
    per = collections.defaultdict(lambda: [0, 0])
    for x in ndvi[rid]["modis_qa"]:
        per[x["date"][:4]][1] += 1
        per[x["date"][:4]][0] += x["source"] == "measured"
    print("   " + f"{rid:<24}" + "".join(f"{(100 * per[y][0] / per[y][1] if per[y][1] else 0):>5.0f}" for y in years))

print("\n   SMAP (satellite soil moisture) and land cover:")
for rid in regions:
    s = smap[rid]
    rec = sum(x["sm_recommended"] != "" for x in s)
    print(f"   {rid:<24} smap days {len(s):>5}  recommended-quality {100 * rec / len(s):>3.0f}%  | MCD12Q1 years {min(lc[rid])}-{max(lc[rid])} ({len(lc[rid])} yrs)")

# ---------------------------------------------------------------- C. NDVI cross-source
print("\n== C. Accuracy: two independent NDVI sources over 2023-2025 (MODIS/AppEEARS vs GIBS image)")
for rid in regions:
    a = {x["date"]: f(x["median_final"]) for x in ndvi[rid]["modis_qa"] if x["source"] == "measured" and x["date"] >= "2023"}
    b = {x["date"]: f(x["median_final"]) for x in ndvi[rid].get("gibs", []) if x["source"] == "measured"}
    common = sorted(set(a) & set(b))
    if len(common) < 5:
        print(f"   {rid:<24} not enough common dates ({len(common)})")
        continue
    xs, ys = [a[d] for d in common], [b[d] for d in common]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    r = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    mae = statistics.fmean(abs(x - y) for x, y in zip(xs, ys))
    print(f"   {rid:<24} common dates {len(common):>3}  Pearson r {r:>5.2f}  mean |diff| {mae:.2f}  mean bias (GIBS-MODIS) {my - mx:+.2f}")


# ---------------------------------------------------------------- D. phenology
def peaks(vals, min_val=0.45, min_prom=0.15):
    out = []
    n = len(vals)
    for i in range(1, n - 1):
        v = vals[i]
        if v is None or v < min_val or not (v >= vals[i - 1] and v > vals[i + 1]):
            continue
        lm = rm = v
        l = i - 1
        while l >= 0 and vals[l] <= v:
            lm, l = min(lm, vals[l]), l - 1
        r_ = i + 1
        while r_ < n and vals[r_] <= v:
            rm, r_ = min(rm, vals[r_]), r_ + 1
        if v - max(lm, rm) >= min_prom:
            out.append(i)
    return out


print("\n== D. Phenology check: NDVI peaks (crop cycles) per full year, MODIS 2015-2025")
expect = {"thai_binh_rice": "2 (lúa 2 vụ)", "an_giang_rice": "2-3 (lúa 2-3 vụ)", "soc_trang_rice_shrimp": "1-2 (lúa-tôm)",
          "dak_lak_coffee": "~1 (cây lâu năm, ít biến động)", "son_la_maize": "1 (ngô vụ hè)", "ninh_thuan_dryland": "1-2 (khô hạn)"}
for rid in regions:
    s = sorted(ndvi[rid]["modis_qa"], key=lambda x: x["date"])
    idx = peaks([f(x["smoothed"]) for x in s])
    cnt = collections.Counter(s[i]["date"][:4] for i in idx)
    per = [cnt.get(str(y), 0) for y in range(2015, 2026)]
    print(f"   {rid:<24} peaks/year {per}  median {statistics.median(per)}   expected {expect.get(rid, '?')}")

# ---------------------------------------------------------------- E. location sanity
print("\n== E. Location sanity: NASADEM elevation vs the place each region claims to be")
want = {"thai_binh_rice": (0, 20), "an_giang_rice": (0, 20), "soc_trang_rice_shrimp": (0, 15), "ninh_thuan_dryland": (0, 100),
        "dak_lak_coffee": (300, 800), "son_la_maize": (400, 1100)}
for rid in regions:
    t = terrain[rid]
    lo, hi = want.get(rid, (-10, 9000))
    med = float(t["median_m"])
    print(f"   {rid:<24} median {med:>6.0f} m  [{float(t['min_m']):.0f}..{float(t['max_m']):.0f}]  expected {lo}-{hi} m  {'OK' if lo <= med <= hi else 'CHECK'}")

# ---------------------------------------------------------------- F. climate plausibility
print("\n== F. Climate plausibility (NASA POWER 2015-2025)")
print(f"   {'region':<24}{'T mean':>7}{'rain mm/yr':>11}{'rain min..max':>15}{'wettest':>9}{'T2M_MIN<5C days/yr':>20}{'RH>100':>8}")
for rid in regions:
    p = power[rid]
    t = statistics.fmean(f(x["t2m"]) for x in p)
    rain_by_year, by_month = collections.defaultdict(float), collections.defaultdict(float)
    for x in p:
        rain_by_year[x["date"][:4]] += f(x["prectotcorr"])
        by_month[x["date"][5:7]] += f(x["prectotcorr"])
    ys = list(rain_by_year.values())
    wet = max(by_month, key=by_month.get)
    cold = sum(1 for x in p if f(x["t2m_min"]) is not None and f(x["t2m_min"]) < 5) / 11
    rh = sum(1 for x in p if f(x["rh2m"]) is not None and f(x["rh2m"]) > 100)
    print(f"   {rid:<24}{t:>7.1f}{statistics.fmean(ys):>11.0f}{min(ys):>8.0f}..{max(ys):<6.0f}{'T' + wet:>9}{cold:>20.1f}{rh:>8}")

# ---------------------------------------------------------------- G. rain outliers
print("\n== G. Rain outliers (PRECTOTCORR is model output; a single day above ~250 mm is implausible in these regions)")
for rid in regions:
    best = max(power[rid], key=lambda x: f(x["prectotcorr"]))
    by_year = collections.defaultdict(float)
    for x in power[rid]:
        by_year[x["date"][:4]] += f(x["prectotcorr"])
    lo, hi = min(by_year, key=by_year.get), max(by_year, key=by_year.get)
    big = sum(f(x["prectotcorr"]) > 250 for x in power[rid])
    print(f"   {rid:<24} wettest day {best['date']} = {f(best['prectotcorr']):>4.0f} mm (days >250 mm: {big}) | "
          f"driest year {lo} {by_year[lo]:.0f} mm, wettest year {hi} {by_year[hi]:.0f} mm")

# ---------------------------------------------------------------- H. GAEZ
print("\n== H. GAEZ crop suitability coverage")
for rid in regions:
    g = gaez[rid]
    partial = [x for x in g if x["n_valid"] != x["n_px"]]
    zero_all = collections.defaultdict(int)
    for x in g:
        if f(x["value_max"]) == 0:
            zero_all[x["crop_code"]] += 1
    zero_crops = sorted(c for c, n in zero_all.items() if n == 4)
    print(f"   {rid:<24} {len(g)} values, windows with nodata pixels: {len(partial)}, crops with value 0 at all 4 levels: {zero_crops or '-'}")

# ---------------------------------------------------------------- I. requirement coverage
print("\n== I. Requirement coverage (what the data contract and the product need)")
gold_dir = work / "gold" / f"v{catalog['gold_schema_version']}"
one = json.loads((gold_dir / f"{next(iter(regions))}.json").read_text(encoding="utf-8"))
print("   dim_region columns:", ", ".join(next(iter(regions.values())).keys()))
print("   dim_crop columns  :", ", ".join(next(iter(crops.values())).keys()))
need_crop = ["planting_season", "growth_days", "temp_opt_min_c", "temp_opt_max_c", "cold_limit_c", "heat_limit_c",
             "water_need_mm", "is_legume", "ground_cover_erosion", "market_value", "source"]
have = set(next(iter(crops.values())).keys())
print("   crop-table fields from the data contract still missing:", ", ".join(c for c in need_crop if c not in have))
print("   gold metadata keys:", ", ".join(one["metadata"].keys()))
print("   power units in gold:", one["climate"]["units"])
print("   ndvi row keys     :", ", ".join(one["ndvi"]["sources"]["modis_qa"]["series"][0].keys()))
n_gold = {rid: len(json.loads((gold_dir / f"{rid}.json").read_text(encoding="utf-8"))["ndvi"]["sources"]["modis_qa"]["series"]) for rid in regions}
n_sil = {rid: len(ndvi[rid]["modis_qa"]) for rid in regions}
print("   gold vs silver NDVI row counts equal:", n_gold == n_sil)
print("   datasets in catalog:", ", ".join(catalog["datasets"]))
