"""Repository for evento data access."""

import logging
from typing import List, Dict, Any, Optional
from bson import ObjectId
from datetime import datetime
from pymongo import UpdateOne

from app.repositories.base_repository import BaseRepository
from app.exceptions import NotFoundException, DatabaseException
from app.utils.json_utils import convert_to_json

logger = logging.getLogger(__name__)


class EventoRepository(BaseRepository):
    """Repository for evento data access operations."""

    async def find_by_id(self, id: str) -> Optional[Dict[str, Any]]:
        """
        Find an evento by ID.

        Args:
            id: The evento ID

        Returns:
            The evento document or None if not found
        """
        try:
            if not ObjectId.is_valid(id):
                return None

            evento = await self.collection.find_one({"_id": ObjectId(id)})
            return convert_to_json(evento) if evento else None
        except Exception as e:
            logger.error(f"Error finding evento by ID {id}: {e}")
            raise DatabaseException(f"Error finding evento: {str(e)}")

    async def find_all(
        self,
        filter_query: Optional[Dict[str, Any]] = None,
        skip: int = 0,
        limit: int = 100,
        sort: Optional[Dict[str, int]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Find all eventos matching the filter.

        Args:
            filter_query: MongoDB filter query
            skip: Number of documents to skip
            limit: Maximum number of documents to return
            sort: Sort specification

        Returns:
            List of evento documents
        """
        try:
            cursor = self.collection.find(filter_query or {})

            if sort:
                cursor = cursor.sort(list(sort.items()))

            cursor = cursor.skip(skip).limit(limit)
            eventos = await cursor.to_list(length=None)

            return convert_to_json(eventos)
        except Exception as e:
            logger.error(f"Error finding eventos: {e}")
            raise DatabaseException(f"Error finding eventos: {str(e)}")

    async def count(self, filter_query: Optional[Dict[str, Any]] = None) -> int:
        """
        Count eventos matching the filter.

        Args:
            filter_query: MongoDB filter query

        Returns:
            Number of matching eventos
        """
        try:
            return await self.collection.count_documents(filter_query or {})
        except Exception as e:
            logger.error(f"Error counting eventos: {e}")
            raise DatabaseException(f"Error counting eventos: {str(e)}")

    async def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new evento.

        Args:
            data: Evento data

        Returns:
            The created evento document
        """
        try:
            # Add timestamps
            now = datetime.now()
            data["importado_em"] = now
            data["atualizado_em"] = now
            data["origem"] = data.get("origem", "api")

            result = await self.collection.insert_one(data)
            novo_evento = await self.collection.find_one({"_id": result.inserted_id})

            return convert_to_json(novo_evento)
        except Exception as e:
            logger.error(f"Error creating evento: {e}")
            raise DatabaseException(f"Error creating evento: {str(e)}")

    async def update(
        self, id: str, data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Update an evento by ID.

        Args:
            id: The evento ID
            data: Update data

        Returns:
            The updated evento document or None if not found
        """
        try:
            if not ObjectId.is_valid(id):
                return None

            # Add update timestamp
            data["atualizado_em"] = datetime.now()

            result = await self.collection.update_one(
                {"_id": ObjectId(id)}, {"$set": data}
            )

            if result.matched_count == 0:
                return None

            evento_atualizado = await self.collection.find_one({"_id": ObjectId(id)})
            return convert_to_json(evento_atualizado)
        except Exception as e:
            logger.error(f"Error updating evento {id}: {e}")
            raise DatabaseException(f"Error updating evento: {str(e)}")

    async def delete(self, id: str) -> bool:
        """
        Delete an evento by ID.

        Args:
            id: The evento ID

        Returns:
            True if deleted, False if not found
        """
        try:
            if not ObjectId.is_valid(id):
                return False

            result = await self.collection.delete_one({"_id": ObjectId(id)})
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"Error deleting evento {id}: {e}")
            raise DatabaseException(f"Error deleting evento: {str(e)}")

    async def exists(self, filter_query: Dict[str, Any]) -> bool:
        """
        Check if an evento exists.

        Args:
            filter_query: MongoDB filter query

        Returns:
            True if exists, False otherwise
        """
        try:
            count = await self.collection.count_documents(filter_query, limit=1)
            return count > 0
        except Exception as e:
            logger.error(f"Error checking evento existence: {e}")
            raise DatabaseException(f"Error checking evento existence: {str(e)}")

    async def bulk_upsert(self, eventos: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Perform bulk upsert operations for multiple eventos.

        Args:
            eventos: List of evento data

        Returns:
            Dictionary with operation counts
        """
        try:
            if not eventos:
                return {"inserted": 0, "updated": 0, "total": 0}

            operations = []
            for evento in eventos:
                # Add timestamp
                evento["atualizado_em"] = datetime.now()

                # Build unique key filter: nome_evento is required, datas_realizacao is optional
                filter_query = {"nome_evento": evento.get("nome_evento")}

                # Add datas_realizacao to unique key if present
                if "datas_realizacao" in evento and evento["datas_realizacao"]:
                    filter_query["datas_realizacao"] = evento["datas_realizacao"]

                operations.append(
                    UpdateOne(filter_query, {"$set": evento}, upsert=True)
                )

            if operations:
                result = await self.collection.bulk_write(operations)
                return {
                    "inserted": result.upserted_count,
                    "updated": result.modified_count,
                    "total": len(operations),
                }

            return {"inserted": 0, "updated": 0, "total": 0}
        except Exception as e:
            logger.error(f"Error in bulk upsert: {e}")
            raise DatabaseException(f"Error in bulk upsert: {str(e)}")
