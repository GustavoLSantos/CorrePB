"""Dependency injection container and factories."""

from functools import lru_cache
from motor.motor_asyncio import AsyncIOMotorCollection

from app.core.database import Database
from app.repositories import EventoRepository
from app.services.evento_service import EventoService


class DependencyContainer:
    """Container for managing application dependencies."""

    _evento_repository: EventoRepository = None
    _evento_service: EventoService = None

    @classmethod
    async def get_evento_repository(cls) -> EventoRepository:
        """Get or create EventoRepository instance."""
        if cls._evento_repository is None:
            collection = await Database.get_collection("eventos")
            cls._evento_repository = EventoRepository(collection)
        return cls._evento_repository

    @classmethod
    async def get_evento_service(cls) -> EventoService:
        """Get or create EventoService instance."""
        if cls._evento_service is None:
            repository = await cls.get_evento_repository()
            cls._evento_service = EventoService(repository)
        return cls._evento_service

    @classmethod
    def reset(cls):
        """Reset all cached dependencies (useful for testing)."""
        cls._evento_repository = None
        cls._evento_service = None


# FastAPI dependency functions
async def get_evento_service() -> EventoService:
    """
    FastAPI dependency for EventoService.

    Returns:
        EventoService instance
    """
    return await DependencyContainer.get_evento_service()
