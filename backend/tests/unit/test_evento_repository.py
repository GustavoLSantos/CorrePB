"""Unit tests for EventoRepository."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from bson import ObjectId

from app.repositories.evento_repository import EventoRepository


class TestEventoRepository:
    """Test cases for EventoRepository."""

    @pytest.fixture
    def mock_collection(self):
        """Create a mock MongoDB collection."""
        collection = AsyncMock()
        return collection

    @pytest.fixture
    def repository(self, mock_collection):
        """Create a repository instance with mocked collection."""
        return EventoRepository(mock_collection)

    @pytest.mark.asyncio
    async def test_find_by_id_success(self, repository, mock_collection):
        """Test finding an evento by valid ID."""
        # Arrange
        test_id = str(ObjectId())
        mock_evento = {
            "_id": ObjectId(test_id),
            "nome": "Test Event",
            "cidade": "Test City",
        }
        mock_collection.find_one.return_value = mock_evento

        # Act
        result = await repository.find_by_id(test_id)

        # Assert
        assert result is not None
        assert result["nome"] == "Test Event"
        mock_collection.find_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_find_by_id_invalid_id(self, repository):
        """Test finding an evento with invalid ID."""
        # Arrange
        invalid_id = "invalid-id"

        # Act
        result = await repository.find_by_id(invalid_id)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_count_success(self, repository, mock_collection):
        """Test counting eventos."""
        # Arrange
        mock_collection.count_documents.return_value = 10

        # Act
        result = await repository.count()

        # Assert
        assert result == 10
        mock_collection.count_documents.assert_called_once_with({})

    @pytest.mark.asyncio
    async def test_exists_true(self, repository, mock_collection):
        """Test checking if an evento exists (true case)."""
        # Arrange
        filter_query = {"nome": "Test Event"}
        mock_collection.count_documents.return_value = 1

        # Act
        result = await repository.exists(filter_query)

        # Assert
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_success(self, repository, mock_collection):
        """Test deleting an evento successfully."""
        # Arrange
        test_id = str(ObjectId())
        mock_result = MagicMock()
        mock_result.deleted_count = 1
        mock_collection.delete_one.return_value = mock_result

        # Act
        result = await repository.delete(test_id)

        # Assert
        assert result is True
