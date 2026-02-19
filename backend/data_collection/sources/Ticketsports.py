from bs4 import BeautifulSoup
import time
import re
import unicodedata
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from data_collection.core.Driver import setup_driver
from data_collection.utils.PriceUtils import parse_price_str, fmt_entry


def is_ticketsports_domain(domain: str) -> bool:
    """Retorna True se o domínio pertence ao Ticketsports."""
    if not domain:
        return False
    return 'ticketsports.com.br' in domain.lower()


def load_ticketsports_soup(url: str, driver=None, wait_seconds: int = 20, debug: bool = False, return_counts: bool = False):
    """
    Carrega a página do Ticketsports, tenta abrir a área de inscrição e retorna o soup já renderizado.
    Mantém horários extraídos cedo e aplica fallback via requests quando necessário.
    """
    created = False
    local_driver = driver
    horario = ''

    def _safe_click(elem) -> bool:
        try:
            elem.click()
            time.sleep(0.6)
            return True
        except Exception:
            try:
                local_driver.execute_script("arguments[0].click();", elem)
                time.sleep(0.6)
                return True
            except Exception:
                return False

    def _fetch_soup(url_target: str):
        try:
            resp = requests.get(url_target, timeout=10)
            if resp.status_code == 200:
                return BeautifulSoup(resp.text, 'html.parser')
        except Exception:
            return None
        return None

    try:
        if local_driver is None:
            local_driver = setup_driver()
            created = True

        try:
            local_driver.set_page_load_timeout(60)
            local_driver.get(url)
            time.sleep(1.0)
        except Exception:
            pass

        # horário logo após o carregamento inicial
        initial_soup = BeautifulSoup(local_driver.page_source, 'html.parser')
        horario = extract_ticketsports_schedule(initial_soup)

        wait = WebDriverWait(local_driver, wait_seconds)
        inscreva_href = None

        # Tenta clicar no botão primário de inscrição
        clicked_inscricao = False
        try:
            btn = wait.until(EC.presence_of_element_located((By.ID, 'bot_inscrever')))
            txt = (btn.text or '').strip().upper()
            if not txt or any(k in txt for k in ['INSCREVER', 'INSCREVER-SE', 'SIGN UP', 'SIGNUP', 'REGISTER']):
                clicked_inscricao = _safe_click(btn)
        except Exception:
            pass

        # Fallback: links com texto de inscrição
        if not clicked_inscricao:
            try:
                links = local_driver.find_elements(
                    By.XPATH,
                    "//a[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÂÃÀÄÅÇÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÝ', 'abcdefghijklmnopqrstuvwxyzáâãàäåçéèêëíìîïóòôõöúùûüý'), 'inscreva') or contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÂÃÀÄÅÇÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÝ', 'abcdefghijklmnopqrstuvwxyzáâãàäåçéèêëíìîïóòôõöúùûüý'), 'inscrever')]"
                )
                for link in links:
                    href = link.get_attribute('href') or ''
                    if href and 'ticketsports' in href.lower():
                        inscreva_href = href
                        if 'inscricao' in href.lower():
                            try:
                                local_driver.get(href)
                                time.sleep(1.2)
                                clicked_inscricao = True
                            except Exception:
                                pass
                        break
            except Exception:
                pass

        # scroll para garantir carregamento
        try:
            local_driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
            time.sleep(0.6)
        except Exception:
            pass

        # fecha overlay e abre a primeira modalidade, se existir
        try:
            click_closebtn(local_driver, debug)
            modals = local_driver.find_elements(By.CSS_SELECTOR, '.display-modality')
            if modals:
                _safe_click(modals[0])
        except Exception:
            pass

        # tenta clicar em cards/opções para assegurar que detalhes (ex.: horário) fiquem visíveis
        try:
            clickable_cards = local_driver.find_elements(By.CSS_SELECTOR, 'div.card, div.bloco-radio, .display-modality')
            if clickable_cards:
                # tenta clicar nas primeiras opções (até 2) para forçar renderização dos detalhes
                for el in clickable_cards[:2]:
                    try:
                        _safe_click(el)
                        time.sleep(0.6)
                    except Exception:
                        continue
        except Exception:
            pass

        # aguarda blocos de preço ou cards
        try:
            WebDriverWait(local_driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div.card, div.bloco-radio'))
            )
        except Exception:
            pass

        try:
            local_driver.execute_script('window.scrollTo(0, 0);')
            time.sleep(0.4)
        except Exception:
            pass

        # Aguarda até que o horário esteja presente na página para aumentar determinismo
        try:
            def _has_schedule(drv):
                try:
                    s = BeautifulSoup(drv.page_source, 'html.parser')
                    return bool(extract_ticketsports_schedule(s))
                except Exception:
                    return False
            WebDriverWait(local_driver, wait_seconds).until(_has_schedule)
        except Exception:
            # não falhar aqui — continuará com o estado atual da página
            pass

        soup = BeautifulSoup(local_driver.page_source, 'html.parser')

        # fallback: requests se não encontrar blocos de preço
        if not soup.find('div', class_=lambda c: c and 'bloco-radio' in c):
            soup_req = _fetch_soup(inscreva_href or url)
            if soup_req and soup_req.find('div', class_=lambda c: c and 'bloco-radio' in c):
                soup = soup_req

        # fallback extra para horário
        if not horario:
            horario = extract_ticketsports_schedule(soup)
        if not horario:
            soup_req = _fetch_soup(url)
            if soup_req:
                horario_req = extract_ticketsports_schedule(soup_req)
                if horario_req:
                    horario = horario_req

        # tentativa de reload + interação caso o horário não tenha sido encontrado
        if not horario and created and local_driver:
            try:
                try:
                    local_driver.get(url)
                    time.sleep(1.0)
                except Exception:
                    pass

                try:
                    click_closebtn(local_driver, debug)
                    modals = local_driver.find_elements(By.CSS_SELECTOR, '.display-modality')
                    if modals:
                        _safe_click(modals[0])
                except Exception:
                    pass

                try:
                    clickable_cards = local_driver.find_elements(By.CSS_SELECTOR, 'div.card, div.bloco-radio, .display-modality')
                    if clickable_cards:
                        for el in clickable_cards[:2]:
                            try:
                                _safe_click(el)
                                time.sleep(0.6)
                            except Exception:
                                continue
                except Exception:
                    pass

                try:
                    local_driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
                    time.sleep(0.6)
                except Exception:
                    pass

                try:
                    def _has_schedule_retry(drv):
                        try:
                            s2 = BeautifulSoup(drv.page_source, 'html.parser')
                            return bool(extract_ticketsports_schedule(s2))
                        except Exception:
                            return False
                    WebDriverWait(local_driver, wait_seconds).until(_has_schedule_retry)
                except Exception:
                    pass

                soup2 = BeautifulSoup(local_driver.page_source, 'html.parser')
                horario2 = extract_ticketsports_schedule(soup2)
                if horario2:
                    horario = horario2
                    soup = soup2
            except Exception:
                pass

        num_cards = len(soup.select('div.card')) if soup else 0
        if return_counts:
            return soup, created, local_driver, horario, num_cards
        return soup, created, local_driver, horario
    except Exception:
        if created and local_driver:
            try:
                local_driver.quit()
            except Exception:
                pass
        return None, created, None, horario


def extract_ticketsports_modalities(soup, debug: bool = False):
    """
    Extrai modalidades e opções (km, price) de uma página Ticketsports.

    Para cada `span.titulo-categoria-menor` encontra o container relacionado
    e procura por `div` cujo id contenha 'ul-lista-card-modalidade'. Dentro
    dele, cada `div` com classes 'radio' e 'bloco-radio' representa uma
    opção de quilometragem. Retorna lista de dicts:
    [
      {
        'modality': str,
        'options': [ { 'label': str|None, 'km': str|None, 'km_value': float|None, 'price': float|None, 'raw': str } ]
      },
      ...
    ]

    Usa heurísticas razoáveis para extrair km e preço a partir do texto.
    """
    results = []
    if not soup:
        return results

    price_regex = re.compile(r'R\$\s*([\d.,]+)')
    km_regex = re.compile(r'(\d+(?:[.,]\d+)?)\s*(?:km\b|k\b)', re.IGNORECASE)
    number_regex = re.compile(r'(\d+(?:[.,]\d+)?)')

    def parse_option(raw_text: str):
        raw_text = (raw_text or '').strip()
        price = parse_price_str(price_regex.search(raw_text).group(1)) if price_regex.search(raw_text) else parse_price_str(raw_text)

        km = None
        km_value = None
        km_match = km_regex.search(raw_text)
        if km_match:
            km = km_match.group(1).replace(',', '.')
            try:
                km_value = float(km)
            except Exception:
                km_value = None
        else:
            for n in number_regex.findall(raw_text):
                try:
                    v = float(n.replace(',', '.'))
                except Exception:
                    continue
                if price is not None and abs(v - (price or 0)) < 0.01:
                    continue
                if 0 < v < 1000:
                    km_value = v
                    km = str(v)
                    break

        return {'label': None, 'km': km, 'km_value': km_value, 'price': price, 'raw': raw_text}

    seen_raw = set()
    cards = soup.find_all('div', class_='card')
    for card in cards:
        name = None
        title_span = card.find('span', class_='titulo-categoria-menor')
        if title_span and title_span.get_text(strip=True):
            name = title_span.get_text(separator=' ', strip=True).strip()
        else:
            h = card.find(['h3', 'h4', 'h2'])
            if h and h.get_text(strip=True):
                name = h.get_text(separator=' ', strip=True).strip()

        list_div = card.find(lambda tag: tag.name == 'div' and tag.get('id') and 'ul-lista-card-modalidade' in tag.get('id'))
        if not list_div:
            list_div = card.find('div', id=lambda x: x and 'lista-card-modalidade' in x)

        options = []
        if list_div:
            radios = list_div.find_all('div', class_=lambda c: c and 'radio' in c and 'bloco-radio' in c)
            if not radios:
                radios = list_div.find_all('div', class_='bloco-radio')
            for r in radios:
                raw = r.get_text(separator=' ', strip=True)
                if raw in seen_raw:
                    continue
                seen_raw.add(raw)
                options.append(parse_option(raw))

        results.append({'modality': name, 'options': options})

    # Fallback: blocos de preço fora dos cards tradicionais
    extra_options = []
    for r in soup.find_all('div', class_=lambda c: c and 'bloco-radio' in c):
        raw = r.get_text(separator=' ', strip=True)
        if raw in seen_raw:
            continue
        seen_raw.add(raw)
        extra_options.append(parse_option(raw))

    if extra_options:
        results.append({'modality': None, 'options': extra_options})

    def normalize_name(s: str) -> str:
        if not s:
            return ''
        s = str(s)
        s = unicodedata.normalize('NFD', s)
        s = ''.join(ch for ch in s if not unicodedata.category(ch).startswith('M'))
        s = re.sub(r'\s+', ' ', s).strip().lower()
        return s

    seen_modalities = set()
    deduped = []
    for item in results:
        n = normalize_name(item.get('modality') or '')
        if n in seen_modalities:
            continue
        seen_modalities.add(n)
        deduped.append(item)
    return deduped


def extract_ticketsports_ticket_prices(soup, debug: bool = False):
    """
    Converte a estrutura de modalidades extraída por `extract_ticketsports_modalities`
    em uma lista de entradas de preço padronizadas compatíveis com o pipeline.

    Cada entrada retornada é um dict com as chaves esperadas por `fmt_entry` e
    pelo `scraper_brasilquecorre.extract_price_entries`: { 'label', 'price', 'tax', 'raw' }
    """
    def normalize_text(s: str) -> str:
        if not s:
            return ''
        try:
            s = str(s)
        except Exception:
            return ''
        s = unicodedata.normalize('NFD', s)
        s = ''.join(ch for ch in s if not unicodedata.category(ch).startswith('M'))
        s = re.sub(r'\s+', ' ', s).strip().lower()
        return s

    results = []
    if not soup:
        return results

    modalities = extract_ticketsports_modalities(soup, debug=debug)
    if debug:
        print(f"[Ticketsports] modalities found: {len(modalities)}")

    # evita duplicatas usando chave (mod_name_normalized, km_value, price, tax)
    seen_keys = set()
    for m in modalities:
        mod_name = (m.get('modality') or 'GERAL').strip()
        for opt in m.get('options', []):
            price = opt.get('price')
            raw = opt.get('raw') or ''
            # tenta extrair taxa: padrão '+ R$ 8,80' ou '(+8,80 taxa)'
            tax = None
            tax_m = re.search(r'\+\s*R\$\s*([\d.,]+)', raw)
            if tax_m:
                tax = parse_price_str(tax_m.group(1))
            else:
                tax_m2 = re.search(r'\(\s*\+?([\d.,]+)\s*(?:taxa|tax|fee)\s*\)', raw, re.IGNORECASE)
                if tax_m2:
                    tax = parse_price_str(tax_m2.group(1))

            try:
                km_value = opt.get('km_value') if opt.get('km_value') is not None else None
            except Exception:
                km_value = None
            try:
                price_key = float(price) if price is not None else None
            except Exception:
                price_key = price
            try:
                tax_key = float(tax) if tax is not None else None
            except Exception:
                tax_key = tax
            key = (normalize_text(mod_name), km_value, price_key, tax_key)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            # monta label combinando modalidade e km quando disponível
            km = opt.get('km')
            if km:
                # normalize km representation (remove trailing 'km' if present)
                try:
                    km_s = str(km).strip()
                    # remove trailing 'km' if it exists
                    km_s = re.sub(r'\s*[kK][mM]\b', '', km_s)
                    label = f"{mod_name} — {km_s}KM"
                except Exception:
                    label = f"{mod_name} — {km}"
            else:
                label = mod_name

            entry = {'label': label, 'price': price, 'tax': tax, 'raw': raw}
            # formata usando fmt_entry para garantir consistência com Sympla extractor
            try:
                formatted = fmt_entry(entry)
                results.append(formatted)
            except Exception:
                # se fmt_entry falhar, acrescenta raw minimal
                entry['formatted'] = entry.get('formatted') or (f"R$ {price}" if price is not None else 'Valor não encontrado')
                results.append(entry)

    # Dedup por (label, price, tax)
    unique = []
    seen = set()
    for e in results:
        try:
            lbl = e.get('label') or ''
            price_val = float(e.get('price') if e.get('price') is not None else -1)
            tax_val = e.get('tax') if e.get('tax') is None else float(e.get('tax'))
            key = (normalize_text(lbl), price_val, tax_val)
        except Exception:
            key = (normalize_text(e.get('label') or ''), e.get('price'), e.get('tax'))
        if key not in seen:
            seen.add(key)
            unique.append(e)

    # filtra preços plausíveis
    valid = [e for e in unique if e.get('price') is not None and 0 <= e.get('price') <= 500]
    if any(e['price'] > 0 for e in valid):
        valid = [e for e in valid if e['price'] > 0]

    # já estão no formato do fmt_entry
    return valid


def extract_ticketsports_schedule(soup) -> str:
    """Extrai o horário do evento a partir do HTML do Ticketsports (ex.: <b>HORÁRIO</b>: 04h00)."""
    if not soup:
        return ''

    page_text = soup.get_text(' ', strip=True)

    # Normaliza acentos para facilitar busca
    def _strip_accents(s):
        import unicodedata
        if not s:
            return ''
        s = unicodedata.normalize('NFD', s)
        s = ''.join(ch for ch in s if not unicodedata.category(ch).startswith('M'))
        return s

    page_text_norm = _strip_accents(page_text).lower()

    # Direct search in full text for horario followed by time
    m = re.search(r'horario[^\d]{0,30}(\d{1,2})\s*[:hH]\s*(\d{0,2})', page_text_norm, re.IGNORECASE)
    if m:
        hh = m.group(1)
        mm = m.group(2) or '00'
        try:
            h = int(hh)
            min_val = int(mm)
            if 0 <= h <= 23 and 0 <= min_val <= 59:
                return f"{h:02d}:{min_val:02d}"
        except Exception:
            pass

    # Fallback: look for <b>/<strong> labels
    def normalize_time(hour_str, minute_str=None):
        try:
            h = int(hour_str)
            m = int(minute_str) if minute_str not in (None, '') else 0
        except Exception:
            return None
        if h < 0 or h > 23 or m < 0 or m > 59:
            return None
        return f"{h:02d}:{m:02d}"

    def normalize_label(s: str) -> str:
        if not s:
            return ''
        s = unicodedata.normalize('NFD', s)
        s = ''.join(ch for ch in s if not unicodedata.category(ch).startswith('M'))
        return s.lower()

    time_patterns = [
        re.compile(r'(?<!\d)(\d{1,2})\s*[:hH]\s*(\d{0,2})(?!\d)'),
        re.compile(r'(?<!\d)(\d{1,2})\s*h\s*(\d{0,2})\b(?!\d)')
    ]

    # Procura labels em <b> ou <strong> com texto "HORÁRIO"
    for label in soup.find_all(['b', 'strong']):
        label_text = normalize_label(label.get_text(' ', strip=True))
        if 'horario' not in label_text and 'saida' not in label_text and 'largada' not in label_text:
            continue
        # Junta texto dos irmãos seguintes até encontrar outro label forte
        collected_parts = []
        for sib in label.next_siblings:
            if getattr(sib, 'name', '').lower() in ('b', 'strong'):
                break
            txt = ''
            if isinstance(sib, str):
                txt = sib
            else:
                try:
                    txt = sib.get_text(' ', strip=True)
                except Exception:
                    txt = ''
            txt = (txt or '').strip()
            if txt:
                collected_parts.append(txt)
        candidate_zone = ' '.join(collected_parts).strip()
        # normalize candidate_zone and try to find a time
        candidate_zone_norm = _strip_accents(candidate_zone).lower()
        for pat in time_patterns:
            m = pat.search(candidate_zone_norm)
            if m:
                hh = m.group(1)
                mm = m.group(2) if m.lastindex and m.lastindex >= 2 and m.group(2) else None
                norm = normalize_time(hh, mm)
                if norm:
                    return norm
        # fallback: tenta no texto do pai
        try:
            parent_text = label.parent.get_text(' ', strip=True)
            parent_text_norm = _strip_accents(parent_text).lower()
            for pat in time_patterns:
                m = pat.search(parent_text_norm)
                if m:
                    hh = m.group(1)
                    mm = m.group(2) if m.lastindex and m.lastindex >= 2 and m.group(2) else None
                    norm = normalize_time(hh, mm)
                    if norm:
                        return norm
        except Exception:
            pass

    return ''


def click_closebtn(driver, debug: bool = False) -> bool:
    """
    Tenta fechar o modal/overlay clicando em <a class="closebtn"> (ou elemento similar).
    Retorna True se encontrou e clicou, False caso contrário.
    """
    try:
        # tentativa rápida: procura por a.closebtn
        elems = driver.find_elements(By.CSS_SELECTOR, 'a.closebtn, a[class*="closebtn"], button.closebtn')
        if elems:
            for e in elems:
                try:
                    try:
                        e.click()
                        time.sleep(0.5)
                        return True
                    except Exception:
                        # fallback JS
                        try:
                            driver.execute_script("arguments[0].click();", e)
                            time.sleep(0.5)
                            return True
                        except Exception:
                            continue
                except Exception:
                    continue
        # fallback: procurar por elementos que pareçam ser botões de fechar (icons)
        try:
            # localizar por atributo title ou aria-label
            close_candidates = driver.find_elements(By.XPATH, "//a[contains(@class,'close') or contains(@aria-label,'close') or contains(@title,'Close') or contains(@title,'Fechar')]")
            for c in close_candidates:
                try:
                    c.click()
                    time.sleep(0.5)
                    return True
                except Exception:
                    try:
                        driver.execute_script("arguments[0].click();", c)
                        time.sleep(0.5)
                        return True
                    except Exception:
                        continue
        except Exception:
            pass
    except Exception:
        pass
    return False
