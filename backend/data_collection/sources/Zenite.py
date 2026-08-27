import re
import time
from urllib.parse import urljoin, urlparse
from datetime import datetime
from bs4 import BeautifulSoup, Tag
from selenium.webdriver.remote.webdriver import WebDriver

from data_collection.utils.PriceUtils import PriceEntry
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from data_collection.core.Driver import setup_driver


def is_zenite_domain(domain: str) -> bool:
    """Retorna True se o domínio pertence ao Zenite."""
    if not domain:
        return False
    return 'zeniteesportes.com' in domain.lower()


def load_zenite_soup(
    url: str,
    driver: WebDriver | None = None,
    wait_seconds: int = 30,
    debug: bool = False,
) -> tuple[BeautifulSoup | None, bool, WebDriver | None, str]:
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
            _ = WebDriverWait(local_driver, wait_seconds).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'span.disc1'))
            )
        except Exception:
            pass

        wd: WebDriver = local_driver
        wd.execute_script('window.scrollTo(0, document.body.scrollHeight);')  # pyright: ignore[reportUnknownMemberType]
        time.sleep(2)
        wd.execute_script('window.scrollTo(0, 0);')  # pyright: ignore[reportUnknownMemberType]
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


def extract_zenite_schedule(soup: BeautifulSoup) -> str:
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


def extract_zenite_ticket_prices(soup: BeautifulSoup, debug: bool = False) -> list[PriceEntry]:
    """Extrai preços do Zenite a partir do HTML renderizado.

    Procura por <span class="pro_price">R$70,00</span> e variações. Retorna lista de
    entradas formatadas com `fmt_entry` (ver `data_collection.utils.PriceUtils`).
    """
    from data_collection.utils.PriceUtils import fmt_entry, parse_price_str

    candidates: list[PriceEntry] = []
    if not soup:
        return []

    # Seleciona spans que contenham a classe pro_price (padrão informado)
    def has_pro_price(c: str | list[str] | None) -> bool:
        return bool(c and "pro_price" in c)

    price_elems: list[Tag] = soup.find_all("span", class_=has_pro_price)

    for pe in price_elems:
        txt = pe.get_text(separator=" ", strip=True) or ""
        if debug:
            print(f"[zenite] candidato raw: {txt}")

        # Padrão principal: R$ 123,45 (fallback: qualquer número no texto)
        m = re.search(r"R\$\s*([\d.,]+)", txt)
        price = parse_price_str(m.group(1) if m else txt)

        # Detecta taxa explícita no texto: '+ R$ 8,80' ou '(+8,80 taxa)'
        tax_m = re.search(r"\+\s*R\$\s*([\d.,]+)", txt)
        if tax_m is None:
            tax_m = re.search(r"\(\s*\+?([\d.,]+)\s*(?:taxa|tax|fee)\s*\)", txt, re.IGNORECASE)
        tax = parse_price_str(tax_m.group(1)) if tax_m else None

        candidates.append({"label": None, "price": price, "tax": tax, "raw": txt})

    # Dedup e filtro básico (mesma lógica usada em outros extractors)
    unique: list[PriceEntry] = []
    seen: set[tuple[str, float, float | None]] = set()
    for e in candidates:
        label = str(e.get("label") or "")
        raw_price = e.get("price")
        raw_tax = e.get("tax")
        price_f = float(raw_price) if isinstance(raw_price, (int, float)) else -1.0
        tax_f = float(raw_tax) if isinstance(raw_tax, (int, float)) else None
        key = (label, price_f, tax_f)
        if key in seen:
            continue
        seen.add(key)

        # Filtra preços irracionais (mantém 0..500 como no scraper principal)
        if raw_price is not None and not isinstance(raw_price, (int, float)):
            continue
        if price_f >= 0 and (price_f < 0 or price_f > 500):
            if debug:
                print(f"[zenite] descartando por range: {price_f} ({e.get('raw')})")
            continue
        unique.append(e)

    # Se houver preços positivos, remove entradas com preço 0 ou None
    has_positive = any((e.get("price") or 0) > 0 for e in unique)
    if has_positive:
        unique = [e for e in unique if (e.get("price") or 0) > 0]

    # Ordena por preço (None por último)
    unique.sort(key=lambda x: (x.get("price") is None, x.get("price") or 0.0))

    # Formata usando fmt_entry para manter consistência com outros extractors
    formatted: list[PriceEntry] = []
    for e in unique:
        try:
            formatted.append(fmt_entry(e))
        except Exception:
            formatted.append(
                {
                    "label": e.get("label"),
                    "price": e.get("price"),
                    "tax": e.get("tax"),
                    "formatted": None,
                    "raw": e.get("raw"),
                }
            )

    if debug:
        print(f"[zenite] preços extraídos: {formatted}")

    return formatted


# ─── API dedicada (catálogo próprio do site Zenite) ──────────────────────────

from data_collection.core.ScraperCommon import (
    entries_to_json,
    fix_encoding,
    format_date_string,
    get_http_session,
    get_with_rate_limit,
    parse_date_string,
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


def discover_zenite_events() -> list[dict[str, str]]:
    """Descobre eventos nos cards da home (div.caption), com cidade e data.

    Cada card traz h4 (nome), p com 'Cidade - UF', p com 'Data: dd/mm/aaaa'
    e o link de inscrição — dados usados como fallback quando a página do
    produto não os informa.
    """
    resp = get_with_rate_limit(_session, ZENITE_BASE_URL, timeout=20)
    if resp is None:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")

    cards: list[dict[str, str]] = []
    seen: set[str] = set()
    for caption in soup.select("div.caption"):
        a = caption.select_one("a[href]")
        if a is None:
            continue
        href = urljoin(ZENITE_BASE_URL, str(a.get("href") or ""))
        parsed = urlparse(href)
        if "zeniteesportes.com" not in parsed.netloc:
            continue
        path = parsed.path.rstrip("/")
        if not _is_product_url(path) or path in seen:
            continue
        seen.add(path)

        cidade = ""
        data_br = ""
        for p_text in (p.get_text(" ", strip=True) for p in caption.find_all("p")):
            m_data = re.match(r"Data:\s*(\d{1,2}/\d{1,2}/\d{4})", p_text, re.IGNORECASE)
            if m_data:
                data_br = m_data.group(1)
                continue
            m_city = re.match(rf"(.+?)\s*[–—\-/]\s*({_UFS})\b", p_text)
            if not cidade and m_city:
                cidade = fix_encoding(m_city.group(1).strip())

        cards.append(
            {
                "url": f"{ZENITE_BASE_URL}/{path.strip('/')}",
                "cidade": cidade,
                "data": data_br,
            }
        )
    return cards


def _zenite_data_corrida(soup: BeautifulSoup) -> tuple[str, str]:
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


def _zenite_cidade(soup: BeautifulSoup) -> str:
    """Extrai a cidade com estratégias ordenadas por confiabilidade.

    1) Rótulo 'Local:' seguido de 'Cidade – UF' (ex.: 'Açude Velho, Campina Grande – PB')
    2) Menção 'na cidade de X' no texto/regulamento embutido (ex.: 'Goiana/PE')
    3) 'Cidade UF' em qualquer separador (–, -, / ou parênteses), fora do rodapé
       — cobre 'Goiana / PE' e 'João Pessoa(PB)'
    """
    text = soup.get_text(" ", strip=True)

    # Nome seguido de UF com qualquer separador comum: traço, barra ou parênteses
    nome_grupo = r"([A-ZÀ-Ú][\wà-úá-ú'.]+(?:\s+[A-Za-zà-úÁ-Ú'.]+)*)"
    sep_grupo = rf"\s*(?:[–—\-/]\s*|\(\s*)({_UFS})\b(?:\s*\))?"
    padrao = re.compile(nome_grupo + sep_grupo)

    conectores = {"de", "da", "do", "das", "dos", "e"}

    def _limpa(nome: str) -> str:
        """Normaliza o nome e descarta palavras arrastadas de frases anteriores
        (mantém apenas a sequência final de tokens com inicial maiúscula)."""
        nome = re.sub(r"[\s.,;:/()\-]+", " ", fix_encoding(nome)).strip()
        tokens = nome.split(" ")
        keep: list[str] = []
        for tok in reversed(tokens):
            limpo = tok.strip(".")
            if limpo[:1].isupper() or limpo.lower() in conectores:
                keep.append(tok)
            else:
                break
        return fix_encoding(" ".join(reversed(keep))) if keep else fix_encoding(nome)

    def _eh_rodape(contexto: str) -> bool:
        return bool(re.search(r"CEP|Centro|Rodrigues|Desenvolvido", contexto, re.IGNORECASE))

    # 1) após o rótulo Local:
    m_local = re.search(r"Local:\s*(.{0,100})", text)
    if m_local:
        m = padrao.search(m_local.group(1))
        if m:
            return _limpa(m.group(1))

    # 2) 'na cidade de X' (comum no regulamento embutido na aba descrição)
    cidade_de = (
        rf"cidade de\s+([A-ZÀ-Ú][\wà-úá-ú'.]+(?:\s+[A-Za-zà-úÁ-Ú'.]+)*)"
        rf"(?:\s*[/–—-]\s*({_UFS}))?"
    )
    m = re.search(cidade_de, text, re.IGNORECASE)
    if m:
        return _limpa(m.group(1))

    # 3) primeira menção 'Cidade UF' fora do rodapé; prefere grafia mista
    #    (regulamentos embutidos às vezes trazem o nome em caixa alta e/ou
    #    quebrado pelo extrator de PDF)
    primeiro = ""
    for m in padrao.finditer(text):
        contexto = text[max(0, m.start() - 60) : m.end() + 40]
        if _eh_rodape(contexto):
            continue
        nome = _limpa(m.group(1))
        if not nome:
            continue
        if not primeiro:
            primeiro = nome
        sem_espacos = nome.replace(" ", "")
        if not (sem_espacos.isupper() and len(nome) > 2):
            return nome
    return primeiro


def _zenite_distancias(soup: BeautifulSoup) -> str:
    """Distâncias a partir do rótulo 'Percursos:'; fallback: tokens KM únicos na página."""
    text = soup.get_text(" ", strip=True)
    trecho = text
    m = re.search(r"Percursos?:\s*(.{0,120})", text, re.IGNORECASE)
    if m:
        trecho = m.group(1)

    vistos: list[str] = []
    for km in re.finditer(r"\b\d{1,2}(?:[.,]\d)?\s?[kK][mM]\b", trecho):
        normalizado = re.sub(r"\s+", "", km.group(0)).lower().replace(",", ".")
        if normalizado not in vistos:
            vistos.append(normalizado)
    return ", ".join(vistos).upper()


def _zenite_edital(soup: BeautifulSoup) -> str:
    """PDF de regulamento via abrirPDF(...) ou link .pdf direto."""
    html = str(soup)
    m = re.search(r"abrirPDF\('([^']+\.pdf)'?\)", html, re.IGNORECASE)
    if m:
        return m.group(1)
    for a in soup.find_all("a", href=True):
        href_pdf = str(a.get("href") or "")
        if ".pdf" in href_pdf.lower():
            return urljoin(ZENITE_BASE_URL, href_pdf)
    return "edital não encontrado"


def _zenite_preco_key(e: PriceEntry) -> float:
    preco = e.get("price")
    return float(preco) if isinstance(preco, (int, float)) else 0.0


def _zenite_precos(soup: BeautifulSoup) -> list[PriceEntry]:
    """Entradas de preço via extractor oficial + fallback R$ genérico no texto."""
    from data_collection.utils.PriceUtils import parse_price_str

    entradas = extract_zenite_ticket_prices(soup)
    if entradas:
        return entradas

    texto = soup.get_text(" ", strip=True)
    saida: list[PriceEntry] = []
    vistos: set[float] = set()
    for m in re.finditer(r"R\$\s*([\d.,]+)", texto):
        preco = parse_price_str(m.group(1))
        if preco and preco > 0 and preco <= 500 and preco not in vistos:
            vistos.add(preco)
            saida.append({"label": None, "price": preco, "tax": None, "raw": m.group(0)})
    return sorted(saida, key=_zenite_preco_key)


def build_zenite_record(
    url: str, card: dict[str, str] | None = None
) -> dict[str, str] | None:
    """Monta o registro padrão de um evento a partir da página do produto.

    `card` são os metadados colhidos na home (cidade/data) usados como
    fallback para o que a página do produto não informar.
    """
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
    card = card or {}

    return {
        "Nome do Evento": nome,
        "Link de Inscrição": url,
        "Link da Imagem": imagem,
        "Data": format_date_string(data_br or card.get("data", "")),
        "Horário": horario,
        "Cidade": _zenite_cidade(soup) or fix_encoding(card.get("cidade", "")),
        "Distância": _zenite_distancias(soup),
        "Organizador": ORGANIZADOR,
        "Link do Edital": _zenite_edital(soup),
        "precos_entries": entries_to_json(_zenite_precos(soup)),
        "_data_br": data_br or card.get("data", ""),
    }


def get_zenite_events(somente_futuros: bool = True) -> list[dict[str, str]]:
    """Coleta completa dos eventos do catálogo Zenite via requests (sem Selenium)."""
    records: list[dict[str, str]] = []
    cards = discover_zenite_events()
    print(f"Descobertos {len(cards)} produtos no catálogo Zenite")

    for i, card in enumerate(cards, 1):
        url = card["url"]
        try:
            rec = build_zenite_record(url, card)
            if not rec:
                print(f"[{i}/{len(cards)}] sem dados: {url}")
                continue

            # Páginas de serviço (Consultoria, Cronometragem...) não têm 'Data da corrida'
            if not rec.get("_data_br"):
                print(f"[{i}/{len(cards)}] ignorado (não é evento): {rec['Nome do Evento'][:40]}")
                continue

            if somente_futuros:
                dt = parse_date_string(rec.pop("_data_br", ""))
                if dt and dt < datetime.now():
                    continue
            else:
                _ = rec.pop("_data_br", "")
            records.append(rec)
            print(f"[{i}/{len(cards)}] OK {rec['Nome do Evento'][:50]}")
        except Exception as e:
            print(f"[{i}/{len(cards)}] ERRO {url}: {e}")

    return records
