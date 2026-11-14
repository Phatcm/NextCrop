"""The UI in app/web is served by the same app, under the API routes."""
import json

import pytest
from fastapi.testclient import TestClient

from fakes import FakeRepo
from fieldshift_api import config, main


@pytest.fixture
def client():
    main.app.dependency_overrides[main.get_repo] = lambda: FakeRepo()
    yield TestClient(main.app, raise_server_exceptions=False)
    main.app.dependency_overrides.clear()


def test_the_ui_folder_is_found():
    assert config.web_dir() is not None and (config.web_dir() / "index.html").is_file()


def test_index_is_served_at_the_root(client):
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "NextCrop" in r.text and 'src="js/app.js"' in r.text


def test_scripts_have_a_javascript_mime_type_or_browsers_refuse_modules(client):
    for path in ("/js/app.js", "/js/lib.js", "/js/api.js"):
        r = client.get(path)
        assert r.status_code == 200 and "javascript" in r.headers["content-type"], path


def test_province_boundaries_are_served_and_look_like_geojson(client):
    r = client.get("/data/provinces.geojson")
    assert r.status_code == 200
    assert "json" in r.headers["content-type"]
    assert len(json.loads(r.text)["features"]) >= 60


def test_api_routes_still_win_over_the_static_mount(client):
    assert client.get("/api/health").json() == {"status": "ok", "database": True}
    assert client.get("/api/crops").status_code == 200
    assert client.get("/docs").status_code == 200


def test_unknown_paths_are_404_and_nothing_outside_web_is_reachable(client):
    assert client.get("/nope.js").status_code == 404
    for evil in ("/../api/README.md", "/..%2fapi%2fREADME.md", "/%2e%2e/api/README.md", "/js/../../api/README.md"):
        r = client.get(evil)
        assert r.status_code in (400, 404) or "app/api" not in r.text, evil
        assert "backend chỉ đọc" not in r.text, evil                  # a line that only app/api/README.md contains


def test_static_files_are_get_only(client):
    assert client.post("/index.html").status_code in (404, 405)


def test_favicon_is_an_svg(client):
    r = client.get("/favicon.svg")
    assert r.status_code == 200 and "svg" in r.headers["content-type"] and "<svg" in r.text
