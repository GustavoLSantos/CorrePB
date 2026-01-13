import re
import time
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from data_collection.core.Driver import setup_driver
from data_collection.utils.PriceUtils import parse_price_str, fmt_entry


def is_sympla_domain(domain: str) -> bool:
    """Retorna True se o domínio pertence ao Sympla."""
    if not domain:
        return False
    return 'sympla' in domain.lower()


def load_sympla_soup(url: str, driver=None, wait_seconds: int = 30):
    """
    Carrega a página Sympla usando Selenium (cria um driver se `driver` for None),
    aguarda o elemento de ticket-grid e retorna um BeautifulSoup da página.

    Retorna (soup, driver_was_created) onde driver_was_created indica se
    a função criou e fechou o driver internamente.
    """
    created = False
    local_driver = driver
    try:
        if local_driver is None:
            local_driver = setup_driver()
            created = True
        local_driver.set_page_load_timeout(60)
        local_driver.get(url)

        # Aguarda o ticket-grid específico do Sympla
        try:
            wait_selector = '[data-testid="ticket-grid"]'
            WebDriverWait(local_driver, wait_seconds).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector))
            )
        except Exception:
            # Se não aparecer, tentar um pequeno scroll e aguardar menos
            try:
                local_driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
                time.sleep(1)
            except Exception:
                pass

        # Pequeno scroll para forçar carregamento lazy
        try:
            local_driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
            time.sleep(0.8)
        except Exception:
            pass

        soup = BeautifulSoup(local_driver.page_source, 'html.parser')
        return soup, created, local_driver
    except Exception:
        if created and local_driver:
            try:
                local_driver.quit()
            except Exception:
                pass
        return None, created, None


def extract_sympla_ticket_prices(soup):
    """
    Extrai preços do ticket-grid do Sympla a partir do BeautifulSoup.

    Retorna lista de dicts: {label, price, tax, raw}
    """
    candidates = []
    if not soup:
        return candidates

    try:
        for grid in soup.find_all(attrs={'data-testid': re.compile(r'ticket-grid', re.IGNORECASE)}):
            items = grid.find_all(attrs={'data-testid': re.compile(r'ticket-grid-item', re.IGNORECASE)})
            if not items:
                # fallback para nós filhos diretos
                items = grid.find_all(True, recursive=False)
            for item in items:
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

    # Dedup e filtro básico (mantém 0..500 como no scraper principal)
    unique = []
    seen = set()
    for e in candidates:
        try:
            key = (e.get('label') or '', float(e.get('price') if e.get('price') is not None else -1), e.get('tax') if e.get('tax') is None else float(e.get('tax')))
        except Exception:
            key = (e.get('label') or '', e.get('price'), e.get('tax'))
        if key not in seen:
            seen.add(key)
            unique.append(e)

    valid = [e for e in unique if e.get('price') is not None and 0 <= e.get('price') <= 500]
    if any(e['price'] > 0 for e in valid):
        valid = [e for e in valid if e['price'] > 0]

    # Usa fmt_entry centralizado para formatar
    return [fmt_entry(e) for e in sorted(valid, key=lambda x: x.get('price') or 0)]