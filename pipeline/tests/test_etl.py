import struct
import zlib

import pytest

from src.extractors.appeears_client import build_task, read_results, task_hash
from src.extractors.gibs_ndvi import NdviLookup, composite_dates, parse_colormap, qa_metrics
from src.extractors.power_client import build_url, parse_regional, parse_response
from src.models import NdviObservation, Region
from src.png_decode import read_png
from src.transformers.appeears_transform import (SM, SM_QF, landcover_by_year, modis_ndvi_observations,
                                                 monthly_mean, smap_daily)
from src.transformers.climate import annual_anomalies, grid_cells, monthly_normals, ndvi_profile
from src.transformers.ndvi_qa import build_series, flag_days, interpolate, moving_average
from src.transformers.silver_to_gold import build_region_gold, landcover_check

QA = {"cloud_ndvi_below": 0.10, "min_valid_frac": 0.90, "max_cloud_frac": 0.50,
      "min_median": 0.20, "max_drop_vs_neighbors": 0.50}


# ---------- PNG ----------
def _chunk(t: bytes, d: bytes) -> bytes:
    return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)


def _png(w, h, color_type, rows, filt=0, plte=b"", trns=b"", bit_depth=8):
    raw = b"".join(bytes([filt]) + r for r in rows)
    out = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, bit_depth, color_type, 0, 0, 0))
    if plte:
        out += _chunk(b"PLTE", plte)
    if trns:
        out += _chunk(b"tRNS", trns)
    return out + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b"")


def test_png_rgba_unfiltered():
    rows = [bytes([10, 20, 30, 255, 0, 0, 0, 0])]
    w, h, px = read_png(_png(2, 1, 6, rows))
    assert (w, h) == (2, 1)
    assert px[0] == [(10, 20, 30, 255), (0, 0, 0, 0)]


def test_png_sub_and_up_filters():
    # Sub filter: second pixel stored as delta from first
    w, h, px = read_png(_png(2, 1, 2, [bytes([100, 100, 100, 5, 5, 5])], filt=1))
    assert px[0] == [(100, 100, 100, 255), (105, 105, 105, 255)]
    # Up filter on row 2
    raw = b"\x00" + bytes([1, 2, 3]) + b"\x02" + bytes([1, 1, 1])
    data = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 2, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b""))
    assert read_png(data)[2][1] == [(2, 3, 4, 255)]


def test_png_palette_with_trns():
    plte = bytes([255, 0, 0, 0, 255, 0])
    w, h, px = read_png(_png(2, 1, 3, [bytes([0, 1])], plte=plte, trns=bytes([0])))
    assert px[0] == [(255, 0, 0, 0), (0, 255, 0, 255)]


def test_png_rejects_non_png():
    with pytest.raises(ValueError):
        read_png(b"<?xml version='1.0'?><ServiceExceptionReport/>")


# ---------- colormap / NDVI ----------
CMAP = """<ColorMaps><ColorMap title="NDVI"><Entries>
<ColorMapEntry rgb="0,0,0" transparent="true" sourceValue="[0]" value="[NaN]" nodata="true"/>
<ColorMapEntry rgb="200,200,200" transparent="false" sourceValue="[0,10)" value="[0.0,0.1)" label="0"/>
<ColorMapEntry rgb="0,128,0" transparent="false" sourceValue="[10,20)" value="[0.6,0.8)" label="0.7"/>
</Entries></ColorMap></ColorMaps>"""


def test_parse_colormap_midpoints_and_skips_transparent():
    t = parse_colormap(CMAP)
    assert t == {(200, 200, 200): pytest.approx(0.05), (0, 128, 0): pytest.approx(0.7)}


def test_lookup_nearest_color():
    lk = NdviLookup(parse_colormap(CMAP))
    assert lk((0, 130, 2)) == pytest.approx(0.7)
    assert lk.n_nearest == 1


def test_qa_metrics_counts_alpha_as_nodata():
    lk = NdviLookup(parse_colormap(CMAP))
    px = [[(0, 128, 0, 255)] * 3 + [(200, 200, 200, 255)], [(0, 0, 0, 0)] * 4]
    o = qa_metrics("2023-01-01", px, lk)
    assert o.valid_frac == 0.5
    assert o.cloud_frac == 0.25
    assert o.median == pytest.approx(0.7)


def test_composite_dates_23():
    d = composite_dates(2023)
    assert len(d) == 23 and d[0] == "2023-01-01" and d[1] == "2023-01-17" and d[-1] == "2023-12-19"


# ---------- QA + interpolation (values from FIELD-SHIFT-NOTES 3.3) ----------
def _notes_obs():
    rows = [("2023-01-01", 1.0, 0.89, 0.07), ("2023-01-17", 0.97, 0.06, 0.30),
            ("2023-02-02", 1.0, 0.98, 0.04), ("2023-02-18", 1.0, 0.02, 0.38),
            ("2023-03-22", 1.0, 0.0, 0.55), ("2023-04-23", 1.0, 0.0, 0.70),
            ("2023-07-28", 1.0, 0.0, 0.57), ("2023-12-19", 1.0, 0.01, 0.36)]
    return [NdviObservation(date=d, valid_frac=v, cloud_frac=c, median=m) for d, v, c, m in rows]


def test_notes_example_reproduced():
    s = build_series(_notes_obs(), QA)
    flags = [p.flag_bad for p in s]
    assert flags == [True, False, True, False, False, False, False, False]
    assert s[0].median_final == pytest.approx(0.30)
    assert s[2].median_final == pytest.approx(0.34)
    assert s[2].source == "interpolated" and s[1].source == "measured"
    assert "nhiều pixel giống mây" in s[0].reasons


def test_drop_vs_neighbors_rule():
    obs = [NdviObservation("2023-01-01", 1, 0, 0.7), NdviObservation("2023-01-17", 1, 0, 0.3),
           NdviObservation("2023-02-02", 1, 0, 0.7)]
    assert flag_days(obs, QA)[1] == ["sụt mạnh so với ngày kề"]


def test_failed_download_is_missing_not_zero():
    obs = [NdviObservation("2023-01-01", 0, 0, None, error="timeout")]
    s = build_series(obs, QA)
    assert s[0].median_final is None and s[0].source == "missing"
    assert s[0].reasons == ["không tải được ảnh"]


def test_interpolate_edges_and_moving_average():
    dates = ["2023-01-01", "2023-01-17", "2023-02-02"]
    assert interpolate(dates, [0.1, 0.5, 0.2], [False, False, True]) == [0.1, 0.5, 0.5]
    assert moving_average([1.0, 2.0, 3.0]) == [1.5, 2.0, 2.5]


# ---------- POWER ----------
def test_power_parse_fill_and_annual():
    payload = {"header": {"fill_value": -999.0},
               "parameters": {"T2M": {"units": "C"}},
               "properties": {"parameter": {"T2M": {"202301": 17.2, "202302": -999.0, "202313": 24.0}}}}
    r = parse_response(payload, "monthly")
    assert r["rows"] == [{"month": "2023-01", "T2M": 17.2}, {"month": "2023-02", "T2M": None}]
    assert r["annual"] == {"2023": {"T2M": 24.0}}
    assert r["units"] == {"T2M": "C"}


def test_power_url():
    u = build_url("https://x/api/temporal", "daily", 20.45, 106.3, "20230101", "20231231", ["T2M"], "AG", "LST")
    assert "/daily/point?" in u and "latitude=20.4500" in u and "time-standard=LST" in u


def test_power_regional_parse():
    payload = {"header": {"fill_value": -999.0},
               "parameters": {"T2M": {"units": "C"}},
               "features": [{"geometry": {"coordinates": [106.25, 20.5, 3.1]},
                             "properties": {"parameter": {"T2M": {"202301": 17.0, "202313": -999.0}}}}]}
    cells, units, _ = parse_regional(payload)
    assert cells[(20.5, 106.25)]["values"] == {"202301": 17.0, "202313": None}
    assert units == {"T2M": "C"}


# ---------- climate ----------
def test_normals_and_anomalies():
    rows = [{"month": "2015-01", "P": 1.0}, {"month": "2016-01", "P": 3.0}, {"month": "2016-02", "P": None}]
    n = monthly_normals(rows, ["P"])
    assert n["P"][0] == 2.0 and n["P"][1] is None
    a = annual_anomalies({"2015": {"P": 1.0}, "2016": {"P": 3.0}}, ["P"])
    assert a["2015"]["P_anom"] == -1.0 and a["2016"]["P_anom"] == 1.0


def test_grid_cells_normals():
    grid = {"cells": {(20.5, 106.25): {"elev": 3, "params": {"T": {"201501": 10.0, "201601": 20.0,
                                                                  "201513": 15.0}}}}}
    c = grid_cells(grid)[0]
    assert c["normals"]["T"][0] == 15.0 and c["annual"]["T"] == {"2015": 15.0}


def test_grid_coarse_param_filled_from_nearest():
    grid = {"cells": {(20.0, 106.0): {"elev": 1, "params": {"T": {"201501": 1.0}}},
                      (20.5, 106.0): {"elev": 1, "params": {"T": {"201501": 2.0}}},
                      (20.4, 106.1): {"elev": None, "params": {"SOL": {"201501": 9.0}}}}}
    cells = grid_cells(grid)
    assert len(cells) == 2  # solar-only cell is dropped, its value copied to both
    assert all(c["normals"]["SOL"][0] == 9.0 for c in cells)


def test_ndvi_profile_across_years():
    pts = [{"date": "2015-01-01", "median_final": 0.2}, {"date": "2016-01-01", "median_final": 0.4},
           {"date": "2016-12-18", "median_final": 0.5}]  # leap year DOY 353 -> last slot
    prof = ndvi_profile(pts)
    assert prof[0]["median"] == pytest.approx(0.3) and prof[0]["n_years"] == 2
    assert prof[22]["n_years"] == 1


# ---------- AppEEARS ----------
REGION = Region.from_dict({"id": "r1", "name": "R", "bbox": [106.25, 20.40, 106.35, 20.50]})


def test_grid_points_inside_bbox():
    pts = REGION.grid_points(5)
    assert len(pts) == 25
    assert all(20.40 < la < 20.50 and 106.25 < lo < 106.35 for la, lo in pts)


def test_build_task_and_stable_hash():
    tcfg = {"key": "ndvi", "product": "MOD13Q1.061", "layers": ["_250m_16_days_NDVI"], "points": "grid",
            "start": "01-01-{start_year}", "end": "12-31-{end_year}"}
    t = build_task(tcfg, [REGION], 2, 2015, 2025)
    assert t["params"]["dates"] == [{"startDate": "01-01-2015", "endDate": "12-31-2025"}]
    assert len(t["params"]["coordinates"]) == 4
    assert t["params"]["coordinates"][0]["id"] == "r1__00"
    assert task_hash(t) == task_hash(build_task(tcfg, [REGION], 2, 2015, 2025))
    center = build_task({**tcfg, "points": "center"}, [REGION], 5, 2015, 2025)
    assert len(center["params"]["coordinates"]) == 1


def test_read_results_and_modis_qa(tmp_path):
    p = tmp_path / "x-MOD13Q1-061-results.csv"
    p.write_text(
        "ID,Category,Latitude,Longitude,Date,MOD13Q1_061__250m_16_days_NDVI,"
        "MOD13Q1_061__250m_16_days_pixel_reliability,MOD13Q1_061__250m_16_days_NDVI_extra\n"
        "r1__00,r1,20.41,106.26,2015-01-01,0.8,0,x\n"
        "r1__01,r1,20.41,106.28,2015-01-01,6000,1,x\n"      # raw int -> scaled 0.6
        "r1__02,r1,20.41,106.30,2015-01-01,0.1,3,x\n"       # cloudy -> rejected
        "r1__03,r1,20.41,106.32,2015-01-01,-0.3,-1,x\n",    # fill
        encoding="utf-8")
    rows = read_results(p, "MOD13Q1.061", ["_250m_16_days_NDVI", "_250m_16_days_pixel_reliability"])
    assert rows[0]["region"] == "r1" and rows[1]["_250m_16_days_NDVI"] == 6000
    o = modis_ndvi_observations(rows, [0, 1])["r1"][0]
    assert o.valid_frac == 0.5 and o.cloud_frac == 0.25
    assert o.median == pytest.approx(0.7)


def test_modis_point_filter():
    rows = [{"region": "r1", "point": f"r1__0{i}", "date": "2015-01-01",
             "_250m_16_days_NDVI": v, "_250m_16_days_pixel_reliability": 0} for i, v in enumerate([0.2, 0.8, 0.9])]
    o = modis_ndvi_observations(rows, [0], {"r1": {"r1__01", "r1__02"}})["r1"][0]
    assert o.median == pytest.approx(0.85) and o.valid_frac == 1.0


def test_smap_recommended_flag():
    rows = [{"region": "r1", "date": "2016-05-01", SM: 0.30, SM_QF: 0},
            {"region": "r1", "date": "2016-05-02", SM: 0.40, SM_QF: 1},
            {"region": "r1", "date": "2016-05-03", SM: -9999.0, SM_QF: 65534}]
    d = smap_daily(rows)["r1"]
    assert d == [{"date": "2016-05-01", "sm_recommended": 0.3, "sm_all": 0.3},
                 {"date": "2016-05-02", "sm_recommended": None, "sm_all": 0.4}]
    m = monthly_mean(d, ["sm_recommended", "sm_all"])[0]
    assert m["sm_recommended"] == 0.3 and m["n_sm_recommended"] == 1 and m["sm_all"] == 0.35


def test_landcover_check():
    rows = [{"region": "r1", "date": "2023-01-01", "LC_Type1": v} for v in (12, 12, 14, 13)]
    lc = landcover_by_year(rows)["r1"]
    assert lc["2023"]["cropland_frac"] == 0.75 and lc["2023"]["dominant"] == "Đất trồng trọt"
    assert landcover_check(lc)["is_cropland"] is True


def test_qa_rules_can_be_disabled():
    qa = {"min_valid_frac": 0.3, "max_cloud_frac": 0.7, "min_median": None, "max_drop_vs_neighbors": None}
    obs = [NdviObservation("2023-01-01", 1, 0, 0.7), NdviObservation("2023-01-17", 1, 0, 0.1),
           NdviObservation("2023-02-02", 1, 0, 0.7)]
    assert flag_days(obs, qa) == [[], [], []]  # flooded paddy keeps its real low NDVI


# ---------- gold ----------
def test_region_gold_contract_shape():
    g = build_region_gold(REGION, 2015, 2025, power=None,
                          ndvi={"gibs": {"description": "d", "qa": QA, "series": build_series(_notes_obs(), QA)}},
                          smap=None, landcover=None, elevation=None, power_cfg={})
    assert g["metadata"]["center"] == {"lat": 20.45, "lon": 106.3}
    src = g["ndvi"]["sources"]["gibs"]
    for k in ("date", "median_final", "source", "flag_bad", "reasons"):
        assert k in src["series"][0]
    assert src["summary"]["n_interpolated"] == 2 and g["ndvi"]["primary"] == "gibs"
    assert len(src["profile"]) == 23


# ---------- GFSAD GeoTIFF window reader ----------
def _geotiff(path, arr, x0, y0, d, tiled):
    tifffile = pytest.importorskip("tifffile")
    extratags = [(33550, "d", 3, (d, d, 0.0), True),
                 (33922, "d", 6, (0.0, 0.0, 0.0, x0, y0, 0.0), True),
                 (42113, "s", 0, "255", True)]
    kw = {"tile": (16, 16)} if tiled else {"rowsperstrip": 7}
    tifffile.imwrite(path, arr, compression="zlib", extratags=extratags, **kw)


@pytest.mark.parametrize("tiled", [True, False])
def test_geotiff_window_matches_numpy(tmp_path, tiled):
    np = pytest.importorskip("numpy")
    from src.extractors.gfsad import GeoTiff
    arr = (np.arange(50 * 40).reshape(50, 40) % 3).astype("uint8")
    arr[0, 0] = 255
    p = tmp_path / "t.tif"
    _geotiff(p, arr, 100.0, 20.0, 0.1, tiled)  # covers lon 100..104, lat 15..20
    g = GeoTiff(p)
    assert g.bounds() == pytest.approx((100.0, 15.0, 104.0, 20.0))
    assert g.nodata == 255
    w = g.window(100.95, 17.05, 102.35, 19.45)  # cols 9..24, rows 5..30
    assert (w == arr[5:30, 9:24]).all()


def test_lzw_roundtrip():
    from src.tiff_lzw import lzw_decode, lzw_encode
    import random
    random.seed(1)
    for data in (b"", b"a", b"abcabcabc" * 50, bytes(range(256)) * 20,
                 bytes(random.choice(b"0123") for _ in range(20000)),   # forces table resets + 12-bit codes
                 bytes(random.randrange(256) for _ in range(6000))):
        assert lzw_decode(lzw_encode(data)) == data


def test_lzw_matches_tifffile_reference(tmp_path):
    """Our decoder must agree with tifffile's own (spec-conformant) LZW writer, when available."""
    np = pytest.importorskip("numpy")
    from src.tiff_lzw import lzw_decode
    imagecodecs = pytest.importorskip("imagecodecs")
    try:
        ref = imagecodecs.lzw_encode(bytes(range(200)) * 30)
    except Exception:
        pytest.skip("imagecodecs LZW unavailable (blocked DLL)")
    assert lzw_decode(ref) == bytes(range(200)) * 30


def test_gfsad_region_stats(tmp_path):
    np = pytest.importorskip("numpy")
    from src.extractors.gfsad import GeoTiff, region_stats
    arr = np.full((100, 100), 1, dtype="uint8")
    arr[:, 50:] = 2                       # east half cropland
    p = tmp_path / "t.tif"
    _geotiff(p, arr, 106.0, 21.0, 0.01, True)   # lon 106..107, lat 20..21
    r = Region.from_dict({"id": "r", "bbox": [106.30, 20.40, 106.70, 20.60]})
    s = region_stats([GeoTiff(p)], r, 2, [2], footprint_m=2000)
    assert s["bbox_crop_frac"] == pytest.approx(0.5)
    west, east = s["points"][0], s["points"][1]
    assert west["point"] == "r__00" and west["crop_frac"] == 0.0 and east["crop_frac"] == 1.0


def test_region_rejects_bad_bbox():
    with pytest.raises(ValueError):
        Region.from_dict({"id": "x", "bbox": [106.35, 20.40, 106.25, 20.50]})
    with pytest.raises(ValueError):
        Region.from_dict({"id": "a__b", "bbox": [1, 1, 2, 2]})
