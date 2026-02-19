import time
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from data_collection.core.Driver import setup_driver


def is_circuito_domain(domain: str) -> bool:
    if not domain:
        return False
    domain = domain.lower()
    return 'circuitodasestacoes.com' in domain

def load_circuito_soup(url: str, timeout: int = 20):
    """
    Carrega a URL usando Selenium tratando quirks do CircuitoDasEstacoes.

    Retorna (soup, created, driver, horario)
    - soup: BeautifulSoup da página (ou None em falha)
    - created: True se a função criou um driver (caller deve quit() se True)
    - driver: o WebDriver criado (ou None)
    - horario: horário extraído ('' se não encontrado)
    """
    domain = urlparse(url).netloc.lower() if url else ''
    driver = None
    created = False
    try:
        # usar modo headless para execução sem UI
        driver = setup_driver(headless=True)
        created = True
        driver.get(url)

        try:
            selectors = [
                '#race-detailed-info',
                'details',
                '.details-content',
                'summary',
            ]
            found = False
            for sel in selectors:
                try:
                    WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                    found = True
                    break
                except Exception:
                    continue
            if not found:
                pass
        except Exception:
            pass

        # tenta clicar no botão que revela as informações (caso exista)
        try:
            # tenta seletor específico dentro do container
            try:
                buttons = driver.find_elements(By.CSS_SELECTOR, "#race-detailed-info [role='button'], #race-detailed-info button, #race-detailed-info a")
                if buttons and len(buttons) > 0:
                    buttons[0].click()
                    time.sleep(1.5)
            except Exception:
                pass

            # fallback: procura por elementos com texto aproximado 'confira'/'inform'
            try:
                details_count = driver.execute_script("return document.querySelectorAll('details').length")
            except Exception:
                details_count = 0

            if not details_count:
                elems = driver.find_elements(By.XPATH, "//button|//a|//div|//span")
                for el in elems:
                    try:
                        txt = (el.text or '').strip().lower()
                        if 'confira' in txt or 'inform' in txt:
                            el.click()
                            time.sleep(1.5)
                            break
                    except Exception:
                        continue
        except Exception as e:
            print('DEBUG: clicking info failed', e)

        # força abertura de <details> e rolagem para acionar lazy-loads
        try:
            driver.execute_script("document.querySelectorAll('details').forEach(d=>d.open=true);")
            driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
            time.sleep(0.8)
            driver.execute_script('window.scrollTo(0, 0);')
            time.sleep(0.5)
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
            WebDriverWait(driver, timeout).until(_ready)
        except Exception:
            pass

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        horario = extract_circuito_schedule(soup)
        return soup, created, driver, horario

    except Exception:
        return None, created, None, ''


def extract_circuito_schedule(soup) -> str:
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
