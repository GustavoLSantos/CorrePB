import csv
import re
import os
import json
import time
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

from data_collection.core.Driver import setup_driver
from data_collection.sources.Sympla import is_sympla_domain, load_sympla_soup
from data_collection.sources.Liverun import is_liverun_domain, load_liverun_soup
from data_collection.sources.CircuitoDasEstacoes import is_circuito_domain, load_circuito_soup
from data_collection.sources.Race83 import is_race83_domain, is_race83_listing_url, detect_redirects_to_listing, load_race83_soup
from data_collection.utils.PriceUtils import parse_price_str, fmt_entry
from data_collection.utils.PrizeDetection import entry_is_prize

#Extração de preços
def extract_price_entries(soup, domain):
    """
    Retorna uma lista de entradas de preço estruturadas encontradas na página.

    Cada entrada é um dict: {
        label (str|None),
        price (float),
        tax (float|None),
        formatted (str),
        raw (str)
    }
    """
    page_html = str(soup)
    candidates = []

    try:
        from data_collection.sources.Sympla import extract_sympla_ticket_prices, is_sympla_domain as _is_sympla
        if _is_sympla(domain):
            try:
                sym_entries = extract_sympla_ticket_prices(soup)
                for e in sym_entries:
                    candidates.append({'label': e.get('label'), 'price': e.get('price'), 'tax': e.get('tax'), 'raw': e.get('raw')})
            except Exception:
                # se o extractor falhar, segue com heurísticas genéricas abaixo
                pass
    except Exception:
        # import falhou ou Sympla module indisponível: segue com heurísticas genéricas
        pass

    #Elementos de preço por classe
    def has_price_class(classes):
        if not classes:
            return False
        if isinstance(classes, str):
            cls_list = [classes]
        else:
            cls_list = list(classes)
        for c in cls_list:
            try:
                cl = c.lower()
            except Exception:
                continue
            if 'price' in cl or 'preco' in cl or 'valor' in cl or 'kit-price' in cl:
                return True
        return False

    price_elements = soup.find_all(['span', 'div', 'p'], class_=has_price_class)
    for elem in price_elements:
        txt = elem.get_text(separator=' ', strip=True)
        for m in re.findall(r'R\$(?:\s|\xa0|&nbsp;)*([\d.,]+)', txt):
            v = parse_price_str(m)
            tax = None
            tax_m = re.search(r'\(\s*\+?([\d.,]+)\s*(?:taxa|tax|fee)\s*\)', txt, re.IGNORECASE)
            if tax_m:
                tax = parse_price_str(tax_m.group(1))
            candidates.append({'label': None, 'price': v, 'tax': tax, 'raw': txt})


    #Detecta elementos com font-size inline grande que contêm R$
    try:
        for elem in soup.find_all(['span', 'div', 'p']):
            style = elem.get('style', '') or ''
            if 'font-size' in style and 'R$' in elem.get_text():
                m_px = re.search(r'font-size\s*:\s*(\d+)px', style)
                if m_px and int(m_px.group(1)) >= 20:
                    txt = elem.get_text(separator=' ', strip=True)
                    for m in re.findall(r'R\$(?:\s|\xa0|&nbsp;)*([\d.,]+)', txt):
                        v = parse_price_str(m)
                        candidates.append({'label': None, 'price': v, 'tax': None, 'raw': txt})
    except Exception:
        pass

    #Tabelas e tbodies (trata cabeçalhos de seção com colspan e preço na primeira td)
    try:
        blocks = soup.find_all(['table', 'tbody'])
        for table in blocks:
            current_section = None
            for tr in table.find_all('tr'):
                tds = tr.find_all(['td', 'th'])
                if len(tds) == 1 and tds[0].has_attr('colspan'):
                    sec_text = tds[0].get_text(separator=' ', strip=True)
                    sec_text = re.sub(r'\s+', ' ', sec_text).strip()
                    current_section = sec_text
                    continue
                if len(tds) >= 2:
                    left_text = tds[0].get_text(separator=' ', strip=True)
                    right_text = tds[1].get_text(separator=' ', strip=True)
                    left_has_price = bool(re.search(r'R\$', left_text))
                    right_has_price = bool(re.search(r'R\$', right_text))
                    if left_has_price and not right_has_price:
                        for m in re.findall(r'R\$(?:\s|\xa0|&nbsp;)*([\d.,]+)', left_text):
                            v = parse_price_str(m)
                            label = right_text or None
                            if current_section and label and current_section not in label:
                                label = f"{current_section} — {label}"
                            elif current_section and not label:
                                label = current_section
                            candidates.append({'label': label, 'price': v, 'tax': None, 'raw': f'{left_text} | {right_text}'})
                    elif right_has_price and not left_has_price:
                        for m in re.findall(r'R\$(?:\s|\xa0|&nbsp;)*([\d.,]+)', right_text):
                            v = parse_price_str(m)
                            label = left_text or None
                            if current_section and label and current_section not in label:
                                label = f"{current_section} — {label}"
                            elif current_section and not label:
                                label = current_section
                            candidates.append({'label': label, 'price': v, 'tax': None, 'raw': f'{left_text} | {right_text}'})
                    else:
                        # fallback: extrai qualquer preço na linha e tenta associar um label próximo
                        rowtxt = tr.get_text(separator=' ', strip=True)
                        for m in re.findall(r'R\$(?:\s|\xa0|&nbsp;)*([\d.,]+)', rowtxt):
                            v = parse_price_str(m)
                            label = None
                            if left_text and not re.search(r'R\$', left_text):
                                label = left_text
                                if current_section and current_section not in label:
                                    label = f"{current_section} — {label}"
                            elif right_text and not re.search(r'R\$', right_text):
                                label = right_text
                                if current_section and current_section not in label:
                                    label = f"{current_section} — {label}"
                            candidates.append({'label': label, 'price': v, 'tax': None, 'raw': rowtxt})
    except Exception:
        pass

    #Dados estruturados e atributos: meta tags, atributos data-price, JSON-LD
    try:
        # Meta tags
        for meta in soup.find_all('meta'):
            prop = (meta.get('property') or meta.get('name') or '').lower()
            content = meta.get('content', '')
            if prop in ('product:price:amount', 'price', 'og:price:amount') or 'price' in prop:
                if content:
                    v = parse_price_str(content)
                    if v is not None:
                        candidates.append({'label': None, 'price': v, 'tax': None, 'raw': f'meta:{prop}:{content}'})

        # Atributos data como data-price, data-preco, data-value
        for elem in soup.find_all(attrs=True):
            for attr, val in list(elem.attrs.items()):
                if re.search(r'data[-_]?(price|preco|valor|value)', attr, re.IGNORECASE):
                    v = parse_price_str(val)
                    if v is not None:
                        label = None
                        text = elem.get_text(separator=' ', strip=True)
                        if text and 'R$' not in text:
                            label = text
                        candidates.append({'label': label, 'price': v, 'tax': None, 'raw': f'{attr}={val}'})

        # Scripts JSON-LD
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                payload = json.loads(script.string or script.get_text() or '{}')
            except Exception:
                continue
            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                if isinstance(item, dict):
                    offers = item.get('offers') or item.get('priceSpecification')
                    if offers:
                        if isinstance(offers, list):
                            offers_iter = offers
                        else:
                            offers_iter = [offers]
                        for off in offers_iter:
                            if isinstance(off, dict):
                                price = off.get('price') or off.get('priceSpecification') or off.get('priceCurrency')
                                if price:
                                    v = parse_price_str(price)
                                    if v is not None:
                                        label = item.get('name') if item.get('name') else None
                                        candidates.append({'label': label, 'price': v, 'tax': None, 'raw': 'ldjson'})
                    # Campo direto de preço
                    if 'price' in item and item.get('price'):
                        v = parse_price_str(item.get('price'))
                        if v is not None:
                            label = item.get('name') if item.get('name') else None
                            candidates.append({'label': label, 'price': v, 'tax': None, 'raw': 'ldjson-price'})
    except Exception:
        pass

    #Fallbacks: R$ genérico, 'reais', faixas — apenas após parsing estruturado
    for m in re.findall(r'R\$(?:&nbsp;|\s)*([\d.,]+)', page_html):
        v = parse_price_str(m)
        if v is not None:
            candidates.append({'label': None, 'price': v, 'tax': None, 'raw': m})
    for m in re.findall(r'([\d.,]+)\s*reais', page_html, re.IGNORECASE):
        v = parse_price_str(m)
        if v is not None:
            candidates.append({'label': None, 'price': v, 'tax': None, 'raw': m})
    for a, b in re.findall(r'R\$\s*([\d.,]+)\s*(?:a|até|-)\s*(?:R\$)?\s*([\d.,]+)', page_html, re.IGNORECASE):
        va = parse_price_str(a)
        vb = parse_price_str(b)
        # Evita capturar índices pequenos (ex: '1-159,90') como preço '1.0'.
        # Se o lado esquerdo for <10 e não contiver separador decimal, e o direito contiver, ignora o esquerdo.
        try:
            a_has_dec = ',' in a or '.' in a
        except Exception:
            a_has_dec = False
        try:
            b_has_dec = ',' in b or '.' in b
        except Exception:
            b_has_dec = False
        if va is not None:
            if not (va < 10 and not a_has_dec and b_has_dec):
                candidates.append({'label': None, 'price': va, 'tax': None, 'raw': f'{a}-{b}'})
        if vb is not None:
            if not (vb < 10 and not b_has_dec and a_has_dec):
                candidates.append({'label': None, 'price': vb, 'tax': None, 'raw': f'{a}-{b}'})
    for a, b in re.findall(r'(?:R\$)?\s*([\d.,]+)\s*(?:a|até|-)\s*R\$\s*([\d.,]+)', page_html, re.IGNORECASE):
        va = parse_price_str(a)
        vb = parse_price_str(b)
        try:
            a_has_dec = ',' in a or '.' in a
        except Exception:
            a_has_dec = False
        try:
            b_has_dec = ',' in b or '.' in b
        except Exception:
            b_has_dec = False
        if va is not None:
            if not (va < 10 and not a_has_dec and b_has_dec):
                candidates.append({'label': None, 'price': va, 'tax': None, 'raw': f'{a}-{b}'})
        if vb is not None:
            if not (vb < 10 and not b_has_dec and a_has_dec):
                candidates.append({'label': None, 'price': vb, 'tax': None, 'raw': f'{a}-{b}'})

    # Após coletar candidatos, filtra valores de prêmios/premiações usando verificação contextual
    # Usa verificação sensível ao contexto: o raw/label do candidato pode não conter palavras-chave de prêmio,
    # então inspeciona o HTML da página ao redor de onde o preço ocorre também.
    candidates = [e for e in candidates if not entry_is_prize(e, page_html)]

    # Se temos preços rotulados de tabelas/grids estruturados, prefere eles e descarta duplicatas não rotuladas
    labeled_prices = {e.get('price') for e in candidates if e.get('label')}
    if labeled_prices:
        candidates = [e for e in candidates if not (e.get('label') is None and e.get('price') in labeled_prices)]

    # Filtra preços de inscrição plausíveis (ajusta limites se necessário)
    valid_entries = [e for e in candidates if e.get('price') is not None and 0 <= e.get('price') <= 500]

    # Se há preços pagos, exclui entradas gratuitas (0.00) para evitar falsos positivos
    if any(e['price'] > 0 for e in valid_entries):
        valid_entries = [e for e in valid_entries if e['price'] > 0]

    if not valid_entries:
        # Se não há preços pagos, verifica indicadores de gratuito
        if re.search(r'\b(grátis|gratis|gratuito|gratuita|isento|free)\b', page_html, re.IGNORECASE):
            return [{'label': None, 'price': 0.0, 'tax': None, 'formatted': 'R$ 0,00', 'raw': page_html}]
        # Se não foi encontrado indicador de gratuidade, devolve uma entry informativa
        # para que o campo legível 'preco' seja preenchido com 'Valor não encontrado'.
        return [{'label': None, 'price': None, 'tax': None, 'formatted': 'Valor não encontrado', 'raw': page_html}]

    # Deduplica por (label, price, tax)
    seen = set()
    unique = []
    for e in valid_entries:
        key = (e.get('label') or '', float(e.get('price')), e.get('tax') if e.get('tax') is None else float(e.get('tax')))
        if key not in seen:
            seen.add(key)
            unique.append(e)

    # Ordena por preço crescente
    unique_sorted = sorted(unique, key=lambda x: (x.get('price') or 0))


    return [fmt_entry(e) for e in unique_sorted]


#Extração de edital
def extract_edital(url):
    """Extrai o link do edital usando requests."""
    try:
        response = requests.get(url, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        domain = urlparse(url).netloc

        if 'zeniteesportes.com' in domain:
            # Procura por links com texto "regulamento"
            reg_links = [a for a in soup.find_all('a') if re.search(r'regulamento', a.get_text() or '', re.IGNORECASE)]
            for link in reg_links:
                onclick = link.get('onclick', '')
                if '.pdf' in onclick.lower():
                    pdf_match = re.search(r"abrirPDF\('([^']+)'\)", onclick)
                    if pdf_match:
                        return pdf_match.group(1)
                href = link.get('href', '')
                if '.pdf' in href.lower():
                    return href

            # Busca genérica por links PDF
            pdf_links = soup.find_all('a', href=re.compile(r'\.pdf', re.IGNORECASE))
            if pdf_links:
                return pdf_links[0].get('href', '')

        elif 'race83.com.br' in domain or 'correparaiba.com' in domain:
            pdf_link = soup.find('a', href=re.compile(r'\.pdf', re.IGNORECASE))
            if pdf_link:
                return pdf_link.get('href', '')

        return 'edital não encontrado'
    except Exception:
        return 'edital não encontrado'


# PROCESSAMENTO PARALELO DE DETALHES DOS EVENTOS
def process_event_details(events):
    """
    Processa editais e preços de múltiplos eventos em paralelo.
    Usa ThreadPoolExecutor para acelerar a extração de dados de cada URL.
    """
    def fetch_details(event_info):
        """Busca detalhes de um evento específico (edital e preços)."""
        url = event_info.get('link_inscricao', '')
        if url:
            try:
                domain = urlparse(url).netloc
                soup = None
                # variáveis relacionadas ao loader Sympla — inicializa aqui para não depender do branch
                created = False
                sym_driver = None
                temp_driver = None
                liverun_driver = None
                race_driver = None

                # Se o domínio é do race83, detecta redirecionamentos para a listagem genérica
                try:
                    if is_race83_domain(domain):
                        is_listing, final = detect_redirects_to_listing(url, timeout=5)
                        if is_listing:
                            print(f"[SKIP] URL do Race83 redirecionou para listagem /eventos, pulando: {url} -> {final}")
                            return None
                except Exception:
                    pass

                if is_sympla_domain(domain):
                    # Usa o loader específico para Sympla (pode criar/quitar driver internamente)
                    try:
                        soup, created, sym_driver = load_sympla_soup(url)
                    except Exception:
                        soup, created, sym_driver = None, False, None
                elif is_circuito_domain(domain):
                    try:
                        soup, created, temp_driver = load_circuito_soup(url)
                    except Exception:
                        soup, created, temp_driver = None, False, None
                elif is_liverun_domain(domain):
                    try:
                        soup, created, liverun_driver = load_liverun_soup(url)
                    except Exception:
                        soup, created, liverun_driver = None, False, None
                elif is_race83_domain(domain):
                    try:
                        soup, created, race_driver = load_race83_soup(url)
                    except Exception:
                        soup, created, race_driver = None, False, None
                else:
                    # Sites estáticos podem usar requests simples
                    try:
                        response = requests.get(url, timeout=5)
                        soup = BeautifulSoup(response.text, 'html.parser')
                    except Exception:
                        soup = None

                # Se o Sympla loader criou um driver, certifica-se de fechá-lo após usar o soup
                if 'sym_driver' in locals() and sym_driver and 'created' in locals() and created:
                    try:
                        sym_driver.quit()
                    except Exception:
                        pass
                # Fecha driver criado pelo loader de circuito, se houver
                if 'temp_driver' in locals() and temp_driver and 'created' in locals() and created:
                    try:
                        temp_driver.quit()
                    except Exception:
                        pass
                # Fecha driver criado pelo loader de liverun, se houver
                if 'liverun_driver' in locals() and liverun_driver and 'created' in locals() and created:
                    try:
                        liverun_driver.quit()
                    except Exception:
                        pass
                # Fecha driver criado pelo loader de race83, se houver
                if 'race_driver' in locals() and race_driver and 'created' in locals() and created:
                    try:
                        race_driver.quit()
                    except Exception:
                        pass
                if soup:
                    # Extrai edital
                    event_info['link_edital'] = extract_edital(url)

                    # Extrai preços estruturados e formatados
                    entries = extract_price_entries(soup, domain)
                    event_info['precos_entries'] = entries

                    # String legível para humanos (compatibilidade retroativa)
                    if entries:
                        event_info['preco'] = '; '.join(e.get('formatted', '') for e in entries)
                    else:
                        event_info['preco'] = 'preço não encontrado'
                else:
                    event_info['link_edital'] = 'edital não encontrado'
                    event_info['preco'] = 'preço não encontrado'
                    event_info['precos_entries'] = []
            except Exception:
                event_info['link_edital'] = 'edital não encontrado'
                event_info['preco'] = 'preço não encontrado'
                event_info['precos_entries'] = []
        else:
            event_info['link_edital'] = 'edital não encontrado'
            event_info['preco'] = 'preço não encontrado'
            event_info['precos_entries'] = []
        return event_info

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_details, event): event for event in events}
        results = []
        for idx, future in enumerate(as_completed(futures), 1):
            try:
                result = future.result()
                # Se fetch_details retornou None, significa que o evento deve ser pulado
                if result is None:
                    continue
                results.append(result)
                print(f"[{idx}/{len(events)}] ✓ {result.get('nome', '')}")
                print(f"   Edital: {result.get('link_edital', '')[:50]}")
                print(f"   Preço: {result.get('preco', '')}")
            except Exception as e:
                event = futures[future]
                event['link_edital'] = 'edital não encontrado'
                event['preco'] = 'preço não encontrado'
                results.append(event)
        return results

# EXTRAÇÃO DE DADOS DOS EVENTOS
def get_event_data(driver):
    """
    Extrai os dados dos eventos da página Brasil Que Corre - Paraíba.

    Implementa tentativas múltiplas de carregamento para maior robustez.
    Extrai informações básicas (nome, data, cidade, distâncias, etc.) e depois
    busca detalhes adicionais (preços e editais) em paralelo.
    """
    try:
        url = "https://brasilquecorre.com/paraiba"
        attempts = 3

        # Tenta carregar a página com múltiplas tentativas
        for attempt in range(1, attempts + 1):
            try:
                driver.set_page_load_timeout(30)
                driver.get(url)
                break  # Sucesso
            except (TimeoutException, WebDriverException) as e:
                print(f"[get_event_data] Tentativa {attempt} falhou ao carregar a página: {e}")
                # Tenta parar o carregamento e tentar novamente após breve espera
                try:
                    driver.execute_script("window.stop();")
                except Exception:
                    pass
                time.sleep(2)
                if attempt == attempts:
                    raise
                continue

        # Aguarda os elementos dos eventos aparecerem
        wait = WebDriverWait(driver, 20)
        event_boxes = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.cs-box")))

        event_data = []
        data_pattern = re.compile(r'\d{1,2}\s+de\s+[A-Za-zçÇ]+\s+de\s+\d{4}')

        total_events = len(event_boxes)
        print(f"\nEncontrados {total_events} eventos. Iniciando extração\n")

        # Primeira iteração: extrai dados básicos de cada evento
        for idx, box in enumerate(event_boxes, 1):
            event_info = {}
            try:
                # Nome do evento e link de inscrição
                name_element = box.find_element(By.CSS_SELECTOR, "h5 a")
                event_info['nome'] = name_element.text
                event_info['link_inscricao'] = name_element.get_attribute('href')

                # Ignorar URLs redirecionadas/que não são de evento
                try:
                    link_insc = event_info.get('link_inscricao', '') or ''
                    if link_insc.startswith('https://www.liverun.com.br/calendario'):
                        print(f"[SKIP] Pulando link de calendário genérico do Liverun: {link_insc}")
                        continue
                    # Também ignora listagem genérica de eventos do Race83 (usa helper específico)
                    if is_race83_listing_url(link_insc):
                        print(f"[SKIP] Pulando link de eventos genérico do Race83: {link_insc}")
                        continue
                except Exception:
                    pass

                # Imagem do evento
                img_element = box.find_element(By.CSS_SELECTOR, "img.cs-chosen-image")
                event_info['link_imagem'] = img_element.get_attribute('src')

                # Extrai informações textuais (data, cidade, distâncias, organizador)
                text_elements = box.find_elements(By.CSS_SELECTOR, "div.text-editor p")
                distancias_encontradas = []

                for idx_elem, element in enumerate(text_elements):
                    text = element.text.strip()
                    if text and not text.isspace():
                        if data_pattern.search(text):
                            event_info['data'] = text
                        elif any(term in text for term in
                                 ['(corrida)', '(caminhada)', '(trail)', '(ultra)', '(infantil)']):
                            distancias_encontradas.append(text)
                        elif idx_elem == len(text_elements) - 1:
                            event_info['organizador'] = text
                        elif 'cidade' not in event_info:
                            event_info['cidade'] = text

                if distancias_encontradas:
                    event_info['distancia'] = ', '.join(distancias_encontradas)

                event_data.append(event_info)
                print(f"[{idx}/{total_events}] ✓ Dados básicos: {event_info.get('nome', '')}")

            except Exception as e:
                continue

        # Segunda iteração: busca editais e preços em paralelo
        print(f"\nBuscando editais e preços...\n")
        event_data = process_event_details(event_data)

        return event_data

    except Exception as e:
        print(f"Erro crítico ao buscar dados dos eventos: {e}")
        return []

# FUNÇÃO PRINCIPAL E SALVAMENTO DE DADOS
def main():
    """
    Função principal para executar o scraper e salvar os dados.

    Executa todo o processo de scraping:
    1. Configura o driver Selenium
    2. Extrai dados dos eventos
    3. Salva em CSV
    """
    driver = setup_driver()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(base_dir, 'eventos_brasilquecorre.csv')

    try:
        event_data = get_event_data(driver)

        if not event_data:
            print("Nenhum evento encontrado ou ocorreu um erro.")
            return

        print(f"\nTotal de {len(event_data)} eventos encontrados. Salvando no CSV...")

        # Salva dados em CSV
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['Nome do Evento', 'Link de Inscrição', 'Link da Imagem', 'Data', 'Cidade', 'Distância',
                          'Organizador', 'Preço', 'Link do Edital']
            writer = csv.writer(csvfile, delimiter=';')
            writer.writerow(fieldnames)

            for event in event_data:
                writer.writerow([
                    event.get('nome', ''),
                    event.get('link_inscricao', ''),
                    event.get('link_imagem', ''),
                    event.get('data', ''),
                    event.get('cidade', ''),
                    event.get('distancia', ''),
                    event.get('organizador', ''),
                    event.get('preco', ''),
                    event.get('link_edital', '')
                ])

        print(f"\nDados salvos com sucesso em: {csv_path}")

    finally:
        driver.quit()

if __name__ == "__main__":
    main()