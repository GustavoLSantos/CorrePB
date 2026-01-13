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

def open_regulation_modals(driver):
    """
    Detecta modais relacionados a regulamento/preços e tenta abri-los.
    - Analisa o HTML inicial procurando por elementos com id/class contendo 'modal' e
      palavras-chave como 'regul', 'regulation', 'regulamento', ou que contenham uma <ul>
      com itens que mencionam 'lote' ou 'R$'.
    - Para cada modal candidato tenta localizar um gatilho (a[href="#id"], [data-target="#id"], #btn-modal)
      e clicar; se não houver gatilho, força exibição via JS (display/block + add 'show').
    - Aguarda brevemente para que o conteúdo fique disponível.
    """
    try:
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        # procura por possíveis modais cujo id contenha 'modal' + palavra regulatória
        modal_candidates = []
        for elem in soup.find_all(attrs={'id': re.compile(r'.*modal.*', re.IGNORECASE)}):
            mid = elem.get('id')
            text = ' '.join(elem.stripped_strings) or ''
            # heurística: id ou texto que sugira regulamento/price list
            if re.search(r'regul|regulation|regulamento|rule|reglas|reglamento', mid, re.IGNORECASE) or re.search(r'regul|lote|lotes|R\$', text, re.IGNORECASE):
                modal_candidates.append(mid)

        # também busca por elementos com classe 'modal' que contenham <ul> com 'lote' ou 'R$'
        for m in soup.select('.modal'):
            inner = ' '.join(m.stripped_strings) or ''
            if re.search(r'lote|lotes|R\$|regul', inner, re.IGNORECASE):
                mid = m.get('id')
                if mid:
                    modal_candidates.append(mid)

        # dedup
        modal_candidates = list(dict.fromkeys([m for m in modal_candidates if m]))

        for mid in modal_candidates:
            try:
                # tenta encontrar e clicar gatilho
                tried = False
                selectors = [f'a[href="#{mid}"]', f'[data-target="#{mid}"]', f'button[data-target="#{mid}"]', f'a[href*="#{mid}"]', '#btn-modal']
                for sel in selectors:
                    try:
                        elems = driver.find_elements(By.CSS_SELECTOR, sel)
                    except Exception:
                        elems = []
                    for el in elems:
                        try:
                            el.click()
                            tried = True
                            time.sleep(0.4)
                            break
                        except Exception:
                            try:
                                driver.execute_script("arguments[0].dispatchEvent(new MouseEvent('click', {bubbles:true}));", el)
                                tried = True
                                time.sleep(0.4)
                                break
                            except Exception:
                                pass
                    if tried:
                        break

                if not tried:
                    # força exibição via JS
                    try:
                        driver.execute_script("var m=document.getElementById('%s'); if(m){ m.style.display='block'; m.classList.add('show'); }" % mid)
                        time.sleep(0.4)
                    except Exception:
                        pass

                # aguarda se possível a presença de uma UL dentro do modal
                try:
                    WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.CSS_SELECTOR, f'#{mid} ul')))
                    time.sleep(0.2)
                except Exception:
                    # não encontrou UL, segue
                    pass
            except Exception:
                continue
    except Exception:
        return


def parse_price_str(text):
    """
    Normaliza uma string de preço e retorna float ou None.

    Lida com separadores de milhares (.) e decimais (,) ou (.).
    Exemplos: '1.234,56' -> 1234.56, '89,90' -> 89.9, '50' -> 50.0
    """
    if not text:
        return None
    s = re.sub(r'[^\d.,]', '', str(text))
    if not s:
        return None

    # Se ambos separadores presentes, assume '.' para milhares e ',' para decimais
    if '.' in s and ',' in s:
        s = s.replace('.', '').replace(',', '.')
    # Se apenas '.' presente e último grupo não tem 2 dígitos, provavelmente é separador de milhares
    elif '.' in s and len(s.split('.')[-1]) != 2:
        s = s.replace('.', '')
    # Substitui vírgula decimal por ponto
    s = s.replace(',', '.')

    try:
        return float(s)
    except Exception:
        return None


def is_prize_text(text):
    """
    Detecta se um candidato a preço é provavelmente um prêmio/premiação,
    não uma taxa de inscrição.
    """
    if not text:
        return False
    text_l = text.lower()

    # Palavras-chave diretas relacionadas a prêmios
    if re.search(r'\b(prêmio|premiação|premio|prize|award|prêmios|premiações|awards)\b', text_l):
        return True

    # Padrões como "lugar", "colocado", "classificado" com preço
    if re.search(r'\b(lugar|colocado|classificado|classificação|ranking|posição|podium|pódio)\b', text_l):
        return True

    # Padrões como "destinada a quantia", "será destinada", "distribuída da seguinte forma"
    if re.search(r'(destinada a quantia|será destinada|distribuída da seguinte forma)', text_l):
        return True

    # Padrões como "masculino e feminino", "prova de", "km" com preço
    if re.search(r'(masculino|feminino|prova de|km)', text_l) and re.search(r'R\$\s*[\d.,]+', text_l):
        return True

    return False


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

    #Tenta seletores CSS explícitos usados por circuitodasestacoes e similares
    try:
        selectors = ['.kit-price-desktop', '.kit-price-wrapper-desktop p', '.kit-price-wrapper-desktop']
        for sel in selectors:
            for elem in soup.select(sel):
                txt = elem.get_text(separator=' ', strip=True)
                if 'R$' in txt:
                    for m in re.findall(r'R\$(?:\s|\xa0|&nbsp;)*([\d.,]+)', txt):
                        v = parse_price_str(m)
                        candidates.append({'label': None, 'price': v, 'tax': None, 'raw': txt})
    except Exception:
        pass

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

    #Items de ticket-grid (estruturado, comum em Sympla e similares)
    try:
        for grid in soup.find_all(attrs={'data-testid': re.compile(r'ticket-grid', re.IGNORECASE)}):
            items = grid.find_all(attrs={'data-testid': re.compile(r'ticket-grid-item', re.IGNORECASE)})
            if not items:
                items = grid.find_all(True, recursive=False)
            for item in items:
                # Tenta encontrar um label/título dentro do item
                label = None
                for candidate in item.find_all(['h5', 'strong', 'span', 'div']):
                    t = candidate.get_text(separator=' ', strip=True)
                    if t and 'R$' not in t and not re.match(r'^[\d\s,-/]+$', t):
                        label = t
                        break
                item_text = item.get_text(separator=' ', strip=True)
                for m in re.findall(r'R\$(?:\s|\xa0|&nbsp;)*([\d.,]+)', item_text):
                    v = parse_price_str(m)
                    tax = None
                    tax_m = re.search(r'\(\s*\+?([\d.,]+)\s*(?:taxa|tax|fee)\s*\)', item_text, re.IGNORECASE)
                    if tax_m:
                        tax = parse_price_str(tax_m.group(1))
                    candidates.append({'label': label, 'price': v, 'tax': tax, 'raw': item_text})
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
    def entry_is_prize(entry):
        raw = (entry.get('raw') or '').lower()
        label = (entry.get('label') or '')
        if is_prize_text(raw) or is_prize_text(label):
            return True

        # Se temos um preço numérico, procura ocorrências deste preço no HTML da página
        # e verifica uma janela de contexto ao redor de cada ocorrência para palavras-chave de prêmio.
        price = entry.get('price')
        if price is None:
            return False
        try:
            pv = float(price)
        except Exception:
            return False

        # Constrói variantes de string comuns para corresponder como preços aparecem na página
        # Formato brasileiro (1.234,56) e decimal com ponto (1234.56)
        price_br = f"{pv:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        price_dot = f"{pv:.2f}"

        # Padrões que podem aparecer: 'R$ 50,00', '50,00 reais', ou apenas '50,00'
        patterns = [
            rf"R\$\s*{re.escape(price_br)}",
            rf"R\$\s*{re.escape(price_dot)}",
            rf"{re.escape(price_br)}\s*reais",
            rf"{re.escape(price_dot)}\s*reais",
            rf"{re.escape(price_br)}",
            rf"{re.escape(price_dot)}",
        ]

        prize_context_re = re.compile(
            r"\b(prêmio|premiação|premio|prize|award|prêmios|premiações|awards|"
            r"lugar|colocado|classificado|classificação|posição|podium|pódio|"
            r"destinada a quantia|será destinada|distribuída da seguinte forma)\b",
            re.IGNORECASE
        )

        for pat in patterns:
            for m in re.finditer(pat, page_html, re.IGNORECASE):
                start = max(0, m.start() - 120)
                end = min(len(page_html), m.end() + 120)
                context = page_html[start:end]
                if prize_context_re.search(context):
                    return True
        return False

    candidates = [e for e in candidates if not entry_is_prize(e)]

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
        return []

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

    def fmt_entry(e):
        """Formata uma entrada de preço para exibição."""
        v = e.get('price')
        tax = e.get('tax')
        label = (e.get('label') or '').strip()
        price_s = f"R$ {v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        if tax is not None:
            tax_s = f"(+{tax:,.2f} taxa)".replace(',', 'X').replace('.', ',').replace('X', '.')
            if label:
                formatted = f"{label} — {price_s} {tax_s}"
            else:
                formatted = f"{price_s} {tax_s}"
        else:
            if label:
                formatted = f"{label} — {price_s}"
            else:
                formatted = f"{price_s}"
        return {
            'label': label or None,
            'price': float(v),
            'tax': float(tax) if tax is not None else None,
            'formatted': formatted,
            'raw': e.get('raw')
        }

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
            try:
                domain = urlparse(url).netloc
                soup = None

                # Sites que requerem JavaScript precisam de Selenium
                if 'circuitodasestacoes.com' in domain or 'sympla' in domain or 'liverun' in domain:
                    # Reutiliza a configuração centralizada do Selenium via setup_driver()
                    temp_driver = setup_driver()
                    try:
                        temp_driver.get(url)
                        # Aguarda seletor adequado dependendo do site
                        # Sympla usa ticket-grid
                        if 'sympla' in domain:
                            wait_selector = '[data-testid="ticket-grid"]'
                            WebDriverWait(temp_driver, 30).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector))
                            )
                            # scroll leve para forçar carregamento lazy
                            try:
                                temp_driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
                                time.sleep(1)
                            except Exception:
                                pass
                        # LiveRun: precisa abrir o modal com id 'modal-regulation' para exibir a <ul> de preços
                        elif 'liverun' in domain:
                            # tenta clicar no gatilho do modal usando seletores comuns
                            try:
                                trigger = None
                                try:
                                    # incluir seletor do botão específico #btn-modal entre os candidatos
                                    trigger = temp_driver.find_element(By.CSS_SELECTOR, '[data-toggle="modal"], [data-target="#modal-regulation"], a[href="#modal-regulation"], button[data-target="#modal-regulation"], #btn-modal')
                                except Exception:
                                    # procura por links/anchors que contenham '#modal-regulation' no href
                                    try:
                                        trigger = temp_driver.find_element(By.XPATH, "//a[contains(@href, '#modal-regulation') or contains(@data-target, 'modal-regulation')]")
                                    except Exception:
                                        trigger = None
                                if trigger:
                                    try:
                                        trigger.click()
                                    except Exception:
                                        # fallback pra dispatch de evento via JS
                                        try:
                                            temp_driver.execute_script("arguments[0].dispatchEvent(new MouseEvent('click', {bubbles:true}));", trigger)
                                        except Exception:
                                            pass
                                else:
                                    # se não encontrou gatilho, força exibição do modal pelo DOM
                                    try:
                                        temp_driver.execute_script("var m=document.getElementById('modal-regulation'); if(m){ m.style.display='block'; m.classList.add('show'); }")
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                            # aguarda a UL dentro do modal ficar disponível
                            try:
                                WebDriverWait(temp_driver, 15).until(
                                    EC.presence_of_element_located((By.CSS_SELECTOR, '#modal-regulation ul'))
                                )
                                time.sleep(0.5)
                            except Exception:
                                # não achou a ul, mas segue em frente para capturar o que estiver disponível
                                pass
                        else:
                            WebDriverWait(temp_driver, 20).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, ".kit-price-desktop"))
                            )
                        # tenta abrir modais de regulamento/genéricos que contenham listas de preços
                        try:
                            open_regulation_modals(temp_driver)
                        except Exception:
                            pass
                        soup = BeautifulSoup(temp_driver.page_source, 'html.parser')
                    finally:
                        temp_driver.quit()
                else:
                    # Sites estáticos podem usar requests simples
                    response = requests.get(url, timeout=5)
                    soup = BeautifulSoup(response.text, 'html.parser')

                if soup:
                    # Extrai edital
                    event_info['link_edital'] = extract_edital(url)

                    # Extrai preços estruturados e formatados
                    entries = extract_price_entries(soup, domain)
                    event_info['precos_entries'] = entries

                    # String legível para humanos (compatibilidade retroativa)
                    if entries:
                        event_info['preco'] = '; '.join(e.get('formatted', '') for e in entries)
                    else:
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

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_details, event): event for event in events}
        results = []
        for idx, future in enumerate(as_completed(futures), 1):
            try:
                result = future.result()
                results.append(result)
                print(f"[{idx}/{len(events)}] ✓ {result.get('nome', '')}")
                print(f"   Edital: {result.get('link_edital', '')[:50]}")
                print(f"   Preço: {result.get('preco', '')}")
            except Exception as e:
                event = futures[future]
                event['link_edital'] = 'edital não encontrado'
                event['preco'] = 'preço não encontrado'
                results.append(event)
        return results

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

                # Imagem do evento
                img_element = box.find_element(By.CSS_SELECTOR, "img.cs-chosen-image")
                event_info['link_imagem'] = img_element.get_attribute('src')

                # Extrai informações textuais (data, cidade, distâncias, organizador)
                text_elements = box.find_elements(By.CSS_SELECTOR, "div.text-editor p")
                distancias_encontradas = []

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

                if distancias_encontradas:
                    event_info['distancia'] = ', '.join(distancias_encontradas)

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
    csv_path = os.path.join(base_dir, 'eventos_brasilquecorre.csv')

    try:
        event_data = get_event_data(driver)

        if not event_data:
            print("Nenhum evento encontrado ou ocorreu um erro.")
            return

        print(f"\nTotal de {len(event_data)} eventos encontrados. Salvando no CSV...")

        # Salva dados em CSV
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['Nome do Evento', 'Link de Inscrição', 'Link da Imagem', 'Data', 'Cidade', 'Distância',
                          'Organizador', 'Preço', 'Link do Edital']
            writer = csv.writer(csvfile, delimiter=';')
            writer.writerow(fieldnames)

            for event in event_data:
                writer.writerow([
                    event.get('nome', ''),
                    event.get('link_inscricao', ''),
                    event.get('link_imagem', ''),
                    event.get('data', ''),
                    event.get('cidade', ''),
                    event.get('distancia', ''),
                    event.get('organizador', ''),
                    event.get('preco', ''),
                    event.get('link_edital', '')
                ])

        print(f"\nDados salvos com sucesso em: {csv_path}")

    finally:
        driver.quit()

if __name__ == "__main__":
    main()