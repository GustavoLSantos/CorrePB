import csv
import time
import re
import os

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.action_chains import ActionChains


def setup_driver():
    options = webdriver.ChromeOptions()
    # Comentar a linha abaixo para ver o navegador em ação (útil para debug)
    # options.add_argument('--headless')
    # Adicionar argumentos para melhorar a estabilidade
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    driver = webdriver.Chrome(options=options)
    driver.maximize_window()
    return driver


def get_event_distance(driver, event_url):
    try:
        # Acessar a página do evento
        driver.get(event_url)
        # Aguardar carregamento da página com tempo suficiente
        time.sleep(5)

        # Capturar_todo o texto da página
        page_text = driver.find_element(By.TAG_NAME, "body").text

        # Padrões de distância comuns em corridas
        distance_patterns = [
            r'\b\d+\s*[kK][mM]\b',  # Padrão como "5km", "10 KM", etc.
            r'\b\d+\.\d+\s*[kK][mM]\b',  # Padrão como "5.5km", "10.5 KM", etc.
            r'\b\d+\,\d+\s*[kK][mM]\b',  # Padrão como "5,5km", "10,5 KM", etc.
            r'\bMeia Maratona\b',  # Padrão "Meia Maratona" (21km)
            r'\bMaratona\b'  # Padrão "Maratona" (42km)
        ]

        all_distances = []
        for pattern in distance_patterns:
            matches = re.findall(pattern, page_text)
            all_distances.extend(matches)

        if all_distances:
            # Remover duplicatas e ordenar por tamanho (menor para maior)
            def extract_number(text):
                match = re.search(r'\d+', text)
                return float(match.group()) if match else 0
            
            unique_distances = sorted(set(all_distances), key=extract_number)
            return ', '.join(unique_distances)

        return ''  # Retornar string vazia se não encontrar

    except Exception as e:
        print(f"❌ Erro ao buscar distância do evento: {str(e)}")
        return ''


def get_event_data(driver):
    try:
        # Acessar a página de eventos
        driver.get("https://brasilcorrida.com.br/#/calendario")

        # Aguardar a página carregar
        time.sleep(5)

        # Clicar no filtro de modalidade "Corrida de Rua"
        try:
            modalidade = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH,
                                            "//a[contains(@class, 'filtro-modalidade-item')]//label[contains(text(), 'Corrida de Rua')]"))
            )
            modalidade.click()
            time.sleep(2)
            print("✅ Filtro 'Corrida de Rua' selecionado")
        except Exception as e:
            print(f"⚠️ Erro ao clicar no filtro de modalidade: {str(e)}")

        # 1. Clicar na aba/filtro "Local"
        try:
            print("➡️ 1. Procurando e clicando na aba 'Local'...")
            local_tab = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Local')]"))
            )
            local_tab.click()
            time.sleep(1)
            print("✅ Aba 'Local' selecionada")
        except Exception as e:
            print(f"❌ Erro ao clicar na aba 'Local': {str(e)}")

        # 1. Selecionar o estado PB no campo customizado
        try:
            print("➡️ 1. Procurando o input de estado (com placeholder 'Selecione uma Cidade')...")
            estado_input = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//div[label[contains(text(), 'Estado')]]//input[@placeholder='Selecione uma Cidade']"))
            )
            estado_input.click()
            print("✅ Input de estado clicado.")

            # Digitar PB
            estado_input.clear()
            estado_input.send_keys("PB")
            print("✅ 'PB' digitado no campo de estado.")
            time.sleep(1)

            # Esperar a lista de opções aparecer e clicar na opção PB
            print("➡️ 2. Aguardando e clicando na opção PB na lista...")
            pb_option = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'selectize-dropdown-content')]//table[@data-value='PB']"))
            )
            actions = ActionChains(driver)
            actions.move_to_element(pb_option).pause(0.5).click(pb_option).perform()
            print("✅ Estado 'PB' selecionado com sucesso.")
            time.sleep(2)
        except Exception as e:
            print(f"❌ Erro ao selecionar o estado 'PB': {str(e)}")

    

            # Tenta selecionar a sugestão se aparecer
            try:
                sugestao = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'autocomplete-suggestion') and contains(text(), 'Paraíba')]"))
                )
                sugestao.click()
                print("✅ Sugestão 'Paraíba' selecionada")
            except Exception:
                print("⚠️ Sugestão automática não encontrada, continuando apenas com o texto digitado.")

            print("✅ Campo de cidade preenchido com 'Paraíba'")
  

        # Clicar no botão de busca (pesquisa)
        try:
            search_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((
                    By.XPATH,
                    "//button[contains(@class, 'btn-primary') and contains(@class, 'bg-administradora') and .//i[contains(@class, 'fa-search')]]"
                ))
            )
            search_button.click()
            print("✅ Botão de pesquisa clicado")
            time.sleep(3)
        except Exception as e:
            print(f"⚠️ Erro ao clicar no botão de busca: {str(e)}")

        # Lista para armazenar as informações básicas dos eventos
        basic_event_info = []

        # Encontrar todos os cards de evento
        try:
            event_cards = WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.XPATH,
                                                     "//div[contains(@class, 'col-md-3') and contains(@class, 'col-sm-12')]//div[contains(@class, 'card')]"))
            )

            print(f"🔍 Encontrados {len(event_cards)} cards de eventos")

            # PRIMEIRO PASSO: Coletar informações básicas de todos os eventos
            for index, card in enumerate(event_cards):
                try:
                    # Função auxiliar para extrair texto com tratamento de erro
                    def get_text_safe(element, xpath):
                        try:
                            return element.find_element(By.XPATH, xpath).text.strip()
                        except:
                            return ''

                    # Função auxiliar para extrair atributo com tratamento de erro
                    def get_attribute_safe(element, xpath, attribute):
                        try:
                            return element.find_element(By.XPATH, xpath).get_attribute(attribute)
                        except:
                            return ''

                    # Extrair dados do evento
                    nome_evento = get_text_safe(card, ".//h6[contains(@class, 'fs-0')]")
                    link_evento = get_attribute_safe(card, ".//a[contains(@href, 'evento')]", 'href')
                    link_imagem = get_attribute_safe(card, ".//img[contains(@class, 'card-span-img')]", 'src')
                    data_evento = get_text_safe(card, ".//h6[contains(@class, 'fs--2') and contains(text(), '/')]")
                    local_evento = get_text_safe(card, ".//h6[contains(@class, 'fs--2') and contains(text(), ',')]")
                    organizador = get_text_safe(card, ".//a[contains(@href, 'organizador')]")

                    # Formatar a data para o padrão brasileiro
                    if data_evento and '/' in data_evento:
                        try:
                            dia, mes, ano = data_evento.split('/')
                            meses = {
                                '01': 'Janeiro', '02': 'Fevereiro', '03': 'Março',
                                '04': 'Abril', '05': 'Maio', '06': 'Junho',
                                '07': 'Julho', '08': 'Agosto', '09': 'Setembro',
                                '10': 'Outubro', '11': 'Novembro', '12': 'Dezembro'
                            }
                            data_evento = f"{dia} de {meses[mes]} de {ano}"
                        except:
                            pass

                    # Extrair apenas a cidade do local (remover estado)
                    if local_evento and ',' in local_evento:
                        local_evento = local_evento.split(',')[0].strip()

                    # Armazenar informações básicas
                    basic_event_info.append({
                        'nome': nome_evento,
                        'link_inscricao': link_evento,
                        'link_imagem': link_imagem,
                        'data': data_evento,
                        'cidade': local_evento,
                        'organizador': organizador
                    })

                except Exception as e:
                    print(f"❌ Erro ao processar card {index + 1}: {str(e)}")
                    continue

            # SEGUNDO PASSO: Visitar cada página de evento para obter a distância
            complete_event_data = []
            for index, event in enumerate(basic_event_info):
                try:
                    nome_evento = event.get('nome', '')
                    link_evento = event.get('link_inscricao', '')

                    # Obter a distância acessando a página do evento
                    distancia = ''
                    if link_evento:
                        print(f"🔍 [{index + 1}/{len(basic_event_info)}] Buscando distância para: {nome_evento}")
                        distancia = get_event_distance(driver, link_evento)
                        print(f"📏 Distância encontrada: {distancia or 'Não disponível'}")

                    # Criar cópia do evento com a distância
                    event_with_distance = event.copy()
                    event_with_distance['distancia'] = distancia
                    complete_event_data.append(event_with_distance)

                except Exception as e:
                    print(f"❌ Erro ao processar evento {index + 1}: {str(e)}")
                    # Mesmo com erro, adicionar o evento sem distância
                    event_with_distance = event.copy()
                    event_with_distance['distancia'] = ''
                    complete_event_data.append(event_with_distance)

            return complete_event_data

        except Exception as e:
            print(f"❌ Erro ao encontrar cards de eventos: {str(e)}")

        return []

    except Exception as e:
        print(f"❌ Erro ao buscar dados dos eventos: {str(e)}")
        return []


def main():
    # Configurar driver
    driver = setup_driver()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(base_dir, 'data/eventos_brasilcorrida.csv')

    try:
        # Criar arquivo CSV
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile, delimiter=';')
            writer.writerow(
                ['Nome do Evento', 'Link de Inscrição', 'Link da Imagem', 'Data', 'Cidade', 'Distância', 'Organizador'])

            # Obter dados dos eventos
            event_data = get_event_data(driver)
            print(f"\n✅ Encontrados {len(event_data)} eventos")

            # Processar cada evento
            for event in event_data:
                writer.writerow([
                    event.get('nome', ''),
                    event.get('link_inscricao', ''),
                    event.get('link_imagem', ''),
                    event.get('data', ''),
                    event.get('cidade', ''),
                    event.get('distancia', ''),
                    event.get('organizador', '')
                ])
                print(f"📝 Evento salvo: {event.get('nome', '')}")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()