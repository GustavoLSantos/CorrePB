import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.database import database
from fastapi import APIRouter
from pydantic import BaseModel, Field


class CountItem(BaseModel):
    label: str
    count: int


class EstadoCount(BaseModel):
    estado: str
    count: int


class CidadeCount(BaseModel):
    cidade: str
    count: int


class DistanciaCount(BaseModel):
    distancia: str
    count: int


class OrganizadorCount(BaseModel):
    organizador: str
    count: int


class FonteCount(BaseModel):
    fonte: str
    count: int


class DensidadeItem(BaseModel):
    data: str
    count: int


class StatusInscricoes(BaseModel):
    abertas: int
    emBreve: int = Field(alias="emBreve")
    encerradas: int

    model_config = {"populate_by_name": True}


class ScraperHealthItem(BaseModel):
    fonte: str
    display: str
    count: int
    semLink: int
    semRegulamento: int
    semImagem: int
    semPreco: int
    maxDataColeta: str | None = None


class ProximoEventoItem(BaseModel):
    _id: str
    nome_evento: str
    data_realizacao: str
    datas_realizacao: list[str] | None = None
    cidade: str
    estado: str
    organizador: str


class DashboardStats(BaseModel):
    total: int
    ativos: int
    passados: int
    proximos30d: int
    proximos90d: int
    semPreco: int
    patrocinados: int
    semImagem: int
    semLink: int
    semRegulamento: int
    valorMedio: float
    lote1Count: int
    porMes: list[CountItem]
    porEstado: list[EstadoCount]
    porCidade: list[CidadeCount]
    porDistancia: list[DistanciaCount]
    porOrganizador: list[OrganizadorCount]
    porFonte: list[FonteCount]
    densidade: list[DensidadeItem]
    choques: int
    statusInscricoes: StatusInscricoes
    comPercurso: int
    comKits: int
    porHorario: list[CountItem]
    porKit: list[CountItem]
    scraperHealth: list[ScraperHealthItem] = []
    proximosEventos: list[ProximoEventoItem] = []


def _is_valid_local_largada(s: str) -> bool:
    if not s or len(s) < 10 or len(s) > 120:
        return False
    if "Art." in s or "CAPÍTULO" in s or "meia hora" in s.lower():
        return False
    low = s.strip().lower()
    if low.startswith(("com ", "para ", "com pelo")):
        return False
    words = s.strip().split()
    if len(words) < 2:
        return False
    upper = s.strip().upper()
    if upper in {"PRAÇA", "RUA", "AVENIDA", "CENTRO", "PRAÇA "}:
        return False
    if re.match(r"^[A-Za-zÀ-ÿ\s\-]+ - [A-Z]{2}$", s.strip()) and len(words) <= 4 and "," not in s:
        low2 = s.lower()
        if not any(
            k in low2
            for k in [
                "rua",
                "av",
                "avenida",
                "praça",
                "parque",
                "estádio",
                "ginásio",
                "igreja",
                "shopping",
                "orla",
                "pista",
                "centro",
                "bairro",
                "frente",
                "matriz",
            ]
        ):
            return False
    return True


router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])

MESES_PT = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "março": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


def _parse_data_realizacao(raw: str, datas_iso=None):
    if datas_iso:
        try:
            first = datas_iso[0]
            if isinstance(first, datetime):
                return first if first.tzinfo else first.replace(tzinfo=timezone.utc)
            d = datetime.fromisoformat(str(first).replace("Z", "+00:00"))
            if not d.tzinfo:
                d = d.replace(tzinfo=timezone.utc)
            return d
        except:
            pass
    if not raw:
        return None
    try:
        if "-" in raw:
            d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if not d.tzinfo:
                d = d.replace(tzinfo=timezone.utc)
            if d.year > 1900:
                return d
    except:
        pass
    try:
        parts = raw.lower().strip().split()
        dia = int(parts[0])
        mes = MESES_PT.get(parts[2].lower())
        ano = int(parts[4])
        if not dia or not mes or not ano:
            return None
        return datetime(ano, mes, dia, tzinfo=timezone.utc)
    except:
        return None


@router.get(
    "/stats",
    response_model=DashboardStats,
    summary="Estatísticas do dashboard",
    description=(
        "Agrega todos os eventos para o dashboard administrativo: totais, "
        "ativos/passados, próximos 30/90 dias, qualidade de dados "
        "(sem preço/imagem/link/regulamento), preço médio, distribuição por "
        "mês/estado/cidade/distância/organizador/fonte, densidade por dia, "
        "choques de data e status de inscrições."
    ),
    response_description="Estatísticas consolidadas de eventos",
)
async def dashboard_stats() -> dict[str, Any]:
    collection = database.get_collection()
    cursor = collection.find(
        {},
        {
            "_id": 1,
            "nome_evento": 1,
            "data_realizacao": 1,
            "datas_realizacao": 1,
            "data_coleta": 1,
            "estado": 1,
            "cidade": 1,
            "site_coleta": 1,
            "organizador": 1,
            "precos_entries": 1,
            "patrocinado": 1,
            "url_imagem": 1,
            "url_inscricao": 1,
            "link_edital": 1,
            "distancias": 1,
            "percurso": 1,
            "kits": 1,
            "horario": 1,
        },
    )
    eventos = [doc async for doc in cursor]
    total = len(eventos)

    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    in30 = now + timedelta(days=30)
    in90 = now + timedelta(days=90)
    in7 = now + timedelta(days=7)

    ativos = passados = proximos30d = proximos90d = 0
    sem_preco = patrocinados = sem_imagem = sem_link = sem_regulamento = 0
    por_mes = Counter()
    por_estado = Counter()
    por_cidade = Counter()
    cidade_display = {}
    por_distancia = Counter()
    por_org = Counter()
    org_display = {}
    por_fonte = Counter()
    fonte_display = {}
    densidade_por_dia = Counter()
    status_abertas = status_breve = status_encerradas = 0
    precos_vals: list[float] = []
    lote1_count = 0
    com_percurso = com_kits = 0
    por_horario = Counter()
    por_kit = Counter()
    health_map: dict[str, dict[str, Any]] = {}
    proximos_candidates: list[dict[str, Any]] = []

    for doc in eventos:
        raw = doc.get("data_realizacao", "")
        datas_iso = doc.get("datas_realizacao") or []
        d = _parse_data_realizacao(raw, datas_iso)

        d_utc = None
        if d:
            d_utc = d.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            if d_utc >= now:
                ativos += 1
                if d_utc <= in30:
                    proximos30d += 1
                if d_utc <= in90:
                    proximos90d += 1
            else:
                passados += 1
            por_mes[f"{d_utc.year}-{d_utc.month:02d}"] += 1
            densidade_por_dia[d_utc.strftime("%Y-%m-%d")] += 1
            if d_utc < now:
                status_encerradas += 1
            elif d_utc <= in7:
                status_breve += 1
            else:
                status_abertas += 1
        else:
            # sem data parseável conta como encerrada para status
            status_encerradas += 1

        precos = doc.get("precos_entries")
        if not precos:
            sem_preco += 1
        else:
            for p in precos:
                if isinstance(p, str) and "lote 1" in p.lower():
                    lote1_count += 1
                    break
            for p in precos:
                m = re.search(r"R\$\s*([0-9.,]+)", str(p))
                if m:
                    try:
                        val = float(m.group(1).replace(".", "").replace(",", "."))
                        precos_vals.append(val)
                    except:
                        pass

        horario = (doc.get("horario") or "").strip()
        if horario and re.match(r"^\d{2}:\d{2}$", horario) and len(horario) <= 5:
            por_horario[horario] += 1

        percurso = doc.get("percurso")
        if isinstance(percurso, dict) and (
            percurso.get("local_largada") or percurso.get("trajeto")
        ):
            local_raw = (percurso.get("local_largada") or "").strip()
            trajeto_raw = (percurso.get("trajeto") or "").strip()
            has_valid = False
            if local_raw and _is_valid_local_largada(local_raw):
                has_valid = True
            if (
                trajeto_raw
                and len(trajeto_raw) <= 500
                and "Art." not in trajeto_raw
                and "CAPÍTULO" not in trajeto_raw
            ):
                has_valid = True
            if has_valid:
                com_percurso += 1

        kits = doc.get("kits")
        if isinstance(kits, list) and kits:
            valid_kits = [
                k
                for k in kits
                if isinstance(k, dict)
                and (k.get("nome") or "").strip()
                and len((k.get("nome") or "").strip()) <= 50
                and "Art." not in (k.get("nome") or "")
            ]
            if valid_kits:
                com_kits += 1
                for kit in valid_kits:
                    nome = (kit.get("nome") or "Kit").strip() or "Kit"
                    if len(nome) <= 50 and "Art." not in nome:
                        por_kit[nome] += 1

        if doc.get("patrocinado"):
            patrocinados += 1
        if not doc.get("url_imagem"):
            sem_imagem += 1
        if not doc.get("url_inscricao"):
            sem_link += 1
        if not doc.get("link_edital") or doc.get("link_edital") == "edital não encontrado":
            sem_regulamento += 1

        est = (doc.get("estado") or "—").strip().upper() or "—"
        por_estado[est] += 1

        cid_raw = (doc.get("cidade") or "—").strip()
        cid_key = cid_raw.lower()
        if cid_key not in cidade_display:
            normalized = " ".join(w.capitalize() for w in cid_raw.lower().split())
            cidade_display[cid_key] = normalized
        por_cidade[cid_key] += 1

        raw_dist = doc.get("distancias")
        if isinstance(raw_dist, str):
            dist_list = [d.strip() for d in raw_dist.split(",") if d.strip()]
        elif isinstance(raw_dist, list):
            dist_list = raw_dist
        else:
            dist_list = []
        for dstr in dist_list:
            raw = str(dstr).strip()
            if not raw or len(raw) > 30 or "Art." in raw or "CAPÍTULO" in raw:
                continue
            matches = re.findall(r"\d+(?:[.,]\d+)?\s*KM", raw.upper())
            for m in matches:
                norm = re.sub(r"\s+", "", m).upper().replace(",", ".")
                if len(norm) <= 10:
                    por_distancia[norm] += 1

        org_raw = (doc.get("organizador") or "—").strip()
        org_key = org_raw.lower()
        if org_key not in org_display:
            org_display[org_key] = org_raw
        por_org[org_key] += 1

        fonte_raw = (doc.get("site_coleta") or "—").strip()
        fonte_key = fonte_raw.lower()
        if fonte_key not in fonte_display:
            fonte_display[fonte_key] = fonte_raw
        por_fonte[fonte_key] += 1

        if (
            fonte_raw
            and fonte_raw != "—"
            and not any(ig in fonte_key for ig in ("manual", "ticketsports"))
        ):
            h = health_map.get(fonte_key)
            sem_link = 0 if doc.get("url_inscricao") else 1
            link_edital = doc.get("link_edital")
            sem_reg = 0 if link_edital and link_edital != "edital não encontrado" else 1
            sem_img = 0 if doc.get("url_imagem") else 1
            sem_prc = 0 if doc.get("precos_entries") else 1
            dc = doc.get("data_coleta")
            dc_iso = dc.isoformat() if isinstance(dc, datetime) else (str(dc) if dc else None)
            if h is None:
                health_map[fonte_key] = {
                    "fonte": fonte_key,
                    "display": fonte_raw,
                    "count": 1,
                    "semLink": sem_link,
                    "semRegulamento": sem_reg,
                    "semImagem": sem_img,
                    "semPreco": sem_prc,
                    "maxDataColeta": dc_iso,
                }
            else:
                h["count"] += 1
                h["semLink"] += sem_link
                h["semRegulamento"] += sem_reg
                h["semImagem"] += sem_img
                h["semPreco"] += sem_prc
                if dc_iso and (not h["maxDataColeta"] or dc_iso > h["maxDataColeta"]):
                    h["maxDataColeta"] = dc_iso

        # candidatos a próximos 30 dias (top 5)
        if d_utc and d_utc >= now and d_utc <= in30:
            proximos_candidates.append(
                {
                    "_id": str(doc.get("_id", "")),
                    "nome_evento": doc.get("nome_evento", ""),
                    "data_realizacao": doc.get("data_realizacao", ""),
                    "datas_realizacao": [
                        d.isoformat()
                        for d in (doc.get("datas_realizacao") or [])
                        if isinstance(d, datetime)
                    ],
                    "cidade": doc.get("cidade", ""),
                    "estado": doc.get("estado", ""),
                    "organizador": doc.get("organizador", ""),
                    "_sort": d_utc,
                }
            )

    valor_medio = round(sum(precos_vals) / len(precos_vals), 2) if precos_vals else 0
    choques = sum(1 for v in densidade_por_dia.values() if v > 1)
    scraper_health = sorted(
        health_map.values(), key=lambda x: x["maxDataColeta"] or "", reverse=True
    )
    proximos_eventos = sorted(proximos_candidates, key=lambda x: x["_sort"])[:5]
    for p in proximos_eventos:
        p.pop("_sort", None)

    return {
        "total": total,
        "ativos": ativos,
        "passados": passados,
        "proximos30d": proximos30d,
        "proximos90d": proximos90d,
        "semPreco": sem_preco,
        "patrocinados": patrocinados,
        "semImagem": sem_imagem,
        "semLink": sem_link,
        "semRegulamento": sem_regulamento,
        "valorMedio": valor_medio,
        "lote1Count": lote1_count,
        "porMes": [{"label": k, "count": v} for k, v in sorted(por_mes.items())],
        "porEstado": [{"estado": k, "count": v} for k, v in por_estado.most_common()],
        "porCidade": [
            {"cidade": cidade_display[k], "count": v} for k, v in por_cidade.most_common()
        ],
        "porDistancia": [{"distancia": k, "count": v} for k, v in por_distancia.most_common()],
        "porOrganizador": [
            {"organizador": org_display[k], "count": v} for k, v in por_org.most_common()
        ],
        "porFonte": [{"fonte": fonte_display[k], "count": v} for k, v in por_fonte.most_common()],
        "densidade": [{"data": k, "count": v} for k, v in sorted(densidade_por_dia.items())],
        "choques": choques,
        "statusInscricoes": {
            "abertas": status_abertas,
            "emBreve": status_breve,
            "encerradas": status_encerradas,
        },
        "comPercurso": com_percurso,
        "comKits": com_kits,
        "porHorario": [{"label": k, "count": v} for k, v in por_horario.most_common()],
        "porKit": [{"label": k, "count": v} for k, v in por_kit.most_common()],
        "scraperHealth": scraper_health,
        "proximosEventos": proximos_eventos,
    }
