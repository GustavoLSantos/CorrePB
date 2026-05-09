import certifi
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings


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
        collection_name = name or settings.MONGODB_COLLECTION
        return self.db[collection_name]


database = Database()
