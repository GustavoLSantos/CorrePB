import logging
from datetime import datetime, timezone

import certifi
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ReturnDocument

from app.core.config import settings

logger = logging.getLogger(__name__)


class Database:
    _instance: "Database | None" = None
    client: AsyncIOMotorClient | None = None
    db: AsyncIOMotorDatabase | None = None

    def __new__(cls) -> "Database":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def connect(self) -> None:
        uri = settings.MONGODB_REMOTE_URI or settings.MONGODB_URI
        db_name = (
            settings.MONGODB_REMOTE_DB_NAME
            if settings.MONGODB_REMOTE_URI and settings.MONGODB_REMOTE_DB_NAME
            else settings.MONGODB_DB_NAME
        )

        self.client = AsyncIOMotorClient(uri, tlsCAFile=certifi.where())
        self.db = self.client[db_name]

    async def disconnect(self) -> None:
        if self.client:
            self.client.close()

    def get_collection(self, name: str | None = None):
        if self.db is None:
            raise RuntimeError("Database not connected — call await database.connect() first")
        collection_name = name or settings.MONGODB_COLLECTION
        return self.db[collection_name]

    async def get_next_sequence(self, prefix: str) -> int:

        if self.db is None:
            raise RuntimeError("Database not connected — call await database.connect() first")
        counters = self.db["counters"]
        doc = await counters.find_one_and_update(
            {"_id": prefix},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        seq = int(doc["seq"])
        # Migração legada: seq==1 mas já existem eventos com esse prefixo
        if seq == 1:
            try:
                eventos = self.db[settings.MONGODB_COLLECTION]
                last = await eventos.find_one(
                    {"_id": {"$regex": f"^{prefix}"}},
                    sort=[("_id", -1)],
                )
                if last and isinstance(last.get("_id"), str):
                    raw = last["_id"]
                    # sufixo de 4 dígitos
                    legacy_seq = 0
                    try:
                        legacy_seq = int(raw[-4:])
                    except ValueError:
                        legacy_seq = 0
                    if legacy_seq >= 1:
                        # avança contador para legacy_seq + 1
                        doc2 = await counters.find_one_and_update(
                            {"_id": prefix},
                            {"$set": {"seq": legacy_seq + 1}},
                            return_document=ReturnDocument.AFTER,
                        )
                        seq = int(doc2["seq"])  # type: ignore[union-attr]
                        logger.info(
                            f"[counters] prefix {prefix} inicializado em {seq} (legado {legacy_seq})"
                        )
            except Exception as e:
                logger.warning(f"[counters] falha ao inicializar legado {prefix}: {e}")
        return seq

    async def get_next_evento_id(self) -> str:
        prefix = datetime.now(timezone.utc).strftime("%Y%m")
        seq = await self.get_next_sequence(prefix)
        return f"{prefix}{seq:04d}"


database = Database()
