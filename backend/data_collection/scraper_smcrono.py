import sys
import os
import csv
import re
import io
import json
from datetime import datetime, timedelta

import requests
from PyPDF2 import PdfReader

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

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

MESES_EXTENSO = {
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


def fix_encoding(text):
    if not text:
        return ""
    try:
        return text.encode("latin1").decode("utf-8")
    except Exception:
        return text


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
                    (num for num, nome in MESES_EXTENSO.items() if nome.startswith(nome_mes[:3])),
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


def _formatar_data(data_str):
    """'30/08/2026' -> '30 de agosto de 2026'"""
    try:
        d, m, a = data_str.strip().split("/")
        return f"{int(d)} de {MESES_EXTENSO[int(m)]} de {int(a)}"
    except Exception:
        return data_str


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
    """Coleta eventos SmCrono via API da plataforma.

    somente_futuros descarta eventos cuja data (da lista ou dos detalhes)
    já passou — os detalhes são a fonte canônica quando divergirem.
    """
    from datetime import datetime as _dt

    def _parse_br(s):
        try:
            d, m, a = (s or "").strip().split("/")
            return _dt(int(a), int(m), int(d))
        except Exception:
            return None


    eventos_lista = _load_events_json()
    events_data = []
    vistos = set()

    for ev in eventos_lista:
        nome_ref = ev.get("eve_nome", "?")
        try:
            url_evento = (ev.get("url_evento") or "").strip("/")
            if not url_evento or url_evento in vistos:
                continue
            vistos.add(url_evento)

            data_lista = ev.get("eve_data_evento") or ""
            if somente_futuros and _parse_br(data_lista) and _parse_br(data_lista) < _dt.now():
                continue

            print(f"Analisando: {nome_ref}")
            det = _fetch_event_details(url_evento)
            if det is None:
                det = {}

            if somente_futuros:
                data_final = det.get("data_evento") or data_lista
                dt_final = _parse_br(data_final) or _parse_br(data_lista)
                if dt_final and dt_final < _dt.now():
                    print(f"  -> Ignorado: evento passado ({data_final})")
                    continue


            cidade, estado = _extrair_cidade_estado(det.get("local"), ev)
            if estado_filter and estado != estado_filter:
                print(f"  -> Ignorado: Estado detectado '{estado}'")
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

            kits = extract_kits_from_pdf(edital_link)
            kits_json = json.dumps(kits, ensure_ascii=False) if kits else ""

            partida = fix_encoding((det.get("partida") or "").strip())
            percurso = {"local_largada": partida} if partida else None
            percurso_json = json.dumps(percurso, ensure_ascii=False) if percurso else ""

            events_data.append(
                {
                    "Nome do Evento": fix_encoding(
                        (det.get("titulo") or ev.get("eve_nome") or "").strip()
                    ),
                    "Link de Inscrição": f"{BASE_URL}/new/{url_evento}",
                    "Link da Imagem": (
                        det.get("imagem_capa") or ev.get("imagem_capa") or ""
                    ).strip(),
                    "Data": _formatar_data(
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
                    "Kits": kits_json,
                }
            )
            print(f"  [OK] {events_data[-1]['Data']} | Precos: {len(precos)} entradas")
        except Exception as e:
            print(f"  [ERRO]: {e} ({nome_ref})")
            continue

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
