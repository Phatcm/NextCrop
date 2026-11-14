import json

from src.extractors import chirps
from src.models import Region
from src.transformers import rain_validation as rv


def months(year, value):
    return {f"{year}-{m:02d}": value for m in range(1, 13)}


def test_power_month_mm_converts_mm_per_day():
    rows = [{"month": "2020-02", "PRECTOTCORR": 2.0}, {"month": "2020-03", "PRECTOTCORR": None}]
    assert rv.power_month_mm(rows) == {"2020-02": 58.0}      # 2020 is a leap year


def test_validate_flags_biased_power_and_uses_chirps():
    power, ch = {}, {}
    for y in range(2015, 2025):
        power.update(months(y, 170.0))                       # 2,040 mm/yr
        ch.update(months(y, 75.0))                           # 900 mm/yr  (Ninh Thuan-like)
    res = rv.validate(power, ch)
    s = res["summary"]
    assert s["verdict"] == "power_biased" and s["bias"] > 1.0 and s["n_years"] == 10
    assert all(r["status"] == "power_high" for r in res["years"])
    assert all(m["best_source"] == "chirps" and m["best_mm"] == 75.0 for m in res["monthly"])
    assert "climate.rain_best" in rv.caveat(s)


def test_validate_consistent_and_single_bad_year():
    power, ch = {}, {}
    for y in range(2015, 2025):
        ch.update(months(y, 100.0))
        power.update(months(y, 105.0))
    assert rv.validate(power, ch)["summary"]["verdict"] == "power_consistent"
    assert rv.caveat(rv.validate(power, ch)["summary"]) is None
    power.update(months(2015, 20.0))                          # Dak Lak 2015-like fault
    s = rv.validate(power, ch)["summary"]
    assert s["verdict"] == "power_bad_years" and s["bad_years"] == [2015]


def test_partial_years_and_missing_chirps_month_are_not_compared_or_invented():
    power = {**months(2020, 100.0), **months(2021, 100.0)}
    ch = months(2020, 100.0)
    del ch["2020-05"]                                         # a gap is not zero
    res = rv.validate(power, ch)
    assert res["years"] == []                                 # 2020 incomplete in CHIRPS, 2021 absent
    may = next(m for m in res["monthly"] if m["month"] == "2020-05")
    assert may["best_source"] == "power_fallback" and may["chirps_mm"] is None and may["best_mm"] == 100.0
    assert rv.validate({}, {})["summary"]["verdict"] == "insufficient"


def test_gold_block_normals_and_annual_only_for_full_years():
    ch = {**months(2020, 50.0), "2021-01": 10.0}
    block = rv.gold_block(rv.validate(ch, ch), "x")
    assert block["normals_mm"][0] == 30.0 and block["normals_mm"][1] == 50.0
    assert block["annual_mm"] == {"2020": 600.0}


def test_chirps_window_mean_ignores_nodata_and_negative():
    assert chirps.window_mean([[-9999, 10.0], [20.0, -1.0]], -9999) == 15.0
    assert chirps.window_mean([[-9999]], -9999) is None


def test_chirps_offline_uses_cache_and_never_invents(tmp_path):
    r = Region("r1", "R1", (100.0, 19.0, 100.1, 19.1))
    out, probs = chirps.fetch_monthly({}, r, 2020, 2020, tmp_path, offline=True)
    assert out == {} and probs and "offline" in probs[0]
    chirps.cache_path(tmp_path, r, 2020, 2020).write_text(json.dumps({"2020-01": 12.5}), encoding="utf-8")
    out, probs = chirps.fetch_monthly({}, r, 2020, 2020, tmp_path, offline=True)
    assert out == {"2020-01": 12.5} and probs == []
