"""Base importer class for data import operations."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class BaseImporter(ABC):
    """Base class for data importers."""

    def __init__(self, source_name: str):
        """
        Initialize importer.

        Args:
            source_name: Name of the data source
        """
        self.source_name = source_name
        self.logger = logging.getLogger(f"{__name__}.{source_name}")

    @abstractmethod
    async def import_data(self, data: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Import data to the database.

        Args:
            data: List of data to import

        Returns:
            Dictionary with import statistics
        """
        pass

    def log_success(self, stats: Dict[str, int]):
        """Log successful import."""
        self.logger.info(
            f"Import from {self.source_name} completed: "
            f"{stats.get('inserted', 0)} inserted, "
            f"{stats.get('updated', 0)} updated"
        )

    def log_error(self, error: Exception):
        """Log import error."""
        self.logger.error(f"Error importing from {self.source_name}: {str(error)}")
