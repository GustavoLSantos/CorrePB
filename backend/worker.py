"""Worker de scraping: consome jobs criados pela API Go e executa o pipeline.

A API cria o job com status ``queued`` e responde 202 imediatamente.
Este worker reivindica o job (``queued`` -> ``running``, atomicamente),
executa ``data_collection/pipeline_agent.py`` como subprocesso e marca o
resultado (``complete``/``failed`` + ``active: false``, liberando o slot).

Modos:
    python worker.py --once        reivindica e executa UM job e sai
                               (ideal para Azure Container Apps Job)
    python worker.py --loop        repete --once a cada --interval segundos
    python worker.py --dry-run     mostra o que faria, sem Mongo e sem scrape
    python worker.py --self-test   valida o protocolo claim/complete num banco
                               de teste (requer WORKER_ALLOW_SELF_TEST=1)

Variáveis de ambiente (nunca hardcode segredos):
    MONGODB_URI            conexão MongoDB/Atlas (obrigatória)
    MONGODB_DB_NAME        banco (default: corridas_db)
    WORKER_POLL_INTERVAL   segundos entre polls no --loop (default: 60)
    WORKER_JOB_TIMEOUT     segundos máximos do pipeline (default: 3600)
    WORKER_ALLOW_SELF_TEST=1  libera o --self-test
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import pymongo
    from pymongo import ReturnDocument
except ImportError:  # dependência só exigida nos modos com Mongo
    pymongo = None  # type: ignore[no-redef]
    ReturnDocument = None  # type: ignore[no-redef]

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # produção usa env do Container App
    pass

BACKEND_DIR = Path(__file__).resolve().parent
PIPELINE_SCRIPT = BACKEND_DIR / "data_collection" / "pipeline_agent.py"
REPORT_PATH = BACKEND_DIR / "data_collection" / "data" / "last-report.json"

QUEUED = "queued"
RUNNING = "running"
COMPLETE = "complete"
FAILED = "failed"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("worker")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def mongo_collection():
    if pymongo is None:
        raise RuntimeError("pymongo é obrigatório: pip install -r data_collection/requirements.txt")
    uri = os.environ.get("MONGODB_URI", "")
    if not uri:
        raise RuntimeError("MONGODB_URI não configurado")
    db_name = os.environ.get("MONGODB_DB_NAME", "corridas_db")
    client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=15000)
    client.admin.command("ping")
    return client, client[db_name]["scrape_jobs"], client[db_name]["scrape_state"]


def claim_next_job(jobs) -> dict[str, Any] | None:
    """Reivindica o job queued mais antigo de forma atômica.

    find_one_and_update garante que dois workers nunca pegam o mesmo job,
    mesmo em réplicas simultâneas.
    """
    return jobs.find_one_and_update(
        {"status": QUEUED},
        {"$set": {"status": RUNNING, "started_at": now_iso()}},
        sort=[("started_at", 1)],
        return_document=ReturnDocument.AFTER,
    )


def finish_job(jobs, states, job_id: str, ok: bool, report: dict, error: str | None) -> None:
    """Marca conclusão e libera o slot (active:false) para o próximo acquire."""
    finished_at = now_iso()
    jobs.update_one(
        {"_id": job_id},
        {
            "$set": {
                "status": COMPLETE if ok else FAILED,
                "finished_at": finished_at,
                "report": report,
                "error": error,
                "active": False,
            }
        },
    )
    if ok:
        states.update_one(
            {"_id": "last_scrape"}, {"$set": {"finished_at": finished_at}}, upsert=True
        )


def run_pipeline(timeout_s: int, extra_args: str = "") -> tuple[bool, dict[str, Any]]:
    """Executa o pipeline existente como subprocesso, sem alterá-lo.

    extra_args carrega "--mode <fase> --job <id>"; argv continua fixo
    além dessas flags controladas pelo worker.
    """
    start = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S603 - argv fixo: interpretador + script do repo
            [sys.executable, str(PIPELINE_SCRIPT), *extra_args.split()],
            cwd=str(BACKEND_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
        duration = round(time.monotonic() - start, 1)
        stdout = proc.stdout or ""
        return proc.returncode == 0, {
            "pipeline_ok": proc.returncode == 0,
            "duration_s": duration,
            "exit_code": proc.returncode,
            "log_tail": stdout[-4000:],
            "stderr_tail": (proc.stderr or "")[-2000:],
        }
    except subprocess.TimeoutExpired:
        duration = round(time.monotonic() - start, 1)
        return False, {
            "pipeline_ok": False,
            "duration_s": duration,
            "exit_code": None,
            "log_tail": "",
            "stderr_tail": f"Timeout após {timeout_s}s",
        }


def load_frontend_report() -> dict[str, Any]:
    """Lê o ScrapeReport gerado pelo pipeline.

    Retorna o formato vazio do contrato quando o arquivo não existe ou é
    inválido: o modal do frontend trata listas ausentes como seções vazias.
    """
    try:
        data = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("started_at", None)
            data.setdefault("finished_at", None)
            data.setdefault("scrapers", [])
            data.setdefault("csvs", [])
            return data
    except Exception as exc:
        logger.warning(f"Relatório estruturado indisponível: {exc}")
    return {"started_at": None, "finished_at": None, "scrapers": [], "csvs": []}


def merge_import_report(job: dict, import_report: dict[str, Any]) -> dict[str, Any]:
    previous = job.get("report") if isinstance(job.get("report"), dict) else {}
    if not previous.get("scrapers"):
        return import_report
    merged = dict(import_report)
    merged["scrapers"] = previous.get("scrapers") or []
    if previous.get("started_at") and not merged.get("started_at"):
        merged["started_at"] = previous["started_at"]
    return merged


def mark_awaiting_import(jobs, job_id: str, report: dict[str, Any]) -> None:
    """Congela o job em awaiting_import com o relatório parcial.

    `active` permanece True: o slot do run continua ocupado até a
    confirmação (ou cancelamento), então dois runs não coexistem.
    """
    jobs.update_one(
        {"_id": job_id},
        {
            "$set": {
                "status": "awaiting_import",
                "report": report,
                "finished_at": "",
            }
        },
    )


def process_one(timeout_s: int) -> int:
    """Reivindica e executa um job na fase indicada por `phase`.

    collect (default): scrapers -> payload no Mongo -> job em awaiting_import
    (com relatório parcial para revisão; slot continua ocupado).
    import: restaura CSVs -> ImportToDB/ImportToBucket -> complete.
    """
    _, jobs, states = mongo_collection()
    job = claim_next_job(jobs)
    if job is None:
        logger.info("Nenhum job queued. Nada a fazer.")
        return 0

    job_id = str(job.get("_id") or job.get("job_id", ""))
    phase = str(job.get("phase") or "collect")
    logger.info(f"Job {job_id} reivindicado (fase {phase}).")

    if phase == "import":
        pipeline_ok, _ = run_pipeline(timeout_s, f"--mode import --job {job_id}")
        report = merge_import_report(job, load_frontend_report())
        error = None if pipeline_ok else "importação falhou"
        finish_job(jobs, states, job_id, pipeline_ok, report, error)
        logger.info(f"Job {job_id} finalizado: {'complete' if pipeline_ok else 'failed'}.")
        return 0 if pipeline_ok else 1

    pipeline_ok, _ = run_pipeline(timeout_s, f"--mode collect --job {job_id}")
    if not pipeline_ok:
        finish_job(jobs, states, job_id, False, load_frontend_report(), "coleta falhou")
        return 1

    mark_awaiting_import(jobs, job_id, load_frontend_report())
    logger.info(f"Job {job_id} aguardando confirmação de importação.")
    return 0


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def self_test() -> int:
    """Valida o protocolo de claim/complete num banco de teste, sem scrape.

    Cobre as duas fases: collect -> awaiting_import (slot mantido) e
    a transição import -> queued com phase marcada.
    """
    if os.environ.get("WORKER_ALLOW_SELF_TEST") != "1":
        print("self-test bloqueado: defina WORKER_ALLOW_SELF_TEST=1", file=sys.stderr)
        return 2
    _, jobs, states = mongo_collection()
    test_id = f"selftest-{int(time.time())}"
    jobs.insert_one(
        {
            "_id": test_id,
            "job_id": test_id,
            "status": QUEUED,
            "phase": "collect",
            "started_at": now_iso(),
            "finished_at": "",
            "report": None,
            "error": None,
            "active": True,
        }
    )
    try:
        claimed = claim_next_job(jobs)
        check(claimed is not None and str(claimed["_id"]) == test_id, "claim falhou")
        check(claimed["status"] == RUNNING, "status deveria ser running")

        # Fase collect concluída -> job congela em awaiting_import com slot.
        mark_awaiting_import(jobs, test_id, {"self_test": True})
        awaiting = jobs.find_one({"_id": test_id})
        check(awaiting["status"] == "awaiting_import", "status deveria ser awaiting_import")
        check(awaiting.get("active") is True, "active deveria permanecer True")

        # Fase import liberada pelo usuário -> complete + slot liberado.
        finish_job(jobs, states, test_id, True, {"self_test": True}, None)
        final = jobs.find_one({"_id": test_id})
        check(final is not None, "job sumiu")
        check(final["status"] == COMPLETE, "status deveria ser complete")
        check(final.get("active") is False, "active deveria ser false")
        state = states.find_one({"_id": "last_scrape"})
        check(state is not None and state.get("finished_at"), "last_scrape não gravado")
        print(
            "self-test OK: claim -> running -> awaiting_import (slot) -> complete + active:false + last_scrape"
        )
        return 0
    finally:
        jobs.delete_one({"_id": test_id})


def dry_run(timeout_s: int, interval_s: int) -> int:
    print("worker dry-run (nada será executado ou gravado):")
    print(f"  pipeline : {PIPELINE_SCRIPT} (existe: {PIPELINE_SCRIPT.exists()})")
    print(f"  timeout  : {timeout_s}s")
    print(f"  intervalo: {interval_s}s")
    print("  mongo    : usa MONGODB_URI/MONGODB_DB_NAME do ambiente")
    print("  fluxo    : claim queued->running -> subprocesso -> complete/failed + active:false")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Worker de scraping (jobs do MongoDB)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true", help="processa um job e sai")
    group.add_argument("--loop", action="store_true", help="repete --once a cada intervalo")
    group.add_argument("--dry-run", action="store_true", help="mostra o plano sem executar")
    group.add_argument(
        "--self-test", action="store_true", help="valida o protocolo num banco de teste"
    )
    parser.add_argument(
        "--interval", type=int, default=int(os.environ.get("WORKER_POLL_INTERVAL", "60"))
    )
    parser.add_argument(
        "--timeout", type=int, default=int(os.environ.get("WORKER_JOB_TIMEOUT", "3600"))
    )
    args = parser.parse_args(argv)

    if args.dry_run:
        return dry_run(args.timeout, args.interval)
    if args.self_test:
        return self_test()
    if args.once:
        return process_one(args.timeout)
    while True:
        code = process_one(args.timeout)
        if code != 0:
            logger.warning(f"Ciclo terminou com falha (exit {code}). Aguardando próximo intervalo.")
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
