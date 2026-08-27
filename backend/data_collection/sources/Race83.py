import json
from typing import TypedDict, cast
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests
from data_collection.core.Driver import setup_driver
from data_collection.utils.PriceUtils import PriceEntry
from data_collection.core.ScraperCommon import (
    _as_object_list,
    _as_str_object_dict,
    fix_encoding,
    format_date_string,
    get_http_session,
    get_with_rate_limit,
    parse_date_string,
)
from selenium.common.exceptions import WebDriverException

BASE_URL = "https://www.race83.com.br"
ORGANIZADOR = "Race83"


def is_race83_domain(domain: str) -> bool:
    if not domain:
        return False
    return 'race83.com.br' in domain.lower()


def is_race83_listing_url(url: str) -> bool:
    if not url:
        return False
    try:
        p = urlparse(url)
        host = p.netloc.lower()
        path = p.path or ''
        return host.endswith('race83.com.br') and path.startswith('/eventos')
    except Exception:
        return False


def detect_redirects_to_listing(url: str, timeout: int = 5) -> tuple[bool, str]:
    try:
        resp = requests.get(url, timeout=timeout, allow_redirects=True)
        final = resp.url or url
        p = urlparse(final)
        if p.netloc and p.netloc.lower().endswith('race83.com.br') and p.path.startswith('/eventos'):
            return True, final
        return False, final
    except Exception:
        return False, url


def load_race83_soup(url: str, timeout: int = 5):
    driver = None
    created = False
    try:
        driver = setup_driver()
        created = True
        driver.get(url)
        time.sleep(1.0)
        final = driver.current_url or url
        p = urlparse(final)
        if p.netloc and p.netloc.lower().endswith('race83.com.br') and p.path.startswith('/eventos'):
            return None, created, driver

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        return soup, created, driver
    except WebDriverException:
        try:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            resp = requests.get(url, timeout=timeout)
            soup = BeautifulSoup(resp.text, 'html.parser')
            return soup, False, None
        except Exception:
            return None, False, None
    except Exception:
        try:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
        except Exception:
            pass
        return None, created, None

# ─── API dedicada (plataforma race83/smcrono) ────────────────────────────────
class EventoLista(TypedDict, total=False):
    """Item de listEventos (arquivo session/*_events.json)."""

    eve_id: int
    eve_nome: str
    eve_cidade: str
    eve_estado: str
    eve_data_evento: str
    eve_hora: str
    url_evento: str
    imagem_capa: str


class PrecoItem(TypedDict, total=False):
    valor: str
    categoria: str
    modalidade: str


class LotePrecos(TypedDict, total=False):
    lote_nome: str
    precos: list[PrecoItem]


class Documento(TypedDict, total=False):
    nome: str
    url: str


class Percurso(TypedDict, total=False):
    nome: str


class EventoDetalhes(TypedDict, total=False):
    """Resposta de api_evento.php."""

    titulo: str
    data_evento: str
    hora_evento: str
    local: str
    imagem_capa: str
    documentos: list[Documento]
    percursos: list[Percurso]
    precos_categorias: list[LotePrecos]


_session = get_http_session()


def _candidate_events_urls() -> list[str]:
    """URLs candidatas do JSON de eventos (arquivo datado gerado pela plataforma)."""
    urls: list[str] = []
    try:
        html = get_with_rate_limit(_session, BASE_URL, timeout=20)
        if html:
            m = re.search(r"url_arquivo_events\s*=\s*'([^']+)'", html.text)
            if m:
                urls.append(m.group(1))
    except Exception:
        pass
    for delta in (0, 1):
        dia = datetime.now() - timedelta(days=delta)
        urls.append(f"{BASE_URL}/session/{dia:%Y%m%d}_race83_events.json")
    return urls


def load_events_json() -> list[EventoLista]:
    """Carrega listEventos do arquivo JSON diário da plataforma."""
    for url in _candidate_events_urls():
        resp = get_with_rate_limit(_session, url, timeout=20)
        if resp is None:
            continue
        try:
            payload = _as_str_object_dict(cast("object", resp.json()))
            raw_list = _as_object_list((payload or {}).get("listEventos"))
            eventos = [cast("EventoLista", item) for item in raw_list]
        except Exception:
            continue
        if eventos:
            print(f"Lista carregada de {url}: {len(eventos)} eventos")
            return eventos
    return []


def fetch_event_details(url_evento: str) -> EventoDetalhes | None:
    """Detalhes estruturados via api_evento.php (preços, percursos, edital)."""
    """Detalhes estruturados de um evento via api_evento.php (preços, percursos, edital)."""
    resp = get_with_rate_limit(_session, f"{BASE_URL}/api_evento.php?url={url_evento}", timeout=20)
    if resp is None:
        return None
    try:
        det = cast("EventoDetalhes | None", _as_str_object_dict(cast("object", resp.json())))
        return det
    except Exception:
        return None


# Reparos conservadores para mojibake do banco da plataforma
# ('JoÃo' -> 'João', 'PraÇa' -> 'Praça', 'JosÉ' -> 'José').
# Nenhuma palavra portuguesa legítima contém esses padrões mistos.
_ORPHAN_MOJIBAKE = re.compile(r"Ã([oa])\b")
_MID_UPPER_CEDILLA = re.compile(r"(?<=[a-z])Ç(?=[a-z])")
_TRAIL_UPPER_ACUTE = re.compile(r"(?<=[a-z])É\b")


def _reparar(texto: str) -> str:
    texto = fix_encoding(texto)
    texto = _ORPHAN_MOJIBAKE.sub(r"ã\1", texto)
    texto = _MID_UPPER_CEDILLA.sub("ç", texto)
    texto = _TRAIL_UPPER_ACUTE.sub("é", texto)
    return texto


def _limpar_nome(nome: str) -> str:
    return _reparar(nome)


def _extrair_cidade(local: str, ev: EventoLista) -> str:
    m = re.match(r"^(.*?)\s*-\s*[A-Z]{2}\s*$", _reparar((local or "").strip()))
    if m:
        return m.group(1).strip()
    cidade = fix_encoding((ev.get("eve_cidade") or "").strip())
    return cidade.title() if cidade.isupper() else cidade


def _montar_precos(precos_categorias: list[LotePrecos]) -> list[str]:
    """Converte lotes/categorias da API em entradas legíveis ordenadas por preço."""
    from data_collection.utils.PriceUtils import parse_price_str

    lotes = precos_categorias or []
    multi_lote = len(lotes) > 1
    entradas: list[PriceEntry] = []
    vistos: set[tuple[float, str]] = set()

    for lote in lotes:
        lote_nome = str(lote.get("lote_nome") or "").strip()
        for p in lote.get("precos") or []:
            valor = (p.get("valor") or "").strip()
            preco = parse_price_str(valor)
            if not valor or preco is None:
                continue  # valor inexistente/ininteligível na plataforma
            partes = [x.strip() for x in (p.get("modalidade"), p.get("categoria")) if x and x.strip()]
            label = " — ".join(fix_encoding(x) for x in partes) or "Geral"
            if multi_lote and lote_nome:
                label = f"Lote {lote_nome}: {label}"

            chave = (preco, label)
            if chave in vistos:
                continue
            vistos.add(chave)
            entradas.append({"label": label, "price": preco, "formatted": fix_encoding(valor)})

    def _preco_num(x: PriceEntry) -> float:
        v = x.get("price")
        return float(v) if isinstance(v, (int, float)) else 0.0

    entradas.sort(key=_preco_num)
    return [f"{e['formatted']} | {e['label']}" for e in entradas]


def _event_slug(ev: EventoLista) -> str:
    slug = (ev.get("url_evento") or "").rstrip("/").split("/")[-1]
    return f"{ev.get('eve_id')}/{slug}" if slug and ev.get("eve_id") else ""


def get_race83_events(
    estado_filter: str = "PB", somente_futuros: bool = True
) -> list[dict[str, str]]:
    """Coleta completa dos eventos Race83 direto da API da plataforma.

    Retorna registros no schema padrão do projeto (Nome do Evento, precos_entries, ...),
    sem depender do listing do Brasil Que Corre nem de Selenium.
    """
    events_data: list[dict[str, str]] = []
    vistos: set[str] = set()

    for ev in load_events_json():
        nome_ref = ev.get("eve_nome", "?")
        try:
            api_url = _event_slug(ev)
            if not api_url or api_url in vistos:
                continue
            vistos.add(api_url)

            estado = (ev.get("eve_estado") or "").strip()[-2:].upper()
            if estado_filter and estado != estado_filter.upper():
                continue

            data_ev = ev.get("eve_data_evento") or ""
            data_parsed = parse_date_string(data_ev)
            if somente_futuros and data_parsed and data_parsed < datetime.now():
                continue

            print(f"Analisando: {nome_ref}")
            det = fetch_event_details(api_url)
            if not det:
                print("  -> detalhes indisponíveis")
                continue

            # Re-checa a data com o valor canônico dos detalhes (a lista às vezes erra)
            data_final = det.get("data_evento") or data_ev
            data_final_parsed = parse_date_string(data_final) or data_parsed
            if somente_futuros and data_final_parsed and data_final_parsed < datetime.now():
                print(f"  -> Ignorado: evento passado ({data_final})")
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
            precos = _montar_precos(det.get("precos_categorias") or [])
            nome = _limpar_nome((det.get("titulo") or "").strip()) or _limpar_nome(nome_ref)

            events_data.append(
                {
                    "Nome do Evento": nome,
                    "Link de Inscrição": f"{BASE_URL}/evento/{api_url}",
                    "Link da Imagem": (det.get("imagem_capa") or ev.get("imagem_capa") or "").strip(),
                    "Data": format_date_string(data_final),
                    "Horário": (det.get("hora_evento") or ev.get("eve_hora") or "").strip(),
                    "Cidade": _extrair_cidade(det.get("local") or "", ev),
                    "Distância": ", ".join(percursos),
                    "Organizador": ORGANIZADOR,
                    "Link do Edital": edital_link,
                    "precos_entries": json.dumps(precos, ensure_ascii=False) if precos else "[]",
                }
            )
            print(f"  [OK] {events_data[-1]['Data']} | Preços: {len(precos)} entradas")
        except Exception as e:
            print(f"  [ERRO]: {e} ({nome_ref})")
            continue

    return events_data
