import csv
import re
import os
import json
import time
from urllib.parse import urlparse
import logging
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

import requests
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

from data_collection.core.Driver import setup_driver
from data_collection.sources.Sympla import is_sympla_domain, load_sympla_soup
from data_collection.sources.Liverun import is_liverun_domain, load_liverun_soup
from data_collection.sources.CircuitoDasEstacoes import is_circuito_domain, load_circuito_soup, extract_circuito_ticket_prices
from data_collection.sources.Race83 import is_race83_domain, is_race83_listing_url, detect_redirects_to_listing, load_race83_soup
from data_collection.sources.Ticketsports import is_ticketsports_domain, load_ticketsports_soup, extract_ticketsports_ticket_prices, extract_ticketsports_schedule
from data_collection.sources.Nightrun import is_nightrun_domain, load_nightrun_soup
from data_collection.sources.Zenite import is_zenite_domain, load_zenite_soup, extract_zenite_schedule
from data_collection.utils.PriceUtils import parse_price_str, fmt_entry
from data_collection.utils.PrizeDetection import entry_is_prize


def _get_http_session():
    """Cria sessão requests com retry automático e User-Agent.
    
    Implementa:
    - Retry com backoff exponencial (3 tentativas, espera 1s, 2s, 4s)
    - User-Agent customizado para evitar bloqueios
    - Timeout padrão de 10s
    - Reúsa conexões TCP/HTTP para performance
    """
    session = requests.Session()
    
    # User-Agent comum para não ser bloqueado como bot
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    })
    
    # Retry automático com backoff exponencial
    retry_strategy = Retry(
        total=3,  # Máximo de 3 tentativas
        status_forcelist=[429, 500, 502, 503, 504],  # Retry em rate limit e erros de servidor
        allowed_methods=['GET', 'POST'],  # Métodos para retentar
        backoff_factor=1  # Espera: 1s, 2s, 4s
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    
    return session


_global_session = _get_http_session()
_last_request_time = {}  # Rastreia último request por domínio para rate limiting


def _get_with_rate_limit(url, timeout=10):
    """Realiza GET com retry automático e rate limiting por domínio.
    
    Args:
        url: URL a acessar
        timeout: Timeout em segundos (padrão 10s)
    
    Returns:
        Response object ou None se falhar após retries
    """
    try:
        domain = urlparse(url).netloc
        
        # Rate limiting: aguarda 0.5s entre requisições ao mesmo domínio
        if domain in _last_request_time:
            elapsed = time.time() - _last_request_time[domain]
            if elapsed < 0.5:
                time.sleep(0.5 - elapsed)
        
        _last_request_time[domain] = time.time()
        
        response = _global_session.get(url, timeout=timeout)
        response.raise_for_status()
        return response
    except Exception as e:
        logger.warning(f"Erro ao acessar {url}: {e}")
        return None


def _safe_quit(driver):
    """Fecha o driver Selenium sem propagar exceções."""
    try:
        if driver:
            driver.quit()
    except Exception:
        pass


def _strip_accents(s):
    """Remove acentos/diacríticos de uma string para buscas normalizadas."""
    import unicodedata
    if not s:
        return ''
    s = unicodedata.normalize('NFD', s)
    return ''.join(ch for ch in s if not unicodedata.category(ch).startswith('M'))


def _normalize_time(raw_time: str) -> str:
    """Normaliza uma string de hora (ex: '4h30', '04:30', '4:30') para 'HH:MM'. Retorna '' se inválida."""
    if not raw_time:
        return ''
    normalized = raw_time.replace('h', ':').replace('H', ':')
    if ':' in normalized:
        parts = normalized.split(':')
        hour = parts[0]
        minute = parts[1] if len(parts) > 1 and parts[1] else '00'
    else:
        hour = normalized
        minute = '00'
    try:
        h = int(hour)
        m = int(minute)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
    except Exception:
        return ''
    return ''


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
        return ''

    # 1) DD/MM/YYYY - HH:MM
    m = re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\s*[-–—]\s*(\d{1,2}(?:[:hH]\d{2})?)(?:\s*[hH])?\b", text)
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
        mm = m.group(2) or '00'
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

    return ''


def _entries_to_json(entries):
    """Serializa entradas de preço em uma lista JSON segura, sem calcular resumo."""
    if not entries:
        return '[]'
    safe_prices = []
    for p in entries:
        formatted = None
        if isinstance(p, str):
            formatted = p.strip()
        elif isinstance(p, dict):
            label_atual = (p.get('label') or '').strip() or 'GERAL'
            formatted = (p.get('formatted') or '').strip()
            if not formatted:
                price_val = p.get('price')
                if price_val is not None:
                    try:
                        price_s = f"R$ {float(price_val):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
                    except Exception:
                        price_s = f"R$ {price_val}"
                    formatted = f"{label_atual} — {price_s}"
        if formatted:
            safe_prices.append(formatted)
    try:
        return json.dumps(safe_prices, ensure_ascii=False) if safe_prices else '[]'
    except Exception:
        return '[]'

#Extração de preços
def extract_price_entries(soup, domain, driver=None):
    """
    Retorna uma lista de entradas de preço estruturadas encontradas na página.

    Cada entrada é um dict ou uma string formatada. Em casos específicos (ex: NightRun), o extractor
    pode devolver diretamente valores como '5KM - 69,90'.
    
    NOTA: page_html é criado sob demanda (lazy) para evitar duplicar memória do objeto soup
    inteiro, e é deletado após uso para permitir garbage collection.
    """
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
                if driver:
                    try:
                        raw_prices = extract_nightrun_ticket_prices(driver)
                        if raw_prices:
                            return raw_prices
                    except Exception:
                        pass
            if 'extract_zenite_ticket_prices' in locals() and extract_zenite_ticket_prices and is_zenite_domain(domain):
                return extract_zenite_ticket_prices(soup)
            if is_circuito_domain(domain) and driver:
                prices = extract_circuito_ticket_prices(driver)
                if prices:
                    return prices
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
    # Cria page_html apenas quando necessário para evitar duplicar memória do objeto soup inteiro
    page_html = str(soup)
    try:
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
    except Exception:
        # Se regex fallback falhar, continua com autres testes
        pass

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
    # Rastreia preços descartados para debug de problemas de parsing
    discarded_prices = []
    valid_entries = []
    
    for e in candidates:
        price = e.get('price')
        
        if price is None:
            # Valores None são esperados, apenas continua
            continue
        
        # Verifica se preço está fora do intervalo válido
        if not (0 <= price <= 500):
            discarded_prices.append({
                'price': price,
                'label': e.get('label'),
                'raw': e.get('raw'),
                'reason': 'fora do intervalo [0, 500]'
            })
            # Log se preço é negativo (possível bug de parsing)
            if price < 0:
                logger.warning(f"Preco negativo descartado: {e}. Possivelmente bug em parse_price_str().")
            continue
        
        valid_entries.append(e)
    
    # Log resumo se muitos preços foram descartados
    if discarded_prices and len(discarded_prices) > len(valid_entries):
        logger.info(f"Descartados {len(discarded_prices)} precos invalidos contra {len(valid_entries)} validos. Precos descartados: {discarded_prices[:3]}")

    # Se há preços pagos, exclui entradas gratuitas (0.00) para evitar falsos positivos
    if any(e['price'] > 0 for e in valid_entries):
        valid_entries = [e for e in valid_entries if e['price'] > 0]

    if not valid_entries:
        # Se não há preços pagos, verifica indicadores de gratuito
        if re.search(r'\b(grátis|gratis|gratuito|gratuita|isento|free)\b', page_html, re.IGNORECASE):
            return [{'label': None, 'price': 0.0, 'tax': None, 'formatted': 'R$ 0,00', 'raw': page_html}]
        # Se não foi encontrado indicador de gratuidade, devolve uma entry informativa
        # para que o campo legível de valor seja preenchido com 'Valor não encontrado'.
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

    result = [fmt_entry(e) for e in unique_sorted]
    
    # Libera memória de page_html se foi criado
    if 'page_html' in locals():
        del page_html
    
    return result

#Extração de edital
def extract_edital(url):
    """Extrai o link do edital usando requests com retry automático."""
    try:
        response = _get_with_rate_limit(url, timeout=10)
        if not response:
            return 'edital não encontrado'
        
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
    Processa editais e preços de múltiplos eventos sequencialmente.
    """
    if not events:
        return []
    def fetch_details(event_info):
        """Busca detalhes de um evento específico (edital e preços)."""
        evt = dict(event_info)
        url = evt.get('link_inscricao', '') or ''
        if not url:
            evt.setdefault('link_edital', 'edital não encontrado')
            evt.setdefault('precos_entries', '[]')
            return evt

        domain = urlparse(url).netloc
        horario = (evt.get('horario') or '').strip()
        drivers_to_close = []
        current_driver = None  # Rastreia driver da sessão atual para extract_price_entries

        def _safe_register_driver(driver):
            """Registra driver para fechamento garantido, mesmo se exceção ocorrer."""
            if driver:
                drivers_to_close.append(driver)
            return driver

        try:
            # Trata redirecionamentos do Race83 que levam para listagem
            if is_race83_domain(domain):
                try:
                    is_listing, final = detect_redirects_to_listing(url, timeout=5)
                    if is_listing:
                        print(f"[SKIP] URL do Race83 redirecionou para listagem /eventos, pulando: {url} -> {final}")
                        return None
                except Exception:
                    pass

            soup = None
            if is_sympla_domain(domain):
                try:
                    soup, _, driver = load_sympla_soup(url)
                    current_driver = _safe_register_driver(driver)
                except Exception:
                    soup = None
            elif is_circuito_domain(domain):
                try:
                    soup, _, driver, loader_horario = load_circuito_soup(url)
                    current_driver = _safe_register_driver(driver)
                    if loader_horario:
                        horario = horario or loader_horario
                except Exception:
                    soup = None
            elif is_liverun_domain(domain):
                try:
                    soup, _, driver = load_liverun_soup(url)
                    current_driver = _safe_register_driver(driver)
                except Exception:
                    soup = None
            elif is_race83_domain(domain):
                try:
                    soup, _, driver = load_race83_soup(url)
                    current_driver = _safe_register_driver(driver)
                except Exception:
                    soup = None
            elif is_ticketsports_domain(domain):
                try:
                    soup, _, driver, loader_horario = load_ticketsports_soup(url, driver=None, wait_seconds=30, debug=False)
                    current_driver = _safe_register_driver(driver)
                    if loader_horario:
                        horario = horario or loader_horario
                except Exception:
                    soup = None
            elif is_nightrun_domain(domain):
                try:
                    soup, _, driver, nightrun_schedule = load_nightrun_soup(url, driver=None, wait_seconds=30)
                    current_driver = _safe_register_driver(driver)
                    if nightrun_schedule:
                        horario = horario or nightrun_schedule
                except Exception:
                    soup = None
            elif is_zenite_domain(domain):
                try:
                    soup, _, driver, loader_horario = load_zenite_soup(url, driver=None, wait_seconds=30)
                    current_driver = _safe_register_driver(driver)
                    if loader_horario:
                        horario = horario or loader_horario
                except Exception:
                    soup = None
            else:
                try:
                    response = _get_with_rate_limit(url, timeout=10)
                    if response:
                        soup = BeautifulSoup(response.text, 'html.parser')
                    else:
                        soup = None
                except Exception:
                    soup = None

            if soup:
                try:
                    evt['link_edital'] = extract_edital(url)
                except Exception:
                    evt['link_edital'] = 'edital não encontrado'

                try:
                    if is_ticketsports_domain(domain) and not horario:
                        horario = extract_ticketsports_schedule(soup)
                    elif is_zenite_domain(domain) and not horario:
                        horario = extract_zenite_schedule(soup)
                    if not horario:
                        page_text = soup.get_text(' ', strip=True)
                        extracted = extract_time_from_text(page_text)
                        if extracted:
                            horario = extracted
                except Exception:
                    pass

                try:
                    entries = extract_ticketsports_ticket_prices(soup, debug=False) if is_ticketsports_domain(domain) else extract_price_entries(soup, domain, current_driver)
                except Exception:
                    entries = []

                evt['precos_entries'] = _entries_to_json(entries)
                if horario:
                    evt['horario'] = horario
                
                # Libera memória do objeto soup para evitar memory leak
                del soup
            else:
                evt['link_edital'] = 'edital não encontrado'
                evt['precos_entries'] = '[]'
                if horario:
                    evt['horario'] = horario

            return evt
        except Exception:
            evt['link_edital'] = 'edital não encontrado'
            evt['precos_entries'] = '[]'
            if horario:
                evt['horario'] = horario
            return evt
        finally:
            # Garantir fechamento de todos drivers mesmo se exceção ocorreu
            for drv in drivers_to_close:
                _safe_quit(drv)

    def _process_sequential(evts):
        """Processa eventos sequencialmente para evitar race conditions com Selenium.
        """
        if not evts:
            return []
        
        results = []
        total = len(evts)
        for idx, event in enumerate(evts, 1):
            try:
                result = fetch_details(dict(event))
                if result is None:
                    continue
                results.append(result)
                print(f"[{idx}/{total}] OK {result.get('nome', '')}")
                print(f"   Edital: {result.get('link_edital', '')[:50]}")
            except Exception:
                logger.exception(f"Erro ao processar evento: {event.get('nome', 'N/A')}")
                event = dict(event)
                event['link_edital'] = 'edital não encontrado'
                event['precos_entries'] = '[]'
                results.append(event)
        
        return results

    tickets = []
    others = []
    for ev in events:
        try:
            dom = urlparse(ev.get('link_inscricao', '')).netloc
        except Exception:
            dom = ''
        if is_ticketsports_domain(dom):
            tickets.append(ev)
        else:
            others.append(ev)

    # Processar sequencialmente em vez de paralelo para evitar race conditions com Selenium
    processed = []
    processed += _process_sequential(tickets)
    processed += _process_sequential(others)

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

                full_text = ' '.join([el.text for el in text_elements]) if text_elements else (box.text if hasattr(box, 'text') else '')
                extracted_time = extract_time_from_text(full_text)
                if extracted_time:
                    event_info['horario'] = extracted_time

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
                if not event_info.get('horario'):
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
                          'Organizador', 'Link do Edital', 'precos_entries']
            writer = csv.writer(csvfile, delimiter=';')
            writer.writerow(fieldnames)

            for event in event_data:
                writer.writerow([
                    event.get('nome', ''),
                    event.get('link_inscricao', ''),
                    event.get('link_imagem', ''),
                    event.get('data', ''),
                    (event.get('horario') or 'Horário de largada não encontrado'),
                    event.get('cidade', ''),
                    event.get('distancia', ''),
                    event.get('organizador', ''),
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
