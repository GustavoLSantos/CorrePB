import csv
import re
import os
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def setup_driver():
    """Configura o driver do Selenium."""
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-images')
    options.add_argument('--blink-settings=imagesEnabled=false')
    options.add_argument('--disable-software-rasterizer')
    options.add_argument('--disable-dev-tools')
    options.add_argument('--disable-logging')
    options.add_argument('--log-level=3')
    options.add_argument('--silent')
    options.add_argument('--disable-blink-features=AutomationControlled')
    
    prefs = {
        'profile.default_content_setting_values': {
            'images': 2,
            'plugins': 2,
            'popups': 2,
            'geolocation': 2,
            'notifications': 2,
            'media_stream': 2,
        },
        'profile.managed_default_content_settings': {
            'images': 2,
            'stylesheets': 2,
        }
    }
    options.add_experimental_option('prefs', prefs)
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    options.page_load_strategy = 'eager'

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(10)
    return driver


def extract_edital_with_requests(url):
    # Extraindo o link do edital usando requests (mais rápido que o selenium)
    try:
        response = requests.get(url, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        domain = urlparse(url).netloc

        if 'zeniteesportes.com' in domain:
            # Procura por links com regulamento ou onclick com PDF
            reg_links = soup.find_all('a', str=re.compile(r'regulamento', re.IGNORECASE))
            for link in reg_links:
                onclick = link.get('onclick', '')
                if '.pdf' in onclick.lower():
                    pdf_match = re.search(r"abrirPDF\('([^']+)'\)", onclick)
                    if pdf_match:
                        return pdf_match.group(1)
                href = link.get('href', '')
                if '.pdf' in href.lower():
                    return href

            # Busca qualquer link com PDF
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


def process_edital_batch(events):
    # Processando editais com ThreadPoolExecutor para melhorar performance
    def fetch_edital(event_info):
        url = event_info.get('link_inscricao', '')
        if url:
            edital = extract_edital_with_requests(url)
            event_info['link_edital'] = edital
        else:
            event_info['link_edital'] = 'edital não encontrado'
        return event_info

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_edital, event): event for event in events}
        results = []
        for idx, future in enumerate(as_completed(futures), 1):
            try:
                result = future.result()
                results.append(result)
                print(
                    f"[{idx}/{len(events)}] ✓ {result.get('nome', '')} - Edital: {result.get('link_edital', '')[:50]}")
            except Exception as e:
                event = futures[future]
                event['link_edital'] = 'edital não encontrado'
                results.append(event)
        return results



def get_event_data(driver):
    """Extrai os dados dos eventos, incluindo o link e o texto do edital."""
    try:
        driver.get("https://brasilquecorre.com/paraiba")

        wait = WebDriverWait(driver, 5)
        event_boxes = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.cs-box")))

        event_data = []
        data_pattern = re.compile(r'\d{1,2}\s+de\s+[A-Za-zçÇ]+\s+de\s+\d{4}')

        total_events = len(event_boxes)
        print(f"\nEncontrados {total_events} eventos. Iniciando extração\n")

        #Primeira iteração para extrair dados básicos
        for idx, box in enumerate(event_boxes, 1):
            event_info = {}
            try:
                name_element = box.find_element(By.CSS_SELECTOR, "h5 a")
                event_info['nome'] = name_element.text
                event_info['link_inscricao'] = name_element.get_attribute('href')

                img_element = box.find_element(By.CSS_SELECTOR, "img.cs-chosen-image")
                event_info['link_imagem'] = img_element.get_attribute('src')

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

        #Segunda iteração buscar editais em paralelo
        print(f"\n Buscando editais\n")
        event_data = process_edital_batch(event_data)

        return event_data

    except Exception as e:
        print(f"Erro crítico ao buscar dados dos eventos: {e}")
        return []

def main():
    """Função principal para executar o scraper e salvar os dados."""
    driver = setup_driver()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(base_dir, 'eventos_brasilquecorre.csv')

    try:
        # Obter dados dos eventos
        event_data = get_event_data(driver)

        if not event_data:
            print("Nenhum evento encontrado ou ocorreu um erro.")
            return

        print(f"\nTotal de {len(event_data)} eventos encontrados. Salvando no CSV...")

        # Criar arquivo CSV e salvar os dados
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            # Adiciona os novos campos ao cabeçalho
            fieldnames = ['Nome do Evento', 'Link de Inscrição', 'Link da Imagem', 'Data', 'Cidade', 'Distância',
                          'Organizador', 'Link do Edital']
            writer = csv.writer(csvfile, delimiter=';')
            writer.writerow(fieldnames)

            # Escrever os dados de cada evento
            for event in event_data:
                writer.writerow([
                    event.get('nome', ''),
                    event.get('link_inscricao', ''),
                    event.get('link_imagem', ''),
                    event.get('data', ''),
                    event.get('cidade', ''),
                    event.get('distancia', ''),
                    event.get('organizador', ''),
                    event.get('link_edital', '')
                ])

        print(f"\nDados salvos com sucesso em: {csv_path}")

    finally:
        driver.quit()

if __name__ == "__main__":
    main()