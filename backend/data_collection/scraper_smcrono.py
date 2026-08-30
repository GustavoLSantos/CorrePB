import sys
import os
import re
import io
import json
from datetime import datetime, timedelta

import logging

import requests
from PyPDF2 import PdfReader
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_collection.core.ScraperCommon import (
    MONTHS_PT,
    fix_encoding,
    format_date_string,
    parse_date_string,
    run_standard_scraper,
    sync_csv_to_mongodb,
    write_events_csv,
)
from data_collection.utils.PriceUtils import parse_price_str
from data_collection.utils.PrizeDetection import entry_is_prize

BASE_URL = "https://www.smcrono.com.br"

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }
)
# Retry com backoff para reduzir falhas transientes e evitar thundering herd
_retry = Retry(
    total=2,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
    raise_on_status=False,
)
_adapter = HTTPAdapter(max_retries=_retry, pool_connections=20, pool_maxsize=20)
SESSION.mount("https://", _adapter)
SESSION.mount("http://", _adapter)

# ─── Kit (extração de itens a partir do PDF do regulamento) ──────────────────

KIT_ITEMS_PATTERN = re.compile(
    r"\b(camiseta|camisa|medalha|n[uú]mero\s+d[oea]+\s*peito|chip|meia|viseira|"
    r"sacochila|bon[eé]|squeeze|ecobag|mochila|toalha|pochete|regata)\b",
    re.IGNORECASE,
)

KIT_ITEMS_NORMALIZE = {
    "camisa": "camiseta",
}


def _normalize_item(item):
    item = re.sub(r"\s+", " ", item.strip().lower())
    item = re.sub(r"n[uú]mero\s+d[oea]+\s*peito", "número de peito", item)
    return KIT_ITEMS_NORMALIZE.get(item, item)


MAX_PDF_BYTES = 10 * 1024 * 1024  # 10MB limit to avoid OOM


def _extract_pdf_text(pdf_url):
    resp = SESSION.get(pdf_url, timeout=15, stream=True)
    resp.raise_for_status()

    content_length = resp.headers.get("Content-Length")
    if content_length and int(content_length) > MAX_PDF_BYTES:
        raise ValueError(f"PDF too large: {content_length} bytes > {MAX_PDF_BYTES}")

    content = b""
    for chunk in resp.iter_content(chunk_size=8192):
        content += chunk
        if len(content) > MAX_PDF_BYTES:
            raise ValueError(f"PDF exceeded {MAX_PDF_BYTES} bytes limit")

    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _find_kit_sections(text):
    header_patterns = [
        r"(?:^|\n)\s*(?:\d+[\.\-\s]*)*\s*(?:D[AO]S?\s+)?(?:COMPOSI[CÇ][AÃ]O\s+D[OE]S?\s+)?KITS?\s*(?:D[OE]S?\s+ATLETAS?)?",
        r"(?:^|\n)\s*(?:\d+[\.\-\s]*)*\s*(?:ENTREGA|RETIRADA)\s+D[OE]S?\s+KITS?",
        r"(?:^|\n)\s*(?:Cap[ií]tulo|Art(?:igo)?)\s+[^\n]*KITS?",
        r"(?:^|\n)\s*Entrega\s+d[eo]s?\s+kits?[:\s]",
    ]
    sections = []
    for pat in header_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            end = len(text)
            next_header = re.search(
                r"\n\s*(?:\d+[\.\-\s]*)+\s*(?:CRONOMETRAGEM|PREMIA|REGRAS?\s+GERA|PERCURSO|LARGADA|CATEGORIAS|DECLARA|DISPOSI|PENALID)",
                text[m.end() :],
                re.IGNORECASE,
            )
            if next_header:
                end = m.end() + next_header.start()
            sections.append(text[m.start() : end])
    return sections


def _parse_kit_info(text):
    a_definir = re.compile(r"^\(?[àa]\s*definir\)?\.?\s*$", re.IGNORECASE)

    kit_sections = _find_kit_sections(text)
    if not kit_sections:
        return None

    combined = "\n".join(kit_sections)
    itens = list({_normalize_item(m.group(0)) for m in KIT_ITEMS_PATTERN.finditer(combined)})

    local_retirada = None
    local_patterns = [
        r"[Ee]ndere[cç]o[:\s\-–]+(.+)",
        r"[Ll]ocal\s*(?:de|da|para)\s*(?:entrega|retirada)[:\s\-–]+(.+)",
    ]
    local_blacklist = re.compile(
        r"http|www\.|deslocamento|anteced[eê]ncia|estabelecid|largada|obrigat|comprova|inscri[çc]",
        re.IGNORECASE,
    )
    for pat in local_patterns:
        for m in re.finditer(pat, combined, re.IGNORECASE):
            candidate = m.group(1).strip().split("\n")[0].strip()
            candidate = re.sub(r"^[:\s\-–]+", "", candidate)
            candidate = re.sub(r"\s{2,}", " ", candidate).strip(" .")
            if (
                candidate
                and not a_definir.match(candidate)
                and not local_blacklist.search(candidate)
                and len(candidate) > 3
            ):
                local_retirada = candidate
                break
        if local_retirada:
            break

    if not local_retirada:
        for section in kit_sections:
            skip = re.compile(
                r"^(D[AEOI]S?\b|PARA\b|KIT|PROVA|EVENTO|RETIRADA|E\s+DATA|HOR|QUE\b|ONDO)",
                re.IGNORECASE,
            )
            for loc_m in re.finditer(r"[–\-]\s*LOCAL\s+([A-Z][A-Za-z\s]{4,})", section):
                candidate = re.sub(r"\s{2,}", " ", loc_m.group(1).strip()).strip(" .")
                if (
                    candidate
                    and not skip.match(candidate)
                    and not local_blacklist.search(candidate)
                ):
                    local_retirada = candidate
                    break
            if local_retirada:
                break

    data_retirada = None
    entrega_context = re.findall(r"(?:entrega|retirada)[^\n]{0,80}", combined, re.IGNORECASE)
    search_text = "\n".join(entrega_context) if entrega_context else combined

    date_m = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+(?:de\s+)?(\d{4})", search_text, re.IGNORECASE)
    if not date_m:
        date_m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", search_text)
    if date_m:
        try:
            g = date_m.groups()
            if "/" in date_m.group(0):
                data_retirada = datetime(int(g[2]), int(g[1]), int(g[0])).isoformat()
            else:
                nome_mes = g[1].lower().rstrip(".")
                mes = next(
                    (num for num, nome in MONTHS_PT.items() if nome.startswith(nome_mes[:3])),
                    None,
                )
                if mes:
                    data_retirada = datetime(int(g[2]), mes, int(g[0])).isoformat()
        except (ValueError, KeyError) as exc:
            logger.debug(f"kit date parse failed: {exc}", exc_info=True)

    if not itens:
        itens = list({_normalize_item(m.group(0)) for m in KIT_ITEMS_PATTERN.finditer(text)})

    if not itens and not local_retirada:
        return None

    return [
        {
            "nome": "Kit",
            "itens": sorted(itens),
            "local_retirada": local_retirada,
            "data_retirada": data_retirada,
        }
    ]


def extract_kits_from_pdf(pdf_url):
    if not pdf_url or pdf_url.lower() in ("edital não encontrado", "edital nao encontrado", ""):
        return None
    try:
        text = _extract_pdf_text(pdf_url)
        if not text.strip():
            return None
        return _parse_kit_info(text)
    except Exception as e:
        logger.warning(f"Erro ao extrair PDF ({pdf_url}): {e}")
        return None


def _candidate_events_urls():
    urls = []
    try:
        html = SESSION.get(f"{BASE_URL}/calendario-eventos", timeout=15).text
        m = re.search(r"url_arquivo_events\s*=\s*'([^']+)'", html)
        if m:
            urls.append(m.group(1))
    except Exception as e:
        logger.warning(f"Calendar shell unavailable: {e}")
    for delta in (0, 1):
        dia = datetime.now() - timedelta(days=delta)
        urls.append(f"{BASE_URL}/session/{dia:%Y%m%d}_smcrono_events.json")
    return urls


def _load_events_json():
    for url in _candidate_events_urls():
        try:
            resp = SESSION.get(url, timeout=20)
            resp.raise_for_status()
            eventos = (resp.json() or {}).get("listEventos") or []
            if eventos:
                logger.info(f"List loaded from {url}: {len(eventos)} events")
                return eventos
            logger.warning(f"Empty list at {url}")
        except Exception as e:
            logger.warning(f"Failed to load {url}: {e}")
    return []


def _fetch_event_details(url_evento):
    resp = SESSION.get(f"{BASE_URL}/api_evento.php", params={"url": url_evento}, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _extrair_cidade_estado(local, ev):
    m = re.match(r"^(.*?)\s*-\s*([A-Z]{2})\s*$", (local or "").strip())
    if m:
        return fix_encoding(m.group(1).strip().title()), m.group(2).upper()
    cidade = (ev.get("eve_cidade") or "").strip()
    estado_m = re.search(r"([A-Z]{2})\s*$", (ev.get("eve_estado") or "").strip())
    return fix_encoding(cidade.title()), estado_m.group(1) if estado_m else ""


def _montar_precos(precos_categorias):
    lotes = precos_categorias or []
    multi_lote = len(lotes) > 1
    entradas = []
    vistos = set()

    for lote in lotes:
        lote_nome = str(lote.get("lote_nome") or "").strip()
        for p in lote.get("precos") or []:
            valor = (p.get("valor") or "").strip()
            preco = parse_price_str(valor)
            if not valor or not preco:
                continue
            partes = [
                x.strip() for x in (p.get("modalidade"), p.get("categoria")) if x and x.strip()
            ]
            label = " — ".join(partes) if partes else "Geral"
            if multi_lote and lote_nome:
                label = f"Lote {lote_nome}: {label}"
            label = fix_encoding(label)

            chave = (preco, label)
            if chave in vistos:
                continue
            vistos.add(chave)

            entry = {"raw": "", "label": label, "price": preco}
            try:
                if entry_is_prize(entry, ""):
                    continue
            except Exception as exc:
                logger.debug(f"entry_is_prize check failed: {exc}", exc_info=True)

            entradas.append({"label": label, "price": preco, "formatted": valor})

    entradas.sort(key=lambda x: x["price"])
    return [f"{e['formatted']} | {e['label']}" for e in entradas]


def _parse_br_date(date_str: str | None):
    return parse_date_string(date_str)


def _filter_candidates(
    eventos_lista: list, estado_filter: str | None, somente_futuros: bool
) -> tuple[list, int]:
    candidates: list = []
    seen: set[str] = set()
    pre_filtered = 0
    for ev in eventos_lista:
        url_evento = (ev.get("url_evento") or "").strip("/")
        if not url_evento or url_evento in seen:
            continue
        seen.add(url_evento)
        if somente_futuros:
            dt = _parse_br_date(ev.get("eve_data_evento") or "")
            if dt and dt < datetime.now():
                pre_filtered += 1
                continue
        if estado_filter:
            raw_state = (ev.get("eve_estado") or "").strip().upper()
            if raw_state and estado_filter.upper() not in raw_state:
                if raw_state not in ("", "-", " -"):
                    m_uf = re.search(r"\b([A-Z]{2})\b", raw_state)
                    if m_uf and m_uf.group(1) != estado_filter.upper():
                        pre_filtered += 1
                        continue
        candidates.append(ev)
    return candidates, pre_filtered


def _fetch_details_parallel(candidates: list) -> list[tuple[dict, dict]]:
    import concurrent.futures

    def _fetch_safe(ev: dict):
        url_evento = (ev.get("url_evento") or "").strip("/")
        try:
            det = _fetch_event_details(url_evento)
            return (ev, det or {}, None)
        except Exception as e:
            return (ev, {}, e)

    max_workers = min(10, max(4, len(candidates) // 2)) if candidates else 1
    fetched: list[tuple[dict, dict]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_fetch_safe, ev): ev for ev in candidates}
        for fut in concurrent.futures.as_completed(futs):
            ev, det, err = fut.result()
            if err is not None:
                logger.warning(f"falha ao buscar detalhes {ev.get('eve_nome', '?')}: {err}")
            fetched.append((ev, det))
    return fetched


def _build_event_record(ev: dict, det: dict) -> tuple[dict | None, str | None]:
    url_evento = (ev.get("url_evento") or "").strip("/")
    cidade, _ = _extrair_cidade_estado(det.get("local"), ev)

    edital_link = "edital não encontrado"
    for doc in det.get("documentos") or []:
        doc_url = (doc.get("url") or "").strip()
        if doc_url.lower().endswith(".pdf"):
            edital_link = doc_url
            break

    percursos = [
        fix_encoding((p.get("nome") or "").strip())
        for p in det.get("percursos") or []
        if (p.get("nome") or "").strip()
    ]

    precos = _montar_precos(det.get("precos_categorias"))
    json_precos = json.dumps(precos, ensure_ascii=False) if precos else "[]"

    partida = fix_encoding((det.get("partida") or "").strip())
    percurso = {"local_largada": partida} if partida else None
    percurso_json = json.dumps(percurso, ensure_ascii=False) if percurso else ""

    record = {
        "Nome do Evento": fix_encoding((det.get("titulo") or ev.get("eve_nome") or "").strip()),
        "Link de Inscrição": f"{BASE_URL}/new/{url_evento}",
        "Link da Imagem": (det.get("imagem_capa") or ev.get("imagem_capa") or "").strip(),
        "Data": format_date_string(det.get("data_evento") or ev.get("eve_data_evento") or ""),
        "Horário": (det.get("hora_evento") or ev.get("eve_hora") or "").replace(":", "h"),
        "Cidade": cidade,
        "Distância": ", ".join(percursos),
        "Organizador": "SmCrono",
        "Link do Edital": edital_link,
        "precos_entries": json_precos,
        "Percurso": percurso_json,
        "Kits": "",
    }
    edital_pdf = edital_link if edital_link.lower().endswith(".pdf") else None
    return record, edital_pdf


def _fetch_kits_parallel(events_data: list[dict], pending_kits: list[tuple[int, str]]) -> None:
    """Fetch kit PDFs in parallel and update events_data in place."""
    import concurrent.futures

    if not pending_kits:
        return
    logger.info(f"iniciando extração de kits para {len(pending_kits)} PDFs em paralelo...")

    def _kit_safe(args: tuple[int, str]):
        idx, url = args
        try:
            kits = extract_kits_from_pdf(url)
            return (idx, kits, None)
        except Exception as e:
            return (idx, None, e)

    t_kit = __import__("time").monotonic()
    max_workers = min(6, len(pending_kits))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_kit_safe, a): a for a in pending_kits}
        for fut in concurrent.futures.as_completed(futs):
            idx, kits, err = fut.result()
            if err is not None:
                logger.warning(f"kit falhou idx={idx}: {err}")
                kits = None
            kits_json = json.dumps(kits, ensure_ascii=False) if kits else ""
            events_data[idx]["Kits"] = kits_json

    logger.info(f"kits paralelos: {__import__('time').monotonic() - t_kit:.2f}s")


def get_smcrono_events_api(estado_filter="PB", somente_futuros=True):
    """Coleta eventos SmCrono via API da plataforma (paralelizado).

    somente_futuros descarta eventos cuja data (da lista ou dos detalhes)
    já passou — os detalhes são a fonte canônica quando divergirem.
    """
    t0_total = __import__("time").monotonic()

    eventos_lista = _load_events_json()
    logger.info(f"_load_events_json: {__import__('time').monotonic() - t0_total:.2f}s | {len(eventos_lista)} events in list"
    )

    candidates, pre_filtered = _filter_candidates(eventos_lista, estado_filter, somente_futuros)
    logger.info(f"pre-filter: {len(candidates)} candidates (+{pre_filtered} discarded before fetch)"
    )

    t_fetch = __import__("time").monotonic()
    fetched = _fetch_details_parallel(candidates)
    logger.info(f"fetch details: {__import__('time').monotonic() - t_fetch:.2f}s for {len(fetched)} events (workers={min(10, max(4, len(candidates) // 2)) if candidates else 1})"
    )

    events_data: list[dict] = []
    pending_kits: list[tuple[int, str]] = []

    for ev, det in fetched:
        if somente_futuros:
            data_final = det.get("data_evento") or ev.get("eve_data_evento") or ""
            dt_final = _parse_br_date(data_final) or _parse_br_date(ev.get("eve_data_evento") or "")
            if dt_final and dt_final < datetime.now():
                continue
        cidade, estado = _extrair_cidade_estado(det.get("local"), ev)
        if estado_filter and estado != estado_filter:
            continue

        record, edital_pdf = _build_event_record(ev, det)
        record["Cidade"] = cidade
        events_data.append(record)
        if edital_pdf:
            pending_kits.append((len(events_data) - 1, edital_pdf))
        logger.info(f"  [OK] {record['Data']} | Prices: {len(_montar_precos(det.get('precos_categorias') or []))} entries | {record['Nome do Evento'][:45]}"
        )

    _fetch_kits_parallel(events_data, pending_kits)

    logger.info(f"total get_smcrono_events_api: {__import__('time').monotonic() - t0_total:.2f}s | {len(events_data)} final events"
    )
    return events_data


def main():
    fieldnames = [
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
        "Percurso",
        "Kits",
    ]
    run_standard_scraper(
        lambda: get_smcrono_events_api(estado_filter="PB"),
        "eventos_smcrono.csv",
        "smcrono",
        fieldnames=fieldnames,
    )


if __name__ == "__main__":
    main()
