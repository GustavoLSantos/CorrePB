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
    created = False
    local_driver = driver
    schedule = ''
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

        # tenta scrollar para o elemento de preço para forçar renderização lazy
        try:
            el = local_driver.find_element(By.CSS_SELECTOR, 'p.kit-price-mobile, p.kit-price-desktop')
            local_driver.execute_script("arguments[0].scrollIntoView(true);", el)
            time.sleep(0.5)
        except Exception:
            # não encontrado via driver, segue adiante
            pass

        # tenta abrir painéis de informações (<details>) para expor horário e outros dados
        try:
            # abrir detalhes específicos do container de informações quando presente
            try:
                local_driver.execute_script("document.querySelectorAll('#race-detailed-info details').forEach(d=>d.open=true);")
            except Exception:
                pass
            # abrir genericamente qualquer <details>
            try:
                local_driver.execute_script("document.querySelectorAll('details').forEach(d=>d.open=true);")
            except Exception:
                pass
            # clicar em summaries dentro do container para forçar renderização
            try:
                summaries = local_driver.find_elements(By.CSS_SELECTOR, '#race-detailed-info details summary, details summary')
                for s in summaries:
                    try:
                        local_driver.execute_script('arguments[0].click();', s)
                        time.sleep(0.2)
                    except Exception:
                        continue
            except Exception:
                pass
            time.sleep(0.8)
        except Exception:
            pass

        try:
            pre_cta_soup = BeautifulSoup(local_driver.page_source, 'html.parser')
            schedule = extract_nightrun_schedule(pre_cta_soup) or schedule
        except Exception:
            pass

        if not schedule:
            try:
                schedule = _extract_schedule_from_detailed_component(url, wait_seconds) or schedule
            except Exception:
                pass
        try:
            cta_anchors = local_driver.find_elements(By.CSS_SELECTOR, 'a.kit-cta-desktop.font-1, a.kit-cta-desktop')
            if not cta_anchors:
                all_a = local_driver.find_elements(By.TAG_NAME, 'a')
                for a_el in all_a:
                    try:
                        href = (a_el.get_attribute('href') or '').lower()
                        txt = (a_el.text or '').lower()
                        aria = (a_el.get_attribute('aria-label') or '').lower()
                        if ('garanta' in txt or 'garanta' in aria or 'inscrev' in txt or 'inscrev' in aria) and href:
                            cta_anchors = [a_el]
                            break
                    except Exception:
                        continue
            if cta_anchors:
                try:
                    target = cta_anchors[0]
                    target_href = target.get_attribute('href') or ''
                    try:
                        local_driver.execute_script('arguments[0].scrollIntoView(true);', target)
                    except Exception:
                        pass
                    try:
                        local_driver.execute_script('arguments[0].click();', target)
                    except Exception:
                        try:
                            target.click()
                        except Exception:
                            pass
                    time.sleep(1.0)
                    try:
                        WebDriverWait(local_driver, min(6, wait_seconds)).until(lambda d: len(d.window_handles) > 1)
                    except Exception:
                        pass
                    # se abriu nova aba, alterna para ela
                    try:
                        if len(local_driver.window_handles) > 1:
                            local_driver.switch_to.window(local_driver.window_handles[-1])
                            time.sleep(0.6)
                    except Exception:
                        pass
                    if target_href:
                        try:
                            current = (local_driver.current_url or '').split('#')[0]
                            if not current.lower().startswith(target_href.lower()):
                                local_driver.get(target_href)
                                time.sleep(1.0)
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass

        soup = BeautifulSoup(local_driver.page_source, 'html.parser')

        try:
            btns = local_driver.find_elements(By.XPATH, "//button[contains(@class,'absolute') and contains(@class,'top-[25px]') and contains(@class,'left-[20px]') and contains(@class,'z-50')]")
            if not btns:
                btns = local_driver.find_elements(By.XPATH, "//button[descendant::svg and contains(@class,'absolute')]")
            if btns:
                try:
                    local_driver.execute_script('arguments[0].click();', btns[0])
                except Exception:
                    try:
                        btns[0].click()
                    except Exception:
                        pass
                time.sleep(0.5)
        except Exception:
            pass

        return soup, created, local_driver, schedule
    except Exception:
        if created and local_driver:
            try:
                local_driver.quit()
            except Exception:
                pass
        return None, created, None, schedule


def _extract_schedule_from_detailed_component(url: str, wait_seconds: int):
    """Tenta carregar o componente RaceDetailedInfoProvider para extrair o horário."""
    detail_driver = None
    try:
        detail_driver = setup_driver()
        detail_driver.set_page_load_timeout(60)
        q = 'showsOnly=Header,RaceDetailedInfoProvider&raceDetailedComponent=info'
        detail_url = url + ('&' + q if '?' in url else '?' + q)
        detail_driver.get(detail_url)
        time.sleep(1.0)
        try:
            detail_driver.execute_script("document.querySelectorAll('details').forEach(d=>d.open=true);")
        except Exception:
            pass
        time.sleep(0.6)
        detail_soup = BeautifulSoup(detail_driver.page_source, 'html.parser')
        return extract_nightrun_schedule(detail_soup)
    except Exception:
        return ''
    finally:
        if detail_driver:
            try:
                detail_driver.quit()
            except Exception:
                pass


def extract_nightrun_schedule(soup) -> str:
    """Extrai o horário de largada do site NightRun, retornando 'HH:MM', 'Em breve' ou '' se não encontrado."""
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
            container = details.find(class_='details-content') or details

            # procura por possíveis rótulos/headers dentro do container
            for header in container.find_all(['h5', 'h4', 'h3', 'strong', 'b', 'summary', 'p']):
                header_text = _strip_accents(header.get_text(' ', strip=True)).lower()
                if not header_text:
                    continue
                if 'horario' in header_text or 'largad' in header_text or 'saida' in header_text:
                    # tenta extrair texto associado preferindo elementos dentro do mesmo 'campo' pai
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
        m = re.search(r"(?:horario|largad|saida)[^\d]{0,50}(\d{1,2})\s*[:hH]\s*(\d{0,2})", page)
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


def _parse_price_str_to_float(token):
    import re
    if not token:
        return None
    s = re.sub(r'[^\d\.,]', '', str(token))
    if not s:
        return None
    if '.' in s and ',' in s:
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s and '.' not in s:
        s = s.replace(',', '.')
    try:
        return float(s)
    except Exception:
        try:
            return float(s.replace('.', '').replace(',', '.'))
        except Exception:
            return None


def extract_nightrun_ticket_prices(driver, wait_seconds: int = 30):
    try:
        import re, time
        price_sel = 'div[class*="option-priceBlock"], span[class*="option-specialPrice"], span[class*="priceBlock-oldP"], div[class*="option-root"], [class*="option-rootLeft"]'
        try:
            WebDriverWait(driver, min(wait_seconds, 40), poll_frequency=0.5).until(lambda d: len(d.find_elements(By.CSS_SELECTOR, price_sel))>0 or 'R$' in (d.page_source or ''))
        except Exception:
            pass

        blocks = driver.find_elements(By.CSS_SELECTOR, 'div[class*="option-root"], div[class*="option-priceBlock"], [class*="option-rootLeft"], div[class*="priceBlock-block"]') or []
        if not blocks:
            try:
                iframes = driver.find_elements(By.TAG_NAME, 'iframe')
                for fr in iframes:
                    try:
                        driver.switch_to.frame(fr)
                        found = driver.find_elements(By.CSS_SELECTOR, 'div[class*="option-root"], div[class*="option-priceBlock"], [class*="option-rootLeft"], div[class*="priceBlock-block"]')
                        if found:
                            blocks = found
                            break
                        driver.switch_to.default_content()
                    except Exception:
                        try:
                            driver.switch_to.default_content()
                        except Exception:
                            pass
            except Exception:
                pass

        out = {}
        for b in blocks:
            try:
                try:
                    lbl_el = b.find_element(By.CSS_SELECTOR, '[class*="option-label"], .option-label, .option-labelLeft, .option-labelLeft-f8R, h4, h3')
                    label = (lbl_el.text or '').strip()
                except Exception:
                    label = None
                try:
                    price_el = b.find_element(By.CSS_SELECTOR, 'span[class*="option-specialPrice"], .option-specialPrice')
                except Exception:
                    try:
                        price_el = b.find_element(By.CSS_SELECTOR, 'span[class*="priceBlock-oldP"], .priceBlock-oldP, span[class*="priceBlock-fromPrice"]')
                    except Exception:
                        price_el = None

                if not price_el or not label:
                    continue

                txt = price_el.text or ''
                m = re.search(r'R\$\s*([\d\.,]+)', txt)
                val = None
                if m:
                    val = _parse_price_str_to_float(m.group(1))
                else:
                    mm = re.search(r'([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{2})|[0-9]+(?:[\.,][0-9]{2}))', txt)
                    if mm:
                        val = _parse_price_str_to_float(mm.group(1))
                if val is None:
                    continue
                key = label.strip().upper()
                if key in out:
                    continue
                out[key] = "{:.2f}".format(val).replace('.', ',')
            except Exception:
                continue

        return [f"{k} - {v}" for k, v in out.items()]
    except Exception:
        return []
