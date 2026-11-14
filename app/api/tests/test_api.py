import pytest
from fastapi.testclient import TestClient

from fakes import FakeRepo
from fieldshift_api import main

BASE = "/api/options?lat=10.45&lon=105.35&crop=RCW"


@pytest.fixture
def client():
    main.app.dependency_overrides[main.get_repo] = lambda: FakeRepo()
    yield TestClient(main.app, raise_server_exceptions=False)
    main.app.dependency_overrides.clear()


def test_health_reports_the_database(client):
    assert client.get("/api/health").json() == {"status": "ok", "database": True}
    main.app.dependency_overrides[main.get_repo] = lambda: FakeRepo(ok=False)
    assert client.get("/api/health").json()["database"] is False
    main.app.dependency_overrides[main.get_repo] = lambda: None
    assert client.get("/api/health").json()["database"] is False


def test_endpoints_say_503_when_no_database_is_configured(client):
    main.app.dependency_overrides[main.get_repo] = lambda: None
    r = client.get("/api/crops")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "db_not_configured"


def test_crops(client):
    body = client.get("/api/crops").json()["crops"]
    assert {c["crop_code"] for c in body} >= {"RCW", "COF"}
    assert [c for c in body if c["crop_code"] == "COF"][0]["rotatable"] is False


def test_options_end_to_end(client):
    r = client.get(BASE + "&priorities=nitrogen&priorities=yield&seasons=3&min_index=5000")
    assert r.status_code == 200
    body = r.json()
    assert body["options"][0]["id"] == "keep" and body["location"]["cell_lat"] == 10.4583
    assert body["assumptions"]["min_index"]["value"] == 5000


@pytest.mark.parametrize("query,status,code", [
    ("lat=30&lon=105&crop=RCW", 422, "outside_grid"),
    ("lat=10.45&lon=105.35&crop=ZZZ", 422, "unknown_crop"),
    ("lat=11&lon=106&crop=RCW", 404, "no_data"),
    ("lat=10.45&lon=105.35&crop=RCW&mode=bad", 422, "invalid_mode"),
])
def test_error_bodies(client, query, status, code):
    r = client.get("/api/options?" + query)
    assert r.status_code == status and r.json()["detail"]["code"] == code


@pytest.mark.parametrize("extra", ["&seasons=4", "&min_index=10001", "&gap_rice=61", "&gap_other=-1"])
def test_parameter_ranges_are_validated(client, extra):
    assert client.get(BASE + extra).status_code == 422


def test_missing_parameters_are_422(client):
    assert client.get("/api/options?lat=10.45").status_code == 422


def test_cells_endpoint(client):
    r = client.get("/api/cells?west=105&south=10&east=106&north=11&crop=RCW")
    assert r.status_code == 200 and r.json()["count"] == 1


def test_only_get_is_allowed_and_nothing_writes(client):
    assert client.post("/api/options").status_code == 405
    assert client.delete("/api/crops").status_code == 405


def test_cors_allows_the_vite_dev_origin(client):
    r = client.get("/api/crops", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_a_down_database_is_503_not_500():
    import pg8000.exceptions

    class Down(FakeRepo):
        def crops(self):
            raise pg8000.exceptions.InterfaceError("connection closed")

    main.app.dependency_overrides[main.get_repo] = lambda: Down()
    try:
        r = TestClient(main.app, raise_server_exceptions=False).get(BASE)
        assert r.status_code == 503 and r.json()["detail"]["code"] == "db_unavailable"
    finally:
        main.app.dependency_overrides.clear()


def test_lang_parameter_end_to_end(client):
    en = client.get(BASE + "&lang=en").json()
    assert en["options"][0]["label"] == "Keep as is" and en["lang"] == "en"
    assert client.get(BASE).json()["options"][0]["label"] == "Giữ nguyên"
    crops = client.get("/api/crops?lang=en").json()["crops"]
    assert [c["name"] for c in crops if c["crop_code"] == "RCW"] == ["Wetland rice"]
    r = client.get(BASE + "&lang=fr")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_lang"
    assert client.get("/api/crops?lang=fr").status_code == 422


def test_nasa_endpoint(client):
    r = client.get("/api/nasa?lat=10.45&lon=105.35")
    assert r.status_code == 200
    body = r.json()
    assert len(body["temperature"]["months"]) == 12 and body["demo_area"]["region_id"] == "an_giang_rice"
    assert client.get("/api/nasa?lat=16&lon=106").json()["detail"]["code"] == "no_data"
    assert client.get("/api/nasa?lat=30&lon=105").status_code == 422
    assert client.get("/api/nasa?lat=10.45").status_code == 422
    assert client.post("/api/nasa?lat=10&lon=105").status_code == 405
