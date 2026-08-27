import sys
import os
import csv
import re
import io
import json
from datetime import datetime, timedelta

import requests
from PyPDF2 import PdfReader
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_collection.core.ScraperCommon import MONTHS_PT, fix_encoding, format_date_string
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


def _extract_pdf_text(pdf_url):
    resp = SESSION.get(pdf_url, timeout=15)
    resp.raise_for_status()
    reader = PdfReader(io.BytesIO(resp.content))
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
        except (ValueError, KeyError):
            pass

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
        print(f"  [WARN] Erro ao extrair PDF ({pdf_url}): {e}")
        return None


def _candidate_events_urls():
    urls = []
    try:
        html = SESSION.get(f"{BASE_URL}/calendario-eventos", timeout=15).text
        m = re.search(r"url_arquivo_events\s*=\s*'([^']+)'", html)
        if m:
            urls.append(m.group(1))
    except Exception as e:
        print(f"[WARN] Shell do calendário indisponível: {e}")
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
                print(f"Lista carregada de {url}: {len(eventos)} eventos")
                return eventos
            print(f"[WARN] Lista vazia em {url}")
        except Exception as e:
            print(f"[WARN] Falha ao carregar {url}: {e}")
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
            except Exception:
                pass

            entradas.append({"label": label, "price": preco, "formatted": valor})

    entradas.sort(key=lambda x: x["price"])
    return [f"{e['formatted']} | {e['label']}" for e in entradas]


def get_smcrono_events_api(estado_filter="PB", somente_futuros=True):
    """Coleta eventos SmCrono via API da plataforma (paralelizado).

    somente_futuros descarta eventos cuja data (da lista ou dos detalhes)
    já passou — os detalhes são a fonte canônica quando divergirem.

    Otimizações:
    - Deduplicação e filtro de data antes de I/O
    - Fetch de detalhes em paralelo (ThreadPool)
    - Extração de kits (PDF) em paralelo
    """
    import concurrent.futures

    from datetime import datetime as _dt

    def _parse_br(s):
        try:
            d, m, a = (s or "").strip().split("/")
            return _dt(int(a), int(m), int(d))
        except Exception:
            return None

    t0_total = __import__("time").monotonic()

    eventos_lista = _load_events_json()
    print(f"[profile] _load_events_json: {__import__('time').monotonic() - t0_total:.2f}s | {len(eventos_lista)} eventos na lista")

    # --- Fase 1: deduplicação + filtro rápido antes de qualquer I/O ---
    candidatos = []
    vistos = set()
    pre_filtrados = 0
    for ev in eventos_lista:
        url_evento = (ev.get("url_evento") or "").strip("/")
        if not url_evento or url_evento in vistos:
            continue
        vistos.add(url_evento)
        # filtro de data usa apenas dado da lista (sem fetch)
        if somente_futuros:
            dl = ev.get("eve_data_evento") or ""
            dt = _parse_br(dl)
            if dt and dt < _dt.now():
                pre_filtrados += 1
                continue
        # pré-filtro por estado quando disponível no campo eve_estado (evita fetch desnecessário)
        if estado_filter:
            eve_estado_raw = (ev.get("eve_estado") or "").strip().upper()
            # eve_estado vem como " - PB" ou "PB"
            if eve_estado_raw and estado_filter.upper() not in eve_estado_raw:
                # mantém se campo vazio (fallback para det.local), senão pula
                if eve_estado_raw not in ("", "-", " -"):
                    # heurística: se contém UF diferente, provavelmente não é PB
                    m_uf = __import__("re").search(r"\b([A-Z]{2})\b", eve_estado_raw)
                    if m_uf and m_uf.group(1) != estado_filter.upper():
                        pre_filtrados += 1
                        continue
        candidatos.append(ev)

    print(f"[profile] pré-filtro: {len(candidatos)} candidatos (+{pre_filtrados} descartados antes de fetch)")

    # --- Fase 2: fetch de detalhes em paralelo ---
    t_fetch = __import__("time").monotonic()

    def _fetch_safe(ev):
        url_evento = (ev.get("url_evento") or "").strip("/")
        nome_ref = ev.get("eve_nome", "?")
        try:
            det = _fetch_event_details(url_evento)
            return (ev, det or {}, None)
        except Exception as e:
            return (ev, {}, e)

    max_workers_details = min(10, max(4, len(candidatos) // 2))
    fetched = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers_details) as ex:
        futs = {ex.submit(_fetch_safe, ev): ev for ev in candidatos}
        for fut in concurrent.futures.as_completed(futs):
            ev, det, err = fut.result()
            if err is not None:
                print(f"  [WARN] falha ao buscar detalhes {ev.get('eve_nome','?')}: {err}")
            fetched.append((ev, det))

    print(f"[profile] fetch detalhes: {__import__('time').monotonic() - t_fetch:.2f}s para {len(fetched)} eventos (workers={max_workers_details})")

    # --- Fase 3: processamento + filtro por estado/data final + coleta de kits ---
    events_data = []
    pendentes_kit = []  # [(idx, edital_link)]

    for ev, det in fetched:
        nome_ref = ev.get("eve_nome", "?")
        url_evento = (ev.get("url_evento") or "").strip("/")
        try:
            # re-valida data com dado canônico dos detalhes
            if somente_futuros:
                data_final = det.get("data_evento") or ev.get("eve_data_evento") or ""
                dt_final = _parse_br(data_final) or _parse_br(ev.get("eve_data_evento") or "")
                if dt_final and dt_final < _dt.now():
                    # print(f"  -> Ignorado: evento passado ({data_final}) [{nome_ref}]")
                    continue

            cidade, estado = _extrair_cidade_estado(det.get("local"), ev)
            if estado_filter and estado != estado_filter:
                # print(f"  -> Ignorado: Estado detectado '{estado}' [{nome_ref}]")
                continue

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
            json_precos_entries = json.dumps(precos, ensure_ascii=False) if precos else "[]"

            partida = fix_encoding((det.get("partida") or "").strip())
            percurso = {"local_largada": partida} if partida else None
            percurso_json = json.dumps(percurso, ensure_ascii=False) if percurso else ""

            idx = len(events_data)
            events_data.append(
                {
                    "Nome do Evento": fix_encoding(
                        (det.get("titulo") or ev.get("eve_nome") or "").strip()
                    ),
                    "Link de Inscrição": f"{BASE_URL}/new/{url_evento}",
                    "Link da Imagem": (
                        det.get("imagem_capa") or ev.get("imagem_capa") or ""
                    ).strip(),
                    "Data": format_date_string(
                        det.get("data_evento") or ev.get("eve_data_evento") or ""
                    ),
                    "Horário": (det.get("hora_evento") or ev.get("eve_hora") or "").replace(
                        ":", "h"
                    ),
                    "Cidade": cidade,
                    "Distância": ", ".join(percursos),
                    "Organizador": "SmCrono",
                    "Link do Edital": edital_link,
                    "precos_entries": json_precos_entries,
                    "Percurso": percurso_json,
                    "Kits": "",  # preenchido na fase paralela abaixo
                }
            )
            # mantém nome para log posterior ordenado
            if edital_link.lower().endswith(".pdf"):
                pendentes_kit.append((idx, edital_link))
            print(f"  [OK] {events_data[-1]['Data']} | Precos: {len(precos)} entradas | {events_data[-1]['Nome do Evento'][:45]}")
        except Exception as e:
            print(f"  [ERRO]: {e} ({nome_ref})")
            continue

    # --- Fase 4: extração de kits (PDF) em paralelo — gargalo mais pesado ---
    if pendentes_kit:
        t_kit = __import__("time").monotonic()
        print(f"[profile] iniciando extração de kits para {len(pendentes_kit)} PDFs em paralelo...")

        def _kit_safe(args):
            idx, url = args
            try:
                kits = extract_kits_from_pdf(url)
                return (idx, kits, None)
            except Exception as e:
                return (idx, None, e)

        max_workers_kits = min(6, len(pendentes_kit))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers_kits) as ex:
            futs = {ex.submit(_kit_safe, a): a for a in pendentes_kit}
            for fut in concurrent.futures.as_completed(futs):
                idx, kits, err = fut.result()
                if err is not None:
                    print(f"  [WARN] kit falhou idx={idx}: {err}")
                    kits = None
                kits_json = json.dumps(kits, ensure_ascii=False) if kits else ""
                events_data[idx]["Kits"] = kits_json

        print(f"[profile] kits paralelos: {__import__('time').monotonic() - t_kit:.2f}s")

    print(f"[profile] total get_smcrono_events_api: {__import__('time').monotonic() - t0_total:.2f}s | {len(events_data)} eventos finais")
    return events_data


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(base_dir, "data/eventos_smcrono.csv")

    events = get_smcrono_events_api(estado_filter="PB")

    if not events:
        print("Nenhum evento encontrado.")
        return

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

    print(f"\nTotal de {len(events)} eventos encontrados. Salvando no CSV...")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            delimiter=";",
            quoting=csv.QUOTE_ALL,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(events)

    print(f"\nSalvo com sucesso: {csv_path}")

    # Sincronização
    if not os.environ.get("CORREPB_COLLECT_ONLY"):
        try:
            from data_collection.utils import ImportToDB as sync_module

            sync_module.import_csv_to_mongodb(sync_module.remote_db, csv_path, "smcrono")
        except Exception as e:
            print(f"Sincronização ignorada: {e}")


if __name__ == "__main__":
    main()
