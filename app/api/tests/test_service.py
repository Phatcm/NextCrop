import pytest

from fakes import CELL, FakeRepo, VALUES
from fieldshift_api.service import ApiError, Service


def svc(**kw):
    return Service(FakeRepo(**kw))


def test_options_for_a_point_start_with_keep_and_carry_cell_info():
    r = svc().options(10.45, 105.35, "RCW")
    assert r["options"][0]["id"] == "keep" and r["options"][0]["sequence"] == ["RCW"] * 3
    assert r["location"]["cell_lat"] == 10.4583 and r["location"]["cell_area_km2"] == pytest.approx(84.4, abs=0.2)
    assert r["cell_indices"]["RCW"] == 8504 and r["current_gaez"] == {"index": 8504, "class": "Rất phù hợp"}


def test_mode_changes_the_indices_used():
    assert svc().options(10.45, 105.35, "RCW", mode="hilm")["cell_indices"]["RCW"] == 8200


def test_adjustable_parameters_are_echoed_as_custom():
    a = svc().options(10.45, 105.35, "RCW", min_index=5000, gap_rice=10, gap_other=20)["assumptions"]
    assert a["min_index"]["value"] == 5000 and a["min_index"]["custom"] is True
    assert a["gap_rice"]["days"] == 10 and a["gap_other"]["days"] == 20


def test_perennial_crop_gets_a_message_not_options():
    r = svc().options(10.45, 105.35, "COF")
    assert r["options"] == [] and "cây lâu năm" in r["message"]


@pytest.mark.parametrize("kwargs,code,status", [
    (dict(lat=30, lon=105, crop="RCW"), "outside_grid", 422),
    (dict(lat=10.45, lon=105.35, crop="ZZZ"), "unknown_crop", 422),
    (dict(lat=10.45, lon=105.35, crop="RCW", mode="xxxx"), "invalid_mode", 422),
    (dict(lat=11.0, lon=106.0, crop="RCW"), "no_data", 404),             # a sea cell: no rows
])
def test_errors_carry_a_code_and_status(kwargs, code, status):
    with pytest.raises(ApiError) as e:
        svc().options(**kwargs)
    assert (e.value.code, e.value.status) == (code, status)


def test_invalid_generator_argument_is_a_422():
    with pytest.raises(ApiError) as e:
        svc().options(10.45, 105.35, "RCW", min_index=-5)
    assert e.value.status == 422 and e.value.code == "invalid_argument"


def test_crop_table_is_cached_between_requests():
    repo = FakeRepo()
    s = Service(repo)
    s.options(10.45, 105.35, "RCW")
    s.options(10.45, 105.35, "RCD")
    assert repo.calls.count("crops") == 1


def test_crop_cache_expires():
    repo, t = FakeRepo(), [0.0]
    s = Service(repo, clock=lambda: t[0])
    s.crops()
    t[0] = 1000
    s.crops()
    assert repo.calls.count("crops") == 2


def test_same_cell_is_read_once_until_the_cache_expires():
    repo, t = FakeRepo(), [0.0]
    s = Service(repo, clock=lambda: t[0])
    for _ in range(3):
        s.options(10.45, 105.35, "RCW", min_index=4000)
    s.options(10.45, 105.35, "RCW", min_index=5000)                       # a slider moved: same cell
    assert [c for c in repo.calls if c[0] == "cell_values"] == [("cell_values", 10.4583, 105.375)]
    t[0] = 1000
    s.options(10.45, 105.35, "RCW")
    assert len([c for c in repo.calls if c[0] == "cell_values"]) == 2


def test_cell_cache_is_bounded():
    s = Service(FakeRepo())
    for k in range(600):
        s.cell_values(10 + k / 1000, 105.0)
    assert len(s._cells) <= 512


def test_crop_list_flags_what_can_be_rotated():
    flags = {c["crop_code"]: c["rotatable"] for c in svc().crop_list()}
    assert flags["RCW"] is True and flags["COF"] is False


def test_cells_in_a_bbox_for_the_map_layer():
    r = svc().cells(105, 10, 106, 11, "RCW")
    assert r["count"] == 1 and r["cells"] == [{"lat": CELL[0], "lon": CELL[1], "index": VALUES["RCW"]["hrlm"]}]
    assert svc().cells(100, 10, 101, 11, "RCW")["cells"] == []


def test_cells_reject_bad_bbox_and_too_many_cells():
    with pytest.raises(ApiError) as e:
        svc().cells(106, 10, 105, 11, "RCW")
    assert e.value.code == "invalid_bbox"
    many = {(10 + k / 100, 105.0): {"RCW": dict(hilm=1, hrlm=1, lilm=1, lrlm=1)} for k in range(5)}
    with pytest.raises(ApiError) as e:
        svc(cells=many).cells(104, 9, 106, 12, "RCW", limit=3)
    assert e.value.status == 413


def test_options_in_english_use_english_names_and_sentences():
    r = svc().options(10.45, 105.35, "RCW", lang="en", priorities=["nitrogen"])
    assert r["lang"] == "en" and r["options"][0]["label"] == "Keep as is"
    assert r["options"][0]["names"] == ["Wetland rice"] * 3
    assert r["current_gaez"]["class"] == "Very suitable"
    assert r["assumptions"]["gap_rice"]["source"].startswith("Between two wetland-rice crops")


def test_default_language_is_still_vietnamese():
    r = svc().options(10.45, 105.35, "RCW")
    assert r["lang"] == "vi" and r["options"][0]["label"] == "Giữ nguyên" and r["options"][0]["names"][0] == "Lúa nước"


def test_unknown_language_is_a_422():
    with pytest.raises(ApiError) as e:
        svc().options(10.45, 105.35, "RCW", lang="fr")
    assert (e.value.status, e.value.code) == (422, "invalid_lang")
    with pytest.raises(ApiError):
        svc().crop_list("de")


def test_crop_list_has_both_names_and_a_display_name():
    en = {c["crop_code"]: c for c in svc().crop_list("en")}
    vi = {c["crop_code"]: c for c in svc().crop_list("vi")}
    assert en["RCW"]["name"] == "Wetland rice" and en["RCW"]["name_vi"] == "Lúa nước" and en["RCW"]["name_en"] == "Wetland rice"
    assert vi["RCW"]["name"] == "Lúa nước"


# ---- NASA card
def test_nasa_in_a_demo_area_has_temperature_rain_and_ndvi():
    r = svc().nasa(10.45, 105.35)
    assert r["location"]["cell_lat"] == 10.4583
    assert len(r["temperature"]["months"]) == 12 and r["temperature"]["years"] == [2015, 2025]
    assert r["temperature"]["months"][0] == {"m": 1, "mean": 25.0, "min": 20.0, "max": 31.0}
    assert r["temperature"]["grid_cell"] == {"lat": 10.5, "lon": 105.5}
    a = r["demo_area"]
    assert a["region_id"] == "an_giang_rice" and a["distance_km"] < 10
    assert [m["mm"] for m in a["rain"]["months"]][:3] == [10.0, 20.0, 30.0] and "not NASA" in a["rain"]["source"]
    assert a["ndvi"]["months"][0] == {"m": 1, "mean": 0.51, "min": 0.3, "max": 0.8, "n": 22} and "NASA" in a["ndvi"]["source"]


def test_nasa_far_from_every_demo_area_still_has_temperature_but_no_rain_or_ndvi():
    r = svc().nasa(12.5, 108.0)
    assert len(r["temperature"]["months"]) == 12 and r["demo_area"] is None


def test_nasa_is_refused_where_there_is_no_power_cell_and_outside_the_grid():
    with pytest.raises(ApiError) as e:
        svc().nasa(16.0, 106.0)                                     # inside the rectangle, 400 km from any POWER cell
    assert (e.value.status, e.value.code) == (404, "no_data")
    with pytest.raises(ApiError) as e:
        svc().nasa(30.0, 105.0)
    assert (e.value.status, e.value.code) == (422, "outside_grid")


def test_nasa_answers_are_cached_per_cell_and_keep_the_users_own_point():
    repo = FakeRepo()
    s = Service(repo)
    a, b = s.nasa(10.45, 105.35), s.nasa(10.46, 105.36)             # two points in the same data cell
    assert len([c for c in repo.calls if c[0] == "ndvi"]) == 1
    assert a["location"]["lat"] == 10.45 and b["location"]["lat"] == 10.46


def test_distance_km():
    from fieldshift_api.grid import distance_km
    assert distance_km(10, 105, 10, 105) == 0
    assert abs(distance_km(10, 105, 11, 105) - 111.2) < 0.5
    assert abs(distance_km(0, 105, 0, 106) - 111.2) < 0.5 and distance_km(60, 0, 60, 1) < 56


# ---------------------------------------------------------------- moisture check (annotation only)

from fakes import AN_GIANG_WB, CROPS, FAR_CELL  # noqa: E402
from fieldshift_api.service import _for_generator  # noqa: E402
from src.rotation import options as ro  # noqa: E402


def direct_generate(crop="RCW", mode="hrlm", **kw):
    """What the generator returns on its own for the fake cell: the reference the API must not deviate from."""
    crops = {k: _for_generator(v) for k, v in CROPS.items()}
    return ro.generate(crop, crops, {c: VALUES[c][mode] for c in CROPS}, mode=mode, **kw)


def test_a_demo_area_in_rain_fed_mode_gets_the_moisture_check():
    cc = svc().options(10.45, 105.35, "RCW")["climate_check"]
    assert cc["applies"] is True and cc["area"]["region_id"] == "an_giang_rice" and cc["area"]["distance_km"] <= 60
    assert cc["moist_season"]["months"] == [5, 6, 7, 8, 9, 10, 11, 12] and cc["moist_season"]["days"] == 245
    keep = cc["options"]["keep"]                                   # 3 x 105 days + 2 rests of 7 days, in a 245-day moist season
    assert keep["status"] == "short" and keep["days_needed"] == 329 and keep["shortfall_days"] == 84
    assert len(cc["monthly"]) == 12 and "CHIRPS" in cc["sources"] and cc["not_checked"] and cc["caveats"]


def test_the_options_are_identical_with_or_without_the_check():
    """The ranking guarantee: the check is a separate key, so options and their order are what the generator returns."""
    for kw in ({}, {"priorities": ["nitrogen", "yield"]}, {"seasons": 2}, {"min_index": 3000}, {"lang": "en"}):
        got = svc().options(10.45, 105.35, "RCW", **kw)
        want = direct_generate(**kw)
        assert got["options"] == want["options"], kw
        assert [o["id"] for o in got["options"]] == [o["id"] for o in want["options"]]
        assert got["skipped"] == want["skipped"] and got["assumptions"] == want["assumptions"]


def test_an_irrigated_mode_is_not_limited_by_rain():
    r = svc().options(10.45, 105.35, "RCW", mode="hilm")
    assert r["climate_check"]["applies"] is False and r["climate_check"]["reason"] == "irrigated_mode"
    assert r["options"] == direct_generate(mode="hilm")["options"]


def test_a_point_far_from_every_demo_area_says_so_and_does_not_guess():
    r = svc(cells={FAR_CELL: VALUES}).options(21.04, 105.85, "RCW")
    assert r["climate_check"]["applies"] is False and r["climate_check"]["reason"] == "no_demo_area"
    assert "60 km" in r["climate_check"]["message"]
    assert r["options"] == direct_generate()["options"]


def test_the_check_never_breaks_the_options_when_the_water_balance_cannot_be_read():
    class Broken(FakeRepo):
        def water_balance_climatology(self, region_id):
            raise RuntimeError("table not loaded yet")

    r = Service(Broken()).options(10.45, 105.35, "RCW")
    assert r["climate_check"] == {"applies": False, "reason": "no_data", "message": r["climate_check"]["message"]}
    assert r["options"] == direct_generate()["options"]
    nodata = Service(FakeRepo(cells={FAR_CELL: VALUES, CELL: VALUES}))        # a demo area without data (Son La in the fake)
    assert nodata.options(10.45, 105.35, "RCW")["climate_check"]["applies"] is True


def test_the_water_balance_is_read_once_per_area_not_on_every_slider_move():
    repo = FakeRepo()
    s = Service(repo)
    for seasons in (1, 2, 3, 2, 1):
        s.options(10.45, 105.35, "RCW", seasons=seasons)
    assert [c for c in repo.calls if c[0] == "water_balance"] == [("water_balance", "an_giang_rice")]


def test_english_check_text_and_no_check_for_a_perennial_crop():
    cc = svc().options(10.45, 105.35, "RCW", lang="en")["climate_check"]
    assert "not enough moisture" in cc["options"]["keep"]["message"].lower() and cc["lang"] == "en"
    assert "climate_check" not in svc().options(10.45, 105.35, "COF")        # no options, so nothing to check