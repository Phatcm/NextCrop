"""NASA AppEEARS point extraction (MOD13Q1 NDVI + QA, SMAP, MCD12Q1, NASADEM).

Needs an Earthdata Login account (EARTHDATA_USERNAME / EARTHDATA_PASSWORD in .env).
Credentials stay in this script; never ship them to the browser or the repo.

Tasks are recorded in bronze/appeears/tasks.json keyed by a hash of the request, so a
re-run never resubmits the same request: it resumes waiting / downloading instead.
"""
from __future__ import annotations

import base64
import csv
import datetime as dt
import hashlib
import json
import os
import time
from pathlib import Path

from src.http_client import HttpError, request
from src.models import Region


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


class AppEEARS:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.token: str | None = None

    def login(self, user: str, password: str) -> None:
        auth = base64.b64encode(f"{user}:{password}".encode()).decode()
        body = request(f"{self.base}/login", method="POST", data=b"",
                       headers={"Authorization": f"Basic {auth}",
                                "Content-Type": "application/x-www-form-urlencoded"}, retries=2)
        self.token = json.loads(body)["token"]

    def _h(self) -> dict:
        if not self.token:
            raise RuntimeError("call login() first")
        return {"Authorization": f"Bearer {self.token}"}

    def submit(self, task: dict) -> str:
        body = request(f"{self.base}/task", method="POST", data=json.dumps(task).encode(),
                       headers={**self._h(), "Content-Type": "application/json"}, retries=1)
        return json.loads(body)["task_id"]

    def status(self, task_id: str) -> str:
        return json.loads(request(f"{self.base}/task/{task_id}", headers=self._h())).get("status", "?")

    def download_bundle(self, task_id: str, out_dir: Path) -> list[Path]:
        bundle = json.loads(request(f"{self.base}/bundle/{task_id}", headers=self._h()))
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for f in bundle.get("files", []):
            name = Path(f["file_name"]).name
            if not name.endswith((".csv", ".json")):
                continue
            p = out_dir / name
            p.write_bytes(request(f"{self.base}/bundle/{task_id}/{f['file_id']}",
                                  headers=self._h(), timeout=300))
            paths.append(p)
        return paths


# ---------------------------------------------------------------- requests

def build_task(tcfg: dict, regions: list[Region], grid_n: int, start_year: int, end_year: int) -> dict:
    coords = []
    for r in regions:
        pts = [r.center] if tcfg.get("points") == "center" else r.grid_points(grid_n)
        for k, (lat, lon) in enumerate(pts):
            coords.append({"id": f"{r.id}__{k:02d}", "category": r.id, "latitude": lat, "longitude": lon})
    fmt = {"start_year": start_year, "end_year": end_year}
    return {
        "task_type": "point",
        "task_name": f"field-shift-{tcfg['key']}-{start_year}-{end_year}",
        "params": {
            "dates": [{"startDate": tcfg["start"].format(**fmt), "endDate": tcfg["end"].format(**fmt)}],
            "layers": [{"product": tcfg["product"], "layer": l} for l in tcfg["layers"]],
            "coordinates": coords,
        },
    }


def task_hash(task: dict) -> str:
    return hashlib.sha1(json.dumps(task, sort_keys=True).encode()).hexdigest()[:12]


def results_csv(task_dir: Path) -> Path | None:
    hits = sorted(task_dir.glob("*-results.csv")) if task_dir.exists() else []
    return hits[0] if hits else None


def run_tasks(cfg: dict, regions: list[Region], start_year: int, end_year: int, bronze: Path,
              *, offline: bool = False, wait: bool = True, log=print) -> dict[str, Path]:
    """Ensure every configured task has a downloaded results CSV. Returns {task_key: csv}."""
    root = bronze / "appeears"
    reg_path = root / "tasks.json"
    registry = json.loads(reg_path.read_text(encoding="utf-8")) if reg_path.exists() else {}

    def save_registry():
        root.mkdir(parents=True, exist_ok=True)
        reg_path.write_text(json.dumps(registry, indent=1), encoding="utf-8")

    plans = {}
    for tcfg in cfg["tasks"]:
        task = build_task(tcfg, regions, cfg.get("grid_n", 5), start_year, end_year)
        h = task_hash(task)
        plans[tcfg["key"]] = (task, h, root / f"{tcfg['key']}_{h}")

    done = {k: results_csv(d) for k, (_t, _h, d) in plans.items()}
    pending = [k for k, p in done.items() if p is None]
    if not pending:
        return {k: p for k, p in done.items() if p}
    if offline:
        log(f"  [appeears] offline: no results yet for {', '.join(pending)}")
        return {k: p for k, p in done.items() if p}

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    user, pw = os.environ.get("EARTHDATA_USERNAME"), os.environ.get("EARTHDATA_PASSWORD")
    if not (user and pw):
        log("  [appeears] skipped: EARTHDATA_USERNAME / EARTHDATA_PASSWORD not set in .env")
        return {k: p for k, p in done.items() if p}
    client = AppEEARS(cfg["base_url"])
    client.login(user, pw)

    for k in pending:
        task, h, _d = plans[k]
        if h not in registry:
            n = len(task["params"]["coordinates"])
            tid = client.submit(task)
            registry[h] = {"key": k, "task_id": tid, "points": n,
                           "submitted_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
            save_registry()
            log(f"  [appeears] submitted {k}: task {tid} ({n} points)")
        else:
            log(f"  [appeears] resuming {k}: task {registry[h]['task_id']}")

    deadline = time.time() + (cfg.get("max_wait_s", 5400) if wait else 0)
    remaining = list(pending)
    while remaining:
        for k in list(remaining):
            task, h, d = plans[k]
            tid = registry[h]["task_id"]
            try:
                st = client.status(tid)
            except HttpError as e:
                log(f"  [appeears] {k}: status check failed ({e}); will retry")
                continue
            if st == "done":
                files = client.download_bundle(tid, d)
                done[k] = results_csv(d)
                log(f"  [appeears] {k}: downloaded {len(files)} files")
                remaining.remove(k)
            elif st == "error":
                log(f"  [appeears] {k}: task {tid} FAILED on server; delete its entry in tasks.json to resubmit")
                remaining.remove(k)
        if not remaining or time.time() >= deadline:
            break
        log(f"  [appeears] waiting for: {', '.join(remaining)} (poll {cfg.get('poll_s', 30)}s)")
        time.sleep(cfg.get("poll_s", 30))
    if remaining:
        log(f"  [appeears] still processing: {', '.join(remaining)} -> re-run later to download")
    return {k: p for k, p in done.items() if p}


# ---------------------------------------------------------------- parsing

def _num(v: str | None) -> float | None:
    if v is None or v.strip() == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def read_results(path: Path, product: str, layers: list[str]) -> list[dict]:
    """Rows: {"region", "point", "lat", "lon", "date", <layer>: float|None}."""
    prefix = product.replace(".", "_")
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        colmap = {}
        for layer in layers:
            exact = f"{prefix}_{layer}"
            if exact in cols:
                colmap[layer] = exact
            else:
                cand = [c for c in cols if c.endswith(layer)]
                if not cand:
                    raise ValueError(f"{path.name}: no column for layer {layer}")
                colmap[layer] = cand[0]
        rows = []
        for r in reader:
            pid = r.get("ID", "")
            region = r.get("Category") or pid.split("__")[0]
            rows.append({"region": region, "point": pid, "lat": _num(r.get("Latitude")),
                         "lon": _num(r.get("Longitude")), "date": (r.get("Date") or "")[:10],
                         **{l: _num(r.get(c)) for l, c in colmap.items()}})
    return rows
