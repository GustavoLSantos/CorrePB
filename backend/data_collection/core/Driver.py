"""Fábrica reutilizável de driver Selenium com suporte automático ao webdriver-manager.

Fornece `setup_driver(...)` que tentará usar webdriver-manager para baixar
e instalar um chromedriver compatível. Se webdriver-manager não estiver instalado ou
falhar, faz fallback para criar webdriver.Chrome() diretamente (esperando que o chromedriver
esteja no PATH ou que o sistema já providencie um driver).

Parâmetros suportados por setup_driver:
- headless: bool (padrão True)
- page_load_timeout: int (segundos) (padrão 30)
- driver_path: caminho opcional para um binário chromedriver existente
- chrome_binary: caminho opcional para o executável chrome/chromium
- images_enabled: bool para permitir imagens (padrão False)

Este módulo mantém padrões leves apropriados para scraping.
"""
import time
from typing import Optional, Any, cast

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import WebDriverException

# Tenta importar webdriver-manager; se não estiver disponível, fazemos fallback
try:
    from webdriver_manager.chrome import ChromeDriverManager  # type: ignore
    _WEBDRIVER_MANAGER_AVAILABLE = True
except Exception:
    ChromeDriverManager = None
    _WEBDRIVER_MANAGER_AVAILABLE = False


def _get_chrome_options(headless: bool = True, images_enabled: bool = False) -> webdriver.ChromeOptions:
    options = webdriver.ChromeOptions()
    if headless:
        # Usa a nova flag de headless quando suportada
        options.add_argument("--headless=new")
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-extensions')
    if not images_enabled:
        options.add_argument('--blink-settings=imagesEnabled=false')
    options.add_argument('--disable-software-rasterizer')
    options.add_argument('--remote-allow-origins=*')

    prefs = {
        'profile.default_content_setting_values': {
            'images': 1 if images_enabled else 2,
            'plugins': 2,
            'popups': 2,
            'geolocation': 2,
            'notifications': 2,
            'media_stream': 2,
        },
        'profile.managed_default_content_settings': {
            'images': 1 if images_enabled else 2,
            'stylesheets': 1 if images_enabled else 2,
        }
    }
    options.add_experimental_option('prefs', prefs)
    options.add_experimental_option('excludeSwitches', ['enable-automation', 'enable-logging'])
    options.page_load_strategy = 'eager'
    return options


def setup_driver(
    headless: bool = True,
    page_load_timeout: int = 30,
    driver_path: Optional[str] = None,
    chrome_binary: Optional[str] = None,
    images_enabled: bool = False,
) -> webdriver.Chrome:
    """Cria e retorna uma instância configurada de Chrome WebDriver.

    A função tentará usar webdriver-manager para instalar um chromedriver
    compatível automaticamente. Se `driver_path` for fornecido, ele terá
    prioridade. Se webdriver-manager não estiver disponível, faz fallback
    para criar webdriver.Chrome() diretamente.

    Lança WebDriverException se falhar ao iniciar o navegador.
    """
    options = _get_chrome_options(headless=headless, images_enabled=images_enabled)
    if chrome_binary:
        options.binary_location = chrome_binary

    try:
        if driver_path:
            service = Service(executable_path=driver_path)
            driver = webdriver.Chrome(service=service, options=options)
        elif _WEBDRIVER_MANAGER_AVAILABLE:
            # Usa webdriver-manager para baixar e fornecer um binário chromedriver
            manager_cls = cast(Any, ChromeDriverManager)  # type: ignore
            assert manager_cls is not None, "ChromeDriverManager não disponível"
            driver_binary = manager_cls().install()
            service = Service(executable_path=driver_binary)
            driver = webdriver.Chrome(service=service, options=options)
        else:
            # Fallback: assume que o chromedriver está no PATH ou que o Selenium o gerenciará
            driver = webdriver.Chrome(options=options)

        driver.set_page_load_timeout(page_load_timeout)
        # Pequena pausa para permitir que o driver inicialize em alguns ambientes
        time.sleep(0.2)
        return driver
    except WebDriverException:
        # Re-lança para que os chamadores possam decidir como tratar falhas
        raise

