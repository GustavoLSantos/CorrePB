import time
import re

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from data_collection.core.Driver import setup_driver

def extract_liverun_date(soup):
    """
    Extrai a data do evento de uma página Liverun.
    Procura por <h3>Data</h3> seguido de <p> com a data.
    """
    if not soup:
        return ""
    
    try:
        h3_data = soup.find('h3', string=re.compile(r'Data', re.IGNORECASE))
        if h3_data:
            parent = h3_data.find_parent('div')
            if parent:
                p_date = parent.find('p')
                if p_date:
                    date_text = p_date.get_text(strip=True)
                    if re.match(r'\d{2}/\d{2}$', date_text):
                        page_text = soup.get_text()
                        year_match = re.search(r'202[4-9]|203\d', page_text)
                        if year_match:
                            return f"{date_text}/{year_match.group(0)}"
                    return date_text
        
        text = soup.get_text(separator=' ', strip=True)
        match = re.search(r'\b(\d{2}/\d{2}/\d{4})\b', text)
        if match:
            return match.group(1)
        
        match = re.search(r'\b(\d{2}/\d{2})\b', text)
        if match:
            year_match = re.search(r'202[4-9]|203\d', text)
            if year_match:
                return f"{match.group(1)}/{year_match.group(0)}"
            return match.group(1)
        
    except Exception:
        pass
    
    return ""

def is_liverun_domain(domain: str) -> bool:
    if not domain:
        return False
    return 'liverun' in domain.lower()

def open_regulation_modals(driver):
    """
    Detecta modais relacionados a regulamento/preços e tenta abri-los.
    Mesma lógica que existia no scraper original: procura elementos com id/class contendo
    'modal' e palavras-chave relevantes, tenta clicar em gatilhos ou força exibição via JS.
    """
    try:
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        modal_candidates = []
        for elem in soup.find_all(attrs={'id': re.compile(r'.*modal.*', re.IGNORECASE)}):
            mid = elem.get('id')
            text = ' '.join(elem.stripped_strings) or ''
            if re.search(r'regul|regulation|regulamento|rule|reglas|reglamento', mid, re.IGNORECASE) or re.search(r'regul|lote|lotes|R\$', text, re.IGNORECASE):
                modal_candidates.append(mid)

        for m in soup.select('.modal'):
            inner = ' '.join(m.stripped_strings) or ''
            if re.search(r'lote|lotes|R\$|regul', inner, re.IGNORECASE):
                mid = m.get('id')
                if mid:
                    modal_candidates.append(mid)

        modal_candidates = list(dict.fromkeys([m for m in modal_candidates if m]))

        for mid in modal_candidates:
            try:
                tried = False
                selectors = [f'a[href="#%s"]' % mid, f'[data-target="#%s"]' % mid, f'button[data-target="#%s"]' % mid, f'a[href*="#%s"]' % mid, '#btn-modal']
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
                    try:
                        driver.execute_script("var m=document.getElementById('%s'); if(m){ m.style.display='block'; m.classList.add('show'); }" % mid)
                        time.sleep(0.4)
                    except Exception:
                        pass

                try:
                    WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.CSS_SELECTOR, f'#{mid} ul')))
                    time.sleep(0.2)
                except Exception:
                    pass
            except Exception:
                continue
    except Exception:
        return


def load_liverun_soup(url: str, timeout: int = 20):
    """
    Carrega uma página LiveRun/Liverun usando Selenium e tenta abrir o modal
    com id 'modal-regulation' para expor listas de preços/regulamento.

    Retorna (soup, created, driver)
    """
    driver = None
    created = False
    try:
        driver = setup_driver()
        created = True
        driver.get(url)

        try:
            trigger = None
            try:
                trigger = driver.find_element(By.CSS_SELECTOR,
                    '[data-toggle="modal"], [data-target="#modal-regulation"], a[href="#modal-regulation"], button[data-target="#modal-regulation"], #btn-modal')
            except Exception:
                try:
                    trigger = driver.find_element(By.XPATH,
                        "//a[contains(@href, '#modal-regulation') or contains(@data-target, 'modal-regulation')]")
                except Exception:
                    trigger = None

            if trigger:
                try:
                    trigger.click()
                except Exception:
                    try:
                        driver.execute_script("arguments[0].dispatchEvent(new MouseEvent('click', {bubbles:true}));", trigger)
                    except Exception:
                        pass
            else:
                try:
                    driver.execute_script(
                        "var m=document.getElementById('modal-regulation'); if(m){ m.style.display='block'; m.classList.add('show'); }"
                    )
                except Exception:
                    pass
        except Exception:
            pass

        try:
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, '#modal-regulation ul')))
            time.sleep(0.45)
        except Exception:
            pass

        try:
            open_regulation_modals(driver)
        except Exception:
            pass

        try:
            driver.execute_script(
                "var elems=document.querySelectorAll('[id*=\"modal\"], .modal');"
                "elems.forEach(function(m){ if(m && m.id){ m.style.display='block'; m.classList.add('show'); } });"
            )
            time.sleep(0.25)
        except Exception:
            pass

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        return soup, created, driver

    except Exception:
        return None, created, driver