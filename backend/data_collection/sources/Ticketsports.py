from bs4 import BeautifulSoup
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from data_collection.core.Driver import setup_driver


def is_ticketsports_domain(domain: str) -> bool:
    """Retorna True se o domínio pertence ao Ticketsports."""
    if not domain:
        return False
    return 'www.ticketsports.com.br' in domain.lower()


def load_ticketsports_soup(url: str, driver=None, wait_seconds: int = 20, debug: bool = False, return_counts: bool = False):
    """
    Carrega a página do Ticketsports com Selenium e tenta clicar no botão de inscrição
    identificado por <a id="bot_inscrever"> com texto 'INSCREVER-SE' ou 'SIGN UP'.

    Além disso, conta quantas `div.card` existem (cada card representa uma modalidade)
    e tenta clicar no primeiro elemento `.display-modality` para expandir/selecionar a modalidade.

    Retorna (soup, created, driver) - segue o mesmo contrato dos outros loaders.
    """
    created = False
    local_driver = driver
    try:
        if local_driver is None:
            local_driver = setup_driver()
            created = True

        # tenta carregar a página
        try:
            local_driver.set_page_load_timeout(60)
            local_driver.get(url)
        except Exception:
            # se o carregamento falhar por timeout, tenta prosseguir com a página atual
            pass

        wait = WebDriverWait(local_driver, wait_seconds)

        # Primeiro, tentar clicar no botão de inscrição se presente
        try:
            btn = wait.until(EC.presence_of_element_located((By.ID, 'bot_inscrever')))
            # Verifica texto para ter certeza que é o botão de inscrição
            try:
                txt = (btn.text or '').strip().upper()
            except Exception:
                txt = ''

            should_click = False
            if txt:
                if any(k in txt for k in ['INSCREVER', 'INSCREVER-SE', 'SIGN UP', 'SIGNUP', 'REGISTER']):
                    should_click = True
            else:
                # Se não há texto (ou é imagem), assumir que devemos tentar clicar
                should_click = True

            if should_click:
                try:
                    btn.click()
                    time.sleep(1)
                except Exception:
                    # fallback: usar JS click
                    try:
                        local_driver.execute_script("arguments[0].click();", btn)
                        time.sleep(1)
                    except Exception:
                        pass
        except Exception:
            pass
            # não encontrou por ID ou não clicável; tentar localizar por xpath buscando texto alternativo
            try:
                xpath = "//a[@id='bot_inscrever' or contains(translate(@id, 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'BOT_INSCRIBER')]"
                elems = local_driver.find_elements(By.XPATH, xpath)
                pass
                for e in elems:
                    try:
                        txt = (e.text or '').strip().upper()
                    except Exception:
                        txt = ''
                    if not txt or any(k in txt for k in ['INSCREVER', 'INSCREVER-SE', 'SIGN UP', 'SIGNUP', 'REGISTER']):
                        try:
                            local_driver.execute_script("arguments[0].click();", e)
                            time.sleep(1)
                            break
                        except Exception:
                            continue
            except Exception:
                pass

        # Pequeno scroll para forçar carregamento lazy
        try:
            local_driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
            time.sleep(0.8)
        except Exception:
            pass

        # Contar quantos cards existem (cada card representa uma modalidade)
        try:
            cards = local_driver.find_elements(By.CSS_SELECTOR, 'div.card')
            num_cards = len(cards)
            pass
        except Exception as e:
            num_cards = 0
            pass

        # Tentar clicar no primeiro .display-modality para expandir modalidades
        try:
            # Antes de interagir com as modalidades, garantir que estamos na tela de modalidades
            try:
                click_closebtn(local_driver, debug)
            except Exception:
                pass
            modals = local_driver.find_elements(By.CSS_SELECTOR, '.display-modality')
            pass
            if modals:
                target = modals[0]
                try:
                    target.click()
                    time.sleep(0.8)
                except Exception:
                    try:
                        local_driver.execute_script("arguments[0].click();", target)
                        time.sleep(0.8)
                    except Exception:
                        pass
        except Exception:
            pass

        # Pequeno scroll final e coleta do HTML atualizado
        try:
            local_driver.execute_script('window.scrollTo(0, 0);')
            time.sleep(0.5)
        except Exception:
            pass

        soup = BeautifulSoup(local_driver.page_source, 'html.parser')
        if return_counts:
            return soup, created, local_driver, num_cards
        return soup, created, local_driver
    except Exception as e:
        if created and local_driver:
            try:
                local_driver.quit()
            except Exception:
                pass
        return None, created, None


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
    from data_collection.utils.PriceUtils import parse_price_str
    import re

    results = []
    if not soup:
        return results

    spans = soup.find_all('span', class_='titulo-categoria-menor')
    pass

    # se não encontrar spans, tentar buscar dentro dos cards
    if not spans:
        cards_fallback = soup.find_all('div', class_='card')
        for card in cards_fallback:
            # tentativa de localizar título dentro do card
            title_span = card.find('span', class_='titulo-categoria-menor')
            if title_span:
                spans.append(title_span)

    # cache de list_id -> options para reutilizar quando múltiplas spans apontam
    list_cache = {}
    for span in spans:
        name = span.get_text(separator=' ', strip=True)
        # busca o container de lista de opções relativo ao card
        card = span.find_parent('div', class_='card')
        list_div = None
        if card:
            # procura por id que contenha 'ul-lista-card-modalidade'
            list_div = card.find(lambda tag: tag.name == 'div' and tag.get('id') and 'ul-lista-card-modalidade' in tag.get('id'))
            if not list_div:
                # fallback: procurar por div com classe que indique lista
                list_div = card.find('div', id=lambda x: x and 'lista-card-modalidade' in x)
        if not list_div:
            # busca global
            list_div = soup.find(lambda tag: tag.name == 'div' and tag.get('id') and 'ul-lista-card-modalidade' in tag.get('id'))

        options = []
        list_id = ''
        if list_div:
            list_id = list_div.get('id') or ''
            # se já temos no cache, reutiliza
            if list_id in list_cache and list_cache[list_id] is not None:
                options = list_cache[list_id]
            else:
                # parseia as opções e armazena
                radios = list_div.find_all('div', class_=lambda c: c and 'radio' in c and 'bloco-radio' in c)
                if not radios:
                    radios = list_div.find_all('div', class_='bloco-radio')
                for r in radios:
                    raw = r.get_text(separator=' ', strip=True)
                    price = None
                    m = re.search(r'R\$\s*([\d.,]+)', raw)
                    if m:
                        price = parse_price_str(m.group(1))
                    else:
                        price = parse_price_str(raw)

                    km = None
                    km_value = None
                    km_m = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:km\b|k\b)', raw, re.IGNORECASE)
                    if km_m:
                        km = km_m.group(1).replace(',', '.')
                        try:
                            km_value = float(km)
                        except Exception:
                            km_value = None
                    else:
                        nums = re.findall(r'(\d+(?:[.,]\d+)?)', raw)
                        if nums:
                            candidate = None
                            for n in nums:
                                try:
                                    v = float(n.replace(',', '.'))
                                except Exception:
                                    continue
                                if price is not None and abs(v - (price or 0)) < 0.01:
                                    continue
                                if v > 0 and v < 1000:
                                    candidate = v
                                    break
                            if candidate is not None:
                                km_value = candidate
                                km = str(candidate)

                    options.append({'label': None, 'km': km, 'km_value': km_value, 'price': price, 'raw': raw})
                # armazena no cache (mesmo que vazio)
                list_cache[list_id] = options
        else:
            pass

        results.append({'modality': name, 'options': options})

    # Dedup por nome de modalidade normalizado
    try:
        import unicodedata
        def normalize_name(s: str) -> str:
            if not s:
                return ''
            s = str(s)
            s = unicodedata.normalize('NFD', s)
            s = ''.join(ch for ch in s if not unicodedata.category(ch).startswith('M'))
            s = re.sub(r'\s+', ' ', s).strip().lower()
            return s

        seen = set()
        deduped = []
        for item in results:
            n = normalize_name(item.get('modality') or '')
            if n in seen:
                continue
            seen.add(n)
            deduped.append(item)
        return deduped
    except Exception:
        return results


def extract_ticketsports_ticket_prices(soup, debug: bool = False):
    """
    Converte a estrutura de modalidades extraída por `extract_ticketsports_modalities`
    em uma lista de entradas de preço padronizadas compatíveis com o pipeline.

    Cada entrada retornada é um dict com as chaves esperadas por `fmt_entry` e
    pelo `scraper_brasilquecorre.extract_price_entries`: { 'label', 'price', 'tax', 'raw' }
    """
    from data_collection.utils.PriceUtils import fmt_entry
    import re
    import unicodedata

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
    modalities = extract_ticketsports_modalities(soup, debug=debug)

    # evita duplicatas usando chave (mod_name_normalized, km_value, price, tax)
    seen_keys = set()
    for m in modalities:
        mod_name = (m.get('modality') or '').strip()
        for opt in m.get('options', []):
            price = opt.get('price')
            raw = opt.get('raw') or ''
            # tenta extrair taxa: padrão '+ R$ 8,80' ou '(+8,80 taxa)'
            tax = None
            tax_m = re.search(r'\+\s*R\$\s*([\d.,]+)', raw)
            if tax_m:
                try:
                    from data_collection.utils.PriceUtils import parse_price_str
                    tax = parse_price_str(tax_m.group(1))
                except Exception:
                    tax = None
            else:
                tax_m2 = re.search(r'\(\s*\+?([\d.,]+)\s*(?:taxa|tax|fee)\s*\)', raw, re.IGNORECASE)
                if tax_m2:
                    try:
                        from data_collection.utils.PriceUtils import parse_price_str
                        tax = parse_price_str(tax_m2.group(1))
                    except Exception:
                        tax = None

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
                label = f"{mod_name} — {km}km"
            else:
                label = mod_name or None

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
