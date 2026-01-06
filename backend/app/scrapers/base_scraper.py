"""Base scraper class for web scraping."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Base class for all scrapers."""

    def __init__(self, source_name: str):
        """
        Initialize scraper.

        Args:
            source_name: Name of the data source
        """
        self.source_name = source_name
        self.logger = logging.getLogger(f"{__name__}.{source_name}")

    @abstractmethod
    async def scrape(self) -> List[Dict[str, Any]]:
        """
        Scrape data from the source.

        Returns:
            List of scraped evento data
        """
        pass

    def log_success(self, count: int):
        """Log successful scraping."""
        self.logger.info(f"Successfully scraped {count} eventos from {self.source_name}")

    def log_error(self, error: Exception):
        """Log scraping error."""
        self.logger.error(f"Error scraping from {self.source_name}: {str(error)}")
