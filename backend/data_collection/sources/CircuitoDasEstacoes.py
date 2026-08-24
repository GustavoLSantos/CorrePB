import contextlib
import json
import re
from datetime import datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from data_collection.core.Driver import setup_driver


def is_circuito_domain(domain: str) -> bool:
    if not domain:
        return False
    domain = domain.lower()
    return 'circuitodasestacoes.com' in domain


from typing import TypedDict, cast

import requests

from data_collection.core.ScraperCommon import (
    PriceEntry,
    fix_encoding,
    formatar_data_br,
    parse_data_br,
    _as_object_list,
    _as_str_object_dict,
    get_http_session,
    get_with_rate_limit,
)

ORGANIZADOR = "TTK MKT ESPORTIVO"

_NORTEMKT_HOME = "https://hotsites.nortemkt.com/api/v2/events/circuito-das-estacoes/home"
_RUNNINGLAND_GRAPHQL = "https://www.runningland.com.br/graphql"
_EVENT_SLUG = "circuito-das-estacoes"

_api_session = get_http_session()


class _Stage(TypedDict, total=False):
    name: str
    slug: str
    url_key: str | None
    date: str
    finished: bool
    coming_soon: bool
    modalities: list[dict[str, object]]


class _Location(TypedDict, total=False):
    name: str
    slug: str
    stages: list[_Stage]


class _KitItem(TypedDict, total=False):
    name: str
    prime_price: float | None
    regular_price: float | None
    special_price: float | None


def _parse_circuito_url(url: str) -> tuple[str, str] | None:
    """Extrai (location_slug, stage_slug) de URLs como /joao-pessoa/verao."""
    path = urlparse(url).path.strip("/")
    parts = [seg for seg in path.split("/") if seg]
    if len(parts) < 2:
        return None
    return parts[-2].lower(), parts[-1].lower()


def _runningland_graphql(query: str, variables: dict[str, object]) -> dict[str, object] | None:
    try:
        resp = _api_session.post(
            _RUNNINGLAND_GRAPHQL,
            data=json.dumps({"query": query, "variables": variables}),
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        resp.raise_for_status()
        payload = _as_str_object_dict(cast("object", resp.json()))
        return cast("dict[str, object] | None", (payload or {}).get("data"))
    except Exception:
        return None


def _kit_prices_by_sku(sku: str) -> list[_KitItem]:
    data = _runningland_graphql(
        "query KitPrice($sku: String) {"
        " bundleChildrenItems(sku: $sku)"
        " { prime_price regular_price special_price name } }",
        {"sku": sku},
    )
    if not data:
        return []
    kits: list[_KitItem] = []
    for item in _as_object_list(data.get("bundleChildrenItems")):
        kit = _as_str_object_dict(item)
        if kit is not None:
            kits.append(cast("_KitItem", cast("object", kit)))
    return kits


def _sku_por_url_key(url_key: str) -> str | None:
    data = _runningland_graphql(
        "query getEventProduct($url_key: String!) {"
        " products(filter: {url_key: {eq: $url_key}}) { items { sku } } }",
        {"url_key": url_key},
    )
    if not data:
        return None
    products = _as_str_object_dict(data.get("products"))
    items = _as_object_list((products or {}).get("items"))
    if not items:
        return None
    first = _as_str_object_dict(items[0])
    sku = (first or {}).get("sku")
    return str(sku) if sku else None



def _horario_por_page(location_slug: str, stage_slug: str) -> str:
    """Horário de largada publicado nos components da página da etapa."""
    base = _NORTEMKT_HOME.rsplit("/home", 1)[0]
    resp = get_with_rate_limit(
        _api_session,
        f"{base}/locations/{location_slug}",
        timeout=25,
    )
    if resp is None:
        return ""
    try:
        root = _as_str_object_dict(cast("object", resp.json()))
        payload = _as_str_object_dict((root or {}).get("data") or {})
        pages = _as_object_list((payload or {}).get("pages"))
    except Exception:
        return ""

    for raw_page in pages:
        page = _as_str_object_dict(raw_page)
        stage_info = _as_str_object_dict((page or {}).get("stage") or {})
        if (stage_info or {}).get("slug") != stage_slug:
            continue
        blob = json.dumps(page or {}, ensure_ascii=False)
        m = re.search(r"HOR[AÁ]RIO DE LARGADA.{0,200}?(\d{1,2})\s*h\s*(\d{2})?", blob, re.IGNORECASE | re.DOTALL)
        if m:
            hh = int(m.group(1))
            mm = int(m.group(2) or "0")
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                return f"{hh:02d}:{mm:02d}"
        break
    return ""


def fetch_circuito_api_data(url: str) -> dict[str, str] | None:
    """Coleta cidade/data/distâncias/preços da etapa via APIs públicas
    (hotsites.nortemkt.com + GraphQL RunningLand), sem Selenium.

    Retorna dict com chaves 'cidade','data','distancia','precos_entries'
    ou None se a etapa não for encontrada.
    """
    alvo = _parse_circuito_url(url)
    if not alvo:
        return None
    location_slug, stage_slug = alvo

    resp = get_with_rate_limit(_api_session, _NORTEMKT_HOME, timeout=25)
    if resp is None:
        return None
    try:
        root = _as_str_object_dict(cast("object", resp.json()))
        payload = _as_str_object_dict((root or {}).get("data") or {})
        event = _as_str_object_dict((payload or {}).get("event") or {})
    except Exception:
        return None
    if not event:
        return None

    location_name = ""
    stage: _Stage | None = None
    for raw_loc in _as_object_list(event.get("locations")):
        loc = _as_str_object_dict(raw_loc)
        if loc is None or loc.get("slug") != location_slug:
            continue
        location_name = str(loc.get("name") or "")
        loc_typed = cast("_Location", cast("object", loc))
        for raw_stage in _as_object_list(loc_typed.get("stages")):
            st = _as_str_object_dict(raw_stage)
            if st is None or st.get("slug") != stage_slug:
                continue
            stage = cast("_Stage", cast("object", st))
            break
        break

    if stage is None:
        return None

    distancias = ", ".join(
        str(mod.get("name") or "")
        for mod in (_as_object_list(stage.get("modalities")))
        if isinstance(mod, dict) and mod.get("name")
    )

    precos_entries: list[str] = []
    url_key = stage.get("url_key")
    if url_key and not stage.get("finished") and not stage.get("coming_soon"):
        sku = _sku_por_url_key(url_key)
        if sku:
            candidatos: list[PriceEntry] = []
            for kit in _kit_prices_by_sku(sku):
                precos_kit: list[float] = []
                for campo in (
                    kit.get("special_price"),
                    kit.get("prime_price"),
                    kit.get("regular_price"),
                ):
                    if isinstance(campo, (int, float)) and campo > 0:
                        precos_kit.append(float(campo))
                if not precos_kit:
                    continue
                nome_kit = str(kit.get("name") or "Inscrição")
                melhor = min(precos_kit)
                preco_br = f"R$ {melhor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                candidatos.append({"label": nome_kit, "price": melhor, "formatted": preco_br})
            candidatos.sort(key=lambda x: x["price"])
            precos_entries = [
                f"{e['formatted']} | {e['label']}" for e in candidatos
            ]

    horario = _horario_por_page(location_slug, stage_slug)

    return {
        "cidade": location_name,
        "data": str(stage.get("date") or ""),
        "distancia": distancias,
        "horario": horario,
        "precos_entries": json.dumps(precos_entries, ensure_ascii=False) if precos_entries else "[]",
    }

def load_circuito_soup(
    url: str, timeout: int = 20, driver: WebDriver | None = None
) -> tuple[BeautifulSoup | None, bool, WebDriver | None, str]:
    """
    Carrega a URL usando Selenium tratando quirks do CircuitoDasEstacoes.

    Aceita um driver externo para reuso entre eventos (evita subir um Chrome por evento).

    Retorna (soup, created, driver, horario)
    - soup: BeautifulSoup da página (ou None em falha)
    - created: True se a função criou um driver (caller deve quit() se True)
    - driver: o WebDriver usado (ou None)
    - horario: horário extraído ('' se não encontrado)
    """
    domain = urlparse(url).netloc.lower() if url else ''
    created = False
    try:
        # usar modo headless para execução sem UI; driver externo é reaproveitado
        if driver is None:
            driver = setup_driver(headless=True)
            created = True
        try:
            driver.get(url)

            # Uma única espera com todos os seletores combinados: antes eram até
            # 5 x timeout (100s+) em páginas onde nenhum seletor existe.
            selectors = [
                'p.kit-price-desktop, p.kit-price-mobile',
                '#race-detailed-info',
                'details',
                '.details-content',
                'summary',
            ]
            with contextlib.suppress(Exception):
                WebDriverWait(driver, min(timeout, 12)).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ', '.join(selectors)))
                )
            # captura o HTML completo antes de qualquer clique que possa navegar
            price_soup = BeautifulSoup(driver.page_source, 'html.parser')

            # guarda o href do CTA antes de navegar para a página de informações
            cta_href = ''
            try:
                cta_anchors = driver.find_elements(By.CSS_SELECTOR, 'a.kit-cta-desktop')
                if not cta_anchors:
                    cta_anchors = driver.find_elements(By.CSS_SELECTOR, 'a[class*="kit-cta"]')
                if cta_anchors:
                    cta_href = cta_anchors[0].get_attribute('href') or ''
            except Exception:
                cta_href = ''

            # tenta clicar no botão que revela as informações (caso exista)
            try:
                # tenta seletor específico dentro do container
                buttons = driver.find_elements(By.CSS_SELECTOR, "#race-detailed-info [role='button'], #race-detailed-info button, #race-detailed-info a")
                if buttons:
                    try:
                        buttons[0].click()
                        WebDriverWait(driver, 5).until(lambda d: 'details' in (d.page_source or '').lower() or len(d.find_elements(By.CSS_SELECTOR, 'details'))>0)
                    except Exception:
                        pass
            except Exception:
                # fallback: procura por elementos com texto aproximado 'confira'/'inform' em anchors e buttons
                try:
                    details_count = driver.execute_script("return document.querySelectorAll('details').length")
                except Exception:
                    details_count = 0

                if not details_count:
                    # procura apenas por anchors e buttons com texto relevante para reduzir escopo
                    xpath = ("//a[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'confira')"
                             " or contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'inform')]"
                             " | //button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'confira')"
                             " or contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'inform')]")
                    try:
                        elems = driver.find_elements(By.XPATH, xpath)
                    except Exception:
                        elems = []

                    for el in elems:
                        try:
                            if not el.is_displayed():
                                continue
                            disabled = el.get_attribute('disabled')
                            if disabled:
                                continue
                            el.click()
                            WebDriverWait(driver, 3).until(lambda d: 'details' in (d.page_source or '').lower() or len(d.find_elements(By.CSS_SELECTOR, 'details'))>0)
                            break
                        except Exception:
                            continue

            # força abertura de <details> e rolagem para acionar lazy-loads
            try:
                driver.execute_script("document.querySelectorAll('details').forEach(d=>d.open=true);")
                driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
                # não usar sleep; confiar nas esperas explícitas posteriores
                driver.execute_script('window.scrollTo(0, 0);')
            except Exception:
                pass

            # espera até que o conteúdo pareça renderizado (presença de 'largada' ou details com texto)
            try:
                def _ready(drv):
                    try:
                        if drv.execute_script("return document.body.innerText.toLowerCase().includes('largada')"):
                            return True
                        cnt = drv.execute_script("return document.querySelectorAll('details').length")
                        if cnt and cnt > 0:
                            has_text = drv.execute_script("let d=document.querySelector('details .details-content'); return d && d.innerText.trim().length>0")
                            return bool(has_text)
                        return False
                    except Exception:
                        return False
                WebDriverWait(driver, min(timeout, 15)).until(_ready)
            except Exception:
                pass

            # extrai o horário da página de informações (URL pode ter navegado)
            schedule_soup = BeautifulSoup(driver.page_source, 'html.parser')
            horario = extract_circuito_schedule(schedule_soup)

            # navega para o CTA (RunningLand) para que extract_circuito_ticket_prices possa usar o driver
            if cta_href:
                try:
                    driver.get(cta_href)

                    def _cta_ready(d):
                        return (
                            len(d.find_elements(By.CSS_SELECTOR, 'div[class*="option-root"]')) > 0
                            or 'R$' in (d.page_source or '')
                        )

                    with contextlib.suppress(Exception):
                        WebDriverWait(driver, min(timeout, 12)).until(_cta_ready)
                except Exception:
                    pass

            return price_soup, created, driver, horario
        finally:
            pass
    except Exception:
        try:
            if created and driver:
                try:
                    driver.quit()
                except Exception:
                    pass
        except Exception:
            pass
        return None, False, None, ''


def _parse_price_str_to_float(token: str | float | None) -> float | None:
    import re
    if not token:
        return None
    s = re.sub(r'[^\d.,]', '', str(token))
    if not s:
        return None
    if '.' in s and ',' in s:
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s and '.' not in s:
        s = s.replace(',', '.')
    try:
        return float(s)
    except Exception:
        try:
            return float(s.replace('.', '').replace(',', '.'))
        except Exception:
            return None


def extract_circuito_ticket_prices(driver: WebDriver, wait_seconds: int = 30) -> list[str]:
    """Extrai preços da página de inscrição do CircuitoDasEstacoes (RunningLand).

    O driver deve estar posicionado na página de compra (RunningLand).
    Retorna uma lista de strings no formato 'LABEL - XX,XX'.
    """
    import re
    if not driver:
        return []
    try:
        price_sel = 'div[class*="option-root"], div[class*="option-priceBlock"], [class*="option-rootLeft"], div[class*="priceBlock-block"]'
        try:
            WebDriverWait(driver, min(wait_seconds, 40), poll_frequency=0.5).until(
                lambda d: len(d.find_elements(By.CSS_SELECTOR, price_sel)) > 0 or 'R$' in (d.page_source or '')
            )
        except Exception:
            pass

        blocks = driver.find_elements(By.CSS_SELECTOR, 'div[class*="option-root"], div[class*="option-priceBlock"], [class*="option-rootLeft"], div[class*="priceBlock-block"]') or []

        out = {}
        for b in blocks:
            try:
                try:
                    lbl_el = b.find_element(By.CSS_SELECTOR, '[class*="option-label"], .option-label, .option-labelLeft, .option-labelLeft-f8R, h4, h3')
                    label = (lbl_el.text or '').strip()
                except Exception:
                    label = None

                # tenta preço especial primeiro, depois preço regular
                price_el = None
                for price_css in [
                    'span[class*="option-specialPrice"], .option-specialPrice',
                    'span[class*="option-regularPrice"], .option-regularPrice',
                    'span[class*="priceBlock-regularPrice"]',
                    'span[class*="priceBlock-oldP"], .priceBlock-oldP, span[class*="priceBlock-fromPrice"]',
                ]:
                    try:
                        price_el = b.find_element(By.CSS_SELECTOR, price_css)
                        if price_el:
                            break
                    except Exception:
                        continue

                if not price_el or not label:
                    continue

                txt = price_el.text or ''
                m = re.search(r'R\$\s*([\d.,]+)', txt)
                val = None
                if m:
                    val = _parse_price_str_to_float(m.group(1))
                else:
                    mm = re.search(r'([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+[.,][0-9]{2})', txt)
                    if mm:
                        val = _parse_price_str_to_float(mm.group(1))
                if val is None:
                    continue

                key = label.strip().upper()
                if key in out:
                    continue
                out[key] = "{:.2f}".format(val).replace('.', ',')
            except Exception:
                continue

        return [f"{k} - {v}" for k, v in out.items()]
    except Exception:
        return []


def extract_circuito_schedule(soup: BeautifulSoup) -> str:
    """Extrai o horário de largada das seções de "Informações" do site CircuitoDasEstacoes.

    O site rendeiriza via JavaScript; este extractor procura por blocos <details>
    e por cabeçalhos (h5/h4/h3/strong/b/summary/p) que contenham 'horário', 'largada' ou 'saída',
    então busca o texto associado (span/p/div) dentro do mesmo bloco e tenta extrair um horário.
    Retorna 'HH:MM', 'Em breve' (quando indicado) ou '' se não encontrado.
    """
    if not soup:
        return ''
    try:
        import re, unicodedata

        def _strip_accents(s):
            if not s:
                return ''
            s = unicodedata.normalize('NFD', s)
            return ''.join(ch for ch in s if not unicodedata.category(ch).startswith('M'))

        # procura por blocos <details> com conteúdo renderizado
        for details in soup.find_all('details'):
            # usa o container de conteúdo se presente
            container = details.find(class_='details-content') or details

            # procura por possíveis rótulos/headers dentro do container
            for header in container.find_all(['h5', 'h4', 'h3', 'strong', 'b', 'summary', 'p']):
                header_text = _strip_accents(header.get_text(' ', strip=True)).lower()
                if not header_text:
                    continue
                if 'horario' in header_text or 'largada' in header_text or 'saida' in header_text:
                    # tenta extrair texto associado preferindo elementos dentro do mesmo 'campo' pai
                    # encontra o ancestor próximo que agrupa o label + valor (ex: div.mt-3)
                    parent = header
                    group = None
                    # sobe até encontrar uma div com múltiplos filhos ou até o próprio 'container'
                    for _ in range(4):
                        if parent is None:
                            break
                        if parent.name == 'div' and len(parent.find_all(recursive=False)) >= 1:
                            group = parent
                            break
                        parent = parent.parent
                    if group is None:
                        group = header.parent if header.parent is not None else container

                    # procura por elementos que contenham o valor dentro do grupo
                    candidate = None
                    # procura por <span> ou <p> diretamente dentro do grupo
                    for tag in ['span', 'p', 'div']:
                        found = group.find(tag)
                        if found and found.get_text(strip=True):
                            candidate = found
                            break

                    # se não achou, pega o próximo elemento significativo após o header
                    if candidate is None:
                        nxt = header.find_next(['span', 'p', 'div'])
                        if nxt and nxt.get_text(strip=True):
                            candidate = nxt

                    content = candidate.get_text(' ', strip=True) if candidate else container.get_text(' ', strip=True)
                    if not content:
                        continue

                    # tenta encontrar padrões como '6h00', '06:00', '6h' ou 'Largada única: 6h00'
                    m = re.search(r"(\d{1,2})\s*[:hH]\s*(\d{1,2})?", content)
                    if m:
                        try:
                            hh = int(m.group(1))
                            mm = int(m.group(2) or '0')
                            if 0 <= hh <= 23 and 0 <= mm <= 59:
                                return f"{hh:02d}:{mm:02d}"
                        except Exception:
                            pass

                    # busca no texto normalizado por 'às HH:MM' ou 'as HHhMM'
                    content_norm = _strip_accents(content).lower()
                    m2 = re.search(r"(?:as\s*)?(\d{1,2})\s*[:hH]\s*(\d{1,2})?", content_norm)
                    if m2:
                        try:
                            hh = int(m2.group(1))
                            mm = int(m2.group(2) or '0')
                            if 0 <= hh <= 23 and 0 <= mm <= 59:
                                return f"{hh:02d}:{mm:02d}"
                        except Exception:
                            pass

                    if re.search(r'\bem\s+breve\b', content_norm):
                        txt = content.strip()
                        if txt and len(txt) <= 120:
                            return txt
                        return 'Em breve'

        page = _strip_accents(soup.get_text(' ', strip=True)).lower()
        m = re.search(r"(?:horario|largada|saida)[^\d]{0,50}(\d{1,2})\s*[:hH]\s*(\d{0,2})", page)
        if m:
            try:
                hh = int(m.group(1))
                mm = int(m.group(2) or '0')
                if 0 <= hh <= 23 and 0 <= mm <= 59:
                    return f"{hh:02d}:{mm:02d}"
            except Exception:
                pass

        # global placeholders in page text
        if re.search(r'\bem\s+breve\b', page) or re.search(r'\ba\s+definir\b', page) or re.search(r'\bnao\s+divulgad', page):
            return 'Em breve'

    except Exception:
        pass
    return ''


def _preco_kit_key(e: PriceEntry) -> float:
    preco = e.get("price")
    return float(preco) if isinstance(preco, (int, float)) else 0.0


# Localidades da Paraíba conhecidas na plataforma (slug); None = todas
LOCALIZACOES_PB = frozenset({"joao-pessoa"})


def get_circuito_events(
    somente_futuros: bool = True,
    localidades: frozenset[str] | set[str] | None = LOCALIZACOES_PB,
) -> list[dict[str, str]]:
    """Coleta completa das etapas do Circuito das Estações via APIs públicas.

    - Catálogo: hotsites.nortemkt.com/api/v2/events/circuito-das-estacoes/home
      (localizações × etapas com cidade, data, modalidades e url_key)
    - Preços: GraphQL RunningLand (sku via url_key -> bundleChildrenItems)
    - Horário de largada: components da página da etapa

    Retorna registros no schema padrão do projeto, sem Selenium.
    """
    resp = get_with_rate_limit(_api_session, _NORTEMKT_HOME, timeout=25)
    if resp is None:
        return []
    try:
        root = _as_str_object_dict(cast("object", resp.json()))
        payload = _as_str_object_dict((root or {}).get("data") or {})
        event = _as_str_object_dict((payload or {}).get("event") or {})
    except Exception:
        return []
    if not event:
        return []

    records: list[dict[str, str]] = []

    for raw_loc in _as_object_list(event.get("locations")):
        loc = _as_str_object_dict(raw_loc)
        if loc is None:
            continue
        location_name = str(loc.get("name") or "")
        loc_typed = cast("_Location", cast("object", loc))
        location_slug = str(loc_typed.get("slug") or "")
        if localidades is not None and location_slug not in localidades:
            continue

        for raw_stage in _as_object_list(loc_typed.get("stages")):
            st = _as_str_object_dict(raw_stage)
            if st is None:
                continue
            stage = cast("_Stage", cast("object", st))

            if somente_futuros and (
                stage.get("finished") or stage.get("coming_soon")
            ):
                continue
            if not stage.get("published", True):
                continue

            stage_slug = str(stage.get("slug") or "")
            url_key = str(stage.get("url_key") or "")
            data_br = str(stage.get("date") or "")

            distancias = ", ".join(
                str(mod.get("name") or "")
                for mod in _as_object_list(stage.get("modalities"))
                if isinstance(mod, dict) and mod.get("name")
            )

            precos_entries = "[]"
            if url_key:
                sku = _sku_por_url_key(url_key)
                if sku:
                    candidatos: list[PriceEntry] = []
                    for kit in _kit_prices_by_sku(sku):
                        precos_kit: list[float] = []
                        for campo in (
                            kit.get("special_price"),
                            kit.get("prime_price"),
                            kit.get("regular_price"),
                        ):
                            if isinstance(campo, (int, float)) and campo > 0:
                                precos_kit.append(float(campo))
                        if not precos_kit:
                            continue
                        nome_kit = str(kit.get("name") or "Inscrição")
                        melhor = min(precos_kit)
                        preco_br = (
                            f"R$ {melhor:,.2f}"
                            .replace(",", "X")
                            .replace(".", ",")
                            .replace("X", ".")
                        )
                        candidatos.append(
                            {
                                "label": nome_kit,
                                "price": melhor,
                                "formatted": preco_br,
                            }
                        )
                    candidatos.sort(key=_preco_kit_key)
                    precos_entries = json.dumps(
                        [f"{e['formatted']} | {e['label']}" for e in candidatos],
                        ensure_ascii=False,
                    )

            records.append(
                {
                    "Nome do Evento": (
                        f"CIRCUITO DAS ESTAÇÕES {str(stage.get('name') or '').upper()}"
                        f" - {location_name.upper()}"
                    ).strip(),
                    "Link de Inscrição": (
                        f"https://www.circuitodasestacoes.com.br/{location_slug}/{stage_slug}"
                    ),
                    "Link da Imagem": "",
                    "Data": formatar_data_br(data_br),
                    "Horário": _horario_por_page(location_slug, stage_slug),
                    "Cidade": fix_encoding(location_name),
                    "Distância": distancias,
                    "Organizador": ORGANIZADOR,
                    "Link do Edital": "edital não encontrado",
                    "precos_entries": precos_entries,
                    "_data_br": data_br,
                }
            )

    return records
