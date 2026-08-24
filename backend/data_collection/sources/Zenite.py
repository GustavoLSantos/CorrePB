import re
import time
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from data_collection.core.Driver import setup_driver


def is_zenite_domain(domain: str) -> bool:
    """Retorna True se o domínio pertence ao Zenite."""
    if not domain:
        return False
    return 'zeniteesportes.com' in domain.lower()


def load_zenite_soup(url: str, driver=None, wait_seconds: int = 30, debug: bool = False):
    """
    Carrega a página do Zenite com Selenium e retorna o soup.

    Retorna: (soup, created, driver, horario)

    Contrato de retorno:
    - soup: BeautifulSoup do conteúdo em caso de sucesso, ou None em erro.
    - created: bool indicando se a função criou o driver (True) ou recebeu um driver externo (False).
    - driver: o WebDriver retornado se sucesso; None em erro.
    - horario: horário extraído (string) ou '' em falta.

    Observações:
    - Se created for True, o chamador é responsável por fechar o driver (driver.quit()) após o uso.
    - Em caso de exceção durante a carga, se a função criou o driver internamente, ela o fecha antes de retornar e
      ajusta created para False. Assim, a função NUNCA retornará (created=True, driver=None).
    """
    created = False
    local_driver = driver
    horario = ''
    try:
        if local_driver is None:
            local_driver = setup_driver()
            created = True

        local_driver.set_page_load_timeout(60)
        local_driver.get(url)

        # Aguarda algum elemento específico, se necessário
        try:
            WebDriverWait(local_driver, wait_seconds).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'span.disc1'))
            )
        except Exception:
            pass

        local_driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        time.sleep(2)
        local_driver.execute_script('window.scrollTo(0, 0);')
        time.sleep(1)

        soup = BeautifulSoup(local_driver.page_source, 'html.parser')
        horario = extract_zenite_schedule(soup)

        return soup, created, local_driver, horario
    except Exception as e:
        if debug:
            print(f"Erro ao carregar Zenite: {e}")
        try:
            if created and local_driver:
                try:
                    local_driver.quit()
                except Exception:
                    pass
                created = False
        except Exception:
            pass
        return None, created, None, horario


def extract_zenite_schedule(soup) -> str:
    if not soup:
        return ''


    try:
        for li in soup.find_all('li'):
            span_disc = li.find('span', class_='disc')
            if not span_disc:
                continue
            label_txt = (span_disc.get_text() or '').strip().lower()
            if 'data' in label_txt and 'corrida' in label_txt:
                span1 = li.find('span', class_='disc1')
                if span1:
                    txt = (span1.get_text() or '').strip()
                    m = re.search(r'(\d{1,2}):(\d{2})', txt)
                    if m:
                        try:
                            h = int(m.group(1))
                            mi = int(m.group(2))
                            if 0 <= h <= 23 and 0 <= mi <= 59:
                                return f"{h:02d}:{mi:02d}"
                        except Exception:
                            pass

    except Exception:
        pass

    span = soup.find('span', class_='disc1')
    if not span:
        return ''

    text = (span.get_text() or '').strip()
    if text:
        m = re.search(r'(\d{1,2}):(\d{2})', text)
        if m:
            try:
                h = int(m.group(1))
                mi = int(m.group(2))
                if 0 <= h <= 23 and 0 <= mi <= 59:
                    return f"{h:02d}:{mi:02d}"
            except Exception:
                pass

    return ''


def extract_zenite_ticket_prices(soup, debug: bool = False):
    """Extrai preços do Zenite a partir do HTML renderizado.

    Procura por <span class="pro_price">R$70,00</span> e variações. Retorna lista de
    entradas formatadas com `fmt_entry` (ver `data_collection.utils.PriceUtils`).
    """
    from data_collection.utils.PriceUtils import fmt_entry, parse_price_str
    import re

    candidates = []
    if not soup:
        return []

    # Seleciona spans que contenham a classe pro_price (padrão informado)
    def has_pro_price(c):
        try:
            return c and 'pro_price' in c
        except Exception:
            return False

    price_elems = soup.find_all('span', class_=has_pro_price)

    for pe in price_elems:
        txt = pe.get_text(separator=' ', strip=True) or ''
        if debug:
            print(f"[zenite] candidato raw: {txt}")

        price = None
        tax = None

        # Padrão principal: R$ 123,45
        m = re.search(r'R\$\s*([\d.,]+)', txt)
        if m:
            price = parse_price_str(m.group(1))
        else:
            # Fallback: tenta extrair qualquer número que pareça preço
            price = parse_price_str(txt)

        # Detecta taxa explícita no texto: '+ R$ 8,80' ou '(+8,80 taxa)'
        tax_m = re.search(r'\+\s*R\$\s*([\d.,]+)', txt)
        if tax_m:
            tax = parse_price_str(tax_m.group(1))
        else:
            tax_m2 = re.search(r'\(\s*\+?([\d.,]+)\s*(?:taxa|tax|fee)\s*\)', txt, re.IGNORECASE)
            if tax_m2:
                tax = parse_price_str(tax_m2.group(1))

        candidates.append({'label': None, 'price': price, 'tax': tax, 'raw': txt})

    # Dedup e filtro básico (mesma lógica usada em outros extractors)
    unique = []
    seen = set()
    for e in candidates:
        try:
            key = (e.get('label') or '', float(e.get('price') if e.get('price') is not None else -1), e.get('tax') if e.get('tax') is None else float(e.get('tax')))
        except Exception:
            key = (e.get('label') or '', e.get('price'), e.get('tax'))
        if key in seen:
            continue
        seen.add(key)

        # Filtra preços irracionais (mantém 0..500 como no scraper principal)
        p = e.get('price')
        try:
            if p is not None and (p < 0 or p > 500):
                if debug:
                    print(f"[zenite] descartando por range: {p} ({e.get('raw')})")
                continue
        except Exception:
            pass

        unique.append(e)

    # Se houver preços positivos, remove entradas com preço 0 ou None
    has_positive = any((e.get('price') is not None and e.get('price') > 0) for e in unique)
    if has_positive:
        unique = [e for e in unique if e.get('price') is not None and e.get('price') > 0]

    # Ordena por preço (None no final)
    unique.sort(key=lambda x: (float('inf') if x.get('price') is None else x.get('price')))

    # Formata usando fmt_entry para manter consistência com outros extractors
    formatted = []
    for e in unique:
        try:
            formatted.append(fmt_entry(e))
        except Exception:
            # Fallback: mantem uma forma bruta se fmt_entry falhar
            formatted.append({
                'label': e.get('label'),
                'price': e.get('price'),
                'tax': e.get('tax'),
                'formatted': None,
                'raw': e.get('raw')
            })

    if debug:
        print(f"[zenite] preços extraídos: {formatted}")

    return formatted


# ─── API dedicada (catálogo próprio do site Zenite) ──────────────────────────
import json
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

from data_collection.core.ScraperCommon import (
    entries_to_json,
    fix_encoding,
    formatar_data_br,
    get_http_session,
    get_with_rate_limit,
    parse_data_br,
)

ZENITE_BASE_URL = "https://zeniteesportes.com"
ORGANIZADOR = "Zenite Esportes"

# Rotas estáticas do OpenCart que não são páginas de evento
_STATIC_ROUTES = {
    "", "contato", "sobre", "resultados", "certificado", "blog", "index.php",
    "politica-privacidade-br", "conta", "busca", "carrinho", "checkout",
    "minha-conta", "acessar", "cadastro", "historico", "informativo",
}

_UFS = (
    "AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO"
)

_session = get_http_session()


def _is_product_url(path: str) -> bool:
    if not path or "/" in path.strip("/"):
        return False
    slug = path.strip("/")
    if slug.lower() in _STATIC_ROUTES or slug.lower().startswith(("conta/", "image/")):
        return False
    # Slugs de evento do Zenite são minúsculos, alfanuméricos e razoavelmente longos
    return bool(re.fullmatch(r"[a-z0-9]{5,}", slug))


def discover_zenite_events() -> list[str]:
    """Descobre URLs de eventos no catálogo da home (links SEO do OpenCart)."""
    resp = get_with_rate_limit(_session, ZENITE_BASE_URL, timeout=20)
    if resp is None:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    urls = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(ZENITE_BASE_URL, str(a["href"]))
        parsed = urlparse(href)
        if "zeniteesportes.com" not in parsed.netloc:
            continue
        path = parsed.path.rstrip("/")
        if not _is_product_url(path):
            continue
        if path not in seen:
            seen.add(path)
            urls.append(f"{ZENITE_BASE_URL}/{path.strip('/')}")
    return urls


def _zenite_data_corrida(soup) -> tuple[str, str]:
    """Extrai (data 'dd/mm/yyyy', horário 'HH:MM') do bloco 'Data da corrida'."""
    for li in soup.find_all("li"):
        disc = li.find("span", class_="disc")
        if not disc:
            continue
        label = (disc.get_text() or "").strip().lower()
        if "data" not in label or "corrida" not in label:
            continue
        valor_span = li.find("span", class_="disc1")
        if not valor_span:
            continue
        txt = (valor_span.get_text() or "").strip()
        m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})(?:\s+(\d{1,2}:\d{2}))?", txt)
        if m:
            return m.group(1), m.group(2) or ""
    return "", ""


def _zenite_cidade(soup) -> str:
    """Extrai a cidade com estratégias ordenadas por confiabilidade.

    1) Rótulo 'Local:' seguido de 'Cidade – UF' (ex.: 'Açude Velho, Campina Grande – PB')
    2) Menção 'na cidade de X' no texto/regulamento embutido (ex.: Goiana/PE)
    3) Primeiro 'Cidade – UF' da página que não seja o endereço do rodapé
    """
    text = soup.get_text(" ", strip=True)
    padrao = re.compile(rf"([A-ZÀ-Ú][\wà-úá-ú\'\.]+(?:\s+[A-Za-zà-úá-ú\'\.]+)*)\s*[–—-]\s*({_UFS})\b")

    def _limpa(nome: str) -> str:
        return fix_encoding(nome.strip(" .,-"))

    # 1) após o rótulo Local:
    m_local = re.search(r"Local:\s*(.{0,100})", text)
    if m_local:
        m = padrao.search(m_local.group(1))
        if m:
            return _limpa(m.group(1))

    # 2) 'na cidade de X' (comum no regulamento embutido na aba descrição)
    m = re.search(
        rf"cidade de\s+([A-ZÀ-Ú][\wà-úá-ú\'\.]+(?:\s+[A-Za-zà-úá-ú\'\.]+)*)"
        rf"(?:\s*[/–—-]\s*({_UFS}))?",
        text,
        re.IGNORECASE,
    )
    if m:
        return _limpa(m.group(1))

    # 3) qualquer 'Cidade – UF', ignorando trechos do rodapé (CEP/Centro)
    for m in padrao.finditer(text):
        contexto = text[max(0, m.start() - 60) : m.end() + 40]
        if re.search(r"CEP|Centro|Rodrigues", contexto, re.IGNORECASE):
            continue
        return _limpa(m.group(1))
    return ""


def _zenite_distancias(soup) -> str:
    """Distâncias a partir do rótulo 'Percursos:'; fallback: tokens KM únicos na página."""
    text = soup.get_text(" ", strip=True)
    trecho = text
    m = re.search(r"Percursos?:\s*(.{0,120})", text, re.IGNORECASE)
    if m:
        trecho = m.group(1)

    vistos: list = []
    for km in re.findall(r"\b\d{1,2}(?:[.,]\d)?\s?[kK][mM]\b", trecho):
        normalizado = re.sub(r"\s+", "", km).lower().replace(",", ".")
        if normalizado not in vistos:
            vistos.append(normalizado)
    return ", ".join(vistos).upper()


def _zenite_edital(soup) -> str:
    """PDF de regulamento via abrirPDF(...) ou link .pdf direto."""
    html = str(soup)
    m = re.search(r"abrirPDF\('([^']+\.pdf)'?\)", html, re.IGNORECASE)
    if m:
        return m.group(1)
    for a in soup.find_all("a", href=True):
        if ".pdf" in a["href"].lower():
            return urljoin(ZENITE_BASE_URL, a["href"])
    return "edital não encontrado"


def _zenite_precos(soup) -> list:
    """Entradas de preço via extractor oficial + fallback R$ genérico no texto."""
    from data_collection.utils.PriceUtils import parse_price_str

    entradas = extract_zenite_ticket_prices(soup)
    if entradas:
        return entradas

    texto = soup.get_text(" ", strip=True)
    saida = []
    vistos = set()
    for m in re.finditer(r"R\$\s*([\d.,]+)", texto):
        preco = parse_price_str(m.group(1))
        if preco and preco > 0 and preco <= 500 and preco not in vistos:
            vistos.add(preco)
            saida.append({"label": None, "price": preco, "tax": None, "raw": m.group(0)})
    return sorted(saida, key=lambda x: x["price"])


def build_zenite_record(url: str) -> dict | None:
    """Monta o registro padrão de um evento a partir da página do produto."""
    resp = get_with_rate_limit(_session, url, timeout=25)
    if resp is None:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")

    nome = ""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        nome = str(og_title["content"]).strip()
    elif soup.h1:
        nome = soup.h1.get_text(strip=True)
    if not nome:
        return None

    imagem = ""
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        imagem = str(og_image["content"]).strip()

    data_br, horario = _zenite_data_corrida(soup)

    return {
        "Nome do Evento": nome,
        "Link de Inscrição": url,
        "Link da Imagem": imagem,
        "Data": formatar_data_br(data_br),
        "Horário": horario,
        "Cidade": _zenite_cidade(soup),
        "Distância": _zenite_distancias(soup),
        "Organizador": ORGANIZADOR,
        "Link do Edital": _zenite_edital(soup),
        "precos_entries": entries_to_json(_zenite_precos(soup)),
        "_data_br": data_br,
    }


def get_zenite_events(somente_futuros: bool = True) -> list[dict]:
    """Coleta completa dos eventos do catálogo Zenite via requests (sem Selenium)."""
    records = []
    urls = discover_zenite_events()
    print(f"Descobertos {len(urls)} produtos no catálogo Zenite")

    for i, url in enumerate(urls, 1):
        try:
            rec = build_zenite_record(url)
            if not rec:
                print(f"[{i}/{len(urls)}] sem dados: {url}")
                continue

            # Páginas de serviço (Consultoria, Cronometragem...) não têm 'Data da corrida'
            if not rec.get("_data_br"):
                print(f"[{i}/{len(urls)}] ignorado (não é evento): {rec['Nome do Evento'][:40]}")
                continue

            if somente_futuros:
                dt = parse_data_br(rec.pop("_data_br", ""))
                if dt and dt < datetime.now():
                    continue
            else:
                rec.pop("_data_br", "")
            records.append(rec)
            print(f"[{i}/{len(urls)}] OK {rec['Nome do Evento'][:50]}")
        except Exception as e:
            print(f"[{i}/{len(urls)}] ERRO {url}: {e}")

    return records
