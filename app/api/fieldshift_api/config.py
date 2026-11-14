"""Settings from environment variables only (no secrets in the repo)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# The rotation generator and the DSN parser live in pipeline/; the API reuses them instead of copying.
PIPELINE_DIR = Path(os.environ.get("PIPELINE_DIR") or Path(__file__).resolve().parents[3] / "pipeline")
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

DEFAULT_CORS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"


def database_url() -> str | None:
    """APP_DATABASE_URL (a read-only role) first, then the pooled Neon URL, then DATABASE_URL."""
    for name in ("APP_DATABASE_URL", "DATABASE_URL_POOLED", "DATABASE_URL"):
        if os.environ.get(name):
            return os.environ[name]
    return None


def web_dir() -> Path | None:
    """The static UI (app/web) served at / when it exists; WEB_DIR overrides the location."""
    d = Path(os.environ.get("WEB_DIR") or Path(__file__).resolve().parents[2] / "web")
    return d if (d / "index.html").is_file() else None


def cors_origins() -> list[str]:
    return [o.strip() for o in os.environ.get("CORS_ORIGINS", DEFAULT_CORS).split(",") if o.strip()]
