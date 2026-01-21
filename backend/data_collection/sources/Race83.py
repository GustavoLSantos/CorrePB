import time
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests
from data_collection.core.Driver import setup_driver
from selenium.common.exceptions import WebDriverException


def is_race83_domain(domain: str) -> bool:
    if not domain:
        return False
    return 'race83.com.br' in domain.lower()


def is_race83_listing_url(url: str) -> bool:
    if not url:
        return False
    try:
        p = urlparse(url)
        host = p.netloc.lower()
        path = p.path or ''
        return host.endswith('race83.com.br') and path.startswith('/eventos')
    except Exception:
        return False


def detect_redirects_to_listing(url: str, timeout: int = 5) -> tuple[bool, str]:
    try:
        resp = requests.get(url, timeout=timeout, allow_redirects=True)
        final = resp.url or url
        p = urlparse(final)
        if p.netloc and p.netloc.lower().endswith('race83.com.br') and p.path.startswith('/eventos'):
            return True, final
        return False, final
    except Exception:
        return False, url


def load_race83_soup(url: str, timeout: int = 5):
    driver = None
    created = False
    try:
        driver = setup_driver()
        created = True
        driver.get(url)
        time.sleep(1.0)
        final = driver.current_url or url
        p = urlparse(final)
        if p.netloc and p.netloc.lower().endswith('race83.com.br') and p.path.startswith('/eventos'):
            return None, created, driver

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        return soup, created, driver
    except WebDriverException:
        try:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            resp = requests.get(url, timeout=timeout)
            soup = BeautifulSoup(resp.text, 'html.parser')
            return soup, False, None
        except Exception:
            return None, False, None
    except Exception:
        try:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
        except Exception:
            pass
        return None, created, None