import asyncio
import logging
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypedDict

from app.core.database import database
from app.services.dedup.csv import DedupStats, deduplicate_csvs
from app.services.dedup.db_bucket import deduplicate_db_and_bucket
from app.services.scrape_config import BASE_DIR, CSV_MAP, DATA_COLLECTION_DIR, DATA_DIR, SCRAPERS

logger = logging.getLogger(__name__)

SCRAPER_TIMEOUT_S = 600
SCRAPER_CONCURRENCY = 3

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
    deduplicacao: list[DedupStats]
    deduplicacao_db: dict | None


ScraperStatus = Literal["running", "complete", "failed"]


@dataclass
class ScraperJob:
    job_id: str
    status: ScraperStatus = "running"
    started_at: str = ""
    finished_at: str = ""
    report: ScraperReport | None = None
    error: str | None = None


_jobs: dict[str, ScraperJob] = {}
_lock = asyncio.Lock()
_active_job_id: str | None = None


def _jobs_collection():
    if database.db is None:
        return None
    return database.db["scrape_jobs"]


def _job_to_doc(job: ScraperJob) -> dict:
    return {
        "_id": job.job_id,
        "job_id": job.job_id,
        "status": job.status,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "report": job.report,
        "error": job.error,
        "updated_at": _now_iso(),
    }


def _doc_to_job(doc: dict) -> ScraperJob:
    return ScraperJob(
        job_id=doc.get("job_id") or doc.get("_id", ""),
        status=doc.get("status", "running"),
        started_at=doc.get("started_at", ""),
        finished_at=doc.get("finished_at", ""),
        report=doc.get("report"),
        error=doc.get("error"),
    )


async def _persist_job(job: ScraperJob) -> None:
    try:
        coll = _jobs_collection()
        if coll is None:
            return
        await coll.update_one({"_id": job.job_id}, {"$set": _job_to_doc(job)}, upsert=True)
    except Exception as e:
        logger.warning(f"Failed to persist job {job.job_id}: {e}")


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
            timeout=SCRAPER_TIMEOUT_S,
        )
        duration = round(time.monotonic() - start, 1)
        ok = proc.returncode == 0
        status = "OK" if ok else "FAIL"
        logger.info(f"Scraper {script_name}: {status} ({duration:.1f}s)")
        if proc.stdout:
            for line in proc.stdout.strip().splitlines():
                logger.info(f"[{script_name}] {line}")
        if proc.stderr:
            for line in proc.stderr.strip().splitlines():
                level = logger.warning if ok else logger.error
                level(f"[{script_name}] {line}")
        return {
            "nome": script_name,
            "ok": ok,
            "duration_s": duration,
            "detail": (proc.stdout or "")[-8000:],
            "stderr": (proc.stderr or "")[-2000:],
        }
    except subprocess.TimeoutExpired:
        duration = round(time.monotonic() - start, 1)
        logger.error(f"Scraper {script_name} timeout after {SCRAPER_TIMEOUT_S}s")
        return {
            "nome": script_name,
            "ok": False,
            "duration_s": duration,
            "detail": "",
            "stderr": f"Timeout after {SCRAPER_TIMEOUT_S}s",
        }
    except Exception as e:
        logger.error(f"Scraper {script_name} exception: {e}", exc_info=True)
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
    await _persist_job(job)
    try:
        cleanup_scraped_csvs()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        sem = asyncio.Semaphore(SCRAPER_CONCURRENCY)

        async def _run_limited(name: str) -> ScraperResult:
            async with sem:
                return await asyncio.to_thread(_run_scraper, name)

        scraper_results = await asyncio.gather(*[_run_limited(s) for s in SCRAPERS])
        report: ScraperReport = {
            "started_at": job.started_at,
            "finished_at": None,
            "scrapers": list(scraper_results),
            "csvs": [],
            "deduplicacao": [],
            "deduplicacao_db": None,
        }
        if any(not r["ok"] for r in scraper_results):
            job.status = "failed"
            job.error = "Um ou mais scrapers falharam"
            await _persist_job(job)
        else:
            try:
                dedup_stats = await asyncio.to_thread(deduplicate_csvs)
                report["deduplicacao"] = dedup_stats
                if any(s["removidos"] > 0 for s in dedup_stats):
                    for s in dedup_stats:
                        if s["removidos"]:
                            print(
                                f"[dedup][CSV] {s['fonte']}: {s['removidos']} removidos, "
                                f"{s['mantidos']} mantidos"
                            )
            except Exception as e:
                print(f"[WARN] falha na deduplicação CSV: {e}")
                report["deduplicacao"] = []

            try:
                db_stats = await deduplicate_db_and_bucket()
                report["deduplicacao_db"] = db_stats  # type: ignore[typeddict-unknown-key]
                if db_stats and db_stats.get("removidos_db"):
                    print(
                        f"[dedup][DB] {db_stats['removidos_db']} docs removidos, "
                        f"{db_stats.get('removidos_bucket', 0)} imagens órfãs"
                    )
            except Exception as e:
                print(f"[WARN] falha na deduplicação DB/bucket: {e}")

            csvs = await asyncio.to_thread(_build_csv_summaries)
            report["csvs"] = csvs
            if any(not c["ok"] for c in csvs):
                job.status = "failed"
                job.error = "Falha na validação dos CSVs"
            else:
                job.status = "complete"
        report["finished_at"] = finished = _now_iso()
        job.finished_at = finished
        job.report = report
        await _persist_job(job)
        if job.status == "complete":
            await _save_last_run(report["finished_at"])
    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.finished_at = _now_iso()
        await _persist_job(job)
    finally:
        _active_job_id = None


async def start_scrape_job() -> str | None:
    global _active_job_id
    async with _lock:
        if _active_job_id:
            return None
        # check persisted running job in case of restart with stale lock
        try:
            coll = _jobs_collection()
            if coll is not None:
                running = await coll.find_one({"status": "running"})
                if running:
                    _jobs[running["_id"]] = _doc_to_job(running)
                    _active_job_id = running["_id"]
                    return None
        except Exception:
            pass
        job = ScraperJob(job_id=str(uuid.uuid4()))
        _jobs[job.job_id] = job
        _active_job_id = job.job_id
        await _persist_job(job)
    task = asyncio.get_running_loop().create_task(_execute_job(job))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return job.job_id


async def get_job_async(job_id: str) -> ScraperJob | None:
    if job_id in _jobs:
        return _jobs[job_id]
    try:
        coll = _jobs_collection()
        if coll is not None:
            doc = await coll.find_one({"_id": job_id})
            if doc:
                job = _doc_to_job(doc)
                _jobs[job_id] = job
                return job
    except Exception:
        pass
    return None


def get_job(job_id: str) -> ScraperJob | None:
    job = _jobs.get(job_id)
    if job is not None:
        return job
    return None


def get_active_job_id() -> str | None:
    if _active_job_id is not None:
        return _active_job_id
    return None


async def get_active_job_id_async() -> str | None:
    if _active_job_id is not None:
        return _active_job_id
    try:
        coll = _jobs_collection()
        if coll is not None:
            doc = await coll.find_one({"status": "running"}, sort=[("started_at", -1)])
            if doc:
                _jobs[doc["_id"]] = _doc_to_job(doc)
                return doc["_id"]
    except Exception:
        pass
    return None
