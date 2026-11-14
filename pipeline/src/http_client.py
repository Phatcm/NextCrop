"""Small stdlib HTTP helper with retries and an on-disk cache (bronze layer)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = "field-shift-etl/0.1"


class HttpError(RuntimeError):
    pass


def request(url: str, *, method: str = "GET", data: bytes | None = None,
            headers: dict | None = None, timeout: float = 60, retries: int = 3,
            backoff: float = 2.0) -> bytes:
    hdrs = {"User-Agent": USER_AGENT}
    hdrs.update(headers or {})
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            body = e.read()[:500].decode("utf-8", "replace")
            last = HttpError(f"HTTP {e.code} for {url}: {body}")
            if 400 <= e.code < 500 and e.code != 429:
                break  # client error: retrying will not help
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = HttpError(f"{type(e).__name__} for {url}: {e}")
        if attempt < retries - 1:
            time.sleep(backoff * (2 ** attempt))
    raise last  # type: ignore[misc]


def get_json(url: str, **kw):
    return json.loads(request(url, **kw).decode("utf-8"))


def fetch_cached(url: str, path: Path, *, offline: bool = False, **kw) -> bytes:
    """Return cached bytes at `path` if present, else download and cache."""
    if path.exists() and path.stat().st_size > 0:
        return path.read_bytes()
    if offline:
        raise HttpError(f"offline mode and no cache at {path}")
    body = request(url, **kw)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(body)
    tmp.replace(path)
    return body
