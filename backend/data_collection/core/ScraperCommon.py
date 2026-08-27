"""Utilitários comuns aos scrapers de eventos.

Concentra sessão HTTP com retry/rate limiting, serialização de preços,
escrita de CSV e sincronização com MongoDB — evitando duplicação entre
scraper_brasilquecorre, scraper_race83, scraper_zenite e novos scrapers.
"""

import csv
import logging
import os
import threading
import time
from collections.abc import Callable, Iterable
from typing import cast

from data_collection.utils.PriceUtils import PriceEntry

__all__ = [
    "PriceEntry",
    "_as_object_list",
    "_as_str_object_dict",
]
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# O domínio brasilquecorre.com publica um certificado SSL inválido; as coletas para
# ele usam verify=False e o aviso de conexão insegura é suprimido intencionalmente.
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_RATE_LIMIT_LOCK = threading.Lock()
_LAST_REQUEST_TIME: dict[str, float] = {}  # último request por domínio (reserva de slot)


def get_http_session(user_agent: str | None = None) -> requests.Session:
    """Cria sessão requests com retry automático (backoff 1s/2s/4s) e User-Agent."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": user_agent
            or (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            )
        }
    )
    retry_strategy = Retry(
        total=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        backoff_factor=0.5,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def get_with_rate_limit(
    session: requests.Session,
    url: str,
    timeout: int | tuple[int, int] = 10,
    verify: bool = True,
) -> requests.Response | None:
    """GET com retry automático e rate limiting por domínio (thread-safe).

    Reserva um slot de 0,5s por domínio antes da requisição, permitindo uso
    concorrente por threads sem estourar o domínio alvo.

    Returns:
        Response em sucesso ou None após esgotar retries.
    """
    try:
        domain = urlparse(url).netloc
        wait = 0.0
        with _RATE_LIMIT_LOCK:
            now = time.time()
            last = _LAST_REQUEST_TIME.get(domain, 0.0)
            wait = max(0.0, 0.5 - (now - last))
            # Reserva o slot para esta requisição
            _LAST_REQUEST_TIME[domain] = now + wait

        if wait > 0:
            time.sleep(wait)

        response = session.get(url, timeout=timeout, verify=verify)
        response.raise_for_status()
        return response
    except Exception as e:
        logger.warning(f"Erro ao acessar {url}: {e}")
        return None


def fix_encoding(text: str | None) -> str:
    """Corrige texto com encoding latin1<->utf-8 quebrado (ex.: 'JoÃ£o' -> 'João')."""
    if not text:
        return ""
    try:
        return text.encode("latin1").decode("utf-8")
    except Exception:
        return text


# ─── Datas ───────────────────────────────────────────────────────────────────
from datetime import datetime  # noqa: E402

MONTHS_PT: dict[int, str] = {
    1: "janeiro",
    2: "fevereiro",
    3: "março",
    4: "abril",
    5: "maio",
    6: "junho",
    7: "julho",
    8: "agosto",
    9: "setembro",
    10: "outubro",
    11: "novembro",
    12: "dezembro",
}
MONTH_BY_NAME: dict[str, int] = {v: k for k, v in MONTHS_PT.items()}
MONTHS_CAPITALIZED: dict[int, str] = {k: v.capitalize() for k, v in MONTHS_PT.items()}


def parse_date_string(date_str: str | None) -> datetime | None:
    s = (date_str or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def format_date_string(date_str: str | None) -> str:
    dt = parse_date_string(date_str)
    if not dt:
        return date_str or ""
    return f"{dt.day} de {MONTHS_PT[dt.month]} de {dt.year}"


def parse_long_date_string(date_str: str | None) -> datetime | None:
    """Parse 'DD de Mês de AAAA' (first date) to datetime. Handles '02, 03 e 15 de Agosto de 2025'."""
    if not date_str:
        return None
    try:
        normalized = date_str.lower().replace("  ", " ").replace(" e ", ", ")
        parts = normalized.split(" de ")
        if len(parts) != 3:
            return None
        first_day = parts[0].split(",")[0].strip()
        month_str = parts[1].strip()
        month = MONTH_BY_NAME.get(month_str)
        if month is None:
            return None
        year = int(parts[2].strip())
        return datetime(year, month, int(first_day))
    except Exception:
        return None


def parse_long_multi_dates(date_str: str | None) -> list[datetime]:
    """Parse '02, 03 e 15 de Agosto de 2025' to list of datetimes. Returns empty list if invalid."""
    if not date_str:
        return []
    try:
        normalized = date_str.lower().replace("  ", " ").replace(" e ", ", ")
        parts = normalized.split(" de ")
        if len(parts) != 3:
            return []
        days = [d.strip() for d in parts[0].split(",")]
        month = MONTH_BY_NAME.get(parts[1].strip())
        if month is None:
            return []
        year = int(parts[2].strip())
        result: list[datetime] = []
        for day in days:
            try:
                result.append(datetime(year, month, int(day)))
            except Exception:
                continue
        return result
    except Exception:
        return []


def format_datetime_to_br(value: datetime | str | None) -> str:
    if not value:
        return ""
    try:
        if isinstance(value, str):
            if "T" in value:
                value = datetime.fromisoformat(value)
            else:
                return value
        if isinstance(value, datetime):
            return f"{value.day} de {MONTHS_CAPITALIZED[value.month]} de {value.year}"
        return str(value)
    except Exception:
        return str(value)


def entries_to_json(entries: Iterable[PriceEntry | str]) -> str:
    """Serializa entradas de preço em lista JSON legível, sem calcular resumo."""
    if not entries:
        return "[]"
    import json

    safe_prices: list[str] = []
    for raw_entry in entries:
        formatted: str | None = None
        if isinstance(raw_entry, str):
            formatted = raw_entry.strip()
        else:
            label_atual = str(raw_entry.get("label") or "").strip() or "GERAL"
            existing = cast("str | None", raw_entry.get("formatted"))
            formatted = existing.strip() if existing else None
            if not formatted:
                price_val = cast("float | int | None", raw_entry.get("price"))
                if price_val is not None:
                    try:
                        price_s = (
                            f"R$ {float(price_val):,.2f}".replace(",", "X")
                            .replace(".", ",")
                            .replace("X", ".")
                        )
                    except Exception:
                        price_s = f"R$ {price_val}"
                    formatted = f"{label_atual} — {price_s}"
        if formatted:
            safe_prices.append(formatted)
    try:
        return json.dumps(safe_prices, ensure_ascii=False) if safe_prices else "[]"
    except Exception:
        return "[]"


def _as_str_object_dict(value: object) -> dict[str, object] | None:
    """Narrowing seguro para dicts de JSON dinâmico."""
    if isinstance(value, dict):
        return cast("dict[str, object]", value)
    return None


def _as_object_list(value: object) -> list[object]:
    """Narrowing seguro para listas de JSON dinâmico."""
    if isinstance(value, list):
        return cast("list[object]", value)
    return [value]


EVENTOS_CSV_FIELDNAMES: list[str] = [
    "Nome do Evento",
    "Link de Inscrição",
    "Link da Imagem",
    "Data",
    "Horário",
    "Cidade",
    "Distância",
    "Organizador",
    "Link do Edital",
    "precos_entries",
]


def write_events_csv(
    csv_path: str,
    records: list[dict[str, str]],
    fieldnames: list[str] | None = None,
) -> None:
    """Grava registros no formato padrão do projeto (CSV ; com quoting total)."""
    fieldnames = fieldnames or EVENTOS_CSV_FIELDNAMES
    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(
            csvfile,
            fieldnames=fieldnames,
            delimiter=";",
            quoting=csv.QUOTE_ALL,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(records)


def sync_csv_to_mongodb(csv_path: str, collection: str) -> bool:
    """Sincroniza o CSV com o MongoDB Atlas (ignorado com CORREPB_COLLECT_ONLY=1)."""
    if os.environ.get("CORREPB_COLLEC_ONLY") or os.environ.get("CORREPB_COLLECT_ONLY"):
        return False
    try:
        from data_collection.utils import ImportToDB as sync_module

        remote_db = cast("object", sync_module.remote_db)
        import_fn = cast(
            "object",
            getattr(sync_module, "import_csv_to_mongodb"),
        )
        _ = cast("Callable[[object, str, str], None]", import_fn)(remote_db, csv_path, collection)
        return True
    except Exception as e:
        print(f"sincronização com mongodb ignorada ({collection}): {e}")
        return False
