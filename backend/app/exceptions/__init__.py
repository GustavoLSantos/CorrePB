"""Custom exceptions for the application."""

from app.exceptions.base_exceptions import (
    AppException,
    NotFoundException,
    ValidationException,
    DatabaseException,
    DuplicateException,
)

__all__ = [
    "AppException",
    "NotFoundException",
    "ValidationException",
    "DatabaseException",
    "DuplicateException",
]
