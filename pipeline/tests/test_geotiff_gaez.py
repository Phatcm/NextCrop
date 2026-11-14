import http.server
import json
import threading
import zlib

import pytest

np = pytest.importorskip("numpy")
tifffile = pytest.importorskip("tifffile")

from src.extractors import gaez
from src.geotiff import GeoTiff, HttpRangeFile, decode_segment
from src.models import Region
from src.tiff_lzw import lzw_encode


def _write_tiff(path, arr, x0, y0, d, tile=(16, 16), nodata="-9"):
    extratags = [(33550, "d", 3, (d, d, 0.0), True), (33922, "d", 6, (0.0, 0.0, 0.0, x0, y0, 0.0), True),
                 (42113, "s", 0, nodata, True)]
    tifffile.imwrite(path, arr, compression="zlib", tile=tile, extratags=extratags)


class _RangeHandler(http.server.BaseHTTPRequestHandler):
    data = b""
    hits = 0

    def log_message(self, *a):
        pass

    def do_GET(self):
        type(self).hits += 1
        rng = self.headers.get("Range")
        if rng:
            a, b = rng.split("=")[1].split("-")
            a, b = int(a), min(int(b), len(self.data) - 1)
            body = self.data[a:b + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {a}-{b}/{len(self.data)}")
        else:
            body = self.data
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def serve(tmp_path):
    servers = []

    def _serve(data: bytes) -> str:
        handler = type("H", (_RangeHandler,), {"data": data, "hits": 0})
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        _serve.handler = handler
        return f"http://127.0.0.1:{srv.server_address[1]}/GAEZ-V5.test.tif"

    yield _serve
    for s in servers:
        s.shutdown()


def test_decode_segment_lzw_int16_and_predictor():
    arr = (np.arange(8 * 16).reshape(8, 16) * 37 - 2000).astype("<i2")
    assert (decode_segment(lzw_encode(arr.tobytes()), 5, 1, "<i2", 8, 16) == arr).all()
    diff = arr.copy()
    diff[:, 1:] = arr[:, 1:] - arr[:, :-1]
    assert (decode_segment(zlib.compress(diff.tobytes()), 8, 2, "<i2", 8, 16) == arr).all()
    assert (decode_segment(arr.tobytes(), 1, 1, "<i2", 8, 16) == arr).all()
    with pytest.raises(ValueError):
        decode_segment(b"x", 7, 1, "<i2", 8, 16)  # JPEG: not supported, must fail loudly


def test_remote_geotiff_reads_only_the_window(tmp_path, serve):
    arr = (np.arange(160 * 200).reshape(160, 200) % 10000).astype("<i2")
    arr[3, 3] = -9
    p = tmp_path / "g.tif"
    _write_tiff(p, arr, 100.0, 20.0, 0.01)           # lon 100..102, lat 18.4..20
    url = serve(p.read_bytes())
    g = GeoTiff(url, block=1 << 12)
    assert g.remote and g.nodata == -9 and g.shape == (160, 200) and g.name == "GAEZ-V5.test.tif"
    win, bounds = g.window_with_bounds(100.55, 19.05, 100.95, 19.45)  # cols 55..95, rows 55..95
    assert (win == arr[55:95, 55:95]).all()
    assert bounds == pytest.approx((100.55, 19.05, 100.95, 19.45))
    assert g.http_requests < len(p.read_bytes()) / (1 << 12)  # far fewer blocks than the whole file


def test_http_range_file_requires_range_support(tmp_path):
    class NoRange(_RangeHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "3")
            self.end_headers()
            self.wfile.write(b"abc")

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), NoRange)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pytest.raises(OSError):
            HttpRangeFile(f"http://127.0.0.1:{srv.server_address[1]}/x.tif", retries=1)
    finally:
        srv.shutdown()


REGION = Region.from_dict({"id": "r1", "bbox": [100.0, 19.0, 100.2, 19.2]})
CFG = {"period": "HP0120", "climate": "AGERA5", "ssp": "HIST", "modes": ["HRLM", "LRLM"],
       "crops": [{"code": "RCW", "name_vi": "Lúa nước"}, {"code": "SUC", "name_vi": "Mía", "name_verified": False}]}


def test_gaez_url_and_window_stats_exclude_nodata():
    assert gaez.file_url(CFG, "RCW", "HRLM").endswith("GAEZ-V5.RES05-SXX30AS.HP0120.AGERA5.HIST.RCW.HRLM.tif")
    win = {"bbox": list(REGION.bbox), "bounds": [100.0, 19.0, 100.2, 19.2], "shape": [2, 2], "nodata": -9,
           "values": [[-9, 4000], [6000, 8000]]}
    s = gaez.window_stats(win, REGION)
    assert s["n_px"] == 4 and s["n_valid"] == 3          # nodata is never counted as 0
    assert s["value_mean"] == 6000.0 and s["value_median"] == 6000 and s["value_min"] == 4000
    assert s["value_center"] in (4000, 6000, 8000, None)
    all_nodata = {**win, "values": [[-9, -9], [-9, -9]]}
    s0 = gaez.window_stats(all_nodata, REGION)
    assert s0["n_valid"] == 0 and s0["value_mean"] is None and s0["value_center"] is None


def test_gaez_fetch_uses_cache_offline_and_builds_rows(tmp_path):
    for crop in ("RCW", "SUC"):
        for mode in ("HRLM", "LRLM"):
            path = gaez._cache_path(CFG, tmp_path, crop, mode)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"windows": {"r1": {
                "bbox": list(REGION.bbox), "bounds": [100.0, 19.0, 100.2, 19.2], "shape": [1, 2], "nodata": -9,
                "values": [[1000 if mode == "LRLM" else 9000, 3000 if mode == "LRLM" else 8000]]}}}), "utf-8")
    windows, problems = gaez.fetch_windows(CFG, [REGION], tmp_path, offline=True, log=lambda *_: None)
    assert not problems
    rows = gaez.build_rows(CFG, [REGION], windows)
    assert len(rows) == 4 and {r["input_mode"] for r in rows} == {"HRLM", "LRLM"}
    block = gaez.gold_block(CFG, rows)
    assert block["values"]["RCW"] == {"HRLM": 8500.0, "LRLM": 2000.0}
    assert gaez.crop_dim_rows(CFG)[1] == {"crop_code": "SUC", "name_vi": "Mía", "name_verified": False}
    # a moved bbox invalidates the cached window (offline: it stays missing instead of being reused)
    moved = Region.from_dict({"id": "r1", "bbox": [100.0, 19.0, 100.3, 19.2]})
    w2, _ = gaez.fetch_windows(CFG, [moved], tmp_path, offline=True, log=lambda *_: None)
    assert gaez.window_stats(w2[("RCW", "HRLM")]["r1"], moved)["n_valid"] == 2  # offline never refetches


def test_layer_is_configurable_and_defaults_to_the_old_total_cell_layer(tmp_path):
    sux = {**CFG, "layer": "RES05-SUX"}
    assert gaez.layer_of(CFG) == "RES05-SXX30AS" and gaez.layer_of(sux) == "RES05-SUX"
    assert gaez.file_url(sux, "RCW", "HRLM") == (
        "https://storage.googleapis.com/fao-gismgr-gaez-v5-data/DATA/GAEZ-V5/MAPSET/RES05-SUX/"
        "GAEZ-V5.RES05-SUX.HP0120.AGERA5.HIST.RCW.HRLM.tif")
    assert gaez.file_url(CFG, "RCW", "HRLM").endswith("RES05-SXX30AS/GAEZ-V5.RES05-SXX30AS.HP0120.AGERA5.HIST.RCW.HRLM.tif")


def test_two_layers_never_share_a_cache_and_the_legacy_path_is_unchanged(tmp_path):
    old = gaez._cache_path(CFG, tmp_path, "RCW", "HRLM")
    new = gaez._cache_path({**CFG, "layer": "RES05-SUX"}, tmp_path, "RCW", "HRLM")
    assert old == tmp_path / "HP0120.AGERA5.HIST" / "RCW_HRLM.json"            # existing bronze keeps working
    assert new == tmp_path / "RES05-SUX" / "HP0120.AGERA5.HIST" / "RCW_HRLM.json" and new != old


def test_gold_block_names_the_layer_so_the_app_can_say_what_the_number_is():
    rows = [{"crop_code": "RCW", "input_mode": "HRLM", "value_mean": 8000.0, "value_median": 8000, "value_min": 7000,
             "value_max": 9000, "value_center": 8100, "n_valid": 4, "n_px": 4}]
    sux = gaez.gold_block({**CFG, "layer": "RES05-SUX"}, rows)
    assert "RES05-SUX" in sux["source"] and sux["layer"] == "RES05-SUX" and "đất canh tác" in sux["layer_note"]
    old = gaez.gold_block(CFG, rows)
    assert old["layer"] == "RES05-SXX30AS" and "cả ô" in old["layer_note"]
