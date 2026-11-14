"""NDVI from NASA GIBS WMS colorized PNGs (MODIS_Terra_L3_NDVI_16Day).

GIBS PNGs are display images: values are quantized to colormap bins and there is no
original QA band. Treat results as approximate; prefer AppEEARS for validated NDVI.
"""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.http_client import HttpError, fetch_cached
from src.models import NdviObservation, Region
from src.png_decode import read_png

_ENTRY_RE = re.compile(r"<ColorMapEntry\b([^>]*?)/?>")
_ATTR_RE = re.compile(r'([\w:-]+)="([^"]*)"')
_NUM_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def composite_dates(year: int) -> list[str]:
    """MODIS 16-day composite start dates: DOY 1, 17, ..., 353 (23 dates)."""
    start = dt.date(year, 1, 1)
    return [(start + dt.timedelta(days=d)).isoformat() for d in range(0, 366, 16)
            if (start + dt.timedelta(days=d)).year == year]


def parse_colormap(xml_text: str) -> dict[tuple[int, int, int], float]:
    """rgb -> NDVI using the midpoint of each entry's value interval [min, max)."""
    table: dict[tuple[int, int, int], float] = {}
    for m in _ENTRY_RE.finditer(xml_text):
        attrs = dict(_ATTR_RE.findall(m.group(1)))
        if attrs.get("transparent", "false").lower() == "true" or attrs.get("nodata") == "true":
            continue
        if "rgb" not in attrs or "value" not in attrs:
            continue
        nums = [float(x) for x in _NUM_RE.findall(attrs["value"])]
        if not nums:
            continue
        rgb = tuple(int(v) for v in attrs["rgb"].split(","))[:3]
        table.setdefault(rgb, sum(nums) / len(nums))  # type: ignore[arg-type]
    if not table:
        raise ValueError("colormap has no usable entries")
    return table


class NdviLookup:
    def __init__(self, table: dict[tuple[int, int, int], float]):
        self.table = dict(table)
        self._items = list(table.items())
        self.n_nearest = 0  # how many distinct colors needed a nearest-match

    def __call__(self, rgb: tuple[int, int, int]) -> float:
        hit = self.table.get(rgb)
        if hit is not None:
            return hit
        r, g, b = rgb
        best = min(self._items, key=lambda kv: (kv[0][0] - r) ** 2 + (kv[0][1] - g) ** 2 + (kv[0][2] - b) ** 2)
        self.table[rgb] = best[1]
        self.n_nearest += 1
        return best[1]


def _percentile(sorted_vals: list[float], q: float) -> float:
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def qa_metrics(date: str, pixels: list[list[tuple[int, int, int, int]]], lookup: NdviLookup,
               cloud_below: float = 0.10) -> NdviObservation:
    total = sum(len(r) for r in pixels)
    vals = sorted(lookup(p[:3]) for row in pixels for p in row if p[3] >= 128)
    if not vals:
        return NdviObservation(date=date, valid_frac=0.0, cloud_frac=0.0, median=None)
    n = len(vals)
    return NdviObservation(
        date=date,
        valid_frac=round(n / total, 4),
        cloud_frac=round(sum(v < cloud_below for v in vals) / n, 4),
        median=round(_percentile(vals, 0.5), 4),
        mean=round(sum(vals) / n, 4),
        p80=round(_percentile(vals, 0.8), 4),
        min=round(vals[0], 4),
        max=round(vals[-1], 4),
        frac_below_030=round(sum(v < 0.30 for v in vals) / n, 4),
    )


def wms_url(cfg: dict, region: Region, date: str) -> str:
    lon_min, lat_min, lon_max, lat_max = region.bbox
    q = {
        "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.3.0",
        "LAYERS": cfg["layer"], "STYLES": "", "FORMAT": "image/png", "TRANSPARENT": "TRUE",
        "WIDTH": cfg["size_px"], "HEIGHT": cfg["size_px"], "CRS": "EPSG:4326",
        # WMS 1.3.0 + EPSG:4326 uses lat,lon axis order
        "BBOX": f"{lat_min},{lon_min},{lat_max},{lon_max}",
        "TIME": date,
    }
    return f"{cfg['wms_url']}?{urllib.parse.urlencode(q)}"


def load_lookup(cfg: dict, cache_dir: Path, offline: bool = False) -> NdviLookup:
    xml = fetch_cached(cfg["colormap_url"], cache_dir / "MODIS_L3_NDVI_colormap.xml",
                       offline=offline, timeout=cfg.get("timeout_s", 60))
    return NdviLookup(parse_colormap(xml.decode("utf-8")))


def fetch_series(cfg: dict, region: Region, year: int, cache_dir: Path, qa_cfg: dict,
                 offline: bool = False, log=print) -> list[NdviObservation]:
    lookup = load_lookup(cfg, cache_dir, offline)
    img_dir = cache_dir / region.id / str(year)

    def one(date: str) -> NdviObservation:
        try:
            png = fetch_cached(wms_url(cfg, region, date), img_dir / f"{date}.png", offline=offline,
                               timeout=cfg.get("timeout_s", 60), retries=cfg.get("retries", 3))
            _w, _h, px = read_png(png)
            obs = qa_metrics(date, px, lookup, qa_cfg.get("cloud_ndvi_below", 0.10))
            log(f"  [gibs] {region.id} {date} valid={obs.valid_frac:.0%} median={obs.median}")
            return obs
        except (HttpError, ValueError) as e:
            bad = img_dir / f"{date}.png"
            if bad.exists() and isinstance(e, ValueError):
                bad.unlink()  # don't keep a corrupt/XML-error response in cache
            log(f"  [gibs] {region.id} {date} FAILED: {e}")
            return NdviObservation(date=date, valid_frac=0.0, cloud_frac=0.0, median=None, error=str(e)[:200])

    with ThreadPoolExecutor(max_workers=cfg.get("workers", 4)) as pool:
        result = list(pool.map(one, composite_dates(year)))
    if lookup.n_nearest:
        log(f"  [gibs] {lookup.n_nearest} colors not in colormap, matched to nearest")
    return result
