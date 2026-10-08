from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

# worker.py vive em backend/ (um nível acima de data_collection/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import worker  # noqa: E402

if worker.ReturnDocument is None:
    worker.ReturnDocument = types.SimpleNamespace(AFTER="after")

REPORT = {"started_at": None, "finished_at": None, "scrapers": [], "csvs": []}


def _fake_jobs():
    class Jobs:
        def find_one_and_update(self, *args: Any, **kwargs: Any) -> dict:
            return {"_id": "job-1", "job_id": "job-1", "status": "running"}

    return Jobs()


def _prepare(phase: str = "collect", pipeline_ok: bool = True) -> dict:
    """Instala os fakes e devolve o dicionário de marcadores."""
    marker: dict[str, Any] = {}

    worker.mongo_collection = lambda: (None, _fake_jobs(), object())
    worker.claim_next_job = lambda jobs: {
        "_id": "job-1",
        "job_id": "job-1",
        "status": "running",
        "phase": phase,
    }
    worker.run_pipeline = lambda timeout, args="": (
        pipeline_ok,
        {"pipeline_ok": pipeline_ok},
    )
    worker.load_frontend_report = lambda: dict(REPORT)

    def fake_mark(jobs, job_id, report):
        marker["awaiting"] = job_id

    def fake_finish(jobs, states, job_id, ok, report, error):
        marker["finished"] = (ok, error)

    worker.mark_awaiting_import = fake_mark
    worker.finish_job = fake_finish
    return marker


def test_collect_success_freezes_job():
    marker = _prepare(phase="collect", pipeline_ok=True)

    code = worker.process_one(3600)

    assert code == 0, f"coleta OK deveria retornar 0, veio {code}"
    assert marker.get("awaiting") == "job-1", "deveria congelar em awaiting_import"
    assert "finished" not in marker, "não deveria marcar complete/failed"


def test_collect_failure_marks_job_failed():
    marker = _prepare(phase="collect", pipeline_ok=False)

    code = worker.process_one(3600)

    assert code == 1, f"falha deveria retornar 1, veio {code}"
    assert "awaiting" not in marker, "não deveria congelar em awaiting_import"
    assert marker["finished"] == (False, "coleta falhou"), marker


def test_import_phase_completes_job():
    marker = _prepare(phase="import", pipeline_ok=True)

    code = worker.process_one(3600)

    assert code == 0, f"import OK deveria retornar 0, veio {code}"
    assert marker["finished"] == (True, None), marker
    assert "awaiting" not in marker, "import não passa por awaiting_import"
