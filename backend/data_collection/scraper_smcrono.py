import sys
import os
import csv
import re
import time
from datetime import datetime
from urllib.parse import urlparse, urljoin

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from data_collection.core.Driver import setup_driver
from data_collection.utils.PriceUtils import parse_price_str, fmt_entry

def fix_encoding(text):
    if not text: return ""
    try:
        return text.encode('latin1').decode('utf-8')
    except:
        return text

def extract_smcrono_details_robust(driver):
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    full_text = soup.get_text(separator='\n', strip=True)
    
    details = {
        'data': '',
        'cidade': '',
        'estado': '',
        'horario': '',
        'distancias': [],
        'precos': []
    }

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

    # HORÁRIO
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

    raw_prices = []
    lines = full_text.split('\n')
    for line in lines:
        if 'R$' in line:
            vals = re.findall(r'R\$\s*(\d+[.,]\d{2})', line)
            for v in vals:
                price_float = parse_price_str(v)
                if price_float > 0:
                    label = line.replace(f"R$ {v}", "").replace(f"R${v}", "").strip()
                    label = fix_encoding(label)
                    if len(label) > 60: label = label[:60] + "..."
                    if not label: label = "Geral"
                    raw_prices.append({'label': label, 'price': price_float, 'formatted': f"R$ {v}"})
    
    seen = set()
    unique_prices = []
    for p in raw_prices:
        k = (p['price'], p['label'])
        if k not in seen:
            seen.add(k)
            unique_prices.append(p)
    details['precos'] = sorted(unique_prices, key=lambda x: x['price'])
    
    dists = set()
    matches = re.findall(r'\b(\d+(?:[.,]\d+)?)\s*(?:k|km|Km|KM)\b', full_text)
    for m in matches:
        try:
            if float(m.replace(',', '.')) < 100: dists.add(f"{m}km (corrida)")
        except: pass
    details['distancias'] = list(dists)

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
                title_elem = soup.find('h1') or soup.find('h2')
                nome_evento = fix_encoding(title_elem.get_text(strip=True)) if title_elem else ""
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
                    print(f"  -> Ignorado: Estado detectado '{details['estado']}' (esperado {estado_filter})")
                    continue

            edital_link = ""
            try:
                link_pdf = driver.find_element(By.CSS_SELECTOR, "a[href$='.pdf']")
                edital_link = link_pdf.get_attribute('href')
            except:
                edital_link = "edital não encontrado"

            str_preco = "Valor não encontrado"
            if details['precos']:
                min_p = details['precos'][0]['formatted']
                max_p = details['precos'][-1]['formatted']
                str_preco = f"{min_p}" if min_p == max_p else f"{min_p} a {max_p}"
            
            lista_precos_fmt = [
                f"{p['label']} — {p['formatted']}" for p in details['precos']
            ]

            ev = {
                'Nome do Evento': fix_encoding(nome_evento),
                'Link de Inscrição': url,
                'Link da Imagem': details['link_imagem'],
                'Data': details['data'],
                'Cidade': details['cidade'],
                'Estado': details['estado'],
                'Distância': ', '.join(details['distancias']),
                'Organizador': "SmCrono",
                'Preço': str_preco,
                'Link do Edital': edital_link,
                'Horario': details['horario'],
                'lista_precos': lista_precos_fmt
            }
            
            print(f"  ✓ Data: {ev['Data']} | Local: {ev['Cidade']}-{ev['Estado']}")
            events_data.append(ev)

        except Exception as e:
            print(f"  ✗ Erro: {e}")
            continue

    return events_data

def main():
    driver = setup_driver()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(base_dir, 'data/eventos_smcrono.csv')
    
    try:
        events = get_smcrono_events_v2(driver, estado_filter='PB')
        
        if events:
            keys = events[0].keys()
            with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=keys, delimiter=';')
                writer.writeheader()
                writer.writerows(events)
            print(f"\nSalvo com sucesso: {csv_path}")
        else:
            print("Nenhum evento encontrado.")
        try:
            from data_collection.utils import ImportToDB as sync_module
            try:
                sync_module.import_csv_to_mongodb(sync_module.remote_db, csv_path, 'brasilquecorre')
            except Exception as e:
                print(f"Falha ao sincronizar CSV para MongoDB: {e}")
        except Exception as e:
            print(f"Sincronização com MongoDB ignorada (import failed): {e}")
          
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
