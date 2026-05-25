import asyncio
import json
import logging

import boto3
from fastapi import HTTPException

from app.core.config import settings
from app.core.database import database
from app.models.evento import EventoResponse

logger = logging.getLogger(__name__)


async def trigger_bucket_sync() -> dict[str, str | int]:
    if not settings.AWS_BUCKET_NAME:
        raise HTTPException(status_code=500, detail="AWS_BUCKET_NAME não configurado")

    collection = database.get_collection()
    docs = await collection.find({}).to_list(length=None)

    eventos = []
    for doc in docs:
        try:
            evento = EventoResponse(**doc)
            eventos.append(evento.model_dump(by_alias=True))
        except Exception as e:
            logger.warning(f"Erro ao serializar evento {doc.get('_id')}: {e}")
            continue

    payload = json.dumps(eventos, ensure_ascii=False, default=str)

    def _upload() -> None:
        s3 = boto3.client(
            "s3",
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
        )
        s3.put_object(
            Bucket=settings.AWS_BUCKET_NAME,
            Key=settings.BUCKET_JSON_KEY,
            Body=payload.encode("utf-8"),
            ContentType="application/json",
        )

    await asyncio.to_thread(_upload)
    logger.info(f"Bucket sync concluído: {len(eventos)} eventos enviados")

    return {"status": "ok", "eventos_synced": len(eventos)}
