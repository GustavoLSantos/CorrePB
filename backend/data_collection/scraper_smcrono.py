import sys
import os
import csv
import re
import io
import time
import json
from datetime import datetime
from urllib.parse import urljoin

import requests
from PyPDF2 import PdfReader

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from data_collection.core.Driver import setup_driver
from data_collection.utils.PriceUtils import parse_price_str
from data_collection.utils.PrizeDetection import entry_is_prize

def fix_encoding(text):
    if not text: return ""
    try:
        return text.encode('latin1').decode('utf-8')
    except:
        return text


KIT_ITEMS_PATTERN = re.compile(
    r'\b(camiseta|camisa|medalha|n[uú]mero\s+d[oea]+\s*peito|chip|meia|viseira|'
    r'sacochila|bon[eé]|squeeze|ecobag|mochila|toalha|pochete|regata)\b',
    re.IGNORECASE
)

KIT_ITEMS_NORMALIZE = {
    'camisa': 'camiseta',
}

def _normalize_item(item):
    item = re.sub(r'\s+', ' ', item.strip().lower())
    item = re.sub(r'n[uú]mero\s+d[oea]+\s*peito', 'número de peito', item)
    return KIT_ITEMS_NORMALIZE.get(item, item)

MESES_NUM = {
    'janeiro': 1, 'fevereiro': 2, 'março': 3, 'marco': 3, 'abril': 4,
    'maio': 5, 'junho': 6, 'julho': 7, 'agosto': 8,
    'setembro': 9, 'outubro': 10, 'novembro': 11, 'dezembro': 12
}


def _extract_pdf_text(pdf_url):
    resp = requests.get(pdf_url, timeout=15)
    resp.raise_for_status()
    reader = PdfReader(io.BytesIO(resp.content))
    return '\n'.join(page.extract_text() or '' for page in reader.pages)


def _parse_largada(text):
    a_definir = re.compile(r'^\(?[àa]\s*definir\)?\.?\s*$', re.IGNORECASE)
    hora_pattern = re.compile(r'^\s*[àa]s\s+\d{1,2}[h:]\d{2}', re.IGNORECASE)
    # Frases genéricas que não são locais
    generic_pattern = re.compile(
        r'com\s+pelo\s+menos|meia\s+hora|anteced[eê]ncia|dever[aá]|ser[aá]\s+[àa]s|no\s+mesmo\s+local',
        re.IGNORECASE
    )
    patterns = [
        r'(?:local\s+d[aeo]\s+largada|ponto\s+de\s+partida)[:\s\-–]+(.+)',
        r'(?:largada\s+e\s+chegada|concentra[çc][aã]o\s+e\s+largada)[:\s\-–]+(.+)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            local = m.group(1).strip().split('\n')[0].strip()
            local = re.sub(r'\s{2,}', ' ', local)
            # Limpar prefixos comuns do PyPDF2
            local = re.sub(r'^e\s+(?:C|c)hegada[:\s\-–]*', '', local).strip()
            if not local or a_definir.match(local) or hora_pattern.match(local) or generic_pattern.search(local):
                continue
            return local
    return None


def _find_kit_sections(text):
    """Encontra todas as seções relacionadas a kit no texto do PDF."""
    # Padrões que iniciam uma seção de kit (variações encontradas nos regulamentos)
    header_patterns = [
        r'(?:^|\n)\s*(?:\d+[\.\-\s]*)*\s*(?:D[AO]S?\s+)?(?:COMPOSI[CÇ][AÃ]O\s+D[OE]S?\s+)?KITS?\s*(?:D[OE]S?\s+ATLETAS?)?',
        r'(?:^|\n)\s*(?:\d+[\.\-\s]*)*\s*(?:ENTREGA|RETIRADA)\s+D[OE]S?\s+KITS?',
        r'(?:^|\n)\s*(?:Cap[ií]tulo|Art(?:igo)?)\s+[^\n]*KITS?',
        r'(?:^|\n)\s*Entrega\s+d[eo]s?\s+kits?[:\s]',
    ]
    sections = []
    for pat in header_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            end = len(text)
            # Buscar próximo cabeçalho de seção para delimitar
            next_header = re.search(
                r'\n\s*(?:\d+[\.\-\s]*)+\s*(?:CRONOMETRAGEM|PREMIA|REGRAS?\s+GERA|PERCURSO|LARGADA|CATEGORIAS|DECLARA|DISPOSI|PENALID)',
                text[m.end():], re.IGNORECASE
            )
            if next_header:
                end = m.end() + next_header.start()
            sections.append(text[m.start():end])
    return sections


def _parse_kit_info(text):
    """Extrai itens, local e data de retirada do texto completo do PDF."""
    a_definir = re.compile(r'^\(?[àa]\s*definir\)?\.?\s*$', re.IGNORECASE)

    kit_sections = _find_kit_sections(text)
    if not kit_sections:
        return None

    combined = '\n'.join(kit_sections)

    # --- ITENS ---
    itens = list({_normalize_item(m.group(0)) for m in KIT_ITEMS_PATTERN.finditer(combined)})

    # --- LOCAL DE RETIRADA ---
    local_retirada = None
    # Padrões específicos para local/endereço de retirada de kit
    local_patterns = [
        r'[Ee]ndere[cç]o[:\s\-–]+(.+)',
        r'[Ll]ocal\s*(?:de|da|para)\s*(?:entrega|retirada)[:\s\-–]+(.+)',
    ]
    local_blacklist = re.compile(
        r'http|www\.|deslocamento|anteced[eê]ncia|estabelecid|largada|obrigat|comprova|inscri[çc]',
        re.IGNORECASE
    )
    for pat in local_patterns:
        for m in re.finditer(pat, combined, re.IGNORECASE):
            candidate = m.group(1).strip().split('\n')[0].strip()
            candidate = re.sub(r'^[:\s\-–]+', '', candidate)
            candidate = re.sub(r'\s{2,}', ' ', candidate).strip(' .')
            if (candidate
                and not a_definir.match(candidate)
                and not local_blacklist.search(candidate)
                and len(candidate) > 3):
                local_retirada = candidate
                break
        if local_retirada:
            break

    # Fallback: buscar "Endereço:" no texto inteiro perto de kit/entrega
    if not local_retirada:
        for m in re.finditer(r'[Ee]ndere[cç]o[:\s\-–]+(.+)', text):
            candidate = m.group(1).strip().split('\n')[0].strip()
            candidate = re.sub(r'\s{2,}', ' ', candidate).strip(' .')
            if candidate and len(candidate) > 5 and not local_blacklist.search(candidate):
                local_retirada = candidate
                break

    # Fallback: "– LOCAL NOME" ou "DATA ... LOCAL NOME" (ex: "LOCAL MEGGA SHOES")
    if not local_retirada:
        skip = re.compile(r'^(D[AEOI]S?\b|PARA\b|KIT|PROVA|EVENTO|RETIRADA|E\s+DATA|HOR|QUE\b|ONDO)', re.IGNORECASE)
        for section in kit_sections:
            for loc_m in re.finditer(r'[–\-]\s*LOCAL\s+([A-Z][A-Za-z\s]{4,})', section):
                candidate = loc_m.group(1).strip()
                candidate = re.sub(r'\s{2,}', ' ', candidate).strip(' .')
                if candidate and not skip.match(candidate) and not local_blacklist.search(candidate):
                    local_retirada = candidate
                    break
            if local_retirada:
                break

    # --- DATA DE RETIRADA ---
    # Buscar datas perto de "entrega" ou "retirada" de kit
    data_retirada = None
    entrega_context = re.findall(
        r'(?:entrega|retirada)[^\n]{0,80}',
        combined, re.IGNORECASE
    )
    search_text = '\n'.join(entrega_context) if entrega_context else combined

    # Formato: "16 de maio 2026" ou "16 de maio de 2026"
    date_m = re.search(r'(\d{1,2})\s+de\s+(\w+)\s+(?:de\s+)?(\d{4})', search_text, re.IGNORECASE)
    if not date_m:
        # Formato: "16/05/2026"
        date_m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', search_text)
    if date_m:
        try:
            g = date_m.groups()
            if '/' in date_m.group(0):
                data_retirada = datetime(int(g[2]), int(g[1]), int(g[0])).isoformat()
            else:
                mes = MESES_NUM.get(g[1].lower())
                if mes:
                    data_retirada = datetime(int(g[2]), mes, int(g[0])).isoformat()
        except (ValueError, KeyError):
            pass

    # Também buscar info de kit no topo do documento (padrão "Entrega do kit: DATA")
    top_kit = re.search(
        r'Entrega\s+d[eo]s?\s+kits?[:\s\-–]+(.+)',
        text[:2000], re.IGNORECASE
    )
    if top_kit and not data_retirada:
        top_line = top_kit.group(1).strip()
        date_m2 = re.search(r'(\d{1,2})\s+(?:de\s+)?(\w+)\s+(?:de\s+)?(\d{4})', top_line, re.IGNORECASE)
        if not date_m2:
            date_m2 = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', top_line)
        if date_m2:
            try:
                g = date_m2.groups()
                if '/' in date_m2.group(0):
                    data_retirada = datetime(int(g[2]), int(g[1]), int(g[0])).isoformat()
                else:
                    mes = MESES_NUM.get(g[1].lower())
                    if mes:
                        data_retirada = datetime(int(g[2]), mes, int(g[0])).isoformat()
            except (ValueError, KeyError):
                pass

    # Também buscar itens no topo do documento se não encontrou nas seções
    if not itens:
        top_itens = list({_normalize_item(m.group(0)) for m in KIT_ITEMS_PATTERN.finditer(text)})
        itens = top_itens

    if not itens and not local_retirada:
        return None

    return [{
        'nome': 'Kit',
        'itens': sorted(itens),
        'local_retirada': local_retirada,
        'data_retirada': data_retirada
    }]


def extract_kits_and_percurso_from_pdf(pdf_url):
    if not pdf_url or pdf_url.lower() in ('edital não encontrado', 'edital nao encontrado', ''):
        return {'percurso': None, 'kits': None}
    try:
        text = _extract_pdf_text(pdf_url)
        if not text.strip():
            return {'percurso': None, 'kits': None}

        local_largada = _parse_largada(text)
        percurso = {'local_largada': local_largada} if local_largada else None
        kits = _parse_kit_info(text)

        return {'percurso': percurso, 'kits': kits}
    except Exception as e:
        print(f"  [WARN] Erro ao extrair PDF ({pdf_url}): {e}")
        return {'percurso': None, 'kits': None}

def extract_smcrono_details_robust(driver):
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    full_text = soup.get_text(separator='\n', strip=True)
    
    details = {
        'data': '',
        'cidade': '',
        'estado': '',
        'horario': '',
        'distancias': [],
        'precos': [],
        'link_imagem': ''
    }

    # --- CIDADE E ESTADO ---
    city_div = soup.find('div', style=re.compile(r'border-left:\s*2px\s+solid\s+#CCC', re.IGNORECASE))
    if city_div:
        text_content = city_div.get_text(separator='|', strip=True)
        parts = text_content.split('|')
        if len(parts) >= 2:
            details['cidade'] = fix_encoding(parts[0].strip().title())
            details['estado'] = parts[1].strip().upper()
        elif len(parts) == 1:
            match = re.search(r'(.*?)\s+([A-Z]{2})$', parts[0])
            if match:
                details['cidade'] = fix_encoding(match.group(1).strip().title())
                details['estado'] = match.group(2)
            else:
                details['cidade'] = fix_encoding(parts[0].strip().title())
                details['estado'] = 'PB'
    
    if not details['cidade']:
        loc_match = re.search(r'([A-ZÀ-Ú][a-zà-ú]+(?:\s[A-ZÀ-Ú][a-zà-ú]+)*)\s*[-/]\s*(PB|PE|RN)', full_text)
        if loc_match:
            details['cidade'] = fix_encoding(loc_match.group(1).strip())
            details['estado'] = loc_match.group(2).upper()

    # --- DATA ---
    date_match = re.search(r'(\d{2}/\d{2}/202[5-6])', full_text)
    if not date_match:
        date_match = re.search(r'Data:\s*(\d{2}/\d{2}/\d{4})', full_text, re.IGNORECASE)
    if date_match:
        try:
            dt_str = date_match.group(1)
            dt = datetime.strptime(dt_str, '%d/%m/%Y')
            meses = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
                     'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']
            details['data'] = f"{dt.day} de {meses[dt.month-1]} de {dt.year}"
        except:
            details['data'] = date_match.group(1)

    # --- HORÁRIO ---
    time_match_specific = re.search(r'\d{2}/\d{2}/\d{4}\s*-\s*(\d{2}:\d{2})h?', full_text)
    if time_match_specific:
        details['horario'] = time_match_specific.group(1).replace(':', 'h')
    else:
        time_match = re.search(r'(\d{1,2}[h:]\d{2})\s*(?:h|hrs|horas)?\s*(?:largada|inicio|manhã)', full_text, re.IGNORECASE)
        if not time_match:
             time_match = re.search(r'Largada[^0-9]{1,20}(\d{1,2}[h:]\d{2})', full_text, re.IGNORECASE)
        if time_match:
            details['horario'] = time_match.group(1).replace(':', 'h').lower()
            
    if details['horario'] and 'h' not in details['horario']:
        details['horario'] += 'h'

    # --- PREÇOS ---
    raw_prices = []
    lines = full_text.split('\n')
    
    # Variável para memorizar a categoria atual (ex: "5KM", "10KM")
    current_category = None
    
    # Regex para identificar cabeçalhos de categoria (números seguidos de KM ou palavras chave)
    # Ex: "3KM", "5 KM", "10km", "CAMINHADA", "KIDS"
    category_pattern = re.compile(r'^(\d+[\s\.]*[Kk][Mm]|\d+[\s\.]*[Mm]|CAMINHADA|KIDS|PNE|PERCURSO)', re.IGNORECASE)

    for i, line in enumerate(lines):
        line = line.strip()
        if not line: continue

        # 1. DETECTAR MUDANÇA DE CATEGORIA
        # Se a linha for curta (< 20 chars) e bater com o padrão de distância, atualizamos a categoria
        if len(line) < 20 and category_pattern.search(line):
             current_category = line.upper()
             continue # Pula para a próxima linha

        # 2. EXTRAIR PREÇO
        if 'R$' in line:
            vals = re.findall(r'R\$\s*(\d+[.,]\d{2})', line)
            for v in vals:
                try:
                    price_float = parse_price_str(v)
                    if price_float > 0:
                        # Remove o preço da linha para sobrar só o nome (ex: "R$ 89,99 GERAL" -> "GERAL")
                        label = line.replace(f"R$ {v}", "").replace(f"R${v}", "").strip()
                        label = fix_encoding(label)
                        
                        # --- CORREÇÃO: BUSCAR LABEL NA PRÓXIMA LINHA SE ESTIVER VAZIO ---
                        # Às vezes o web scraping quebra a linha:
                        # Linha 1: R$ 89,99
                        # Linha 2: GERAL
                        if not label and (i + 1 < len(lines)):
                             next_line = lines[i+1].strip()
                             # Se a próxima linha não for outro preço nem outra categoria, é o label!
                             if 'R$' not in next_line and not category_pattern.search(next_line):
                                 label = fix_encoding(next_line)

                        if len(label) > 60:
                            label = label[:60] + "..."
                        if not label:
                            label = "Geral"

                        # 3. PREFIXAR A CATEGORIA (O PULO DO GATO)
                        # Se temos uma categoria salva (ex: "5KM"), juntamos com o label
                        if current_category:
                            # Só adiciona se o label já não tiver a info (evita "5KM - 5KM GERAL")
                            if current_category not in label.upper():
                                label = f"{current_category} — {label}"


                        normalized_label = re.sub(r"\s+", " ", label).strip()


                        entry = {'raw': line, 'label': normalized_label, 'price': price_float}
                        try:
                            if entry_is_prize(entry, driver.page_source):
                                # ignora entradas que correspondem a premiação
                                continue
                        except Exception:
                            # Em caso de erro na detecção, não bloqueia o scraping — registra silenciosamente e segue
                            pass

                        raw_prices.append({'label': normalized_label, 'price': price_float, 'formatted': f"R$ {v}"})
                except:
                    pass
    
    seen = set()
    unique_prices = []
    for p in raw_prices:
        k = (p['price'], p['label'])
        if k not in seen:
            seen.add(k)
            unique_prices.append(p)
    details['precos'] = sorted(unique_prices, key=lambda x: x['price'])
    
    # --- DISTÂNCIAS ---
    dists = set()
    matches = re.findall(r'\b(\d+(?:[.,]\d+)?)\s*(?:k|km|Km|KM)\b', full_text)
    for m in matches:
        try:
            val = float(m.replace(',', '.'))
            if val < 100: dists.add(f"{m}km (corrida)")
        except: pass
    details['distancias'] = list(dists)

    # --- IMAGEM ---
    img_url = ""
    try:
        banner_div = soup.find('div', class_=re.compile(r'col-.*-5'))
        if banner_div:
            img = banner_div.find('img')
            if img and img.get('src'):
                img_url = img['src']
        
        if not img_url:
            images = soup.find_all('img')
            for img in images:
                src = img.get('src', '')
                if 'logo' in src.lower() or 'icon' in src.lower() or 'whatsapp' in src.lower():
                    continue
                if src and not src.startswith('http'):
                    src = urljoin("https://www.smcrono.com.br", src)
                img_url = src
                break
        
        if img_url and not img_url.startswith('http'):
            img_url = urljoin("https://www.smcrono.com.br", img_url)
    except Exception:
        pass

    details['link_imagem'] = img_url
    return details

def get_smcrono_events_v2(driver, estado_filter='PB'):
    print("Acessando calendário completo...")
    driver.get("https://www.smcrono.com.br/calendario-eventos")
    time.sleep(5) 
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(3)

    links = set()
    elems = driver.find_elements(By.CSS_SELECTOR, "a[href*='/evento/']")
    print(f"Encontrados {len(elems)} elementos com link. Filtrando...")
    for elem in elems:
        href = elem.get_attribute('href')
        if href and '/evento/' in href and 'inscricao' not in href:
            links.add(href)
    
    print(f"Total de {len(links)} URLs únicas de eventos encontradas.")
    events_data = []
    
    for idx, url in enumerate(links, 1):
        try:
            print(f"[{idx}/{len(links)}] Analisando: {url}")
            driver.get(url)
            time.sleep(1.5)
            
            try:
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                title_elem = soup.find('h1') or soup.find('h2') or soup.find('h3')
                nome_evento = title_elem.get_text(strip=True) if title_elem else ""
                if not nome_evento:
                    parts = url.strip('/').split('/')
                    nome_evento = parts[-1].replace('-', ' ').title()
            except:
                nome_evento = "Evento Desconhecido"

            details = extract_smcrono_details_robust(driver)
            
            if estado_filter:
                if not details['estado']:
                    text_u = soup.get_text().upper()
                    if "PARAIBA" in text_u or "PARAÍBA" in text_u or "JOAO PESSOA" in text_u:
                        details['estado'] = "PB"
                if details['estado'] != estado_filter:
                    print(f"  -> Ignorado: Estado detectado '{details['estado']}'")
                    continue

            edital_link = ""
            try:
                link_pdf = driver.find_element(By.CSS_SELECTOR, "a[href$='.pdf']")
                edital_link = link_pdf.get_attribute('href')
            except:
                edital_link = "edital não encontrado"

            pdf_data = extract_kits_and_percurso_from_pdf(edital_link)
            percurso_json = json.dumps(pdf_data['percurso'], ensure_ascii=False) if pdf_data['percurso'] else ""
            kits_json = json.dumps(pdf_data['kits'], ensure_ascii=False) if pdf_data['kits'] else ""

            json_precos_entries = "[]"
            if details['precos']:
                try:
                    safe_prices = []
                    for p in details['precos']:
                        label_atual = str(p.get("label", ""))
                        preco_atual = str(p.get("formatted", ""))
                        texto_formatado = f"{preco_atual} | {label_atual}"
                        safe_prices.append(texto_formatado)
                    json_precos_entries = json.dumps(safe_prices, ensure_ascii=False) if safe_prices else "[]"
                except Exception as e:
                    print(f"  ⚠️ Erro JSON: {e}")
                    json_precos_entries = "[]"

            ev = {
                'Nome do Evento': nome_evento,
                'Link de Inscrição': url,
                'Link da Imagem': details['link_imagem'],
                'Data': details['data'],
                'Horário': details['horario'],
                'Cidade': details['cidade'],
                'Distância': ', '.join(details['distancias']),
                'Organizador': "SmCrono",
                'Link do Edital': edital_link,
                'precos_entries': json_precos_entries,
                'Percurso': percurso_json,
                'Kits': kits_json
            }
            
            print(f"  [OK] {ev['Data']} | Precos: {len(details['precos'])} entradas")
            events_data.append(ev)

        except Exception as e:
            print(f"  [ERRO]: {e}")
            continue

    return events_data

def main():
    driver = setup_driver()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(base_dir, 'data/eventos_smcrono.csv')
    
    try:
        events = get_smcrono_events_v2(driver, estado_filter='PB')
        
        if events:
            fieldnames = [
                'Nome do Evento', 
                'Link de Inscrição', 
                'Link da Imagem', 
                'Data', 
                'Horário', 
                'Cidade', 
                'Distância', 
                'Organizador', 
                'Link do Edital',
                'precos_entries',
                'Percurso',
                'Kits'
            ]

            print(f"\nTotal de {len(events)} eventos encontrados. Salvando no CSV...")

            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';', quoting=csv.QUOTE_ALL, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(events)
            
            print(f"\nSalvo com sucesso: {csv_path}")
            
            # Sincronização
            try:
                from data_collection.utils import ImportToDB as sync_module
                sync_module.import_csv_to_mongodb(sync_module.remote_db, csv_path, 'smcrono')
            except Exception as e:
                print(f"Sincronização ignorada: {e}")
        else:
            print("Nenhum evento encontrado.")
          
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
