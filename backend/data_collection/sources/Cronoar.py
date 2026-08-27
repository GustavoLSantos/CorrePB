"""Fonte Cronoar — cronoar.com.br

Extrai eventos via:
- WP REST wp/v2/etn (lista) + /api/provas?slug= (detalhe completo com lotes/preços)
  Fallback: scraping do calendário em caso de falha da API.

Cobre todas as colunas do CSV: nome, link_inscricao, link_imagem, data,
horario, cidade, distancia, organizador, link_edital, precos_entries.
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

BASE_URL = "https://cronoar.com.br"
API_LIST_URL = f"{BASE_URL}/api/provas?status=aberto"
CALENDARIO_URL = f"{BASE_URL}/"

SESSION = get_http_session(
    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
# Aceita tanto JSON (WP REST) quanto HTML
SESSION.headers.update({"Accept": "application/json, text/html, application/xhtml+xml, */*;q=0.8"})
ORGANIZADOR_PADRAO = "Cronoar"


def is_cronoar_domain(domain: str) -> bool:
    if not domain:
        return False
    d = domain.lower()
    # cronoar.com.br ≠ apcrono.com.br
    return "cronoar.com.br" in d and "apcrono" not in d


def _discover_via_api() -> list[dict[str, str]]:
    """Lista eventos via API oficial /api/provas?status=aberto."""
    try:
        resp = get_with_rate_limit(SESSION, API_LIST_URL, timeout=20)
        if resp and resp.status_code == 200:
            data = resp.json()
            provas = data.get("provas") if isinstance(data, dict) else None
            if isinstance(provas, list) and provas:
                out: list[dict[str, str]] = []
                for item in provas:
                    d = _as_str_object_dict(item) if isinstance(item, dict) else None
                    if not d:
                        continue
                    slug = str(d.get("slug") or "")
                    title = str(d.get("titulo") or d.get("title") or slug)
                    title = BeautifulSoup(title, "html.parser").get_text(strip=True) or slug
                    link = f"{BASE_URL}/eventos/{slug}" if slug else str(d.get("link") or "")
                    if slug and not any(x["slug"] == slug for x in out):
                        out.append({"slug": slug, "title": title, "link": link})
                if out:
                    return out
    except Exception as e:
        print(f"[WARN] falha ao listar via API: {e}")
    return []


def _discover_via_html() -> list[dict[str, str]]:
    """Fallback: raspa calendário/home para links /eventos/<slug>."""
    try:
        resp = get_with_rate_limit(SESSION, BASE_URL, timeout=20)
        if not resp:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        out: list[dict[str, str]] = []
        for a in soup.select('a[href*="/eventos/"]'):
            href = str(a.get("href") or "")
            if "/eventos/" not in href:
                continue
            slug = href.rstrip("/").split("/")[-1]
            if not slug or any(x["slug"] == slug for x in out):
                continue
            # filtra rotas genéricas
            if slug in ("eventos",):
                continue
            title = a.get_text(strip=True) or slug
            # tenta pegar título do card (heading próximo)
            card = a.find_parent("article") or a.find_parent("div")
            if card:
                h = card.find(["h3", "h2"])
                if h and h.get_text(strip=True):
                    title = h.get_text(strip=True)
            out.append({"slug": slug, "title": title, "link": href if href.startswith("http") else urljoin(BASE_URL, href)})
        return out
    except Exception:
        return []


def _parse_prova_api(slug: str) -> dict[str, Any] | None:
    """Busca detalhe completo via /api/provas?slug=<slug>."""
    try:
        resp = get_with_rate_limit(SESSION, f"{BASE_URL}/api/provas?slug={slug}", timeout=20)
        if not resp or resp.status_code != 200:
            return None
        data = resp.json()
        provas = data.get("provas") if isinstance(data, dict) else None
        if isinstance(provas, list) and provas:
            # API retorna lista com 1 elemento para slug específico
            first = provas[0]
            if isinstance(first, dict):
                return first
        # fallback: data é diretamente o objeto (algumas versões)
        if isinstance(data, dict) and "titulo" in data:
            return data  # type: ignore[return-value]
    except Exception:
        pass
    return None


def _build_precos(lotes: Any) -> list[PriceEntry]:
    """Converte lotes[].modalidades[] do cronoar em PriceEntry padronizado."""
    precos: list[PriceEntry] = []
    vistos: set[tuple[str, float]] = set()
    if not isinstance(lotes, list):
        return precos
    for lote in lotes:
        if not isinstance(lote, dict):
            continue
        lote_nome = str(lote.get("nome") or lote.get("lote") or "").strip()
        for mod in (lote.get("modalidades") or []):
            if not isinstance(mod, dict):
                continue
            nome = str(mod.get("nome") or "").strip()
            valor = mod.get("valor")
            # valor pode ser int/float ou string "60" / "60.00"
            try:
                preco = float(str(valor).replace(",", ".")) if valor is not None else None
            except Exception:
                preco = None
            if preco is None or preco <= 0:
                # cronoar usa 0 para inscrições encerradas sem preço? ignora
                # mas mantém se for realmente gratuito? Para cronoar, não há gratuito
                continue
            label = nome
            if lote_nome and lote_nome.lower() not in ("lote único", "lote unico"):
                label = f"{lote_nome} - {nome}" if nome else lote_nome
            label = re.sub(r"\s+", " ", label).strip()
            key = (label.lower(), preco)
            if key in vistos:
                continue
            vistos.add(key)
            precos.append({"label": label, "price": preco, "formatted": f"R$ {preco:.2f}".replace(".", ",")})
    return precos


def get_cronoar_events(
    estado_filter: str | None = None,
    somente_futuros: bool = True,
) -> list[dict[str, str]]:
    """Coleta completa Cronoar.

    - Descoberta via WP REST (fallback HTML)
    - Detalhe via /api/provas?slug= (contém cidade, estado, data, horário, lotes, documentos, imagens)
    """
    from data_collection.core.ScraperCommon import entries_to_json

    # 1. Descoberta (API + fallback HTML)
    lista = _discover_via_api()
    if not lista:
        lista = _discover_via_html()

    records: list[dict[str, str]] = []

    for item in lista:
        slug = item.get("slug", "")
        link_cronoar = item.get("link", f"{BASE_URL}/eventos/{slug}")
        try:
            prova = _parse_prova_api(slug)
            if not prova:
                # fallback: tenta HTML da página do evento
                resp = get_with_rate_limit(SESSION, link_cronoar, timeout=20)
                if not resp:
                    continue
                # sem API, pula (não há dados estruturados para precificar)
                continue

            # Campos base da API
            titulo = str(prova.get("titulo") or item.get("title") or slug).strip()
            cidade = str(prova.get("cidade") or "").strip()
            estado = str(prova.get("estado") or "").strip().upper()
            data = str(prova.get("data") or prova.get("dataFormatada") or "").strip()
            # data vem como "06/09/2026" ou "06 de Setembro de 2026" dependendo do endpoint
            horario_raw = str(prova.get("horario") or "").strip()  # "16:00h"
            horario = re.sub(r"[^0-9:]", "", horario_raw.split()[0]) if horario_raw else ""
            if horario and ":" not in horario and len(horario) <= 2:
                horario = f"{horario}:00"
            # Horário também pode estar em concentracao? ignora

            if estado_filter and estado and estado.upper() != estado_filter.upper():
                continue

            if somente_futuros and data:
                dt = parse_date_string(data)
                # tenta dataFormatada se parse falhou
                if not dt:
                    dt = parse_date_string(str(prova.get("dataFormatada") or ""))
                if dt and dt < datetime.now():
                    continue

            # Distâncias: extrai de modalidades
            distancias_set: list[str] = []
            for lote in (prova.get("lotes") or []):
                if not isinstance(lote, dict):
                    continue
                for mod in (lote.get("modalidades") or []):
                    if not isinstance(mod, dict):
                        continue
                    nome = str(mod.get("nome") or "").strip()
                    # nome como "5KM Sem Camisa" -> extrai "5KM"
                    m = re.search(r"(\d+\s*km)", nome, re.I)
                    base_dist = m.group(1).upper().replace(" ", "") if m else nome
                    if base_dist and base_dist.lower() not in [d.lower() for d in distancias_set]:
                        distancias_set.append(base_dist)
            distancia_str = ", ".join(distancias_set)

            # Imagem
            imagem = str(prova.get("imagemDestaque") or prova.get("imagemCapa") or "").strip()
            if not imagem:
                # tenta og:image via HTML se necessário
                pass

            # Edital
            edital = "edital não encontrado"
            for doc in (prova.get("documentos") or []):
                if isinstance(doc, dict) and str(doc.get("url") or "").lower().endswith(".pdf"):
                    edital = str(doc.get("url") or "").strip()
                    break
                if isinstance(doc, dict) and "regulamento" in str(doc.get("nome") or "").lower():
                    edital = str(doc.get("url") or "").strip()
                    if edital:
                        break

            # Preços
            precos = _build_precos(prova.get("lotes"))
            precos_entries = entries_to_json(precos) if precos else "[]"

            # Link de inscrição: evento tem página de inscrição interna
            link_inscricao = f"{BASE_URL}/eventos/{slug}/inscricao"
            # Se API retornar link direto, prefere
            if prova.get("linkInscricao"):
                link_inscricao = str(prova.get("linkInscricao"))

            data_fmt = format_date_string(data) if data else ""

            records.append({
                "Nome do Evento": fix_encoding(titulo),
                "Link de Inscrição": link_inscricao,
                "Link da Imagem": imagem,
                "Data": data_fmt or data,
                "Horário": horario,
                "Cidade": fix_encoding(cidade),
                "Distância": distancia_str,
                "Organizador": "Cronoar",
                "Link do Edital": edital,
                "precos_entries": precos_entries,
            })
        except Exception as e:
            print(f"[WARN] cronoar {slug}: {e}")
            continue

    return records
