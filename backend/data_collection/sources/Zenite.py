import re
import time
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from data_collection.core.Driver import setup_driver


def is_zenite_domain(domain: str) -> bool:
    """Retorna True se o domínio pertence ao Zenite."""
    if not domain:
        return False
    return 'zeniteesportes.com' in domain.lower()


def load_zenite_soup(url: str, driver=None, wait_seconds: int = 30, debug: bool = False):
    """
    Carrega a página do Zenite com Selenium e retorna o soup.
    Retorna (soup, created, driver, horario)
    """
    created = False
    local_driver = driver
    horario = ''
    try:
        if local_driver is None:
            local_driver = setup_driver()
            created = True

        local_driver.set_page_load_timeout(60)
        local_driver.get(url)

        # Aguarda algum elemento específico, se necessário
        try:
            WebDriverWait(local_driver, wait_seconds).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'span.disc1'))
            )
        except Exception:
            pass

        local_driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        time.sleep(2)
        local_driver.execute_script('window.scrollTo(0, 0);')
        time.sleep(1)

        soup = BeautifulSoup(local_driver.page_source, 'html.parser')
        horario = extract_zenite_schedule(soup)

        return soup, created, local_driver, horario
    except Exception as e:
        if debug:
            print(f"Erro ao carregar Zenite: {e}")
        try:
            if created and local_driver:
                try:
                    local_driver.quit()
                except Exception:
                    pass
                created = False
        except Exception:
            pass
        return None, created, None, horario


def extract_zenite_schedule(soup) -> str:
    if not soup:
        return ''


    try:
        for li in soup.find_all('li'):
            span_disc = li.find('span', class_='disc')
            if not span_disc:
                continue
            label_txt = (span_disc.get_text() or '').strip().lower()
            if 'data' in label_txt and 'corrida' in label_txt:
                span1 = li.find('span', class_='disc1')
                if span1:
                    txt = (span1.get_text() or '').strip()
                    m = re.search(r'(\d{1,2}):(\d{2})', txt)
                    if m:
                        try:
                            h = int(m.group(1))
                            mi = int(m.group(2))
                            if 0 <= h <= 23 and 0 <= mi <= 59:
                                return f"{h:02d}:{mi:02d}"
                        except Exception:
                            pass

    except Exception:
        pass

    span = soup.find('span', class_='disc1')
    if not span:
        return ''

    text = (span.get_text() or '').strip()
    if text:
        m = re.search(r'(\d{1,2}):(\d{2})', text)
        if m:
            try:
                h = int(m.group(1))
                mi = int(m.group(2))
                if 0 <= h <= 23 and 0 <= mi <= 59:
                    return f"{h:02d}:{mi:02d}"
            except Exception:
                pass

    return ''


def extract_zenite_ticket_prices(soup, debug: bool = False):
    """Extrai preços do Zenite a partir do HTML renderizado.

    Procura por <span class="pro_price">R$70,00</span> e variações. Retorna lista de
    entradas formatadas com `fmt_entry` (ver `data_collection.utils.PriceUtils`).
    """
    from data_collection.utils.PriceUtils import fmt_entry, parse_price_str
    import re

    candidates = []
    if not soup:
        return []

    # Seleciona spans que contenham a classe pro_price (padrão informado)
    def has_pro_price(c):
        try:
            return c and 'pro_price' in c
        except Exception:
            return False

    price_elems = soup.find_all('span', class_=has_pro_price)

    for pe in price_elems:
        txt = pe.get_text(separator=' ', strip=True) or ''
        if debug:
            print(f"[zenite] candidato raw: {txt}")

        price = None
        tax = None

        # Padrão principal: R$ 123,45
        m = re.search(r'R\$\s*([\d.,]+)', txt)
        if m:
            price = parse_price_str(m.group(1))
        else:
            # Fallback: tenta extrair qualquer número que pareça preço
            price = parse_price_str(txt)

        # Detecta taxa explícita no texto: '+ R$ 8,80' ou '(+8,80 taxa)'
        tax_m = re.search(r'\+\s*R\$\s*([\d.,]+)', txt)
        if tax_m:
            tax = parse_price_str(tax_m.group(1))
        else:
            tax_m2 = re.search(r'\(\s*\+?([\d.,]+)\s*(?:taxa|tax|fee)\s*\)', txt, re.IGNORECASE)
            if tax_m2:
                tax = parse_price_str(tax_m2.group(1))

        candidates.append({'label': None, 'price': price, 'tax': tax, 'raw': txt})

    # Dedup e filtro básico (mesma lógica usada em outros extractors)
    unique = []
    seen = set()
    for e in candidates:
        try:
            key = (e.get('label') or '', float(e.get('price') if e.get('price') is not None else -1), e.get('tax') if e.get('tax') is None else float(e.get('tax')))
        except Exception:
            key = (e.get('label') or '', e.get('price'), e.get('tax'))
        if key in seen:
            continue
        seen.add(key)

        # Filtra preços irracionais (mantém 0..500 como no scraper principal)
        p = e.get('price')
        try:
            if p is not None and (p < 0 or p > 500):
                if debug:
                    print(f"[zenite] descartando por range: {p} ({e.get('raw')})")
                continue
        except Exception:
            pass

        unique.append(e)

    # Se houver preços positivos, remove entradas com preço 0 ou None
    has_positive = any((e.get('price') is not None and e.get('price') > 0) for e in unique)
    if has_positive:
        unique = [e for e in unique if e.get('price') is not None and e.get('price') > 0]

    # Ordena por preço (None no final)
    unique.sort(key=lambda x: (float('inf') if x.get('price') is None else x.get('price')))

    # Formata usando fmt_entry para manter consistência com outros extractors
    formatted = []
    for e in unique:
        try:
            formatted.append(fmt_entry(e))
        except Exception:
            # Fallback: mantem uma forma bruta se fmt_entry falhar
            formatted.append({
                'label': e.get('label'),
                'price': e.get('price'),
                'tax': e.get('tax'),
                'formatted': None,
                'raw': e.get('raw')
            })

    if debug:
        print(f"[zenite] preços extraídos: {formatted}")

    return formatted
