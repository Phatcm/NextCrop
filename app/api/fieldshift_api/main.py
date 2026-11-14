"""NextCrop API: read-only endpoints over the Postgres data the pipeline loads.

Run (from app/api):  uvicorn fieldshift_api.main:app --reload --port 8000
"""
from __future__ import annotations

import mimetypes
from typing import Annotated

import pg8000.exceptions
from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .repo import PgRepo, Repo
from .service import ApiError, Service

app = FastAPI(title="NextCrop API", version="1.0",
              description="Hỗ trợ ra quyết định luân canh. Chỉ tư vấn; dữ liệu theo ô GAEZ ~9 km, không phải từng thửa.")
app.add_middleware(CORSMiddleware, allow_origins=config.cors_origins(), allow_methods=["GET"], allow_headers=["*"])

_service: Service | None = None
_repo: Repo | None = None


def get_repo() -> Repo | None:
    global _repo
    if _repo is None:
        dsn = config.database_url()
        _repo = PgRepo(dsn) if dsn else None
    return _repo


def get_service(repo: Annotated[Repo | None, Depends(get_repo)]) -> Service:
    global _service
    if repo is None:
        raise ApiError(503, "db_not_configured", "Chưa cấu hình cơ sở dữ liệu (APP_DATABASE_URL hoặc DATABASE_URL_POOLED).")
    if _service is None or _service.repo is not repo:
        _service = Service(repo)
    return _service


@app.exception_handler(ApiError)
async def api_error(_: Request, e: ApiError):
    return JSONResponse(status_code=e.status, content={"detail": {"code": e.code, "message": e.message}})


async def db_down(_: Request, e: Exception):
    # a database that is down or restarting reads as 503; any other exception stays a real 500 (a bug, not hidden)
    return JSONResponse(status_code=503, content={"detail": {"code": "db_unavailable",
                                                             "message": "Không đọc được cơ sở dữ liệu, thử lại sau."}})


for _exc in (pg8000.exceptions.InterfaceError, pg8000.exceptions.DatabaseError, OSError):
    app.add_exception_handler(_exc, db_down)


@app.get("/api/health")
def health(repo: Annotated[Repo | None, Depends(get_repo)]):
    return {"status": "ok", "database": bool(repo and repo.ping())}


@app.get("/api/crops")
def crops(svc: Annotated[Service, Depends(get_service)], lang: str = "vi"):
    """Tất cả cây trong dữ liệu. `rotatable=false` (cây lâu năm hoặc thiếu độ dài vụ) không có phương án luân canh.
    `name` là tên hiển thị theo `lang` (vi hoặc en)."""
    return {"crops": svc.crop_list(lang)}


@app.get("/api/options")
def options(svc: Annotated[Service, Depends(get_service)],
            lat: Annotated[float, Query(ge=-90, le=90)], lon: Annotated[float, Query(ge=-180, le=180)],
            crop: str, mode: str = "hrlm",
            seasons: Annotated[int | None, Query(ge=1, le=3)] = None,
            priorities: Annotated[list[str] | None, Query()] = None,
            min_index: Annotated[int | None, Query(ge=0, le=10000)] = None,
            gap_rice: Annotated[int | None, Query(ge=0, le=60)] = None,
            gap_other: Annotated[int | None, Query(ge=0, le=60)] = None, lang: str = "vi"):
    """Phương án luân canh cho một điểm và cây hiện tại. Phương án đầu tiên luôn là giữ nguyên.
    `lang` (vi mặc định, hoặc en) chọn ngôn ngữ của mọi câu chữ trong kết quả."""
    return svc.options(lat, lon, crop, mode=mode, seasons=seasons, priorities=priorities, min_index=min_index,
                       gap_rice=gap_rice, gap_other=gap_other, lang=lang)


@app.get("/api/cells")
def cells(svc: Annotated[Service, Depends(get_service)], west: float, south: float, east: float, north: float,
          crop: str, mode: str = "hrlm", limit: Annotated[int, Query(ge=1, le=20000)] = 6000):
    """Các ô lưới trong khung bản đồ, chỉ số của một cây (lớp tô màu)."""
    return svc.cells(west, south, east, north, crop, mode, limit)


# The UI (app/web) is plain static files served by this same app, so one container does it all and no CORS is needed.
# Mounted last: every /api route above wins. Module scripts need a JavaScript MIME type, and on some Windows machines
# the registry maps .js to text/plain, so register the types explicitly.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("application/geo+json", ".geojson")
_web = config.web_dir()
if _web is not None:
    app.mount("/", StaticFiles(directory=_web, html=True), name="web")
