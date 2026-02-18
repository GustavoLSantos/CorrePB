import csv
import re
import os
import json
import time
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

from data_collection.core.Driver import setup_driver
from data_collection.sources.Sympla import is_sympla_domain, load_sympla_soup
from data_collection.sources.Liverun import is_liverun_domain, load_liverun_soup
from data_collection.sources.CircuitoDasEstacoes import is_circuito_domain, load_circuito_soup
from data_collection.sources.Race83 import is_race83_domain, is_race83_listing_url, detect_redirects_to_listing, load_race83_soup
from data_collection.sources.Ticketsports import is_ticketsports_domain, load_ticketsports_soup, extract_ticketsports_ticket_prices, extract_ticketsports_schedule
from data_collection.sources.Nightrun import is_nightrun_domain, load_nightrun_soup
from data_collection.sources.Zenite import is_zenite_domain, load_zenite_soup, extract_zenite_schedule
from data_collection.utils.PriceUtils import parse_price_str, fmt_entry
from data_collection.utils.PrizeDetection import entry_is_prize


def _fmt_price_br(v):
    """Formata float para 'R$ 1.234,56' (robusto contra None)."""
    try:
        pv = float(v)
    except Exception:
        return str(v)
    s = f"R$ {pv:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return s


def _prices_from_formatted_list(formatted_iterable):
    """Recebe um iterável de strings (formatted) e tenta extrair floats dos valores R$ presentes.
    Retorna lista ordenada de floats (pode ser vazia).
    """
    prices = []
    if not formatted_iterable:
        return prices
    for item in formatted_iterable:
        try:
            if not item:
                continue
            # tenta encontrar todos valores 'R$' na string
            for m in re.findall(r'R\$\s*([\d.,]+)', str(item)):
                v = parse_price_str(m)
                if v is not None:
                    prices.append(v)
        except Exception:
            continue
    prices = sorted(set(prices))
    return prices

#Extração de preços
def extract_price_entries(soup, domain):
    """
    Retorna uma lista de entradas de preço estruturadas encontradas na página.

    Cada entrada é um dict: {
        label (str|None),
        price (float),
        tax (float|None),
        formatted (str),
        raw (str)
    }
    """
    page_html = str(soup)
    candidates = []

    # Tenta rodar extractors site-specific apenas se o domínio corresponder explicitamente
    # Inicializa variáveis para evitar avisos de referência antes de atribuição
    extract_sympla_ticket_prices = None
    extract_ticketsports_ticket_prices = None
    extract_nightrun_ticket_prices = None
    extract_zenite_ticket_prices = None
    try:
        try:
            from data_collection.sources.Sympla import extract_sympla_ticket_prices
        except Exception:
            extract_sympla_ticket_prices = None
        try:
            from data_collection.sources.Ticketsports import extract_ticketsports_ticket_prices
        except Exception:
            extract_ticketsports_ticket_prices = None
        try:
            from data_collection.sources.Nightrun import extract_nightrun_ticket_prices
        except Exception:
            extract_nightrun_ticket_prices = None
        try:
            from data_collection.sources.Zenite import extract_zenite_ticket_prices
        except Exception:
            extract_zenite_ticket_prices = None
    except Exception:
         # falha ao importar/executar extractors: segue com heurísticas genéricas
         pass

    # Se o domínio for conhecido e houver um extractor específico, usa-o imediatamente
    try:
        if domain:
            if 'extract_sympla_ticket_prices' in locals() and extract_sympla_ticket_prices and is_sympla_domain(domain):
                return extract_sympla_ticket_prices(soup)
            if 'extract_ticketsports_ticket_prices' in locals() and extract_ticketsports_ticket_prices and is_ticketsports_domain(domain):
                # Ticketsports normalmente usa seu próprio loader/flow; keep generic fallback
                return extract_ticketsports_ticket_prices(soup)
            if 'extract_nightrun_ticket_prices' in locals() and extract_nightrun_ticket_prices and is_nightrun_domain(domain):
                return extract_nightrun_ticket_prices(soup)
            if 'extract_zenite_ticket_prices' in locals() and extract_zenite_ticket_prices and is_zenite_domain(domain):
                return extract_zenite_ticket_prices(soup)
    except Exception:
        # Se o extractor específico falhar, segue com heurísticas genéricas abaixo
        pass

    #Elementos de preço por classe
    def has_price_class(classes):
        if not classes:
            return False
        if isinstance(classes, str):
            cls_list = [classes]
        else:
            cls_list = list(classes)
        for c in cls_list:
            try:
                cl = c.lower()
            except Exception:
                continue
            if 'price' in cl or 'preco' in cl or 'valor' in cl or 'kit-price' in cl:
                return True
        return False

    price_elements = soup.find_all(['span', 'div', 'p'], class_=has_price_class)
    for elem in price_elements:
        txt = elem.get_text(separator=' ', strip=True)
        for m in re.findall(r'R\$(?:\s|\xa0|&nbsp;)*([\d.,]+)', txt):
            v = parse_price_str(m)
            tax = None
            tax_m = re.search(r'\(\s*\+?([\d.,]+)\s*(?:taxa|tax|fee)\s*\)', txt, re.IGNORECASE)
            if tax_m:
                tax = parse_price_str(tax_m.group(1))
            candidates.append({'label': None, 'price': v, 'tax': tax, 'raw': txt})


    #Detecta elementos com font-size inline grande que contêm R$
    try:
        for elem in soup.find_all(['span', 'div', 'p']):
            style = elem.get('style', '') or ''
            if 'font-size' in style and 'R$' in elem.get_text():
                m_px = re.search(r'font-size\s*:\s*(\d+)px', style)
                if m_px and int(m_px.group(1)) >= 20:
                    txt = elem.get_text(separator=' ', strip=True)
                    for m in re.findall(r'R\$(?:\s|\xa0|&nbsp;)*([\d.,]+)', txt):
                        v = parse_price_str(m)
                        candidates.append({'label': None, 'price': v, 'tax': None, 'raw': txt})
    except Exception:
        pass

    #Tabelas e tbodies (trata cabeçalhos de seção com colspan e preço na primeira td)
    try:
        blocks = soup.find_all(['table', 'tbody'])
        for table in blocks:
            current_section = None
            for tr in table.find_all('tr'):
                tds = tr.find_all(['td', 'th'])
                if len(tds) == 1 and tds[0].has_attr('colspan'):
                    sec_text = tds[0].get_text(separator=' ', strip=True)
                    sec_text = re.sub(r'\s+', ' ', sec_text).strip()
                    current_section = sec_text
                    continue
                if len(tds) >= 2:
                    left_text = tds[0].get_text(separator=' ', strip=True)
                    right_text = tds[1].get_text(separator=' ', strip=True)
                    left_has_price = bool(re.search(r'R\$', left_text))
                    right_has_price = bool(re.search(r'R\$', right_text))
                    if left_has_price and not right_has_price:
                        for m in re.findall(r'R\$(?:\s|\xa0|&nbsp;)*([\d.,]+)', left_text):
                            v = parse_price_str(m)
                            label = right_text or None
                            if current_section and label and current_section not in label:
                                label = f"{current_section} — {label}"
                            elif current_section and not label:
                                label = current_section
                            candidates.append({'label': label, 'price': v, 'tax': None, 'raw': f'{left_text} | {right_text}'})
                    elif right_has_price and not left_has_price:
                        for m in re.findall(r'R\$(?:\s|\xa0|&nbsp;)*([\d.,]+)', right_text):
                            v = parse_price_str(m)
                            label = left_text or None
                            if current_section and label and current_section not in label:
                                label = f"{current_section} — {label}"
                            elif current_section and not label:
                                label = current_section
                            candidates.append({'label': label, 'price': v, 'tax': None, 'raw': f'{left_text} | {right_text}'})
                    else:
                        # fallback: extrai qualquer preço na linha e tenta associar um label próximo
                        rowtxt = tr.get_text(separator=' ', strip=True)
                        for m in re.findall(r'R\$(?:\s|\xa0|&nbsp;)*([\d.,]+)', rowtxt):
                            v = parse_price_str(m)
                            label = None
                            if left_text and not re.search(r'R\$', left_text):
                                label = left_text
                                if current_section and current_section not in label:
                                    label = f"{current_section} — {label}"
                            elif right_text and not re.search(r'R\$', right_text):
                                label = right_text
                                if current_section and current_section not in label:
                                    label = f"{current_section} — {label}"
                            candidates.append({'label': label, 'price': v, 'tax': None, 'raw': rowtxt})
    except Exception:
        pass

    #Dados estruturados e atributos: meta tags, atributos data-price, JSON-LD
    try:
        # Meta tags
        for meta in soup.find_all('meta'):
            prop = (meta.get('property') or meta.get('name') or '').lower()
            content = meta.get('content', '')
            if prop in ('product:price:amount', 'price', 'og:price:amount') or 'price' in prop:
                if content:
                    v = parse_price_str(content)
                    if v is not None:
                        candidates.append({'label': None, 'price': v, 'tax': None, 'raw': f'meta:{prop}:{content}'})

        # Atributos data como data-price, data-preco, data-value
        for elem in soup.find_all(attrs=True):
            for attr, val in list(elem.attrs.items()):
                if re.search(r'data[-_]?(price|preco|valor|value)', attr, re.IGNORECASE):
                    v = parse_price_str(val)
                    if v is not None:
                        label = None
                        text = elem.get_text(separator=' ', strip=True)
                        if text and 'R$' not in text:
                            label = text
                        candidates.append({'label': label, 'price': v, 'tax': None, 'raw': f'{attr}={val}'})

        # Scripts JSON-LD
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                payload = json.loads(script.string or script.get_text() or '{}')
            except Exception:
                continue
            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                if isinstance(item, dict):
                    offers = item.get('offers') or item.get('priceSpecification')
                    if offers:
                        if isinstance(offers, list):
                            offers_iter = offers
                        else:
                            offers_iter = [offers]
                        for off in offers_iter:
                            if isinstance(off, dict):
                                price = off.get('price') or off.get('priceSpecification') or off.get('priceCurrency')
                                if price:
                                    v = parse_price_str(price)
                                    if v is not None:
                                        label = item.get('name') if item.get('name') else None
                                        candidates.append({'label': label, 'price': v, 'tax': None, 'raw': 'ldjson'})
                    # Campo direto de preço
                    if 'price' in item and item.get('price'):
                        v = parse_price_str(item.get('price'))
                        if v is not None:
                            label = item.get('name') if item.get('name') else None
                            candidates.append({'label': label, 'price': v, 'tax': None, 'raw': 'ldjson-price'})
    except Exception:
        pass

    #Fallbacks: R$ genérico, 'reais', faixas — apenas após parsing estruturado
    for m in re.findall(r'R\$(?:&nbsp;|\s)*([\d.,]+)', page_html):
        v = parse_price_str(m)
        if v is not None:
            candidates.append({'label': None, 'price': v, 'tax': None, 'raw': m})
    for m in re.findall(r'([\d.,]+)\s*reais', page_html, re.IGNORECASE):
        v = parse_price_str(m)
        if v is not None:
            candidates.append({'label': None, 'price': v, 'tax': None, 'raw': m})
    for a, b in re.findall(r'R\$\s*([\d.,]+)\s*(?:a|até|-)\s*(?:R\$)?\s*([\d.,]+)', page_html, re.IGNORECASE):
        va = parse_price_str(a)
        vb = parse_price_str(b)
        # Evita capturar índices pequenos (ex: '1-159,90') como preço '1.0'.
        # Se o lado esquerdo for <10 e não contiver separador decimal, e o direito contiver, ignora o esquerdo.
        try:
            a_has_dec = ',' in a or '.' in a
        except Exception:
            a_has_dec = False
        try:
            b_has_dec = ',' in b or '.' in b
        except Exception:
            b_has_dec = False
        if va is not None:
            if not (va < 10 and not a_has_dec and b_has_dec):
                candidates.append({'label': None, 'price': va, 'tax': None, 'raw': f'{a}-{b}'})
        if vb is not None:
            if not (vb < 10 and not b_has_dec and a_has_dec):
                candidates.append({'label': None, 'price': vb, 'tax': None, 'raw': f'{a}-{b}'})
    for a, b in re.findall(r'(?:R\$)?\s*([\d.,]+)\s*(?:a|até|-)\s*R\$\s*([\d.,]+)', page_html, re.IGNORECASE):
        va = parse_price_str(a)
        vb = parse_price_str(b)
        try:
            a_has_dec = ',' in a or '.' in a
        except Exception:
            a_has_dec = False
        try:
            b_has_dec = ',' in b or '.' in b
        except Exception:
            b_has_dec = False
        if va is not None:
            if not (va < 10 and not a_has_dec and b_has_dec):
                candidates.append({'label': None, 'price': va, 'tax': None, 'raw': f'{a}-{b}'})
        if vb is not None:
            if not (vb < 10 and not b_has_dec and a_has_dec):
                candidates.append({'label': None, 'price': vb, 'tax': None, 'raw': f'{a}-{b}'})

    # Após coletar candidatos, filtra valores de prêmios/premiações usando verificação contextual
    # Usa verificação sensível ao contexto: o raw/label do candidato pode não conter palavras-chave de prêmio,
    # então inspeciona o HTML da página ao redor de onde o preço ocorre também.
    candidates = [e for e in candidates if not entry_is_prize(e, page_html)]

    # Se temos preços rotulados de tabelas/grids estruturados, prefere eles e descarta duplicatas não rotuladas
    labeled_prices = {e.get('price') for e in candidates if e.get('label')}
    if labeled_prices:
        candidates = [e for e in candidates if not (e.get('label') is None and e.get('price') in labeled_prices)]

    # Filtra preços de inscrição plausíveis (ajusta limites se necessário)
    valid_entries = [e for e in candidates if e.get('price') is not None and 0 <= e.get('price') <= 500]

    # Se há preços pagos, exclui entradas gratuitas (0.00) para evitar falsos positivos
    if any(e['price'] > 0 for e in valid_entries):
        valid_entries = [e for e in valid_entries if e['price'] > 0]

    if not valid_entries:
        # Se não há preços pagos, verifica indicadores de gratuito
        if re.search(r'\b(grátis|gratis|gratuito|gratuita|isento|free)\b', page_html, re.IGNORECASE):
            return [{'label': None, 'price': 0.0, 'tax': None, 'formatted': 'R$ 0,00', 'raw': page_html}]
        # Se não foi encontrado indicador de gratuidade, devolve uma entry informativa
        # para que o campo legível 'preco' seja preenchido com 'Valor não encontrado'.
        return [{'label': None, 'price': None, 'tax': None, 'formatted': 'Valor não encontrado', 'raw': page_html}]

    # Deduplica por (label, price, tax)
    seen = set()
    unique = []
    for e in valid_entries:
        key = (e.get('label') or '', float(e.get('price')), e.get('tax') if e.get('tax') is None else float(e.get('tax')))
        if key not in seen:
            seen.add(key)
            unique.append(e)

    # Ordena por preço crescente
    unique_sorted = sorted(unique, key=lambda x: (x.get('price') or 0))


    return [fmt_entry(e) for e in unique_sorted]


#Extração de edital
def extract_edital(url):
    """Extrai o link do edital usando requests."""
    try:
        response = requests.get(url, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        domain = urlparse(url).netloc

        if 'zeniteesportes.com' in domain:
            # Procura por links com texto "regulamento"
            reg_links = [a for a in soup.find_all('a') if re.search(r'regulamento', a.get_text() or '', re.IGNORECASE)]
            for link in reg_links:
                onclick = link.get('onclick', '')
                if '.pdf' in onclick.lower():
                    pdf_match = re.search(r"abrirPDF\('([^']+)'\)", onclick)
                    if pdf_match:
                        return pdf_match.group(1)
                href = link.get('href', '')
                if '.pdf' in href.lower():
                    return href

            # Busca genérica por links PDF
            pdf_links = soup.find_all('a', href=re.compile(r'\.pdf', re.IGNORECASE))
            if pdf_links:
                return pdf_links[0].get('href', '')

        elif 'race83.com.br' in domain or 'correparaiba.com' in domain:
            pdf_link = soup.find('a', href=re.compile(r'\.pdf', re.IGNORECASE))
            if pdf_link:
                return pdf_link.get('href', '')

        return 'edital não encontrado'
    except Exception:
        return 'edital não encontrado'


# PROCESSAMENTO PARALELO DE DETALHES DOS EVENTOS
def process_event_details(events):
    """
    Processa editais e preços de múltiplos eventos em paralelo.
    Usa ThreadPoolExecutor para acelerar a extração de dados de cada URL.
    """
    def fetch_details(event_info):
        """Busca detalhes de um evento específico (edital e preços)."""
        url = event_info.get('link_inscricao', '')
        if url:
            # defaults to ensure variables exist in all control paths
            str_preco = 'preço não encontrado'
            json_precos_entries = '[]'
            try:
                domain = urlparse(url).netloc
                soup = None
                loader_horario = None
                # variáveis relacionadas ao loader Sympla — inicializa aqui para não depender do branch
                created = False
                sym_driver = None
                temp_driver = None
                liverun_driver = None
                race_driver = None

                # Se o domínio é do race83, detecta redirecionamentos para a listagem genérica
                try:
                    if is_race83_domain(domain):
                        is_listing, final = detect_redirects_to_listing(url, timeout=5)
                        if is_listing:
                            print(f"[SKIP] URL do Race83 redirecionou para listagem /eventos, pulando: {url} -> {final}")
                            return None
                except Exception:
                    pass

                if is_sympla_domain(domain):
                    # Usa o loader específico para Sympla (pode criar/quitar driver internamente)
                    try:
                        soup, created, sym_driver = load_sympla_soup(url)
                    except Exception:
                        soup, created, sym_driver = None, False, None
                elif is_circuito_domain(domain):
                    try:
                        soup, created, temp_driver = load_circuito_soup(url)
                    except Exception:
                        soup, created, temp_driver = None, False, None
                elif is_liverun_domain(domain):
                    try:
                        soup, created, liverun_driver = load_liverun_soup(url)
                    except Exception:
                        soup, created, liverun_driver = None, False, None
                elif is_race83_domain(domain):
                    try:
                        soup, created, race_driver = load_race83_soup(url)
                    except Exception:
                        soup, created, race_driver = None, False, None
                elif is_ticketsports_domain(domain):
                    # Usa o loader específico para Ticketsports (renderiza com Selenium)
                    try:
                        soup, created, temp_driver = load_ticketsports_soup(url, driver=None, wait_seconds=30, debug=True)
                    except Exception:
                        import traceback
                        traceback.print_exc()
                        soup, created, temp_driver = None, False, None
                elif is_nightrun_domain(domain):
                    try:
                        soup, created, temp_driver = load_nightrun_soup(url, driver=None, wait_seconds=30)
                    except Exception:
                        soup, created, temp_driver = None, False, None
                elif is_zenite_domain(domain):
                    try:
                        # load_zenite_soup returns (soup, created, driver, horario)
                        soup, created, temp_driver, loader_horario = load_zenite_soup(url, driver=None, wait_seconds=30)
                    except Exception:
                        soup, created, temp_driver, loader_horario = None, False, None, None
                else:
                    # Sites estáticos podem usar requests simples
                    try:
                        response = requests.get(url, timeout=5)
                        soup = BeautifulSoup(response.text, 'html.parser')
                    except Exception:
                        soup = None

                # Se o Sympla loader criou um driver, certifica-se de fechá-lo após usar o soup
                if 'sym_driver' in locals() and sym_driver and 'created' in locals() and created:
                    try:
                        sym_driver.quit()
                    except Exception:
                        pass
                # Fecha driver criado pelo loader de circuito, se houver
                if 'temp_driver' in locals() and temp_driver and 'created' in locals() and created:
                    try:
                        temp_driver.quit()
                    except Exception:
                        pass
                # Fecha driver criado pelo loader de liverun, se houver
                if 'liverun_driver' in locals() and liverun_driver and 'created' in locals() and created:
                    try:
                        liverun_driver.quit()
                    except Exception:
                        pass
                # Fecha driver criado pelo loader de race83, se houver
                if 'race_driver' in locals() and race_driver and 'created' in locals() and created:
                    try:
                        race_driver.quit()
                    except Exception:
                        pass

                if loader_horario:
                    event_info['horario'] = loader_horario

                if soup:
                    # Extrai edital
                    event_info['link_edital'] = extract_edital(url)

                    # Extrai horário do Ticketsports se ainda não temos
                    try:
                        if is_ticketsports_domain(domain):
                            horario_ts = extract_ticketsports_schedule(soup)
                            if horario_ts and not event_info.get('horario'):
                                event_info['horario'] = horario_ts
                        elif is_zenite_domain(domain):
                            horario_zenite = extract_zenite_schedule(soup)
                            if horario_zenite:
                                event_info['horario'] = horario_zenite
                    except Exception:
                        pass

                    try:
                        if is_ticketsports_domain(domain):
                            ts_entries = extract_ticketsports_ticket_prices(soup, debug=False)
                            # monta preco (menor e maior) e precos_entries como JSON com lista completa
                            try:
                                if ts_entries and len(ts_entries) > 0:
                                    # ts_entries are ordered by price asc; use numeric prices to build preco
                                    try:
                                        prices = [p.get('price') for p in ts_entries if isinstance(p, dict) and p.get('price') is not None]
                                    except Exception:
                                        prices = []
                                    if prices:
                                        min_price = prices[0]
                                        max_price = prices[-1]
                                        if min_price == max_price:
                                            str_preco = _fmt_price_br(min_price)
                                        else:
                                            str_preco = f"{_fmt_price_br(min_price)} a {_fmt_price_br(max_price)}"
                                    else:
                                        # fallback to formatted strings
                                        min_p = ts_entries[0].get('formatted')
                                        max_p = ts_entries[-1].get('formatted')
                                        if min_p == max_p:
                                            str_preco = min_p
                                        else:
                                            str_preco = f"{min_p} a {max_p}"
                                    # sempre monta a lista completa de entradas formatadas (JSON)
                                    try:
                                        safe_prices = []
                                        for p in ts_entries:
                                            label_atual = (p.get('label') or '').strip() or 'GERAL'
                                            preco_atual = str(p.get('formatted', '') or '')
                                            texto_formatado = f"{preco_atual} | {label_atual}"
                                            safe_prices.append(texto_formatado)
                                        json_precos_entries = json.dumps(safe_prices, ensure_ascii=False)
                                    except Exception:
                                        json_precos_entries = '[]'
                            except Exception:
                                str_preco = '; '.join(e.get('formatted', '') for e in ts_entries) or 'preço não encontrado'
                                json_precos_entries = '[]'
                            event_info['precos_entries'] = json_precos_entries
                            event_info['preco'] = str_preco
                        else:
                            entries = extract_price_entries(soup, domain)

                            try:
                                if entries and len(entries) > 0:
                                    try:
                                        prices = [p.get('price') for p in entries if isinstance(p, dict) and p.get('price') is not None]
                                    except Exception:
                                        prices = []
                                    if prices:
                                        min_price = prices[0]
                                        max_price = prices[-1]
                                        if min_price == max_price:
                                            str_preco = _fmt_price_br(min_price)
                                        else:
                                            str_preco = f"{_fmt_price_br(min_price)} a {_fmt_price_br(max_price)}"
                                    else:
                                        min_p = entries[0].get('formatted')
                                        max_p = entries[-1].get('formatted')
                                        if min_p == max_p:
                                            str_preco = min_p
                                        else:
                                            str_preco = f"{min_p} a {max_p}"
                                    try:
                                        safe_prices = []
                                        for p in entries:
                                            label_atual = (p.get('label') or '').strip() or 'GERAL'
                                            preco_atual = str(p.get('formatted', '') or '')
                                            texto_formatado = f"{preco_atual} | {label_atual}"
                                            safe_prices.append(texto_formatado)
                                        json_precos_entries = json.dumps(safe_prices, ensure_ascii=False)
                                    except Exception:
                                        json_precos_entries = '[]'
                            except Exception:
                                # fallback: tenta extrair preços numéricos das strings formatted
                                try:
                                    formatted_list = [e.get('formatted', '') for e in entries]
                                    nums = _prices_from_formatted_list(formatted_list)
                                    if nums:
                                        if len(nums) == 1:
                                            str_preco = _fmt_price_br(nums[0])
                                        else:
                                            str_preco = f"{_fmt_price_br(nums[0])} a {_fmt_price_br(nums[-1])}"
                                    else:
                                        str_preco = '; '.join(e.get('formatted', '') for e in entries) or 'preço não encontrado'
                                except Exception:
                                    str_preco = '; '.join(e.get('formatted', '') for e in entries) or 'preço não encontrado'
                                json_precos_entries = '[]'
                            event_info['precos_entries'] = json_precos_entries
                            event_info['preco'] = str_preco
                    except Exception:
                        # fallback final: marca como não encontrado
                        event_info['precos_entries'] = []
                        event_info['preco'] = 'preço não encontrado'
                else:
                    event_info['link_edital'] = 'edital não encontrado'
                    event_info['preco'] = 'preço não encontrado'
                    event_info['precos_entries'] = []
            except Exception:
                event_info['link_edital'] = 'edital não encontrado'
                event_info['preco'] = 'preço não encontrado'
                event_info['precos_entries'] = []
        else:
            event_info['link_edital'] = 'edital não encontrado'
            event_info['preco'] = 'preço não encontrado'
            event_info['precos_entries'] = []
        return event_info

    def _process_parallel(evts):
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(fetch_details, event): event for event in evts}
            results = []
            for idx, future in enumerate(as_completed(futures), 1):
                try:
                    result = future.result()
                    # Se fetch_details retornou None, significa que o evento deve ser pulado
                    if result is None:
                        continue
                    results.append(result)
                    print(f"[{idx}/{len(evts)}] ✓ {result.get('nome', '')}")
                    print(f"   Edital: {result.get('link_edital', '')[:50]}")
                    print(f"   Preço: {result.get('preco', '')}")
                except Exception:
                    event = futures[future]
                    event['link_edital'] = 'edital não encontrado'
                    event['preco'] = 'preço não encontrado'
                    results.append(event)
            return results

    from urllib.parse import urlparse as _urlparse
    tickets = [e for e in events if is_ticketsports_domain(_urlparse(e.get('link_inscricao', '')).netloc)]
    others = [e for e in events if e not in tickets]

    processed = []
    for ev in tickets:
        try:
            url = ev.get('link_inscricao', '')
            try:
                soup, created, driver, horario = load_ticketsports_soup(url, driver=None, wait_seconds=30, debug=True)
            except Exception as ex:
                soup = None
                driver = None
                horario = ''
            if soup:
                # defaults for ticket-specific processing
                str_preco = 'preço não encontrado'
                json_precos_entries = '[]'
                try:
                    ev['link_edital'] = extract_edital(url)
                except Exception:
                    ev['link_edital'] = 'edital não encontrado'
                try:
                    ts_entries = extract_ticketsports_ticket_prices(soup, debug=False)
                    # injeta horario se disponível
                    if horario and isinstance(horario, str):
                        for ent in ts_entries:
                            try:
                                if not ent.get('horario'):
                                    ent['horario'] = horario
                            except Exception:
                                pass
                    ev['precos_entries'] = ts_entries
                    # monta preco (menor e maior) e precos_entries como JSON com lista completa
                    try:
                        if ts_entries and len(ts_entries) > 0:
                            # ts_entries are ordered by price asc; use numeric prices to build preco
                            try:
                                prices = [p.get('price') for p in ts_entries if isinstance(p, dict) and p.get('price') is not None]
                            except Exception:
                                prices = []
                            if prices:
                                min_price = prices[0]
                                max_price = prices[-1]
                                if min_price == max_price:
                                    str_preco = _fmt_price_br(min_price)
                                else:
                                    str_preco = f"{_fmt_price_br(min_price)} a {_fmt_price_br(max_price)}"
                            else:
                                str_preco = 'preço não encontrado'
                                json_precos_entries = '[]'
                    except Exception:
                        str_preco = '; '.join(e.get('formatted', '') for e in ts_entries) or 'preço não encontrado'
                        json_precos_entries = '[]'
                    ev['precos_entries'] = json_precos_entries
                    ev['preco'] = str_preco
                except Exception:
                    entries = extract_price_entries(soup, urlparse(url).netloc)
                    ev['precos_entries'] = entries
                    ev['preco'] = '; '.join(en.get('formatted', '') for en in entries) or 'preço não encontrado'
                ev['horario'] = horario
            else:
                ev['link_edital'] = 'edital não encontrado'
                ev['preco'] = 'preço não encontrado'
                ev['horario'] = horario
            processed.append(ev)

            # ensure driver cleanup
            try:
                if driver:
                    driver.quit()
            except Exception:
                pass
        except Exception as e:
            processed.append(ev)

    # process remaining events in parallel
    if others:
        processed += _process_parallel(others)

    return processed

# EXTRAÇÃO DE DADOS DOS EVENTOS
def get_event_data(driver):
    """
    Extrai os dados dos eventos da página Brasil Que Corre - Paraíba.

    Implementa tentativas múltiplas de carregamento para maior robustez.
    Extrai informações básicas (nome, data, cidade, distâncias, etc.) e depois
    busca detalhes adicionais (preços e editais) em paralelo.
    """
    try:
        url = "https://brasilquecorre.com/paraiba"
        attempts = 3

        # Tenta carregar a página com múltiplas tentativas
        for attempt in range(1, attempts + 1):
            try:
                driver.set_page_load_timeout(30)
                driver.get(url)
                break  # Sucesso
            except (TimeoutException, WebDriverException) as e:
                print(f"[get_event_data] Tentativa {attempt} falhou ao carregar a página: {e}")
                # Tenta parar o carregamento e tentar novamente após breve espera
                try:
                    driver.execute_script("window.stop();")
                except Exception:
                    pass
                time.sleep(2)
                if attempt == attempts:
                    raise
                continue

        # Aguarda os elementos dos eventos aparecerem
        wait = WebDriverWait(driver, 20)
        event_boxes = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.cs-box")))

        event_data = []
        data_pattern = re.compile(r'\d{1,2}\s+de\s+[A-Za-zçÇ]+\s+de\s+\d{4}')
        time_patterns = [
            re.compile(r'(?<!\d)(\d{1,2})\s*[:hH]\s*(\d{2})(?!\d)'),
            re.compile(r'(?<!\d)(\d{1,2})\s*h\b(?!\d)')
        ]

        def normalize_time(hour_str, minute_str=None):
            try:
                h = int(hour_str)
                m = int(minute_str) if minute_str not in (None, '') else 0
            except Exception:
                return None
            if h < 0 or h > 23 or m < 0 or m > 59:
                return None
            return f"{h:02d}:{m:02d}"

        total_events = len(event_boxes)
        print(f"\nEncontrados {total_events} eventos. Iniciando extração\n")

        # Primeira iteração: extrai dados básicos de cada evento
        for idx, box in enumerate(event_boxes, 1):
            event_info = {}
            try:
                # Nome do evento e link de inscrição
                name_element = box.find_element(By.CSS_SELECTOR, "h5 a")
                event_info['nome'] = name_element.text
                event_info['link_inscricao'] = name_element.get_attribute('href')

                # Ignorar URLs redirecionadas/que não são de evento
                try:
                    link_insc = event_info.get('link_inscricao', '') or ''
                    if link_insc.startswith('https://www.liverun.com.br/calendario'):
                        print(f"[SKIP] Pulando link de calendário genérico do Liverun: {link_insc}")
                        continue
                    # Também ignora listagem genérica de eventos do Race83 (usa helper específico)
                    if is_race83_listing_url(link_insc):
                        print(f"[SKIP] Pulando link de eventos genérico do Race83: {link_insc}")
                        continue
                except Exception:
                    pass

                # Imagem do evento
                img_element = box.find_element(By.CSS_SELECTOR, "img.cs-chosen-image")
                event_info['link_imagem'] = img_element.get_attribute('src')

                # Extrai informações textuais (data, cidade, distâncias, organizador)
                text_elements = box.find_elements(By.CSS_SELECTOR, "div.text-editor p")
                distancias_encontradas = []
                horarios_encontrados = []

                horario_pattern = re.compile(r'hor[áa]?rio(?:\s+de\s+largada)?[^\d]{0,20}(\d{1,2})\s*[:hH]\s*(\d{0,2})', re.IGNORECASE)

                for idx_elem, element in enumerate(text_elements):
                    text = element.text.strip()
                    if text and not text.isspace():
                        if data_pattern.search(text):
                            event_info['data'] = text
                        elif any(term in text for term in
                                 ['(corrida)', '(caminhada)', '(trail)', '(ultra)', '(infantil)']):
                            distancias_encontradas.append(text)
                        elif idx_elem == len(text_elements) - 1:
                            event_info['organizador'] = text
                        elif 'cidade' not in event_info:
                            event_info['cidade'] = text

                        m = horario_pattern.search(text)
                        if m:
                            hora = m.group(1)
                            minuto = m.group(2) or '00'
                            horario_fmt = normalize_time(hora, minuto)
                            if horario_fmt and horario_fmt not in horarios_encontrados:
                                horarios_encontrados.append(horario_fmt)

                        for pat in time_patterns:
                            for match in pat.finditer(text):
                                hora = match.group(1)
                                minuto = match.group(2) if match.lastindex and match.lastindex >= 2 else None
                                horario_fmt = normalize_time(hora, minuto)
                                if horario_fmt and horario_fmt not in horarios_encontrados:
                                    horarios_encontrados.append(horario_fmt)

                if distancias_encontradas:
                    event_info['distancia'] = ', '.join(distancias_encontradas)
                if horarios_encontrados:
                    event_info['horario'] = ', '.join(horarios_encontrados)
                else:
                    event_info['horario'] = ''

                event_data.append(event_info)
                print(f"[{idx}/{total_events}] ✓ Dados básicos: {event_info.get('nome', '')}")

            except Exception as e:
                continue

        # Segunda iteração: busca editais e preços em paralelo
        print(f"\nBuscando editais e preços...\n")
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
    1. Configura o driver Selenium
    2. Extrai dados dos eventos
    3. Salva em CSV
    """
    driver = setup_driver()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(base_dir, 'data/eventos_brasilquecorre.csv')

    try:
        event_data = get_event_data(driver)

        if not event_data:
            print("Nenhum evento encontrado ou ocorreu um erro.")
            return

        print(f"\nTotal de {len(event_data)} eventos encontrados. Salvando no CSV...")

        # Salva dados em CSV
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['Nome do Evento', 'Link de Inscrição', 'Link da Imagem', 'Data', 'Horário', 'Cidade', 'Distância',
                          'Organizador', 'Preço', 'Link do Edital', 'precos_entries']
            writer = csv.writer(csvfile, delimiter=';')
            writer.writerow(fieldnames)

            for event in event_data:
                writer.writerow([
                    event.get('nome', ''),
                    event.get('link_inscricao', ''),
                    event.get('link_imagem', ''),
                    event.get('data', ''),
                    event.get('horario', ''),
                    event.get('cidade', ''),
                    event.get('distancia', ''),
                    event.get('organizador', ''),
                    event.get('preco', ''),
                    event.get('link_edital', ''),
                    event.get('precos_entries', '')
                ])

        print(f"\nDados salvos com sucesso em: {csv_path}")

        # Tenta sincronizar o CSV para o MongoDB Atlas
        try:
            from data_collection.utils import ImportToDB as sync_module
            try:
                sync_module.import_csv_to_mongodb(sync_module.remote_db, csv_path, 'brasilquecorre')
            except Exception as e:
                print(f"Falha ao sincronizar CSV para MongoDB: {e}")
        except Exception as e:
            print(f"Sincronização com MongoDB ignorada (import failed): {e}")

    finally:
        driver.quit()

if __name__ == "__main__":
    main()