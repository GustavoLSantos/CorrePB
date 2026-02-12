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

        # Scroll to load dynamic content
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
        return None, created, None, horario


def extract_zenite_schedule(soup) -> str:
    """Extrai o horário do evento a partir do HTML do Zenite (ex.: <span class="disc1"> 22/02/2026 06:00</span>)."""
    if not soup:
        return ''

    # Procura por elementos que contenham span.disc com "data" e span.disc1 com data e horário
    elements = soup.find_all(['li', 'div', 'p', 'span'])
    for element in elements:
        disc_span = element.find('span', class_='disc')
        if disc_span and 'data' in disc_span.get_text(strip=True).lower():
            disc1_span = element.find('span', class_='disc1')
            if disc1_span:
                text = disc1_span.get_text(strip=True)
                print(f"Zenite debug: Found disc1 text: '{text}'")
                # Verifica se contém data e horário no formato DD/MM/YYYY HH:MM
                match = re.search(r'\d{2}/\d{2}/\d{4}\s+(\d{1,2}):(\d{1,2})', text)
                if match:
                    hora = match.group(1)
                    minuto = match.group(2)
                    print(f"Zenite debug: Matched time {hora}:{minuto}")
                    try:
                        h = int(hora)
                        m = int(minuto)
                        if 0 <= h <= 23 and 0 <= m <= 59:
                            return f"{h:02d}:{m:02d}"
                    except ValueError:
                        pass

    return ''
