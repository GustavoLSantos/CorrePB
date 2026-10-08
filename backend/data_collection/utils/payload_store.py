"""Persistência dos CSVs coletados entre as fases do scrape.

Cada execução de worker é um container efêmero: os CSVs do disco não
sobrevivem para a fase de import. Este módulo guarda o conteúdo no
Mongo (`scrape_payload`, com TTL) durante a janela de confirmação humana
e limpa tudo após a importação concluída.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

log = logging.getLogger("payload_store")

COLLECTION = "scrape_payload"
PAYLOAD_TTL_HOURS = 24


def database_name() -> str:
    """Mesma convenção de ImportToDB: remoto tem precedência sobre local."""
    return os.getenv("MONGODB_REMOTE_DB_NAME") or os.getenv("MONGODB_DB_NAME") or "correpb"


def payload_collection(client) -> Any:
    return client[database_name()][COLLECTION]


def ensure_ttl_index(collection) -> None:
    """TTL em expires_at: payloads órfãos somem sem job de limpeza."""
    try:
        collection.create_index("expires_at", expireAfterSeconds=0)
    except Exception as exc:  # índice é otimização; falha não impede operação
        log.warning("TTL scrape_payload não criado: %s", exc)


def _doc_for(job_id: str, fonte: str, content: str, now: datetime) -> Dict[str, Any]:
    return {
        "_id": f"{job_id}|{fonte}",
        "job_id": job_id,
        "fonte": fonte,
        "content": content,
        "expires_at": now + timedelta(hours=PAYLOAD_TTL_HOURS),
        "created_at": now,
    }


def save_payload(collection, job_id: str, csv_map: Dict[str, Path]) -> List[str]:
    """Grava o conteúdo de cada CSV existente. Devolve as fontes salvas."""
    now = datetime.now(timezone.utc)
    saved: List[str] = []
    for fonte, path in csv_map.items():
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as exc:
            log.warning("payload: falha ao ler %s: %s", path, exc)
            continue
        try:
            collection.update_one(
                {"_id": f"{job_id}|{fonte}"},
                {"$set": _doc_for(job_id, fonte, content, now)},
                upsert=True,
            )
        except Exception as exc:
            log.warning("payload: falha ao salvar %s: %s", fonte, exc)
            continue
        saved.append(fonte)
    return saved


def load_payload(collection, job_id: str, csv_map: Dict[str, Path]) -> List[str]:
    """Restaura os CSVs do Mongo para o disco. Devolve as fontes restauradas.

    `fonte` vem sempre do próprio csv_map (nova consulta ao Mongo é filtrada
    por job_id), então um documento com fonte desconhecida é ignorado em vez
    de escrever em caminho arbitrário.
    """
    known = set(csv_map)
    try:
        docs = collection.find({"job_id": job_id})
    except Exception as exc:
        log.error("payload: falha ao consultar: %s", exc)
        return []

    restored: List[str] = []
    for doc in docs:
        fonte = doc.get("fonte")
        content = doc.get("content")
        if fonte not in known or not isinstance(content, str):
            log.warning("payload: documento ignorado (fonte=%r)", fonte)
            continue
        try:
            csv_map[fonte].parent.mkdir(parents=True, exist_ok=True)
            csv_map[fonte].write_text(content, encoding="utf-8")
        except Exception as exc:
            log.error("payload: falha ao restaurar %s: %s", fonte, exc)
            continue
        restored.append(fonte)
    return restored


def drop_payload(collection, job_id: str) -> int:
    """Remove os documentos do job. Devolve quantos foram apagados."""
    try:
        result = collection.delete_many({"job_id": job_id})
        return int(getattr(result, "deleted_count", 0) or 0)
    except Exception as exc:
        log.warning("payload: falha ao limpar %s: %s", job_id, exc)
        return 0


def check_no_leftover(collection, job_id: str) -> bool:
    """Usado em teste/manual: True quando nada restou do job."""
    try:
        return collection.count_documents({"job_id": job_id}) == 0
    except Exception:
        return False


# Compat: datetime/Path reexportados para quem importa daqui
__all__ = [
    "COLLECTION",
    "PAYLOAD_TTL_HOURS",
    "check_no_leftover",
    "database_name",
    "drop_payload",
    "ensure_ttl_index",
    "load_payload",
    "payload_collection",
    "save_payload",
]
