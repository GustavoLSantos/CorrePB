"""Unit tests for EventoService."""

import pytest
from unittest.mock import AsyncMock

from app.services.evento_service import EventoService
from app.schemas import EventoUpdateSchema
from app.exceptions import NotFoundException, ValidationException


class TestEventoService:
    """Test cases for EventoService."""

    @pytest.fixture
    def mock_repository(self):
        """Create a mock repository."""
        repository = AsyncMock()
        return repository

    @pytest.fixture
    def service(self, mock_repository):
        """Create a service instance with mocked repository."""
        return EventoService(mock_repository)

    @pytest.mark.asyncio
    async def test_buscar_evento_por_id_success(self, service, mock_repository):
        """Test finding an evento by ID successfully."""
        # Arrange
        test_id = "507f1f77bcf86cd799439011"
        mock_evento = {
            "_id": test_id,
            "nome_evento": "Test Event",
            "cidade": "Test City",
        }
        mock_repository.find_by_id.return_value = mock_evento

        # Act
        result = await service.buscar_evento_por_id(test_id)

        # Assert
        assert result == mock_evento

    @pytest.mark.asyncio
    async def test_buscar_evento_por_id_not_found(self, service, mock_repository):
        """Test finding an evento by ID when not found."""
        # Arrange
        test_id = "507f1f77bcf86cd799439011"
        mock_repository.find_by_id.return_value = None

        # Act & Assert
        with pytest.raises(NotFoundException):
            await service.buscar_evento_por_id(test_id)

    @pytest.mark.asyncio
    async def test_excluir_evento_success(self, service, mock_repository):
        """Test deleting an evento successfully."""
        # Arrange
        test_id = "507f1f77bcf86cd799439011"
        mock_repository.delete.return_value = True

        # Act
        result = await service.excluir_evento(test_id)

        # Assert
        assert result is True

    @pytest.mark.asyncio
    async def test_atualizar_evento_no_fields(self, service):
        """Test updating an evento with no fields."""
        # Arrange
        test_id = "507f1f77bcf86cd799439011"
        update_data = EventoUpdateSchema()

        # Act & Assert
        with pytest.raises(ValidationException):
            await service.atualizar_evento(test_id, update_data)

    @pytest.mark.asyncio
    async def test_importar_eventos_empty_list(self, service, mock_repository):
        """Test importing an empty list of eventos."""
        # Arrange
        eventos = []

        # Act
        result = await service.importar_eventos(eventos)

        # Assert
        assert result == {"inserted": 0, "updated": 0, "total": 0}
