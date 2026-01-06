import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi_pagination import Params, Page

from app.repositories import EventoRepository
from app.schemas import (
    EventoCreateSchema,
    EventoUpdateSchema,
    EventoResponseSchema,
)
from app.exceptions import NotFoundException, ValidationException
from app.utils.pagination_utils import paginate_with_objectid_conversion

logger = logging.getLogger(__name__)


class EventoService:
    """Service for evento business logic."""

    def __init__(self, repository: EventoRepository):
        """Initialize service with repository."""
        self.repository = repository

    async def listar_eventos(
        self, filtro: Dict[str, Any], order: Dict[str, int], params: Params
    ) -> Page[EventoResponseSchema]:
        """
        List eventos with filters, sorting, and pagination.

        Args:
            filtro: Filter query
            order: Sort specification
            params: Pagination parameters

        Returns:
            Page of eventos
        """
        try:
            # Use the pagination utility
            return await paginate_with_objectid_conversion(
                self.repository.collection,
                query_filter=filtro,
                sort=order,
                params=params,
                model_class=EventoResponseSchema,
            )
        except Exception as e:
            logger.error(f"Error listing eventos: {e}")
            raise

    async def listar_eventos_sem_paginacao(
        self, limit: int = 100, filtro: Dict[str, Any] = None
    ) -> List[EventoResponseSchema]:
        """
        List eventos without pagination.

        Args:
            limit: Maximum number of eventos to return
            filtro: Filter query

        Returns:
            List of eventos
        """
        try:
            eventos = await self.repository.find_all(
                filter_query=filtro,
                limit=limit,
                sort={"datas_realizacao": -1},
            )
            return eventos
        except Exception as e:
            logger.error(f"Error listing eventos without pagination: {e}")
            raise

    async def buscar_evento_por_id(self, id: str) -> Optional[EventoResponseSchema]:
        """
        Find an evento by ID.

        Args:
            id: Evento ID

        Returns:
            Evento data or None if not found

        Raises:
            NotFoundException: If evento is not found
        """
        try:
            evento = await self.repository.find_by_id(id)

            if not evento:
                raise NotFoundException(f"Evento with ID {id} not found")

            return evento
        except NotFoundException:
            raise
        except Exception as e:
            logger.error(f"Error finding evento by ID {id}: {e}")
            raise

    async def criar_evento(
        self, evento: EventoCreateSchema
    ) -> EventoResponseSchema:
        """
        Create a new evento.

        Args:
            evento: Evento creation data

        Returns:
            Created evento

        Raises:
            ValidationException: If validation fails
        """
        try:
            # Convert schema to dict
            evento_dict = evento.model_dump()

            # Create evento
            novo_evento = await self.repository.create(evento_dict)

            return novo_evento
        except Exception as e:
            logger.error(f"Error creating evento: {e}")
            raise

    async def atualizar_evento(
        self, evento_id: str, evento: EventoUpdateSchema
    ) -> EventoResponseSchema:
        """
        Update an existing evento.

        Args:
            evento_id: ID of the evento to update
            evento: Update data

        Returns:
            Updated evento

        Raises:
            NotFoundException: If evento is not found
        """
        try:
            # Convert schema to dict, removing None values
            evento_dict = {
                k: v for k, v in evento.model_dump().items() if v is not None
            }

            if not evento_dict:
                raise ValidationException("No fields to update")

            # Update evento
            evento_atualizado = await self.repository.update(evento_id, evento_dict)

            if not evento_atualizado:
                raise NotFoundException(f"Evento with ID {evento_id} not found")

            return evento_atualizado
        except NotFoundException:
            raise
        except ValidationException:
            raise
        except Exception as e:
            logger.error(f"Error updating evento {evento_id}: {e}")
            raise

    async def excluir_evento(self, evento_id: str) -> bool:
        """
        Delete an evento.

        Args:
            evento_id: ID of the evento to delete

        Returns:
            True if deleted successfully

        Raises:
            NotFoundException: If evento is not found
        """
        try:
            deleted = await self.repository.delete(evento_id)

            if not deleted:
                raise NotFoundException(f"Evento with ID {evento_id} not found")

            return True
        except NotFoundException:
            raise
        except Exception as e:
            logger.error(f"Error deleting evento {evento_id}: {e}")
            raise

    async def importar_eventos(
        self, eventos: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """
        Import multiple eventos (upsert).

        Args:
            eventos: List of evento data

        Returns:
            Dictionary with operation counts
        """
        try:
            if not eventos:
                return {"inserted": 0, "updated": 0, "total": 0}

            return await self.repository.bulk_upsert(eventos)
        except Exception as e:
            logger.error(f"Error importing eventos: {e}")
            raise

    async def obter_estatisticas(self) -> Dict[str, Any]:
        """
        Get statistics about eventos.

        Returns:
            Dictionary with statistics
        """
        try:
            # Total eventos
            total_eventos = await self.repository.count()

            # This can be expanded with more statistics as needed
            return {
                "total_eventos": total_eventos,
            }
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            raise