import json
import logging
import os
import sys
import re
import threading
import time
from collections.abc import Sequence
from typing import cast
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup, Tag

# O domínio brasilquecorre.com publica um certificado SSL inválido; as coletas para
# ele usam verify=False e o aviso de conexão insegura é suprimido intencionalmente.
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

# Registro de evento no schema CSV — todos os valores são strings
EventInfo = dict[str, str]
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_collection.core.Driver import setup_driver
from data_collection.core.ScraperCommon import (
    _as_object_list,
    _as_str_object_dict,
    entries_to_json,
    get_http_session,
    get_with_rate_limit,
    sync_csv_to_mongodb,
    write_events_csv,
)
from selenium.webdriver.remote.webdriver import WebDriver
from data_collection.sources.Nightrun import (
    extract_nightrun_ticket_prices,
    is_nightrun_domain,
    load_nightrun_soup,
)
from data_collection.sources.Race83 import is_race83_listing_url
from data_collection.sources.Sympla import (
    extract_sympla_ticket_prices,
    is_sympla_domain,
    load_sympla_soup,
)
from data_collection.sources.Ticketsports import (
    extract_ticketsports_schedule,
    extract_ticketsports_ticket_prices,
    is_ticketsports_domain,
    load_ticketsports_soup,
)
from data_collection.utils.PriceUtils import PriceEntry, fmt_entry, parse_price_str
from data_collection.utils.PrizeDetection import entry_is_prize


def _get_http_session():
    """Sessão HTTP compartilhada com retry automático e User-Agent (ver ScraperCommon)."""
    return get_http_session()


_global_session = _get_http_session()

# Timeout como tupla (conexão, leitura): falha rápido em servidor inacessível
# sem cortar downloads lentos porém saudáveis.
_HTTP_TIMEOUT = (6, 12)


def _get_with_rate_limit(
    url: str,
    timeout: int | tuple[int, int] = 10,
    verify: bool = True,
) -> requests.Response | None:
    """GET com retry automático e rate limiting por domínio (thread-safe).

    `timeout` aceita int ou tupla (conexão, leitura) — repassado ao requests.
    """
    return get_with_rate_limit(_global_session, url, timeout=timeout, verify=verify)


def _safe_quit(driver: WebDriver | None) -> None:
    """Fecha o driver Selenium sem propagar exceções."""
    try:
        if driver:
            driver.quit()
    except Exception:
        pass


def _strip_accents(s: str | None) -> str:
    """Remove acentos/diacríticos de uma string para buscas normalizadas."""
    import unicodedata

    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if not unicodedata.category(ch).startswith("M"))


def _normalize_time(raw_time: str) -> str:
    """Normaliza uma string de hora (ex: '4h30', '04:30', '4:30') para 'HH:MM'. Retorna '' se inválida."""
    if not raw_time:
        return ""
    normalized = raw_time.replace("h", ":").replace("H", ":")
    if ":" in normalized:
        parts = normalized.split(":")
        hour = parts[0]
        minute = parts[1] if len(parts) > 1 and parts[1] else "00"
    else:
        hour = normalized
        minute = "00"
    try:
        h = int(hour)
        m = int(minute)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
    except Exception:
        return ""
    return ""


def extract_time_from_text(text: str) -> str:
    """Tenta extrair um horário HH:MM a partir de vários padrões no texto.

    Padrões suportados (ordem de preferência):
    - DD/MM/YYYY - HH:MM
    - DD de <mês> de YYYY às HH:MM (com meses por extenso, acentuados ou não)
    - labels como 'HORÁRIO', 'LARGADA', 'SAÍDA' próximos a um horário
    - padrões genéricos HH:MM ou HhMM
    """
    import re

    if not text:
        return ""

    # 1) DD/MM/YYYY - HH:MM
    m = re.search(
        r"\b\d{1,2}/\d{1,2}/\d{4}\s*[-–—]\s*(\d{1,2}(?:[:hH]\d{2})?)(?:\s*[hH])?\b",
        text,
    )
    if m:
        out = _normalize_time(m.group(1))
        if out:
            return out

    # Normaliza para procurar meses por extenso e 'às'
    norm = _strip_accents(text).lower()

    # 2) '14 de março de 2026 às 17:00' (procura 'as' após remoção de acentos)
    m = re.search(r"\b\d{1,2}\s+de\s+[a-z]+\s+de\s+\d{4}\s*as\s*(\d{1,2}(?:[:hH]\d{2})?)", norm)
    if m:
        out = _normalize_time(m.group(1))
        if out:
            return out

    # 3) '<b>HORÁRIO</b>: 04h00' e variações
    m = re.search(r"horario[^\d]{0,30}(\d{1,2})\s*[:hH]\s*(\d{0,2})", norm)
    if m:
        hh = m.group(1)
        mm = m.group(2) or "00"
        out = _normalize_time(f"{hh}:{mm}")
        if out:
            return out

    # 4) 'LARGADA'/'SAIDA' context (usa texto original para preservar formatos)
    m = re.search(r"(?:largada|saida)[^0-9]{0,20}(\d{1,2}(?:[:hH]\d{2})?)", text, re.IGNORECASE)
    if m:
        out = _normalize_time(m.group(1))
        if out:
            return out

    # 5) 'às HH:MM' em texto normalizado
    m = re.search(r"\bas\s*(\d{1,2}(?:[:hH]\d{2})?)", norm)
    if m:
        out = _normalize_time(m.group(1))
        if out:
            return out

    # 6) fallback: primeiro HH:MM encontrado
    m = re.search(r"\b(\d{1,2}[:hH]\d{2})\b", text)
    if m:
        out = _normalize_time(m.group(1))
        if out:
            return out

    return ""


def _collect_jsonld_price_entries(soup: BeautifulSoup, candidates: list[PriceEntry]) -> None:
    """Extrai preços de blocos JSON-LD (schema.org), cuja estrutura é arbitrária."""
    json_ld_scripts: list[Tag] = soup.find_all("script", type="application/ld+json")
    for script in json_ld_scripts:
        try:
            payload = cast("object", json.loads(script.string or script.get_text() or "{}"))
        except Exception:
            continue

        items = _as_object_list(payload)

        for raw_item in items:
            item = _as_str_object_dict(raw_item)
            if item is None:
                continue

            offers_obj = item.get("offers") or item.get("priceSpecification")
            offers_list: list[object] | None = None
            offers_list = (
                cast("list[object]", offers_obj) if isinstance(offers_obj, list) else None
            )
            if offers_list is None:
                single_offer = _as_str_object_dict(cast("object", offers_obj))
                if single_offer is not None:
                    offers_list = [single_offer]

            if offers_list:
                for raw_off in offers_list:
                    off = _as_str_object_dict(raw_off)
                    if off is None:
                        continue
                    price = off.get("price") or off.get("priceSpecification") or off.get("priceCurrency")
                    if price:
                        v = parse_price_str(str(price))
                        name = item.get("name")
                        if v is not None:
                            candidates.append(
                                {"label": str(name) if name else None, "price": v, "tax": None, "raw": "ldjson"}
                            )

            direct_price = item.get("price")
            if direct_price:
                v = parse_price_str(str(direct_price))
                name = item.get("name")
                if v is not None:
                    candidates.append(
                        {"label": str(name) if name else None, "price": v, "tax": None, "raw": "ldjson-price"}
                    )



def _price_sort_key(e: PriceEntry) -> float:
    price = e.get("price")
    return float(price) if isinstance(price, (int, float)) else 0.0


def _ensure_fields(evt: EventInfo, **defaults: str) -> None:
    """Preenche chaves ausentes/vazias de um registro de evento."""
    for key, value in defaults.items():
        if not evt.get(key):
            evt[key] = value


# Extração de preços
def extract_price_entries(
    soup: BeautifulSoup,
    domain: str,
    driver: WebDriver | None = None,
) -> Sequence[PriceEntry | str]:
    """
    Retorna uma lista de entradas de preço estruturadas encontradas na página.

    Cada entrada é um dict ou uma string formatada. Em casos específicos (ex: NightRun), o extractor
    pode devolver diretamente valores como '5KM - 69,90'.

    NOTA: page_html é criado sob demanda (lazy) para evitar duplicar memória do objeto soup
    inteiro, e é deletado após uso para permitir garbage collection.
    """
    candidates: list[PriceEntry] = []

    # Extractors site-specific: se o domínio corresponder, usa-o imediatamente
    try:
        if domain:
            if is_sympla_domain(domain):
                return extract_sympla_ticket_prices(soup)
            if is_ticketsports_domain(domain):
                # Ticketsports normalmente usa seu próprio loader/flow; keep generic fallback
                return extract_ticketsports_ticket_prices(soup)
            if is_nightrun_domain(domain) and driver:
                raw_prices = extract_nightrun_ticket_prices(driver)
                if raw_prices:
                    return raw_prices
    except Exception:
        # Se o extractor específico falhar, segue com heurísticas genéricas abaixo
        pass

    # Elementos de preço por classe
    def has_price_class(classes: str | list[str] | None) -> bool:
        if not classes:
            return False
        cls_list = [classes] if isinstance(classes, str) else list(classes)
        for c in cls_list:
            try:
                cl = c.lower()
            except Exception:
                continue
            if "price" in cl or "preco" in cl or "valor" in cl or "kit-price" in cl:
                return True
        return False

    price_elements: list[Tag] = soup.find_all(["span", "div", "p"], class_=has_price_class)
    for elem in price_elements:
        txt = elem.get_text(separator=" ", strip=True)
        for m in re.finditer(r"R\$(?:\s|\xa0|&nbsp;)*([\d.,]+)", txt):
            v = parse_price_str(m.group(1))
            tax = None
            tax_m = re.search(r"\(\s*\+?([\d.,]+)\s*(?:taxa|tax|fee)\s*\)", txt, re.IGNORECASE)
            if tax_m:
                tax = parse_price_str(tax_m.group(1))
            candidates.append({"label": None, "price": v, "tax": tax, "raw": txt})

    # Detecta elementos com font-size inline grande que contêm R$
    try:
        for elem in soup.find_all(["span", "div", "p"]):
            style = str(elem.get("style") or "")
            if "font-size" in style and "R$" in elem.get_text():
                m_px = re.search(r"font-size\s*:\s*(\d+)px", style)
                if m_px and int(m_px.group(1)) >= 20:
                    txt2 = elem.get_text(separator=" ", strip=True)
                    for m in re.finditer(r"R\$(?:\s|\xa0|&nbsp;)*([\d.,]+)", txt2):
                        v = parse_price_str(m.group(1))
                        candidates.append({"label": None, "price": v, "tax": None, "raw": txt2})
    except Exception:
        pass

    # Tabelas e tbodies (trata cabeçalhos de seção com colspan e preço na primeira td)
    try:
        blocks: list[Tag] = soup.find_all(["table", "tbody"])
        for table in blocks:
            current_section: str | None = None
            for tr in table.find_all("tr"):
                tds: list[Tag] = tr.find_all(["td", "th"])
                if len(tds) == 1 and tds[0].has_attr("colspan"):
                    sec_text = re.sub(r"\s+", " ", tds[0].get_text(separator=" ", strip=True)).strip()
                    current_section = sec_text
                    continue
                if len(tds) >= 2:
                    left_text = tds[0].get_text(separator=" ", strip=True)
                    right_text = tds[1].get_text(separator=" ", strip=True)
                    left_has_price = bool(re.search(r"R\$", left_text))
                    right_has_price = bool(re.search(r"R\$", right_text))
                    if left_has_price and not right_has_price:
                        label = right_text or None
                        if current_section and label and current_section not in label:
                            label = f"{current_section} — {label}"
                        elif current_section and not label:
                            label = current_section
                        for m in re.finditer(r"R\$(?:\s|\xa0|&nbsp;)*([\d.,]+)", left_text):
                            candidates.append(
                                {
                                    "label": label,
                                    "price": parse_price_str(m.group(1)),
                                    "tax": None,
                                    "raw": f"{left_text} | {right_text}",
                                }
                            )
                    elif right_has_price and not left_has_price:
                        label = left_text or None
                        if current_section and label and current_section not in label:
                            label = f"{current_section} — {label}"
                        elif current_section and not label:
                            label = current_section
                        for m in re.finditer(r"R\$(?:\s|\xa0|&nbsp;)*([\d.,]+)", right_text):
                            candidates.append(
                                {
                                    "label": label,
                                    "price": parse_price_str(m.group(1)),
                                    "tax": None,
                                    "raw": f"{left_text} | {right_text}",
                                }
                            )
                    else:
                        # fallback: extrai qualquer preço na linha e tenta associar um label próximo
                        rowtxt = tr.get_text(separator=" ", strip=True)
                        fallback_label: str | None = None
                        if left_text and not re.search(r"R\$", left_text):
                            fallback_label = left_text
                            if current_section and current_section not in fallback_label:
                                fallback_label = f"{current_section} — {fallback_label}"
                        elif right_text and not re.search(r"R\$", right_text):
                            fallback_label = right_text
                            if current_section and current_section not in fallback_label:
                                fallback_label = f"{current_section} — {fallback_label}"
                        for m in re.finditer(r"R\$(?:\s|\xa0|&nbsp;)*([\d.,]+)", rowtxt):
                            candidates.append(
                                {"label": fallback_label, "price": parse_price_str(m.group(1)), "tax": None, "raw": rowtxt}
                            )
    except Exception:
        pass

    # Dados estruturados e atributos: meta tags, atributos data-price, JSON-LD
    try:
        # Meta tags
        metas: list[Tag] = soup.find_all("meta")
        for meta in metas:
            prop = str(meta.get("property") or meta.get("name") or "").lower()
            content = str(meta.get("content") or "")
            if prop in ("product:price:amount", "price", "og:price:amount") or "price" in prop:
                if content:
                    v = parse_price_str(content)
                    if v is not None:
                        candidates.append(
                            {
                                "label": None,
                                "price": v,
                                "tax": None,
                                "raw": f"meta:{prop}:{content}",
                            }
                        )

        # Atributos data como data-price, data-preco, data-value
        all_tags: list[Tag] = soup.find_all(True)
        for elem in all_tags:
            for attr, val in elem.attrs.items():
                attr_name = str(attr)
                if re.search(r"data[-_]?(price|preco|valor|value)", attr_name, re.IGNORECASE):
                    v = parse_price_str(str(val))
                    if v is not None:
                        text = elem.get_text(separator=" ", strip=True)
                        label: str | None = text if (text and "R$" not in text) else None
                        candidates.append(
                            {
                                "label": label,
                                "price": v,
                                "tax": None,
                                "raw": f"{attr_name}={val}",
                            }
                        )

        _collect_jsonld_price_entries(soup, candidates)
    except Exception:
        pass

    # Fallbacks: R$ genérico, 'reais', faixas — apenas após parsing estruturado
    # Cria page_html apenas quando necessário para evitar duplicar memória do objeto soup inteiro
    page_html = str(soup)
    try:
        for m in re.finditer(r"R\$(?:&nbsp;|\s)*([\d.,]+)", page_html):
            v = parse_price_str(m.group(1))
            if v is not None:
                candidates.append({"label": None, "price": v, "tax": None, "raw": m.group(1)})
        for m in re.finditer(r"([\d.,]+)\s*reais", page_html, re.IGNORECASE):
            v = parse_price_str(m.group(1))
            if v is not None:
                candidates.append({"label": None, "price": v, "tax": None, "raw": m.group(1)})

        def _add_range(match: re.Match[str]) -> None:
            """Adiciona preços de uma faixa 'X a Y', evitando índices falsos (ex: '1-159,90')."""
            a, b = match.group(1), match.group(2)
            va, vb = parse_price_str(a), parse_price_str(b)
            a_has_dec = "," in a or "." in a
            b_has_dec = "," in b or "." in b
            if va is not None and not (va < 10 and not a_has_dec and b_has_dec):
                candidates.append({"label": None, "price": va, "tax": None, "raw": f"{a}-{b}"})
            if vb is not None and not (vb < 10 and not b_has_dec and a_has_dec):
                candidates.append({"label": None, "price": vb, "tax": None, "raw": f"{a}-{b}"})

        faixas: tuple[str, ...] = (
            r"R\$\s*([\d.,]+)\s*(?:a|até|-)\s*(?:R\$)?\s*([\d.,]+)",
            r"(?:R\$)?\s*([\d.,]+)\s*(?:a|até|-)\s*R\$\s*([\d.,]+)",
        )
        for faixa in faixas:
            for match in re.finditer(faixa, page_html, re.IGNORECASE):
                _add_range(match)
    except Exception:
        # Se regex fallback falhar, continua avec autres testes
        pass

    # Após coletar candidatos, filtra valores de prêmios/premiações usando verificação contextual
    candidates = [e for e in candidates if not entry_is_prize(e, page_html)]

    # Se temos preços rotulados de tabelas/grids estruturados, prefere eles e descarta duplicatas não rotuladas
    labeled_prices: set[float | None] = {e.get("price") for e in candidates if e.get("label")}
    if labeled_prices:
        candidates = [
            e
            for e in candidates
            if not (e.get("label") is None and e.get("price") in labeled_prices)
        ]

    # Filtra preços de inscrição plausíveis; rastreia descartados para debug
    discarded_prices: list[PriceEntry] = []
    valid_entries: list[PriceEntry] = []

    for e in candidates:
        price = e.get("price")

        if price is None:
            # Valores None são esperados, apenas continua
            continue

        # Verifica se preço está fora do intervalo válido
        if not (0 <= price <= 500):
            discarded_prices.append(
                {
                    "price": price,
                    "label": e.get("label"),
                    "raw": e.get("raw"),
                    "reason": "fora do intervalo [0, 500]",
                }
            )
            # Log se preço é negativo (possível bug de parsing)
            if price < 0:
                logger.warning(
                    f"Preco negativo descartado: {e}. Possivelmente bug em parse_price_str()."
                )
            continue

        valid_entries.append(e)

    # Log resumo se muitos preços foram descartados
    if discarded_prices and len(discarded_prices) > len(valid_entries):
        logger.info(
            f"Descartados {len(discarded_prices)} precos invalidos contra {len(valid_entries)} validos. Precos descartados: {discarded_prices[:3]}"
        )

    # Se há preços pagos, exclui entradas gratuitas (0.00) para evitar falsos positivos
    if any((e["price"] or 0) > 0 for e in valid_entries):
        valid_entries = [e for e in valid_entries if (e["price"] or 0) > 0]

    if not valid_entries:
        # Se não há preços pagos, verifica indicadores de gratuito
        if re.search(
            r"\b(grátis|gratis|gratuito|gratuita|isento|free)\b",
            page_html,
            re.IGNORECASE,
        ):
            return [
                PriceEntry(
                    {
                        "label": None,
                        "price": 0.0,
                        "tax": None,
                        "formatted": "R$ 0,00",
                        "raw": page_html,
                    }
                )
            ]
        # Entrada informativa para o campo legível exibir 'Valor não encontrado'.
        return [
            PriceEntry(
                {
                    "label": None,
                    "price": None,
                    "tax": None,
                    "formatted": "Valor não encontrado",
                    "raw": page_html,
                }
            )
        ]

    # Deduplica por (label, price, tax)
    seen: set[tuple[str, float, float | None]] = set()
    unique: list[PriceEntry] = []
    for e in valid_entries:
        raw_price = e.get("price")
        raw_tax = e.get("tax")
        price_f = float(raw_price) if isinstance(raw_price, (int, float)) else 0.0
        tax_f = float(raw_tax) if isinstance(raw_tax, (int, float)) else None
        key: tuple[str, float, float | None] = (
            e.get("label") or "",
            price_f,
            tax_f,
        )
        if key not in seen:
            seen.add(key)
            unique.append(e)

    # Ordena por preço crescente
    unique_sorted = sorted(unique, key=_price_sort_key)

    result: list[PriceEntry] = [fmt_entry(e) for e in unique_sorted]

    # Libera memória de page_html se foi criado
    if "page_html" in locals():
        del page_html

    return result


# Extração de edital
def extract_edital(url: str, soup: BeautifulSoup | None = None) -> str:
    """Extrai o link do edital. Reusa o soup já carregado quando disponível
    (evita refazer o fetch da mesma página)."""
    try:
        if soup is None:
            response = _get_with_rate_limit(url, timeout=10)
            if not response:
                return "edital não encontrado"
            soup = BeautifulSoup(response.text, "html.parser")

        domain = urlparse(url).netloc

        if "zeniteesportes.com" in domain:
            # Procura por links com texto "regulamento"
            reg_links = [
                a
                for a in soup.find_all("a")
                if re.search(r"regulamento", a.get_text() or "", re.IGNORECASE)
            ]
            for link in reg_links:
                onclick = str(link.get("onclick") or "")
                if ".pdf" in onclick.lower():
                    pdf_match = re.search(r"abrirPDF\('([^']+)'\)", onclick)
                    if pdf_match:
                        return pdf_match.group(1)
                href = str(link.get("href") or "")
                if ".pdf" in href.lower():
                    return href

            # Busca genérica por links PDF
            pdf_links = soup.find_all("a", href=re.compile(r"\.pdf", re.IGNORECASE))
            if pdf_links:
                return str(pdf_links[0].get("href") or "")

        elif "race83.com.br" in domain or "correparaiba.com" in domain:
            pdf_link = soup.find("a", href=re.compile(r"\.pdf", re.IGNORECASE))
            if pdf_link:
                return str(pdf_link.get("href") or "")

        return "edital não encontrado"
    except Exception:
        return "edital não encontrado"


# PROCESSAMENTO PARALELO DE DETALHES DOS EVENTOS
# Fontes com scraper dedicado próprio — ver scraper_race83.py,
# scraper_zenite.py e scraper_smcrono.py
FONTES_COM_SCRAPER_DEDICADO = (
    "race83.com.br",
    "zeniteesportes.com",
    "smcrono.com.br",
    "circuitodasestacoes.com",
)

_SELENIUM_SOURCE_CHECKS = (
    is_sympla_domain,
    is_ticketsports_domain,
    is_nightrun_domain,
)

# Cada driver Chrome consome ~250MB; 2 instâncias paralelas equilibram ganho e custo.
SELENIUM_MAX_DRIVERS = 2


def _is_selenium_source(domain: str) -> bool:
    """Fontes cujas páginas exigem JavaScript real para expor preços/detalhes."""
    return any(check(domain) for check in _SELENIUM_SOURCE_CHECKS)



def _fetch_details_http(event_info: EventInfo) -> EventInfo | None:
    """Enriquece um evento cuja página é server-side rendered (requests puro)."""
    evt = dict(event_info)
    url = evt.get("link_inscricao", "") or ""
    if not url:
        _ensure_fields(evt, link_edital="edital não encontrado", precos_entries="[]")
        return evt

    horario = (evt.get("horario") or "").strip()
    try:
        response = _get_with_rate_limit(url, timeout=_HTTP_TIMEOUT)
        soup = BeautifulSoup(response.text, "html.parser") if response else None

        if soup:
            try:
                evt["link_edital"] = extract_edital(url, soup=soup)
            except Exception:
                evt["link_edital"] = "edital não encontrado"

            if not horario:
                try:
                    extracted = extract_time_from_text(soup.get_text(" ", strip=True))
                    if extracted:
                        horario = extracted
                except Exception:
                    pass

            entries: Sequence[PriceEntry | str] = ()
            try:
                entries = extract_price_entries(soup, urlparse(url).netloc)
            except Exception:
                entries = ()
            evt["precos_entries"] = entries_to_json(entries)
        else:
            evt["link_edital"] = "edital não encontrado"
            evt["precos_entries"] = "[]"

        if horario:
            evt["horario"] = horario
        return evt
    except Exception:
        _ensure_fields(evt, link_edital="edital não encontrado", precos_entries="[]")
        return evt


def _fetch_details_selenium(event_info: EventInfo, driver: WebDriver | None) -> EventInfo | None:
    """Enriquece um evento usando fonte que exige JavaScript, reaproveitando o driver."""
    evt = dict(event_info)
    url = evt.get("link_inscricao", "") or ""
    if not url:
        _ensure_fields(evt, link_edital="edital não encontrado", precos_entries="[]")
        return evt

    domain = urlparse(url).netloc
    horario = (evt.get("horario") or "").strip()
    soup = None
    try:
        if is_sympla_domain(domain):
            soup, _, _ = load_sympla_soup(url, driver=driver)
        elif is_ticketsports_domain(domain):
            soup, _, _, loader_horario = load_ticketsports_soup(
                url, driver=driver, wait_seconds=30, debug=False
            )
            horario = horario or loader_horario
        elif is_nightrun_domain(domain):
            soup, _, _, nightrun_schedule = load_nightrun_soup(url, driver=driver, wait_seconds=30)
            horario = horario or nightrun_schedule
    except Exception:
        soup = None

    try:
        if soup:
            try:
                evt["link_edital"] = extract_edital(url, soup=soup)
            except Exception:
                evt["link_edital"] = "edital não encontrado"

            try:
                if is_ticketsports_domain(domain) and not horario:
                    horario = extract_ticketsports_schedule(soup)
                if not horario:
                    extracted = extract_time_from_text(soup.get_text(" ", strip=True))
                    if extracted:
                        horario = extracted
            except Exception:
                pass

            try:
                entries = (
                    extract_ticketsports_ticket_prices(soup, debug=False)
                    if is_ticketsports_domain(domain)
                    else extract_price_entries(soup, domain, driver)
                )
            except Exception:
                entries = []
            evt["precos_entries"] = entries_to_json(entries)
        else:
            evt["link_edital"] = "edital não encontrado"
            evt["precos_entries"] = "[]"

        if horario:
            evt["horario"] = horario
        return evt
    except Exception:
        _ensure_fields(evt, link_edital="edital não encontrado", precos_entries="[]")
        return evt


def process_event_details(events: list[EventInfo]) -> list[EventInfo]:
    """Enriquece eventos com edital/preços/horário das páginas de inscrição.

    Estratégia de concorrência:
    - Fontes com scraper dedicado são puladas (coletadas pelos scrapers próprios)
    - Grupo HTTP (server-side): paralelo com ThreadPoolExecutor + rate limit por domínio
    - Grupo Selenium: driver ÚNICO criado uma vez (fail-fast: se o Chrome não subir,
      todos os eventos JS são degradados na hora, sem re-tentativa por evento) e
      processado em thread própria, EM PARALELO com o grupo HTTP
    """
    if not events:
        return []

    dedicadas: list[EventInfo] = []
    restantes: list[EventInfo] = []
    for ev in events:
        dom = urlparse(ev.get("link_inscricao", "")).netloc
        if any(d in dom for d in FONTES_COM_SCRAPER_DEDICADO):
            dedicadas.append(ev)
        else:
            restantes.append(ev)
    for ev in dedicadas:
        print(f"[SKIP] {ev.get('nome', '')} — coletado por scraper dedicado")

    http_events: list[EventInfo] = []
    selenium_events: list[EventInfo] = []
    for ev in restantes:
        dom = urlparse(ev.get("link_inscricao", "")).netloc
        if _is_selenium_source(dom):
            selenium_events.append(ev)
        else:
            http_events.append(ev)

    processed: list[EventInfo] = []
    lock = threading.Lock()

    def _run_selenium_group():
        """Processa eventos JS com um pool pequeno de drivers em paralelo.

        Cada worker cria seu próprio driver UMA vez (fail-fast: se o Chrome não
        subir, todos os eventos do worker são degradados na hora, sem re-tentativa).
        """
        if not selenium_events:
            return

        n_drivers = max(1, min(SELENIUM_MAX_DRIVERS, len(selenium_events)))
        chunks = [c for c in (selenium_events[i::n_drivers] for i in range(n_drivers)) if c]

        def _worker(chunk: list[EventInfo], worker_id: int) -> None:
            try:
                shared_driver = setup_driver()
            except Exception as e:
                print(
                    f"[WARN] Selenium indisponível (worker {worker_id}: {e}); {len(chunk)} evento(s) sem detalhes JS"
                )
                for event in chunk:
                    event = dict(event)
                    event["link_edital"] = "edital não encontrado"
                    event["precos_entries"] = "[]"
                    with lock:
                        processed.append(event)
                return

            total = len(chunk)
            for idx, event in enumerate(chunk, 1):
                try:
                    result = _fetch_details_selenium(dict(event), shared_driver)
                    if result is None:
                        continue
                    with lock:
                        processed.append(result)
                    print(f"[w{worker_id} {idx}/{total}] OK {result.get('nome', '')}")
                except Exception:
                    logger.exception(f"Erro ao processar evento: {event.get('nome', 'N/A')}")
                    event = dict(event)
                    event["link_edital"] = "edital não encontrado"
                    event["precos_entries"] = "[]"
                    with lock:
                        processed.append(event)
            _safe_quit(shared_driver)

        threads = [
            threading.Thread(target=_worker, args=(chunk, i + 1), daemon=True)
            for i, chunk in enumerate(chunks)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    selenium_thread = threading.Thread(
        target=_run_selenium_group, name="selenium-details", daemon=True
    )
    selenium_thread.start()

    # Grupo HTTP roda enquanto o Selenium trabalha em paralelo
    if http_events:
        with ThreadPoolExecutor(max_workers=min(8, len(http_events))) as pool:
            for result in pool.map(_fetch_details_http, http_events):
                if result:
                    with lock:
                        processed.append(result)

    selenium_thread.join()
    return processed


# EXTRAÇÃO DE DADOS DOS EVENTOS
BQC_LISTING_URL = "https://brasilquecorre.com/paraiba"

_BQC_SSL_VERIFY = False  # certificado do domínio é inválido (ver comentário nos imports)

_DATA_PATTERN = re.compile(r"\d{1,2}\s+de\s+[A-Za-zçÇ]+\s+de\s+\d{4}", re.IGNORECASE)
_DISTANCE_TERMS = ["(corrida", "(caminhada", "(trail", "(ultra", "(infantil"]


def _is_distance_text(text: str) -> bool:
    """Reconhece parágrafos de distância como '5km e 10km (corrida)' ou '15km (corrida - uphill)'."""
    lowered = text.lower()
    return any(term in lowered for term in _DISTANCE_TERMS)


def _fetch_bqc_listing_html(attempts: int = 3) -> str | None:
    """Baixa o HTML da listagem de eventos com tentativas múltiplas."""
    html = None
    for attempt in range(1, attempts + 1):
        response = _get_with_rate_limit(BQC_LISTING_URL, timeout=30, verify=_BQC_SSL_VERIFY)
        if response is not None:
            html = response.text
            break
        print(f"[get_event_data] Tentativa {attempt} falhou ao baixar a listagem")
        time.sleep(2)
    return html


def _extract_bqc_event_info(box: Tag) -> EventInfo | None:
    """Extrai os dados básicos de um box de evento da listagem do Brasil Que Corre.

    A listagem é renderizada server-side, contendo por evento:
    - h5 > a: nome e link de inscrição
    - img.cs-chosen-image: imagem
    - div.text-editor > p: data, cidade, distâncias e organizador

    Retorna dict com os campos ou None se o box não for um evento.
    """
    name_element = box.select_one("h5 a")
    if not name_element:
        return None

    event_info: EventInfo = {}
    link_inscricao = str(name_element.get("href") or "").strip()
    event_info["nome"] = name_element.get_text(strip=True)

    # Ignorar URLs redirecionadas/que não são de evento
    if link_inscricao.startswith("https://www.liverun.com.br/calendario"):
        print(f"[SKIP] Pulando link de calendário genérico do Liverun: {link_inscricao}")
        return None
    if is_race83_listing_url(link_inscricao):
        print(f"[SKIP] Pulando link de eventos genérico do Race83: {link_inscricao}")
        return None

    event_info["link_inscricao"] = link_inscricao

    # Imagem do evento (resolve URLs relativas contra a URL da listagem)
    img_element = box.select_one("img.cs-chosen-image")
    event_info["link_imagem"] = (
        urljoin(BQC_LISTING_URL, str(img_element.get("src") or "")) if img_element else ""
    )

    # Extrai informações textuais (data, cidade, distâncias, organizador)
    paragraphs = [
        p.get_text(" ", strip=True).replace("\xa0", " ").strip()
        for p in box.select("div.text-editor p")
    ]
    texts = [t for t in paragraphs if t]

    full_text = " ".join(texts)
    extracted_time = extract_time_from_text(full_text)
    if extracted_time:
        event_info["horario"] = extracted_time

    distancias_encontradas: list[str] = []
    outros: list[str] = []
    for text in texts:
        if _DATA_PATTERN.search(text):
            event_info["data"] = text
        elif _is_distance_text(text):
            distancias_encontradas.append(text)
        else:
            outros.append(text)

    # Primeiro parágrafo restante é a cidade; o último (quando distinto) é o organizador.
    if outros:
        event_info["cidade"] = outros[0]
        if len(outros) > 1:
            event_info["organizador"] = outros[-1]

    if distancias_encontradas:
        event_info["distancia"] = ", ".join(distancias_encontradas)
    if not event_info.get("horario"):
        event_info["horario"] = ""

    return event_info


def get_event_data() -> list[EventInfo]:
    """
    Extrai os dados dos eventos da página Brasil Que Corre - Paraíba.

    A listagem é estática (server-side), portanto usa requests + BeautifulSoup,
    sem necessidade de Selenium nesta etapa. Os detalhes (preços, editais e
    horário quando ausente na listagem) continuam sendo coletados em
    process_event_details, que cria drivers sob demanda para fontes que exigem JS.
    """
    try:
        html = _fetch_bqc_listing_html()
        if not html:
            print(f"Erro crítico ao buscar dados dos eventos: falha ao baixar {BQC_LISTING_URL}")
            return []

        soup = BeautifulSoup(html, "html.parser")
        event_boxes = soup.find_all("div", class_="cs-box")

        event_data: list[EventInfo] = []
        total_events = len(event_boxes)
        print(f"\nEncontrados {total_events} boxes na listagem. Iniciando extração\n")

        for idx, box in enumerate(event_boxes, 1):
            try:
                event_info = _extract_bqc_event_info(box)
                if event_info is None:
                    continue
                event_data.append(event_info)
                print(f"[{idx}/{total_events}] ✓ Dados básicos: {event_info.get('nome', '')}")
            except Exception:
                continue

        # Busca editais e preços para complementar os dados básicos
        print("\nBuscando editais e preços...\n")
        event_data = process_event_details(event_data)

        return event_data

    except Exception as e:
        print(f"Erro crítico ao buscar dados dos eventos: {e}")
        return []


# FUNÇÃO PRINCIPAL E SALVAMENTO DE DADOS
def main():
    """
    Função principal para executar o scraper e salvar os dados.

    Executa todo o processo de scraping:
    1. Extrai dados dos eventos (listagem via requests + detalhes via extractors)
    2. Salva em CSV
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(base_dir, "data/eventos_brasilquecorre.csv")

    event_data = get_event_data()

    if not event_data:
        print("Nenhum evento encontrado ou ocorreu um erro.")
        return

    print(f"\nTotal de {len(event_data)} eventos encontrados. Salvando no CSV...")

    records = [
        {
            "Nome do Evento": event.get("nome", ""),
            "Link de Inscrição": event.get("link_inscricao", ""),
            "Link da Imagem": event.get("link_imagem", ""),
            "Data": event.get("data", ""),
            "Horário": (event.get("horario") or "Horário de largada não encontrado"),
            "Cidade": event.get("cidade", ""),
            "Distância": event.get("distancia", ""),
            "Organizador": event.get("organizador", ""),
            "Link do Edital": event.get("link_edital", ""),
            "precos_entries": event.get("precos_entries", ""),
        }
        for event in event_data
    ]
    write_events_csv(csv_path, records)

    print(f"\nDados salvos com sucesso em: {csv_path}")

    synced = sync_csv_to_mongodb(csv_path, "brasilquecorre")
    if not synced:
        print("Sincronização com mongodb pulada ou falhou.")


if __name__ == "__main__":
    main()
