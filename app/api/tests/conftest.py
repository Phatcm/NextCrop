import sys
from pathlib import Path

API = Path(__file__).resolve().parents[1]
for p in (API, API / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
