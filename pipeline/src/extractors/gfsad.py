"""GFSAD30SEACE (cropland extent 2015, 30 m, SE/NE Asia) from LP DAAC.

Used to keep only "pure" cropland MODIS pixels: for each AppEEARS sample point we compute the
share of 30 m cropland pixels inside its ~250 m MODIS footprint (resolution harmonization).

Download needs Earthdata Login (same .env as AppEEARS). Tiles are 10x10 degree GeoTIFFs
(~15-40 MB each); only the tiles touching the configured regions are downloaded.
"""
from __future__ import annotations

import http.cookiejar
import json
import math
import os
import urllib.parse
import urllib.request
from pathlib import Path

from src.geotiff import GeoTiff, class_counts  # noqa: F401  (GeoTiff re-exported for callers)
from src.http_client import USER_AGENT, HttpError, request

CMR = "https://cmr.earthdata.nasa.gov/search/granules.json"
URS = "urs.earthdata.nasa.gov"


def find_tiles(bbox: tuple[float, float, float, float], short_name: str = "GFSAD30SEACE",
               version: str = "001") -> list[str]:
    q = urllib.parse.urlencode({"short_name": short_name, "version": version,
                                "bounding_box": ",".join(map(str, bbox)), "page_size": 20})
    feed = json.loads(request(f"{CMR}?{q}", timeout=60))["feed"]["entry"]
    urls = []
    for g in feed:
        for link in g.get("links", []):
            href = link.get("href", "")
            if href.endswith(".tif") and "data#" in link.get("rel", "") and href.startswith("https"):
                urls.append(href)
    return sorted(set(urls))


def _edl_opener(user: str, password: str) -> urllib.request.OpenerDirector:
    """urllib opener that answers the Earthdata Login challenge and keeps its cookies."""
    pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    pm.add_password(None, f"https://{URS}", user, password)
    return urllib.request.build_opener(urllib.request.HTTPBasicAuthHandler(pm),
                                       urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def download_tile(url: str, out_dir: Path, user: str | None, password: str | None,
                  token: str | None = None, log=print) -> Path:
    """Download one tile unless it is already in out_dir (manual downloads count too).

    Auth: EARTHDATA_TOKEN (Bearer) if set, else username/password via urs.earthdata.nasa.gov.
    """
    path = out_dir / Path(urllib.parse.urlparse(url).path).name
    if path.exists() and path.stat().st_size > 0:
        return path
    out_dir.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    elif user and password:
        opener = _edl_opener(user, password)
    else:
        raise HttpError("no Earthdata credentials (EARTHDATA_TOKEN or USERNAME/PASSWORD)")
    req = urllib.request.Request(url, headers=headers)
    tmp = path.with_suffix(".part")
    try:
        with opener.open(req, timeout=120) as resp, tmp.open("wb") as f:
            ctype = resp.headers.get("Content-Type", "")
            if "html" in ctype:
                raise HttpError(f"got HTML instead of GeoTIFF for {url} (login/EULA problem?)")
            while chunk := resp.read(1 << 20):
                f.write(chunk)
    except urllib.error.HTTPError as e:
        tmp.unlink(missing_ok=True)
        raise HttpError(f"HTTP {e.code} downloading {url}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        tmp.unlink(missing_ok=True)
        raise HttpError(f"cannot download {url}: {e} (urs.earthdata.nasa.gov reachable?)") from e
    tmp.replace(path)
    log(f"  [gfsad] downloaded {path.name} ({path.stat().st_size / 1e6:.1f} MB)")
    return path


def credentials() -> tuple[str | None, str | None, str | None]:
    from src.extractors.appeears_client import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    return (os.environ.get("EARTHDATA_USERNAME"), os.environ.get("EARTHDATA_PASSWORD"),
            os.environ.get("EARTHDATA_TOKEN") or None)


def _deg_box(lat: float, lon: float, half_m: float) -> tuple[float, float, float, float]:
    dlat = half_m / 111_320
    dlon = half_m / (111_320 * math.cos(math.radians(lat)))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def region_stats(tiles: list[GeoTiff], region, grid_n: int, crop_values: list[int],
                 footprint_m: float = 250) -> dict | None:
    """Cropland share of the whole bbox + of each AppEEARS grid point's MODIS footprint.

    Point ids match appeears_client.build_task ("<region>__NN", grid order).
    Returns None when no local tile covers the region.
    """
    import numpy as np
    tile = next((t for t in tiles if t.intersects(region.bbox)), None)
    if tile is None:
        return None
    crop = np.array(crop_values)

    def frac(arr):
        valid = arr if tile.nodata is None else arr[arr != tile.nodata]
        return (round(float(np.isin(valid, crop).mean()), 3) if valid.size else None), int(valid.size)

    whole = tile.window(*region.bbox)
    f_all, n_all = frac(whole)
    points = []
    for k, (lat, lon) in enumerate(region.grid_points(grid_n)):
        f, n = frac(tile.window(*_deg_box(lat, lon, footprint_m / 2)))
        points.append({"point": f"{region.id}__{k:02d}", "lat": lat, "lon": lon, "crop_frac": f, "n_px": n})
    return {"tile": tile.path.name, "bbox_crop_frac": f_all, "bbox_px": n_all,
            "classes": class_counts(whole, tile.nodata), "points": points}


def ensure_tiles(regions, out_dir: Path, offline: bool = False, log=print) -> tuple[list[GeoTiff], list[str]]:
    """Return (opened local tiles, list of tile URLs still missing)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / "tiles.json"
    known: dict[str, list[str]] = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    missing: list[str] = []
    for r in regions:
        if r.id not in known and not offline:
            try:
                known[r.id] = find_tiles(r.bbox)
                cache.write_text(json.dumps(known, indent=1), encoding="utf-8")
            except HttpError as e:
                log(f"  [gfsad] CMR search failed for {r.id}: {e}")
    urls = sorted({u for r in regions for u in known.get(r.id, [])})
    user, pw, token = credentials()
    for u in urls:
        local = out_dir / Path(urllib.parse.urlparse(u).path).name
        if local.exists():
            continue
        if offline:
            missing.append(u)
            continue
        try:
            download_tile(u, out_dir, user, pw, token, log)
        except HttpError as e:
            log(f"  [gfsad] {e}")
            missing.append(u)
    tiles = [GeoTiff(p) for p in sorted(out_dir.glob("*.tif"))]
    return tiles, missing
