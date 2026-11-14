"""Network code tested without a network: urllib is replaced, so retries, error handling and caching are checked offline.

The rules under test come from real incidents: a 4xx must not be retried, a download must never leave a half-written
cache file, offline mode must never reach the network, and a series with a gap must not be cached as if complete.
"""
import io
import json
import urllib.error

import pytest

from src import http_client as hc
from src.extractors import chirps, era5_rain, gbif, power_client
from src.models import Region

R = Region("r1", "R1", (100.0, 10.0, 100.1, 10.1))


class Resp:
    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code: int, body: bytes = b"nope"):
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(body))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(hc.time, "sleep", lambda s: None)


def script(monkeypatch, outcomes):
    """Replace urlopen with a scripted sequence of responses or exceptions; returns the call log."""
    calls = []

    def fake(req, timeout=None):
        calls.append(req.full_url)
        o = outcomes[min(len(calls) - 1, len(outcomes) - 1)]
        if isinstance(o, Exception):
            raise o
        return Resp(o)

    monkeypatch.setattr(hc.urllib.request, "urlopen", fake)
    return calls


def test_request_retries_server_errors_then_succeeds(monkeypatch):
    calls = script(monkeypatch, [http_error(503), urllib.error.URLError("reset"), b"ok"])
    assert hc.request("http://x/a", retries=3) == b"ok" and len(calls) == 3


def test_request_does_not_retry_a_client_error(monkeypatch):
    calls = script(monkeypatch, [http_error(404, b"missing"), b"never"])
    with pytest.raises(hc.HttpError, match="HTTP 404"):
        hc.request("http://x/a", retries=3)
    assert len(calls) == 1


def test_request_retries_rate_limit_429(monkeypatch):
    calls = script(monkeypatch, [http_error(429), b"ok"])
    assert hc.request("http://x/a", retries=3) == b"ok" and len(calls) == 2


def test_request_gives_up_after_the_retries_and_reports_the_url(monkeypatch):
    calls = script(monkeypatch, [urllib.error.URLError("boom")])
    with pytest.raises(hc.HttpError, match="http://x/a"):
        hc.request("http://x/a", retries=2)
    assert len(calls) == 2


def test_fetch_cached_downloads_once_and_leaves_no_part_file(monkeypatch, tmp_path):
    calls = script(monkeypatch, [b"data"])
    p = tmp_path / "d" / "f.json"
    assert hc.fetch_cached("http://x/a", p) == b"data" and p.read_bytes() == b"data"
    assert not list(p.parent.glob("*.part"))
    assert hc.fetch_cached("http://x/a", p) == b"data" and len(calls) == 1               # second call is served from the cache


def test_fetch_cached_offline_never_touches_the_network(monkeypatch, tmp_path):
    calls = script(monkeypatch, [b"data"])
    with pytest.raises(hc.HttpError, match="offline"):
        hc.fetch_cached("http://x/a", tmp_path / "f.json", offline=True)
    assert calls == []
    (tmp_path / "empty.json").write_bytes(b"")                                            # an empty file is not a cache hit
    with pytest.raises(hc.HttpError):
        hc.fetch_cached("http://x/a", tmp_path / "empty.json", offline=True)


def test_failed_download_does_not_create_the_cache_file(monkeypatch, tmp_path):
    script(monkeypatch, [http_error(500)])
    with pytest.raises(hc.HttpError):
        hc.fetch_cached("http://x/a", tmp_path / "f.json", retries=1)
    assert not (tmp_path / "f.json").exists()


# ---------------------------------------------------------------- NASA POWER

def test_power_urls_carry_every_parameter_and_the_time_standard():
    u = power_client.build_url("https://p/api/temporal/", "daily", 10.45, 105.35, "20150101", "20251231",
                               ["T2M", "PRECTOTCORR"], "AG", "LST")
    assert u.startswith("https://p/api/temporal/daily/point?") and "parameters=T2M%2CPRECTOTCORR" in u
    assert "latitude=10.4500" in u and "time-standard=LST" in u
    assert "time-standard" not in power_client.build_url("https://p", "monthly", 1, 2, "2015", "2025", ["T2M"], "AG", "LST")
    reg = power_client.build_regional_url("https://p", [102, 8.5, 110, 16], "PRECTOTCORR", 2015, 2025)
    assert "latitude-min=8.5" in reg and "longitude-max=110" in reg and "/monthly/regional?" in reg


def test_power_parse_turns_fill_values_into_none_and_splits_annual():
    payload = {"header": {"fill_value": -999.0}, "parameters": {"T2M": {"units": "C"}},
               "properties": {"parameter": {"T2M": {"202001": 20.5, "202002": -999.0, "202013": 21.0}}}}
    m = power_client.parse_response(payload, "monthly")
    assert m["rows"] == [{"month": "2020-01", "T2M": 20.5}, {"month": "2020-02", "T2M": None}]   # a gap is never 0
    assert m["annual"] == {"2020": {"T2M": 21.0}} and m["units"] == {"T2M": "C"}
    d = power_client.parse_response({"properties": {"parameter": {"T2M": {"20200101": 20.0}}}}, "daily")
    assert d["rows"][0]["date"] == "2020-01-01"


def test_power_parse_regional_cells():
    payload = {"header": {"fill_value": -999.0}, "parameters": {"T2M": {"units": "C"}},
               "features": [{"geometry": {"coordinates": [105.0, 10.0, 12.0]},
                             "properties": {"parameter": {"T2M": {"202001": 25.0, "202002": -999.0}}}}]}
    cells, units, _h = power_client.parse_regional(payload)
    assert cells[(10.0, 105.0)]["elev"] == 12.0 and cells[(10.0, 105.0)]["values"] == {"202001": 25.0, "202002": None}
    assert units == {"T2M": "C"}


# ---------------------------------------------------------------- GBIF, ERA5

def test_gbif_fetch_family_uses_cache_and_returns_none_on_failure(monkeypatch, tmp_path):
    payload = {"family": "Poaceae", "usageKey": 7, "status": "ACCEPTED", "matchType": "EXACT", "confidence": 99}
    calls = script(monkeypatch, [json.dumps(payload).encode()])
    assert gbif.fetch_family("Oryza sativa", tmp_path)["family"] == "Poaceae"
    assert gbif.fetch_family("Oryza sativa", tmp_path)["usage_key"] == 7 and len(calls) == 1
    script(monkeypatch, [http_error(500)])
    assert gbif.fetch_family("Zea mays", tmp_path) is None                                # unknown is None, never a guess
    assert gbif.fetch_family("Zea mays", tmp_path / "x", offline=True) is None


def test_era5_parse_drops_null_days_and_fetch_failure_is_none(monkeypatch, tmp_path):
    assert era5_rain.parse({"daily": {"time": ["2020-01-01", "2020-01-02"], "precipitation_sum": [1.5, None]}}) == {
        "2020-01-01": 1.5}
    script(monkeypatch, [http_error(500)])
    assert era5_rain.fetch_daily({"url": "http://x"}, 10.0, 100.0, 2020, 2020, tmp_path) is None


# ---------------------------------------------------------------- CHIRPS

def test_chirps_caches_only_a_complete_series(monkeypatch, tmp_path):
    def one(cfg, region, year, month):
        if (year, month) == (2020, 2):
            raise OSError("range request failed")
        return 10.0 + month

    monkeypatch.setattr(chirps, "_one", one)
    out, problems = chirps.fetch_monthly({}, R, 2020, 2020, tmp_path, workers=2)
    assert "2020-02" not in out and len(out) == 11                                         # the gap is left out, not 0
    assert problems and "2020-02" in problems[0]
    assert not chirps.cache_path(tmp_path, R, 2020, 2020).exists()                          # incomplete: a re-run must retry

    monkeypatch.setattr(chirps, "_one", lambda *a: 5.0)
    out, problems = chirps.fetch_monthly({}, R, 2020, 2020, tmp_path, workers=2)
    assert len(out) == 12 and problems == [] and chirps.cache_path(tmp_path, R, 2020, 2020).exists()
    monkeypatch.setattr(chirps, "_one", lambda *a: (_ for _ in ()).throw(AssertionError("must use the cache")))
    again, p2 = chirps.fetch_monthly({}, R, 2020, 2020, tmp_path)
    assert again == out and p2 == []


def test_chirps_month_without_valid_cell_is_a_problem_not_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(chirps, "_one", lambda *a: None)
    out, problems = chirps.fetch_monthly({}, R, 2020, 2020, tmp_path, workers=2)
    assert out == {} and len(problems) == 12 and "no valid cell" in problems[0]


def test_chirps_url_is_built_from_config_template():
    cfg = {"url": "https://c/{year}/chirps.{month:02d}.tif"}
    assert chirps.month_url(cfg, 2020, 3) == "https://c/2020/chirps.03.tif"
