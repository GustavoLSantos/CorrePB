import time
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import re

from data_collection.core.Driver import setup_driver

def is_circuito_domain(domain: str) -> bool:
    if not domain:
        return False
    domain = domain.lower()
    return 'circuitodasestacoes.com' in domain

def extract_circuito_time(soup):
    """
    Fallback: Tenta extrair do soup se o JS falhar.
    """
    if not soup: return ""
    
    # Procura meta tag injetada pelo Selenium
    meta = soup.find("meta", attrs={"name": "selenium-horario"})
    if meta:
        return meta['content']

    full_text = soup.get_text(separator='\n', strip=True)
    # Procura padrão simples no texto completo
    match = re.search(r'(?:largada|horário).*?(\d{1,2}[h:]\d{2})', full_text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).replace(':', 'h').lower()
    
    return ""

def load_circuito_soup(url: str, timeout: int = 20):
    domain = urlparse(url).netloc.lower() if url else ''
    driver = None
    created = False
    
    try:
        driver = setup_driver()
        created = True
        driver.set_page_load_timeout(60)
        driver.get(url)

        # 1. Espera genérica pelo corpo
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        except:
            pass
        
        # 2. ESTRATÉGIA NUCLEAR: Extração via JavaScript
        # Varre todos os elementos de texto da página procurando "Largada" e pegando o próximo número
        js_script = """
        try {
            // Função para pegar todo o texto visível e invisível de forma ordenada
            function getAllText(root) {
                let text = "";
                const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
                while(walker.nextNode()) {
                    text += walker.currentNode.nodeValue + "\\n";
                }
                return text;
            }

            const pageText = getAllText(document.body).toLowerCase();
            const lines = pageText.split('\\n');
            
            for (let i = 0; i < lines.length; i++) {
                if (lines[i].includes('largada') || lines[i].includes('horário')) {
                    // Olha essa linha e as próximas 5
                    let context = "";
                    for (let j = 0; j < 5; j++) {
                        if (lines[i+j]) context += lines[i+j] + " ";
                    }
                    
                    // Regex JS para horário (ex: 6h00, 06:00, 19h)
                    const match = context.match(/(\\d{1,2}[h:]\\d{2}|\\d{1,2}h)/);
                    if (match) return match[0];
                    if (context.includes('em breve')) return 'Em breve';
                }
            }
            return "";
        } catch(e) { return "erro_js"; }
        """
        
        # Espera um pouco para garantir que JS frameworks rodaram
        time.sleep(3) 
        
        horario_js = driver.execute_script(js_script)
        
        # Debug no console python
        if horario_js and horario_js != "erro_js":
             print(f"[DEBUG Circuito] JS encontrou horário: {horario_js}")
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')

        # Injeta o resultado no soup para persistir
        if horario_js and horario_js != "erro_js":
            new_tag = soup.new_tag("meta", attrs={"name": "selenium-horario", "content": horario_js})
            soup.append(new_tag)

        return soup, created, driver

    except Exception:
        if created and driver:
             try: driver.quit()
             except: pass
        return None, created, driver
