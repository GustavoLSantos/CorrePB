import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
from app.core.config import settings
try:
    import pymongo
except Exception:
    pymongo = None

logger = logging.getLogger(__name__)


class Database:
    client: AsyncIOMotorClient = None
    db: AsyncIOMotorDatabase = None

    @classmethod
    async def connect(cls):
        """Estabelece conexão com o banco de dados MongoDB."""
        try:
            # Preferir URI remota se fornecida (por exemplo, Atlas)
            mongo_uri = settings.MONGODB_REMOTE_URI or settings.MONGODB_URI

            # Escolher nome do banco: usar MONGODB_REMOTE_DB_NAME se remoto e fornecido
            db_name = settings.MONGODB_REMOTE_DB_NAME or settings.MONGODB_DB_NAME

            # Se temos uma URI remota e nenhum DB remoto explícito, tentar detectar com pymongo (rápido)
            if settings.MONGODB_REMOTE_URI and not settings.MONGODB_REMOTE_DB_NAME and pymongo is not None:
                try:
                    sync_client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
                    sync_client.admin.command('ping')
                    # Preferir db_name padrão inicialmente, mas procurar por DBs com documentos na coleção 'eventos'
                    candidate_dbs = sync_client.list_database_names()
                    for candidate in candidate_dbs:
                        try:
                            candidate_db = sync_client[candidate]
                            cols = candidate_db.list_collection_names()
                            if 'eventos' in cols:
                                c_count = candidate_db['eventos'].count_documents({})
                                if c_count and c_count > 0:
                                    db_name = candidate
                                    logger.info(f"Detecção (sync) selecionou DB '{db_name}' com {c_count} eventos")
                                    break
                        except Exception:
                            continue
                except Exception:
                    logger.info("Detecção sync por pymongo falhou ou expirou; usando configuração existente")

            # Agora cria o motor async client e atribui o DB detectado
            cls.client = AsyncIOMotorClient(mongo_uri)
            cls.db = cls.client[db_name]
            logger.info(f"Conectado ao banco de dados {db_name} usando URI: {('MONGODB_REMOTE_URI' if settings.MONGODB_REMOTE_URI else 'MONGODB_URI')}")
        except Exception as e:
            logger.error(f"Erro ao conectar ao banco de dados: {e}")
            raise

    @classmethod
    async def close(cls):
        """Fecha a conexão com o banco de dados."""
        if cls.client is not None:  # Usar 'is not None' em vez de verificação booleana
            cls.client.close()
            cls.client = None
            cls.db = None
            logger.info("Conexão com o banco de dados fechada")

    @classmethod
    async def get_database(cls) -> AsyncIOMotorDatabase:
        """
        Retorna a instância do banco de dados.

        Returns:
            AsyncIOMotorDatabase: Instância do banco de dados
        """
        if cls.db is None:  # Usar 'is None' em vez de verificação booleana
            await cls.connect()
        return cls.db

    @classmethod
    async def get_collection(cls, collection_name: str) -> AsyncIOMotorCollection:
        """
        Retorna uma coleção do banco de dados.

        Args:
            collection_name: Nome da coleção

        Returns:
            AsyncIOMotorCollection: Coleção do banco de dados
        """
        db = await cls.get_database()
        return db[collection_name]