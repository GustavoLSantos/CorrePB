import asyncio
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from app.core.database import database

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
DATA_COLLECTION_DIR = BASE_DIR / "data_collection"
DATA_DIR = DATA_COLLECTION_DIR / "data"

SCRAPERS = [
    "scraper_brasilquecorre.py",
    "scraper_smcrono.py",
    "scraper_race83.py",
    "scraper_zenite.py",
    "scraper_circuitodasestacoes.py",
]

CSV_MAP = {
    "brasilquecorre": DATA_DIR / "eventos_brasilquecorre.csv",
    "smcrono": DATA_DIR / "eventos_smcrono.csv",
    "race83": DATA_DIR / "eventos_race83.csv",
    "zenite": DATA_DIR / "eventos_zenite.csv",
    "circuitodasestacoes": DATA_DIR / "eventos_circuitodasestacoes.csv",
}

_background_tasks: set[asyncio.Task[None]] = set()


def cleanup_scraped_csvs(older_than_hours: float | None = None) -> list[str]:
    removed: list[str] = []
    now = time.time()
    for path in CSV_MAP.values():
        try:
            if not path.exists():
                continue
            if (
                older_than_hours is not None
                and (now - path.stat().st_mtime) < older_than_hours * 3600
            ):
                continue
            path.unlink()
            removed.append(path.name)
        except OSError:
            continue
    return removed


class ScraperResult(TypedDict):
    nome: str
    ok: bool
    duration_s: float
    detail: str
    stderr: str


class ValidationSummary(TypedDict):
    fonte: str
    ok: bool
    total: int
    duplicados: int
    sem_preco: int
    eventos_passados: int
    sem_imagem: int
    erros_encoding: int
    erros: list[str]


class ScraperReport(TypedDict):
    started_at: str | None
    finished_at: str | None
    scrapers: list[ScraperResult]
    csvs: list[ValidationSummary]


@dataclass
class ScraperJob:
    job_id: str
    status: str = "running"  # running | complete | failed
    started_at: str = ""
    finished_at: str = ""
    report: ScraperReport | None = None
    error: str | None = None


_jobs: dict[str, ScraperJob] = {}
_lock = asyncio.Lock()
_active_job_id: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_scraper(script_name: str) -> ScraperResult:
    if script_name not in SCRAPERS:
        raise ValueError(f"Script não autorizado: {script_name!r}")
    script_path = (DATA_COLLECTION_DIR / script_name).resolve()
    if not script_path.is_relative_to(DATA_COLLECTION_DIR.resolve()):
        raise ValueError(f"Path traversal detectado: {script_name!r}")
    start = time.monotonic()
    env = {
        **os.environ,
        "PYTHONPATH": str(BASE_DIR),
        "CORREPB_COLLECT_ONLY": "1",
    }
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=str(BASE_DIR),
        )
        return {
            "nome": script_name,
            "ok": proc.returncode == 0,
            "duration_s": round(time.monotonic() - start, 1),
            "detail": (proc.stdout or "")[-2000:],
            "stderr": (proc.stderr or "")[-1000:],
        }
    except Exception as e:
        return {
            "nome": script_name,
            "ok": False,
            "duration_s": round(time.monotonic() - start, 1),
            "detail": "",
            "stderr": str(e),
        }


def _build_csv_summaries() -> list[ValidationSummary]:
    from data_collection.pipeline_agent import validate_csv

    summaries: list[ValidationSummary] = []
    for fonte, path in CSV_MAP.items():
        s = validate_csv(path, fonte)
        summaries.append(
            {
                "fonte": s.fonte,
                "ok": s.ok,
                "total": s.total,
                "duplicados": s.duplicados,
                "sem_preco": s.sem_preco,
                "eventos_passados": s.eventos_passados,
                "sem_imagem": s.sem_imagem,
                "erros_encoding": s.erros_encoding,
                "erros": s.erros[:10],
            }
        )
    return summaries


async def _save_last_run(finished_at: str) -> None:
    """Grava o finished_at do último job completo (base do cooldown de 15 dias)."""
    try:
        collection = database.get_collection("scrape_state")
        await collection.update_one(
            {"_id": "last_scrape"},
            {"$set": {"finished_at": finished_at}},
            upsert=True,
        )
    except Exception as e:
        print(f"[WARN] Falha ao salvar last_scrape: {e}")


async def get_last_run() -> dict | None:
    collection = database.get_collection("scrape_state")
    return await collection.find_one({"_id": "last_scrape"})


async def _execute_job(job: ScraperJob) -> None:
    global _active_job_id
    job.started_at = _now_iso()
    try:
        cleanup_scraped_csvs()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        scraper_results = await asyncio.gather(
            *[asyncio.to_thread(_run_scraper, s) for s in SCRAPERS]
        )
        report: ScraperReport = {
            "started_at": job.started_at,
            "finished_at": None,
            "scrapers": list(scraper_results),
            "csvs": [],
        }
        if any(not r["ok"] for r in scraper_results):
            job.status = "failed"
            job.error = "Um ou mais scrapers falharam"
        else:
            csvs = await asyncio.to_thread(_build_csv_summaries)
            report["csvs"] = csvs
            if any(not c["ok"] for c in csvs):
                job.status = "failed"
                job.error = "Falha na validação dos CSVs"
            else:
                job.status = "complete"
        report["finished_at"] = _now_iso()
        job.report = report
        if job.status == "complete":
            await _save_last_run(report["finished_at"])
    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.finished_at = _now_iso()
    finally:
        _active_job_id = None


async def start_scrape_job() -> str | None:
    global _active_job_id
    async with _lock:
        if _active_job_id:
            return None
        job = ScraperJob(job_id=str(uuid.uuid4()))
        _jobs[job.job_id] = job
        _active_job_id = job.job_id
    task = asyncio.get_running_loop().create_task(_execute_job(job))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return job.job_id


def get_job(job_id: str) -> ScraperJob | None:
    return _jobs.get(job_id)


def get_active_job_id() -> str | None:
    return _active_job_id
