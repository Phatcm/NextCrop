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
