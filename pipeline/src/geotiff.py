"""Windowed GeoTIFF reader without GDAL, for local files and for HTTP range requests.

Why: rasterio/imagecodecs DLLs are blocked on some machines. tifffile (pure Python) only parses the
TIFF tags; tile/strip bytes are decoded here (none, LZW, Deflate, predictor 1/2). Reading a small
window of a huge remote file therefore costs a few range requests, never the whole file.

Supports single-band, north-up, geographic (EPSG:4326-like) rasters with tiles or strips.
A GeoTiff object is NOT thread-safe: use one per thread.
"""
from __future__ import annotations

import contextlib
import io
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

from src.tiff_lzw import lzw_decode

USER_AGENT = "field-shift-pipeline/0.2"


class HttpRangeFile(io.RawIOBase):
    """Read-only seekable file over HTTP Range requests, with a block cache."""

    def __init__(self, url: str, block: int = 1 << 17, timeout: float = 60, retries: int = 3):
        super().__init__()
        self.url, self.block, self.timeout, self.retries = url, block, timeout, retries
        self.pos = 0
        self.requests = 0
        self._cache: dict[int, bytes] = {}
        self._lock = threading.Lock()
        head = self._get("bytes=0-0")
        total = head[1].split("/")[-1]
        if not total.isdigit():
            raise OSError(f"server does not support Range requests: {url}")
        self.size = int(total)

    def _get(self, rng: str) -> tuple[bytes, str]:
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(self.url, headers={"Range": rng, "User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    self.requests += 1
                    return resp.read(), resp.headers.get("Content-Range", "")
            except urllib.error.HTTPError as e:
                last = e
                if e.code < 500 and e.code != 429:
                    break
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = e
            time.sleep(1.5 * (2 ** attempt))
        raise OSError(f"range request failed for {self.url} ({rng}): {last}")

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        return self.pos

    def _block(self, i: int) -> bytes:
        with self._lock:
            if i not in self._cache:
                a, b = i * self.block, min((i + 1) * self.block, self.size) - 1
                self._cache[i] = self._get(f"bytes={a}-{b}")[0]
            return self._cache[i]

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self.size - self.pos
        end = min(self.pos + n, self.size)
        out, p = bytearray(), self.pos
        while p < end:
            blk = self._block(p // self.block)
            o = p % self.block
            chunk = blk[o:o + end - p]
            if not chunk:
                break
            out += chunk
            p += len(chunk)
        self.pos = end
        return bytes(out)

    def readinto(self, b) -> int:
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)

    def close(self) -> None:  # the cache must survive tifffile closing its handle
        pass


def decode_segment(data: bytes, compression: int, predictor: int, dtype, rows: int, width: int):
    """Decode one tile/strip into a (rows, width) array."""
    import numpy as np
    dtype = np.dtype(dtype)
    need = rows * width * dtype.itemsize
    if compression == 1:
        raw = data
    elif compression == 5:
        raw = lzw_decode(data, expected=need)
    elif compression in (8, 32946):
        raw = zlib.decompress(data)
    else:
        raise ValueError(f"unsupported TIFF compression {compression} (supported: none, LZW, Deflate)")
    if len(raw) < need:
        raw += bytes(need - len(raw))
    arr = np.frombuffer(raw[:need], dtype=dtype).reshape(rows, width)
    if predictor == 2:
        arr = np.cumsum(arr, axis=1, dtype=dtype)  # horizontal differencing, wraps like the encoder
    elif predictor != 1:
        raise ValueError(f"unsupported TIFF predictor {predictor}")
    return arr


class GeoTiff:
    def __init__(self, source: Path | str, *, block: int = 1 << 17):
        import tifffile
        text = str(source)
        self.remote = text.startswith(("http://", "https://"))
        self.source = text if self.remote else Path(source)
        self.name = Path(urllib.parse.urlparse(text).path).name if self.remote else self.source.name
        self.path = Path(self.name)  # kept for callers that report the file name
        self._remote = HttpRangeFile(text, block=block) if self.remote else None
        with self._open() as fh, tifffile.TiffFile(fh) as tf:
            pg = tf.pages[0]
            if pg.samplesperpixel != 1:
                raise ValueError("only single-band rasters are supported")
            tags = pg.tags
            scale, tie = tags["ModelPixelScaleTag"].value, tags["ModelTiepointTag"].value
            self.nodata = None
            if "GDAL_NODATA" in tags:
                try:
                    self.nodata = int(float(str(tags["GDAL_NODATA"].value).strip("\x00 ")))
                except ValueError:
                    pass
            self.shape = tuple(pg.shape[:2])
            self.dtype = pg.dtype
            self.dx, self.dy = scale[0], scale[1]
            self.x0 = tie[3] - tie[0] * self.dx   # tiepoint: raster (i, j) -> model (x, y)
            self.y0 = tie[4] + tie[1] * self.dy
            self.tiled = bool(pg.is_tiled)
            self.th, self.tw = (pg.tilelength, pg.tilewidth) if self.tiled else (pg.rowsperstrip, self.shape[1])
            self.compression, self.predictor = int(pg.compression), int(pg.predictor)
            self.offsets, self.counts = tuple(pg.dataoffsets), tuple(pg.databytecounts)

    def _open(self):
        return contextlib.nullcontext(self._remote) if self.remote else self.source.open("rb")

    @property
    def http_requests(self) -> int:
        return self._remote.requests if self._remote else 0

    def bounds(self) -> tuple[float, float, float, float]:
        h, w = self.shape
        return (self.x0, self.y0 - h * self.dy, self.x0 + w * self.dx, self.y0)

    def intersects(self, bbox) -> bool:
        x0, y0, x1, y1 = self.bounds()
        return bbox[0] < x1 and bbox[2] > x0 and bbox[1] < y1 and bbox[3] > y0

    def _rc_window(self, lon_min, lat_min, lon_max, lat_max) -> tuple[int, int, int, int]:
        h, w = self.shape
        eps = 1e-6  # snap edges that fall on a pixel border (54.9999999 must not become 54)
        c0 = max(0, int(math.floor((lon_min - self.x0) / self.dx + eps)))
        c1 = min(w, int(math.ceil((lon_max - self.x0) / self.dx - eps)))
        r0 = max(0, int(math.floor((self.y0 - lat_max) / self.dy + eps)))
        r1 = min(h, int(math.ceil((self.y0 - lat_min) / self.dy - eps)))
        return r0, r1, c0, c1

    def window_with_bounds(self, lon_min: float, lat_min: float, lon_max: float, lat_max: float):
        """(array, (x0, y0, x1, y1)): pixels covering the bbox, with the exact pixel-aligned bounds."""
        import numpy as np
        r0, r1, c0, c1 = self._rc_window(lon_min, lat_min, lon_max, lat_max)
        bounds = (self.x0 + c0 * self.dx, self.y0 - r1 * self.dy, self.x0 + c1 * self.dx, self.y0 - r0 * self.dy)
        out = np.zeros((max(0, r1 - r0), max(0, c1 - c0)), dtype=self.dtype)
        if out.size == 0:
            return out, bounds
        h, w = self.shape
        if self.tiled:
            ntx = (w + self.tw - 1) // self.tw
            cells = [(ty, tx, ty * ntx + tx) for ty in range(r0 // self.th, (r1 - 1) // self.th + 1)
                     for tx in range(c0 // self.tw, (c1 - 1) // self.tw + 1)]
        else:
            cells = [(sy, 0, sy) for sy in range(r0 // self.th, (r1 - 1) // self.th + 1)]
        with self._open() as fh:
            for ty, tx, idx in cells:
                fh.seek(self.offsets[idx])
                data = fh.read(self.counts[idx])
                rows = self.th if self.tiled else min(self.th, h - ty * self.th)
                seg = decode_segment(data, self.compression, self.predictor, self.dtype, rows, self.tw)
                sy0, sx0 = ty * self.th, tx * self.tw
                ys0, ys1 = max(r0, sy0), min(r1, sy0 + seg.shape[0])
                xs0, xs1 = max(c0, sx0), min(c1, sx0 + seg.shape[1])
                if ys1 > ys0 and xs1 > xs0:
                    out[ys0 - r0:ys1 - r0, xs0 - c0:xs1 - c0] = seg[ys0 - sy0:ys1 - sy0, xs0 - sx0:xs1 - sx0]
        return out, bounds

    def window(self, lon_min: float, lat_min: float, lon_max: float, lat_max: float):
        return self.window_with_bounds(lon_min, lat_min, lon_max, lat_max)[0]


def class_counts(arr, nodata: int | None = None) -> dict[int, int]:
    import numpy as np
    vals, counts = np.unique(arr, return_counts=True)
    return {int(v): int(c) for v, c in zip(vals, counts) if nodata is None or int(v) != nodata}
