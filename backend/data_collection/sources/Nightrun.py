from bs4 import BeautifulSoup
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from data_collection.core.Driver import setup_driver


def is_nightrun_domain(domain: str) -> bool:
    """Retorna True se o domínio pertence ao NightRun."""
    if not domain:
        return False
    d = domain.lower()
    return 'nightrun.com.br' in d or 'nightrun' in d


def load_nightrun_soup(url: str, driver=None, wait_seconds: int = 20, debug: bool = False):
    """
    Carrega a página do NightRun com Selenium e retorna (soup, created, driver).
    Não faz cliques adicionais por padrão — apenas renderiza e retorna o HTML.
    """
    created = False
    local_driver = driver
    try:
        if local_driver is None:
            local_driver = setup_driver()
            created = True

        try:
            local_driver.set_page_load_timeout(60)
            local_driver.get(url)
        except Exception:
            # tenta prosseguir mesmo que o load tenha problemas
            pass

        # espera especificamente pelo elemento de preço dinâmico do NightRun
        try:
            WebDriverWait(local_driver, wait_seconds).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'p.kit-price-mobile, p.kit-price-desktop'))
            )
        except Exception:
            # fallback: esperar pela body e aguardar mais tempo
            try:
                WebDriverWait(local_driver, min(5, wait_seconds)).until(
                    EC.presence_of_all_elements_located((By.TAG_NAME, 'body'))
                )
            except Exception:
                pass
            # dar um tempo extra para scripts carregarem
            time.sleep(min(2.0, max(0.6, wait_seconds * 0.1)))

        # tenta scrollear para o elemento de preço para forçar renderização lazy
        try:
            el = local_driver.find_element(By.CSS_SELECTOR, 'p.kit-price-mobile, p.kit-price-desktop')
            local_driver.execute_script("arguments[0].scrollIntoView(true);", el)
            time.sleep(0.5)
        except Exception:
            # não encontrado via driver, segue adiante
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


def extract_nightrun_ticket_prices(soup, debug: bool = False):
    """
    Extrai preço(s) do NightRun a partir do HTML renderizado.

    Busca por <p> com classes contendo 'kit-price-mobile' ou 'kit-price-desktop'
    e extrai o valor em R$. Retorna lista de entradas já formatadas via `fmt_entry`.
    """
    from data_collection.utils.PriceUtils import fmt_entry, parse_price_str
    import re

    results = []
    if not soup:
        return results

    def class_has_kit_price(c):
        if not c:
            return False
        # classe pode ser lista ou string
        if isinstance(c, (list, tuple)):
            cls_list = c
        else:
            cls_list = [c]
        for cl in cls_list:
            try:
                if 'kit-price' in cl:
                    return True
            except Exception:
                continue
        return False

    # procura p.tags que contenham a classe kit-price-mobile ou kit-price-desktop
    price_elems = soup.find_all('p', class_=class_has_kit_price)

    for pe in price_elems:
        txt = pe.get_text(separator=' ', strip=True)
        # procura padrão R$ valor
        m = re.search(r'R\$\s*([\d.,]+)', txt)
        price = None
        if m:
            price = parse_price_str(m.group(1))
        else:
            # fallback: tenta extrair qualquer número
            mm = re.search(r'([\d.,]+)', txt)
            if mm:
                price = parse_price_str(mm.group(1))

        entry = {'label': None, 'price': price, 'tax': None, 'raw': txt}
        try:
            results.append(fmt_entry(entry))
        except Exception:
            entry['formatted'] = entry.get('formatted') or (f"R$ {price}" if price is not None else 'Valor não encontrado')
            results.append(entry)

    # dedup e validação simples (evita zeros e negativos quando há outros preços)
    unique = []
    seen = set()
    for e in results:
        try:
            key = (e.get('label') or '', float(e.get('price') if e.get('price') is not None else -1), e.get('tax'))
        except Exception:
            key = (e.get('label') or '', e.get('price'), e.get('tax'))
        if key not in seen:
            seen.add(key)
            unique.append(e)

    valid = [e for e in unique if e.get('price') is not None and 0 <= e.get('price') <= 500]
    if any(e['price'] > 0 for e in valid):
        valid = [e for e in valid if e['price'] > 0]

    return valid
