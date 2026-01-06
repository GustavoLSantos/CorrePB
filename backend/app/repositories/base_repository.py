"""Base repository interface for common CRUD operations."""

from abc import ABC, abstractmethod
from typing import Generic, TypeVar, List, Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorCollection

T = TypeVar("T")


class BaseRepository(ABC, Generic[T]):
    """Base repository interface with common CRUD operations."""

    def __init__(self, collection: AsyncIOMotorCollection):
        """Initialize repository with collection."""
        self.collection = collection

    @abstractmethod
    async def find_by_id(self, id: str) -> Optional[Dict[str, Any]]:
        """Find a document by ID."""
        pass

    @abstractmethod
    async def find_all(
        self,
        filter_query: Optional[Dict[str, Any]] = None,
        skip: int = 0,
        limit: int = 100,
        sort: Optional[Dict[str, int]] = None,
    ) -> List[Dict[str, Any]]:
        """Find all documents matching the filter."""
        pass

    @abstractmethod
    async def count(self, filter_query: Optional[Dict[str, Any]] = None) -> int:
        """Count documents matching the filter."""
        pass

    @abstractmethod
    async def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new document."""
        pass

    @abstractmethod
    async def update(
        self, id: str, data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Update a document by ID."""
        pass

    @abstractmethod
    async def delete(self, id: str) -> bool:
        """Delete a document by ID."""
        pass

    @abstractmethod
    async def exists(self, filter_query: Dict[str, Any]) -> bool:
        """Check if a document exists."""
        pass
