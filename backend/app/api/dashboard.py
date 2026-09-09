from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter

from app.core.database import database

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])

MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}

def _parse_data_realizacao(raw: str, datas_iso=None):
    if datas_iso:
        try:
            # datas_realizacao is list[datetime]
            first = datas_iso[0]
            if isinstance(first, datetime):
                return first
            d = datetime.fromisoformat(str(first).replace("Z", "+00:00"))
            if not d.tzinfo:
                d = d.replace(tzinfo=timezone.utc)
            return d
        except:
            pass
    if not raw:
        return None
    # Try ISO YYYY-MM-DD
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

@router.get("/stats")
async def dashboard_stats():
    collection = database.get_collection()
    # Fetch minimal fields for aggregation (single DB round-trip)
    cursor = collection.find({}, {
        "data_realizacao": 1,
        "datas_realizacao": 1,
        "estado": 1,
        "site_coleta": 1,
        "organizador": 1,
        "precos_entries": 1,
        "patrocinado": 1,
        "url_imagem": 1,
    })
    eventos = [doc async for doc in cursor]
    total = len(eventos)

    now = datetime.now(timezone.utc)
    now = now.replace(hour=0, minute=0, second=0, microsecond=0)
    in30 = datetime.fromtimestamp(now.timestamp() + 30*24*3600, tz=timezone.utc)
    in90 = datetime.fromtimestamp(now.timestamp() + 90*24*3600, tz=timezone.utc)

    ativos = passados = proximos30d = proximos90d = sem_preco = patrocinados = sem_imagem = 0
    por_mes = Counter()
    por_estado = Counter()
    por_fonte = Counter()
    fonte_display = {}

    for doc in eventos:
        raw = doc.get("data_realizacao", "")
        datas_iso = doc.get("datas_realizacao") or []
        d = _parse_data_realizacao(raw, datas_iso)
        if d:
            # normalize to UTC midnight for comparison
            d_utc = d.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            if d_utc >= now:
                ativos += 1
                if d_utc <= in30:
                    proximos30d += 1
                if d_utc <= in90:
                    proximos90d += 1
            else:
                passados += 1
            key = f"{d_utc.year}-{d_utc.month:02d}"
            por_mes[key] += 1

        precos = doc.get("precos_entries")
        if not precos:
            sem_preco += 1
        if doc.get("patrocinado"):
            patrocinados += 1
        if not doc.get("url_imagem"):
            sem_imagem += 1

        est = (doc.get("estado") or "—").strip().upper() or "—"
        por_estado[est] += 1

        fonte_raw = (doc.get("site_coleta") or "—").strip()
        fonte_key = fonte_raw.lower()
        if fonte_key not in fonte_display:
            fonte_display[fonte_key] = fonte_raw
        por_fonte[fonte_key] += 1

    return {
        "total": total,
        "ativos": ativos,
        "passados": passados,
        "proximos30d": proximos30d,
        "proximos90d": proximos90d,
        "semPreco": sem_preco,
        "patrocinados": patrocinados,
        "semImagem": sem_imagem,
        "porMes": [{"label": k, "count": v} for k, v in sorted(por_mes.items())],
        "porEstado": [{"estado": k, "count": v} for k, v in por_estado.most_common()],
        "porFonte": [{"fonte": fonte_display[k], "count": v} for k, v in por_fonte.most_common()],
    }
