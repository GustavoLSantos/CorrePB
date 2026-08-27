import asyncio
import csv
import os
import re
import subprocess
import sys
import time
import unicodedata
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

# Prioridade entre fontes: maior valor = mantido em caso de duplicata.
# Fontes dedicadas têm prioridade sobre o agregador brasilquecorre.
# Ordem alinhada ao isolamento já feito no BQC (que pula domínios dedicados).
SCRAPER_PRIORITY: dict[str, int] = {
    "circuitodasestacoes": 50,
    "race83": 40,
    "smcrono": 30,
    "zenite": 20,
    "brasilquecorre": 10,
}

# ─── Deduplicação cross-scraper ──────────────────────────────────────────────
_MESES_PT = {
    "janeiro": 1,
    "fevereiro": 2,
    "março": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _normalize_nome(nome: str) -> str:
    """Normaliza nome para fingerprint: sem acentos, lower, sem pontuação extra."""
    s = _strip_accents(nome).lower().strip()
    # remove sufixos de edição/etapa que geram falsos distintos mas mantém ano
    s = re.sub(r"\b\d+\s*º?\s*(edicao|ed\.|etapa)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _normalize_cidade(cidade: str) -> str:
    s = _strip_accents(cidade).lower().strip()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_data_key(data_str: str) -> str:
    """Converte Data do CSV em chave canônica YYYY-MM-DD ou string normalizada."""
    raw = (data_str or "").strip()
    if not raw:
        return ""
    # Tenta "DD de Mês de AAAA" (ex: "27 de setembro de 2026")
    try:
        low = raw.lower().replace("  ", " ").replace(" e ", ", ")
        partes = low.split(" de ")
        if len(partes) == 3:
            dia = partes[0].split(",")[0].strip()
            mes = _MESES_PT.get(partes[1].strip())
            ano = partes[2].strip()
            if mes:
                return f"{int(ano):04d}-{mes:02d}-{int(dia):02d}"
    except Exception:
        pass
    # Tenta DD/MM/YYYY
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)
    if m:
        return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    # Fallback: normaliza string
    return _strip_accents(raw).lower().strip()


def _event_fingerprint(row: dict[str, str]) -> tuple[str, str, str]:
    """Fingerprint estável para deduplicação entre scrapers."""
    nome = _normalize_nome(row.get("Nome do Evento", ""))
    cidade = _normalize_cidade(row.get("Cidade", ""))
    data_key = _parse_data_key(row.get("Data", ""))
    # Fallback para link canônico quando nome/cidade vazios
    if not nome:
        link = (row.get("Link de Inscrição") or "").strip().lower()
        # normaliza host+path sem query
        link = re.sub(r"\?.*$", "", link)
        link = re.sub(r"https?://", "", link).strip("/")
        return (link, data_key, cidade)
    return (nome, data_key, cidade)


class DedupStats(TypedDict):
    fonte: str
    mantidos: int
    removidos: int
    duplicatas: list[str]


def _completeness_score(row: dict[str, str]) -> int:
    """Pontua completude do CSV: quantidade de campos relevantes preenchidos.

    Campos vazios, '[]' ou placeholders como 'edital não encontrado' /
    'Valor não encontrado' não contam. Usado como critério principal
    de desempate na deduplicação.
    """
    score = 0
    for key in (
        "Nome do Evento",
        "Data",
        "Cidade",
        "Link de Inscrição",
        "Link da Imagem",
        "Distância",
        "Organizador",
        "Horário",
        "Link do Edital",
        "precos_entries",
        "Percurso",
        "Kits",
    ):
        v = (row.get(key) or "").strip()
        if not v or v in ("[]", "edital não encontrado", "Valor não encontrado"):
            continue
        # precos_entries com JSON vazio não conta
        if key == "precos_entries" and v in ("[]", '["Valor não encontrado"]'):
            continue
        score += 1
        # bônus leve para campos mais valiosos
        if key in ("precos_entries", "Link da Imagem", "Distância") and v not in ("", "[]"):
            score += 1
    return score


def deduplicate_csvs(
    csv_map: dict[str, Path] | None = None,
    *,
    rewrite_files: bool = True,
) -> list[DedupStats]:
    """
    Remove duplicatas entre diferentes scrapers nos CSVs.

    - Agrupa todas as linhas por fingerprint (nome+cidade+data)
    - Para cada grupo duplicado, mantém a linha com maior completude
      (mais campos preenchidos); em empate usa SCRAPER_PRIORITY
    - Reescreve arquivos afetados atomicamente
    - Retorna estatísticas por fonte
    """
    target_map = csv_map or CSV_MAP

    headers: dict[str, list[str] | None] = {f: None for f in target_map}
    # fingerprint -> lista de (fonte, row, score, priority, order_idx)
    groups: dict[tuple[str, str, str], list[tuple[str, dict[str, str], int, int, int]]] = {}
    order_counter = 0

    for fonte in target_map:
        path = target_map[fonte]
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8-sig", errors="replace") as f:
                reader = csv.DictReader(f, delimiter=";", quoting=csv.QUOTE_ALL)
                headers[fonte] = reader.fieldnames
                for row in reader:
                    clean = {k: (v or "") for k, v in row.items() if k is not None}
                    fp = _event_fingerprint(clean)
                    # fingerprint vazio (sem nome/link e sem data) -> nunca deduplica
                    if fp == ("", "", ""):
                        # usa chave única para não agrupar
                        fp = (f"__empty_{fonte}_{order_counter}", "", "")
                    score = _completeness_score(clean)
                    priority = SCRAPER_PRIORITY.get(fonte, 0)
                    groups.setdefault(fp, []).append((fonte, clean, score, priority, order_counter))
                    order_counter += 1
        except Exception as e:
            # Falha de leitura não deve abortar pipeline
            continue

    # Decide vencedor por grupo: maior completude, desempate por prioridade
    stats: dict[str, DedupStats] = {
        f: {"fonte": f, "mantidos": 0, "removidos": 0, "duplicatas": []} for f in target_map
    }
    kept_rows: dict[str, list[dict[str, str]]] = {f: [] for f in target_map}

    for fp, candidates in groups.items():
        if len(candidates) == 1:
            fonte, row, _, _, _ = candidates[0]
            kept_rows[fonte].append(row)
            stats[fonte]["mantidos"] += 1
            continue
        # Ordena por completude desc, prioridade desc, ordem asc (estável)
        candidates.sort(key=lambda x: (-x[2], -x[3], x[4]))
        winner = candidates[0]
        winner_fonte, _, winner_score, _, _ = winner
        for fonte, row, score, _, _ in candidates:
            is_winner = row is winner[1] and fonte == winner_fonte
            if is_winner:
                kept_rows[fonte].append(row)
                stats[fonte]["mantidos"] += 1
            else:
                stats[fonte]["removidos"] += 1
                if len(stats[fonte]["duplicatas"]) < 5:
                    stats[fonte]["duplicatas"].append(
                        f"'{row.get('Nome do Evento', '')[:40]}' duplicado de '{winner_fonte}' (score {score} < {winner_score})"
                    )

    if rewrite_files:
        for fonte, path in target_map.items():
            if not path.exists() or headers[fonte] is None:
                continue
            if stats[fonte]["removidos"] == 0:
                continue
            tmp = path.with_suffix(".dedup.tmp")
            try:
                with tmp.open("w", encoding="utf-8", newline="") as out:
                    writer = csv.DictWriter(
                        out,
                        fieldnames=headers[fonte] or [],
                        delimiter=";",
                        quoting=csv.QUOTE_ALL,
                    )
                    writer.writeheader()
                    writer.writerows(kept_rows[fonte])
                tmp.replace(path)
            except Exception:
                if tmp.exists():
                    with __import__("contextlib").suppress(Exception):
                        tmp.unlink()
                raise

    # Retorna em ordem de prioridade para relatório estável
    fontes_ordenadas = sorted(
        target_map.keys(), key=lambda k: SCRAPER_PRIORITY.get(k, 0), reverse=True
    )
    return [stats[f] for f in fontes_ordenadas if f in target_map]


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
            "deduplicacao": [],
        }
        if any(not r["ok"] for r in scraper_results):
            job.status = "failed"
            job.error = "Um ou mais scrapers falharam"
        else:
            # Deduplicação cross-scraper priorizando completude
            try:
                dedup_stats = await asyncio.to_thread(deduplicate_csvs)
                report["deduplicacao"] = dedup_stats
                if any(s["removidos"] > 0 for s in dedup_stats):
                    # log resumido, sem poluir report
                    for s in dedup_stats:
                        if s["removidos"]:
                            print(
                                f"[dedup] {s['fonte']}: {s['removidos']} removidos, "
                                f"{s['mantidos']} mantidos"
                            )
            except Exception as e:
                print(f"[WARN] falha na deduplicação: {e}")
                report["deduplicacao"] = []

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
