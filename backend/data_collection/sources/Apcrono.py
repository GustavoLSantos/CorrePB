"""Fonte AP Crono — apcrono.com.br

Extrai eventos do calendário via WP REST (wp/v2/etn) + detalhe HTML
(apcrono evento + tiquet). Preços vêm do tiquet (Inscreva-se).

Sem Selenium, apenas requests + BeautifulSoup + ScraperCommon.
"""

import re
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from data_collection.core.ScraperCommon import (
    PriceEntry,
    _as_object_list,
    _as_str_object_dict,
    fix_encoding,
    format_date_string,
    get_http_session,
    get_with_rate_limit,
    parse_date_string,
)

try:
    from typing import cast
except ImportError:
    cast = lambda t, v: v  # type: ignore

BASE_URL = "https://apcrono.com.br"
CALENDARIO_URL = f"{BASE_URL}/calendario-de-eventos/"
WP_ETN_API = f"{BASE_URL}/wp-json/wp/v2/etn?per_page=100"

SESSION = get_http_session(
    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
SESSION.headers.update({"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
ORGANIZADOR_PADRAO = "AP CRONO"


def is_apcrono_domain(domain: str) -> bool:
    if not domain:
        return False
    return "apcrono.com.br" in domain.lower()


def _strip_accents(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


def _parse_tiquet_date_time(text: str) -> tuple[str, str]:
    """Extrai (data_br DD/MM/YYYY, horario HH:MM) de texto tipo '30/09/2026 19:00'."""
    m = re.search(r"(\d{2}/\d{2}/\d{4})\s*(\d{2}:\d{2})", text)
    if m:
        return m.group(1), m.group(2)
    m = re.search(r"(\d{2}/\d{2}/\d{4})", text)
    if m:
        return m.group(1), ""
    return "", ""


def _parse_apcrono_soup(html: str) -> tuple[str, str, str, str]:
    """Retorna (date_str, location_raw, inscricao_url, regulamento_url) da página /evento/<slug>/."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    # Date : 30/09/2026
    date_str = ""
    m = re.search(r"Date\s*:\s*(\d{2}/\d{2}/\d{4})", text)
    if m:
        date_str = m.group(1)

    # Inscreva-se e Regulamento vêm do content (links tiquet)
    inscricao = ""
    regulamento = ""
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "")
        txt = a.get_text(strip=True).lower()
        if "tiquet.com.br/evento" in href and not inscricao:
            inscricao = href
        if "tiquet.com.br/visualizar/documento" in href and not regulamento:
            regulamento = href
        # fallback por texto
        if not inscricao and "inscreva" in txt and "tiquet" in href:
            inscricao = href
        if not regulamento and "regulamento" in txt and href.lower().endswith(".pdf"):
            regulamento = href

    # location via Add to Calendar links: location=Santa%20Cruz/RN
    location_raw = ""
    m = re.search(r"location=([^&]+)", html)
    if m:
        try:
            from urllib.parse import unquote
            location_raw = unquote(m.group(1).replace("+", " "))
        except Exception:
            location_raw = m.group(1)
    if not location_raw:
        # fallback: extrai de texto após Date
        pass

    return date_str, location_raw.strip(), inscricao, regulamento


def _parse_tiquet_soup(html: str) -> dict[str, Any]:
    """Extrai dados da página tiquet.com.br/evento/..."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    # Data + horário: heading "30/09/2026 19:00"
    tiquet_date, tiquet_horario = _parse_tiquet_date_time(text)

    # Cidade: heading "Santa Cruz - RN"
    cidade = ""
    estado = ""
    # procura h4 com padrão Cidade - UF
    for h in soup.find_all(["h4", "h3", "h2"]):
        t = h.get_text(" ", strip=True)
        m = re.match(r"^\s*(.+?)\s*-\s*([A-Z]{2})\s*$", t)
        if m and len(t) < 60:
            cidade = m.group(1).strip()
            estado = m.group(2).strip()
            break
    # fallback: location Raw já cobre, mas tenta extrair de texto com " - RN"
    if not cidade:
        m = re.search(r"([A-Za-zÀ-ú\s]+)\s*-\s*(RN|PB|CE|PE)\b", text)
        if m:
            cidade = m.group(1).strip().split()[-2] if len(m.group(1).split())>2 else m.group(1).strip()
            # melhor: pega último match antes de endereço longo
            pass

    # Distâncias: headings 5Km / 10Km etc dentro de #categories-lots
    distancias: list[str] = []
    for h in soup.find_all(["h5", "h4", "h3"]):
        t = h.get_text(strip=True)
        if re.match(r"^\d+\s*Km$", t, re.IGNORECASE):
            dist = t.strip()
            if dist.lower() not in [d.lower() for d in distancias]:
                distancias.append(dist)

    # Preços: tabela Categorias e Lotes
    precos: list[PriceEntry] = []
    vistos = set()
    for table in soup.find_all("table"):
        # header row indica 5Km / 10Km - associar
        current_dist = ""
        for row in table.find_all("tr"):
            header = row.find("h5")
            if header:
                current_dist = header.get_text(strip=True)
                continue
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            cat = cells[0].get_text(" ", strip=True)
            price_txt = cells[1].get_text(" ", strip=True)
            if not cat or cat == "-":
                continue
            m = re.search(r"R\$\s*([\d.,]+)", price_txt)
            if not m:
                continue
            # Evita duplicar categorias sem preço real (já filtrado acima)
            label = f"{cat} - {current_dist}" if current_dist else cat
            # Usa texto original para label mais limpo
            label = re.sub(r"\s+", " ", label).strip()
            price_raw = m.group(1)
            # parse via PriceUtils para float, mas mantém string original para formatted
            from data_collection.utils.PriceUtils import parse_price_str
            preco = parse_price_str(price_raw)
            if preco is None:
                continue
            key = (label.lower(), preco)
            if key in vistos:
                continue
            vistos.add(key)
            precos.append({"label": label, "price": preco, "formatted": f"R${price_raw}"})

    # Organizador
    organizador = ""
    org_link = soup.select_one('#event-organizer, a[href*="#event-organizer"]')
    if org_link:
        # o link seguinte contém o nome
        nxt = soup.find(string=re.compile(r"FACISA|AP CRONO", re.I))
        if nxt:
            organizador = nxt.strip()
    if not organizador:
        # fallback: procura FACISA/UFRN no texto do organizer block
        m = re.search(r"FACISA\/UFRN|AP CRONO", text)
        if m:
            organizador = m.group(0)

    # Link do edital direto no tiquet
    edital = ""
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "")
        if "/visualizar/documento/" in href:
            edital = href
            # tiquet usa path relativo -> absolutiza
            if edital.startswith("/"):
                edital = urljoin("https://tiquet.com.br", edital)
            break
        if href.lower().endswith(".pdf") and "regulamento" in a.get_text(strip=True).lower():
            edital = href
            break

    # Imagem do evento no tiquet
    imagem = ""
    # tiquet usa /visualizar/imagem/<id>/ como src; fallback para qualquer img do evento
    for sel in ['img[src*="visualizar/imagem"]', 'img[src*="image-event"]', 'img[src*="tiquet"]', 'main img[src^="https://"]', 'img[src*="/wp-content/"]']:
        img = soup.select_one(sel)
        if img and img.get("src"):
            src = str(img.get("src") or "").strip()
            if src and "logo" not in src.lower() and "whats" not in src.lower():
                imagem = src
                if imagem.startswith("/"):
                    imagem = urljoin("https://tiquet.com.br", imagem)
                break

    return {
        "date": tiquet_date,
        "horario": tiquet_horario,
        "cidade": cidade,
        "estado": estado,
        "distancias": distancias,
        "precos": precos,
        "organizador": organizador,
        "edital": edital,
        "imagem": imagem,
    }


def _discover_via_api() -> list[dict[str, str]]:
    """Lista eventos via wp-json/wp/v2/etn (23 eventos). Fallback para calendário HTML."""
    try:
        resp = get_with_rate_limit(SESSION, WP_ETN_API, timeout=20)
        if resp and resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and data:
                out = []
                for item in data:
                    d = _as_str_object_dict(item) if isinstance(item, dict) else None
                    if not d:
                        continue
                    slug = str(d.get("slug") or "")
                    title = ""
                    t = d.get("title")
                    if isinstance(t, dict):
                        title = str(t.get("rendered") or "")
                    elif isinstance(t, str):
                        title = t
                    # content rendered contém links tiquet
                    link = str(d.get("link") or f"{BASE_URL}/evento/{slug}/")
                    out.append({"slug": slug, "title": BeautifulSoup(title, "html.parser").get_text(strip=True), "link": link})
                if out:
                    return out
    except Exception:
        pass
    # Fallback: raspa calendário HTML
    try:
        resp = get_with_rate_limit(SESSION, CALENDARIO_URL, timeout=20)
        if resp:
            soup = BeautifulSoup(resp.text, "html.parser")
            out = []
            for a in soup.select('a[href*="/evento/"]'):
                href = str(a.get("href") or "")
                if "/evento/" not in href:
                    continue
                slug = href.rstrip("/").split("/")[-1]
                if any(x["slug"] == slug for x in out):
                    continue
                title = a.get_text(strip=True) or slug
                out.append({"slug": slug, "title": title, "link": href if href.startswith("http") else urljoin(BASE_URL, href)})
            return out
    except Exception:
        pass
    return []


def get_apcrono_events(
    estado_filter: str | None = None,
    somente_futuros: bool = True,
) -> list[dict[str, str]]:
    """Coleta completa AP Crono.

    - Lista via wp/v2/etn
    - Para cada evento: GET apcrono detalhe + GET tiquet (se houver Inscreva-se)
    - Filtro opcional por UF (PB/RN/CE...) e por data futura
    """
    from data_collection.core.ScraperCommon import entries_to_json

    lista = _discover_via_api()
    records: list[dict[str, str]] = []

    for item in lista:
        slug = item.get("slug", "")
        link_apcrono = item.get("link", f"{BASE_URL}/evento/{slug}/")
        try:
            # 1. Detalhe apcrono
            resp = get_with_rate_limit(SESSION, link_apcrono, timeout=20)
            if not resp:
                continue
            ap_date, ap_location, inscricao_url, regulamento_ap = _parse_apcrono_soup(resp.text)

            # Se não achou inscrição na página apcrono, tenta extrair do content JSON (wp api content)
            # já vem no content mas parse acima cobre

            # 2. Detalhe tiquet (se houver)
            tiquet_data: dict[str, Any] = {}
            if inscricao_url and "tiquet.com.br" in inscricao_url:
                r2 = get_with_rate_limit(SESSION, inscricao_url, timeout=20)
                if r2:
                    tiquet_data = _parse_tiquet_soup(r2.text)

            # Merge de campos
            # Data: prioriza tiquet (mais completo com horário), senão apcrono
            data_br = str(tiquet_data.get("date") or ap_date or "")
            horario = str(tiquet_data.get("horario") or "")
            # Fallback: extrai horário da string de data/hora combinada se já veio
            if not horario and data_br and " " in data_br:
                # não há, mas mantém
                pass

            cidade = str(tiquet_data.get("cidade") or "")
            estado = str(tiquet_data.get("estado") or "")
            if not cidade and ap_location:
                # ap_location vem como "Santa Cruz/RN" ou "Santa Cruz - RN"
                m = re.match(r"(.+?)\s*[/\-]\s*([A-Z]{2})", ap_location)
                if m:
                    cidade = m.group(1).strip()
                    estado = m.group(2).strip()
                else:
                    cidade = ap_location.split("/")[0].strip()

            if estado_filter and estado.upper() != estado_filter.upper():
                continue

            # Filtro somente_futuros
            if somente_futuros and data_br:
                dt = parse_date_string(data_br)
                if dt and dt < datetime.now():
                    continue

            distancias = tiquet_data.get("distancias") or []
            if isinstance(distancias, list):
                distancia_str = ", ".join(str(d) for d in distancias if d)
            else:
                distancia_str = str(distancias or "")

            precos = tiquet_data.get("precos") or []
            precos_entries = entries_to_json(precos) if precos else "[]"

            # Imagem (tiquet -> og:image -> img destaque apcrono)
            imagem = str(tiquet_data.get("imagem") or "")
            if not imagem:
                try:
                    soup_tmp = BeautifulSoup(resp.text, "html.parser")
                    og = soup_tmp.find("meta", property="og:image")
                    if og and og.get("content"):
                        imagem = str(og.get("content") or "")
                    if not imagem:
                        # fallback: primeira imagem de conteúdo do evento
                        for cand in soup_tmp.select('article img, main img, img[src*="/wp-content/"]'):
                            src_img = str(cand.get("src") or "").strip()
                            if src_img and "logo" not in src_img.lower():
                                imagem = src_img
                                if imagem.startswith("/"):
                                    imagem = urljoin(BASE_URL, imagem)
                                break
                except Exception:
                    pass

            organizador = str(tiquet_data.get("organizador") or ORGANIZADOR_PADRAO)
            edital = str(tiquet_data.get("edital") or regulamento_ap or "edital não encontrado")

            # Formata data para "DD de mês de AAAA"
            from data_collection.core.ScraperCommon import format_date_string as fmt_data
            data_fmt = fmt_data(data_br) if data_br else ""

            records.append({
                "Nome do Evento": fix_encoding(item.get("title") or slug),
                "Link de Inscrição": inscricao_url or link_apcrono,
                "Link da Imagem": imagem,
                "Data": data_fmt or data_br,
                "Horário": horario,
                "Cidade": fix_encoding(cidade),
                "Distância": ", ".join(distancias) if isinstance(distancias, list) else distancia_str,
                "Organizador": fix_encoding(organizador),
                "Link do Edital": edital,
                "precos_entries": precos_entries,
            })
        except Exception as e:
            print(f"[WARN] apcrono {slug}: {e}")
            continue

    return records
