import csv
import logging
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_collection.core.ScraperCommon import MONTH_BY_NAME

# ─── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent  # data_collection/
PROJECT_ROOT = BASE_DIR.parent  # backend/
DATA_DIR = BASE_DIR / "data"

SCRAPERS = [
    "scraper_brasilquecorre.py",
    "scraper_smcrono.py",
    "scraper_race83.py",
    "scraper_zenite.py",
    "scraper_circuitodasestacoes.py",
    "scraper_apcrono.py",
    "scraper_cronoar.py",
]

CSV_MAP: Dict[str, Path] = {
    "brasilquecorre": DATA_DIR / "eventos_brasilquecorre.csv",
    "smcrono": DATA_DIR / "eventos_smcrono.csv",
    "race83": DATA_DIR / "eventos_race83.csv",
    "zenite": DATA_DIR / "eventos_zenite.csv",
    "circuitodasestacoes": DATA_DIR / "eventos_circuitodasestacoes.csv",
    "apcrono": DATA_DIR / "eventos_apcrono.csv",
    "cronoar": DATA_DIR / "eventos_cronoar.csv",
}

IMPORT_TO_DB_SCRIPT = BASE_DIR / "utils" / "ImportToDB.py"
IMPORT_TO_BUCKET_SCRIPT = BASE_DIR / "utils" / "ImportToBucket.py"

# ─── Data structures ──────────────────────────────────────────────────────────


@dataclass
class StepResult:
    name: str
    ok: bool
    duration: float
    stdout: str = ""
    stderr: str = ""
    extra: Dict = field(default_factory=dict)


@dataclass
class CsvSummary:
    fonte: str
    ok: bool
    total: int = 0
    duplicados: int = 0
    sem_preco: int = 0
    eventos_passados: int = 0
    sem_imagem: int = 0
    erros_encoding: int = 0
    nomes_passados: List[str] = field(default_factory=list)
    erros: List[str] = field(default_factory=list)


# ─── Logging ──────────────────────────────────────────────────────────────────


def setup_logging() -> logging.Logger:
    logger = logging.getLogger('pipeline')
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s %(message)s', '%H:%M:%S'))
        logger.addHandler(handler)
        logger.propagate = False
    return logger


logger = setup_logging()

# ─── Subprocess helper ────────────────────────────────────────────────────────


def _build_env() -> Dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}


def _run_subprocess(script_path: Path, label: str) -> StepResult:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_build_env(),
            cwd=str(PROJECT_ROOT),
        )
        duration = time.monotonic() - start
        return StepResult(
            name=label,
            ok=proc.returncode == 0,
            duration=duration,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )
    except Exception as exc:
        duration = time.monotonic() - start
        return StepResult(name=label, ok=False, duration=duration, stderr=str(exc))


# ─── Scrapers ─────────────────────────────────────────────────────────────────


def run_scraper(script_name: str) -> StepResult:
    script_path = BASE_DIR / script_name
    logger.info(f"Iniciando scraper: {script_name}")
    result = _run_subprocess(script_path, script_name)
    status = "OK" if result.ok else "FALHOU"
    logger.info(f"Scraper {script_name}: {status} ({result.duration:.1f}s)")
    return result


def run_scrapers_parallel() -> List[StepResult]:
    results: List[StepResult] = []
    # Limit to 4 parallel scrapers to avoid RAM explosion (each may spawn 4 workers + 2 Chrome drivers ~1GB)
    with ThreadPoolExecutor(max_workers=min(4, len(SCRAPERS))) as executor:
        futures = {executor.submit(run_scraper, s): s for s in SCRAPERS}
        for future in as_completed(futures):
            results.append(future.result())
    # Mantém ordem original
    results.sort(key=lambda r: SCRAPERS.index(r.name) if r.name in SCRAPERS else 99)
    return results


# ─── CSV Validation ───────────────────────────────────────────────────────────

REQUIRED_FIELDS = ["Nome do Evento", "Data", "Cidade", "Link de Inscrição"]
# Mojibake real: replacement char, Ã+minúscula ('JoÃo'), Â+°/»/£, â€ (smart quotes)
# '?' sozinho é conteúdo legítimo e não deve ser sinalizado.
ENCODING_GARBAGE_RE = re.compile(r"\ufffd|Ã[a-zà-ú]|Â[°»£¢]|â€")


def _parse_first_date(data_str: str) -> Optional[datetime]:
    """Extract first date from 'DD de Mês de AAAA' (delegates to ScraperCommon)."""
    from data_collection.core.ScraperCommon import parse_long_date_string

    return parse_long_date_string(data_str)


def validate_csv(path: Path, fonte: str) -> CsvSummary:
    summary = CsvSummary(fonte=fonte, ok=True)
    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    if not path.exists():
        summary.ok = False
        summary.erros.append(f"Arquivo não encontrado: {path}")
        return summary

    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f, delimiter=";")
            rows = list(reader)
    except Exception as exc:
        summary.ok = False
        summary.erros.append(f"Erro ao ler CSV: {exc}")
        return summary

    summary.total = len(rows)
    nomes_vistos: Dict[str, int] = {}

    for i, row in enumerate(rows, start=2):  # linha 1 = cabeçalho
        # Campos obrigatórios ausentes
        for campo in REQUIRED_FIELDS:
            val = row.get(campo, "").strip()
            if not val:
                summary.erros.append(f'Linha {i}: campo "{campo}" vazio')

        nome = row.get("Nome do Evento", "").strip()
        if nome:
            nomes_vistos[nome] = nomes_vistos.get(nome, 0) + 1

        # Eventos passados
        data_raw = row.get("Data", "").strip()
        if data_raw:
            dt = _parse_first_date(data_raw)
            if dt and dt < hoje:
                summary.eventos_passados += 1
                summary.nomes_passados.append(nome or f"linha {i}")

        # Sem imagem
        if not row.get("Link da Imagem", "").strip():
            summary.sem_imagem += 1

        # Sem preços
        precos_raw = row.get("precos_entries", "").strip()
        if not precos_raw or precos_raw in ("[]", ""):
            summary.sem_preco += 1

        # Encoding corrompido
        texto_concatenado = " ".join(str(v) for v in row.values())
        if ENCODING_GARBAGE_RE.search(texto_concatenado):
            summary.erros_encoding += 1

    # Duplicatas
    summary.duplicados = sum(1 for c in nomes_vistos.values() if c > 1)

    return summary


# ─── Imports ──────────────────────────────────────────────────────────────────


def _parse_import_db_output(stdout: str) -> Tuple[int, int]:
    """Extrai (novos, atualizados) do stdout do ImportToDB."""
    novos = atualizados = 0
    for line in stdout.splitlines():
        m = re.search(r"(\d+) novos eventos adicionados", line)
        if m:
            novos += int(m.group(1))
        m = re.search(r"(\d+) eventos atualizados", line)
        if m:
            atualizados += int(m.group(1))
    return novos, atualizados


def _parse_import_bucket_output(stdout: str) -> Dict:
    """Extrai métricas do stdout do ImportToBucket (melhor esforço)."""
    info: Dict = {}
    for line in stdout.splitlines():
        m = re.search(r"(\d+)\s+eventos", line, re.IGNORECASE)
        if m and "total" not in info:
            info["total"] = int(m.group(1))
        m = re.search(r"(\d+)\s+(nova[s]?\s+imagem|imagem.*nova)", line, re.IGNORECASE)
        if m:
            info["novas_imagens"] = int(m.group(1))
        m = re.search(r"(\d+)\s+falha", line, re.IGNORECASE)
        if m:
            info["falhas"] = int(m.group(1))
    return info


def run_import(script_path: Path, name: str) -> StepResult:
    logger.info(f"Iniciando {name}...")
    result = _run_subprocess(script_path, name)
    status = "OK" if result.ok else "FALHOU"
    logger.info(f"{name}: {status} ({result.duration:.1f}s)")
    return result


# ─── Report ───────────────────────────────────────────────────────────────────

SEP_FULL = "═" * 52
SEP_THIN = "─" * 52


def _fmt_duration(seconds: float) -> str:
    return f"{seconds:.1f}s"


def print_report(
    scraper_results: List[StepResult],
    csv_summaries: List[CsvSummary],
    import_db: Optional[StepResult],
    import_bucket: Optional[StepResult],
    total_duration: float,
    aborted: bool = False,
) -> None:
    print()
    print(SEP_FULL)
    print("  PIPELINE CORRE PB — RELATÓRIO FINAL")
    print(SEP_FULL)

    # Scrapers
    print()
    print("SCRAPERS")
    print(SEP_THIN)
    for r in scraper_results:
        tag = "[OK]  " if r.ok else "[FAIL]"
        name_col = r.name.ljust(35)
        print(f"  {tag} {name_col} {_fmt_duration(r.duration)}")
        if not r.ok and r.stderr:
            for line in r.stderr.strip().splitlines()[-3:]:
                print(f"         {line}")

    # CSV Validation
    if csv_summaries:
        print()
        print("VALIDAÇÃO DOS CSVs")
        print(SEP_THIN)
        for s in csv_summaries:
            tag = "[OK]  " if s.ok else "[ERRO]"
            fonte_col = s.fonte.ljust(16)
            stats = (
                f"{s.total} linhas | dup:{s.duplicados} | "
                f"s/preco:{s.sem_preco} | passados:{s.eventos_passados} | "
                f"s/img:{s.sem_imagem}"
            )
            if s.erros_encoding:
                stats += f" | enc_err:{s.erros_encoding}"
            print(f"  {tag} {fonte_col} {stats}")
            for err in s.erros[:5]:
                print(f"  [!] {err}")
            if s.nomes_passados:
                nomes_str = ", ".join(s.nomes_passados[:5])
                extra = f" (+{len(s.nomes_passados) - 5})" if len(s.nomes_passados) > 5 else ""
                print(
                    f"  [AVISO] {s.fonte}: {s.eventos_passados} eventos com data passada: [{nomes_str}{extra}]"
                )

    # Importações
    if import_db or import_bucket:
        print()
        print("IMPORTAÇÕES")
        print(SEP_THIN)

    if import_db:
        tag = "[OK]  " if import_db.ok else "[FAIL]"
        novos, atualizados = _parse_import_db_output(import_db.stdout)
        print(
            f"  {tag} ImportToDB       {novos} novos, {atualizados} atualizados  {_fmt_duration(import_db.duration)}"
        )
        if not import_db.ok:
            for line in import_db.stderr.strip().splitlines()[-3:]:
                print(f"         {line}")

    if import_bucket:
        tag = "[OK]  " if import_bucket.ok else "[FAIL]"
        bkt = _parse_import_bucket_output(import_bucket.stdout)
        total_bkt = bkt.get("total", "?")
        novas_img = bkt.get("novas_imagens", "?")
        falhas_bkt = bkt.get("falhas", 0)
        print(
            f"  {tag} ImportToBucket   {total_bkt} eventos | {novas_img} novas imagens | {falhas_bkt} falhas  {_fmt_duration(import_bucket.duration)}"
        )
        if not import_bucket.ok:
            for line in import_bucket.stderr.strip().splitlines()[-3:]:
                print(f"         {line}")

    print()
    print(SEP_FULL)
    if aborted:
        print(f"  [FALHA] PIPELINE ABORTADO  ({_fmt_duration(total_duration)} total)")
    else:
        print(f"  [OK] PIPELINE CONCLUÍDO COM SUCESSO  ({_fmt_duration(total_duration)} total)")
    print(SEP_FULL)
    print()


# ─── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    pipeline_start = time.monotonic()

    logger.info("=== Pipeline Corre PB iniciado ===")

    # 1. Scrapers em paralelo (limitado a 4 workers para evitar OOM — Task 4)
    max_workers = min(4, len(SCRAPERS))
    logger.info(f"Executando {len(SCRAPERS)} scrapers em paralelo (max {max_workers} workers)...")
    scraper_results = run_scrapers_parallel()

    scrapers_ok = all(r.ok for r in scraper_results)
    if not scrapers_ok:
        failed = [r.name for r in scraper_results if not r.ok]
        logger.error(f"Scrapers com falha: {failed}. Abortando pipeline.")
        print_report(
            scraper_results,
            csv_summaries=[],
            import_db=None,
            import_bucket=None,
            total_duration=time.monotonic() - pipeline_start,
            aborted=True,
        )
        sys.exit(1)

    # 2. Deduplicação cross-scraper nos CSVs (prioriza completude)
    try:
        # Import tardio para evitar ciclo com app.services
        import importlib
        _mod = importlib.import_module("app.services.scraper_runner")
        _dedup = getattr(_mod, "deduplicate_csvs", None)
        if _dedup:
            dup_stats = _dedup()
            for s in dup_stats:
                if s["removidos"]:
                    logger.info(f"[dedup][CSV] {s['fonte']}: {s['removidos']} removidos, {s['mantidos']} mantidos")
    except Exception as e:
        logger.warning(f"Falha na deduplicação CSV: {e}")

    # 3. Validação dos CSVs
    logger.info("Validando CSVs...")
    csv_summaries: List[CsvSummary] = []
    csv_critical_error = False

    for fonte, path in CSV_MAP.items():
        summary = validate_csv(path, fonte)
        csv_summaries.append(summary)
        if not summary.ok:
            logger.error(f"Erro crítico no CSV {fonte}: {summary.erros}")
            csv_critical_error = True
        else:
            if summary.eventos_passados:
                logger.warning(f"{fonte}: {summary.eventos_passados} evento(s) com data passada.")
            if summary.sem_preco:
                logger.warning(f"{fonte}: {summary.sem_preco} evento(s) sem preço.")

    if csv_critical_error:
        logger.error("Erro crítico na validação dos CSVs. Abortando pipeline.")
        print_report(
            scraper_results,
            csv_summaries,
            import_db=None,
            import_bucket=None,
            total_duration=time.monotonic() - pipeline_start,
            aborted=True,
        )
        sys.exit(1)

    # 4. ImportToDB
    logger.info("Executando ImportToDB...")
    import_db_result = run_import(IMPORT_TO_DB_SCRIPT, "ImportToDB")

    if not import_db_result.ok:
        logger.error("ImportToDB falhou. Abortando pipeline.")
        print_report(
            scraper_results,
            csv_summaries,
            import_db=import_db_result,
            import_bucket=None,
            total_duration=time.monotonic() - pipeline_start,
            aborted=True,
        )
        sys.exit(1)

    # 4.5 Deduplicação no banco/bucket (remove duplicatas históricas já persistidas)
    try:
        import asyncio as _asyncio

        from app.services.scraper_runner import deduplicate_db_and_bucket as _dedup_db

        _db_stats = _asyncio.run(_dedup_db())
        if _db_stats and _db_stats.get("removidos_db"):
            logger.info(
                f"[dedup][DB] {_db_stats['removidos_db']} docs removidos em {_db_stats.get('grupos', '?')} grupos"
            )
            if _db_stats.get("removidos_bucket"):
                logger.info(f"[dedup][S3] {_db_stats['removidos_bucket']} imagens órfãs removidas")
    except Exception as e:
        logger.warning(f"Falha na deduplicação DB/bucket: {e}")

    # 5. ImportToBucket
    logger.info("Executando ImportToBucket...")
    import_bucket_result = run_import(IMPORT_TO_BUCKET_SCRIPT, "ImportToBucket")

    # Relatório final (ImportToBucket falha → reporta mas não é exit(1) crítico aqui;
    # porém seguindo o plano: falha → exit(1))
    total_duration = time.monotonic() - pipeline_start
    print_report(
        scraper_results,
        csv_summaries,
        import_db=import_db_result,
        import_bucket=import_bucket_result,
        total_duration=total_duration,
        aborted=not import_bucket_result.ok,
    )

    if not import_bucket_result.ok:
        logger.error("ImportToBucket falhou.")
        sys.exit(1)

    logger.info("Pipeline concluído com sucesso.")
    sys.exit(0)


if __name__ == "__main__":
    main()
