import sys
from pathlib import Path

# Ensure `backend` is on sys.path so `import data_collection...` works when running
# `pytest` from repo root without PYTHONPATH=backend (as in `pytest backend/...`).
# This mirrors scraper's `if __package__ in (None, ""): sys.path.insert(...)` but for tests.
if str(Path(__file__).resolve().parent.parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
