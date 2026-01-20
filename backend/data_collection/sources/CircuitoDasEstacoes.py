import time
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from data_collection.core.Driver import setup_driver


def is_circuito_domain(domain: str) -> bool:
    """Return True if the given domain belongs to CircuitoDasEstacoes."""
    if not domain:
        return False
    domain = domain.lower()
    return 'circuitodasestacoes.com' in domain

def load_circuito_soup(url: str, timeout: int = 20):
    """
    Carrega a URL usando Selenium tratando quirks do CircuitoDasEstacoes.

    Retorna (soup, created, driver)
    - soup: BeautifulSoup da página (ou None em falha)
    - created: True se a função criou um driver (caller deve quit() se True)
    - driver: o WebDriver criado (ou None)
    """
    domain = urlparse(url).netloc.lower() if url else ''
    driver = None
    created = False
    try:
        driver = setup_driver()
        created = True
        driver.get(url)

        try:
            # Algumas vezes mostram preços em elementos com classe `kit-price-mobile` e uma
            # subclasse/elemento `font-2` — então validamos várias alternativas.
            selectors = [
                ".kit-price-desktop",
                ".kit-price-mobile .font-2",
                ".kit-price-mobile.font-2",
                ".kit-price-mobile",
            ]
            found = False
            for sel in selectors:
                try:
                    WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                    found = True
                    break
                except Exception:
                    continue
            # se nenhum seletor for encontrado dentro do timeout, seguimos em frente sem erro
            if not found:
                pass
        except Exception:
            pass

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        return soup, created, driver

    except Exception:
        return None, created, driver