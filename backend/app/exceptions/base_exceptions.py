"""Base exception classes for the application."""

from typing import Any, Optional


class AppException(Exception):
    """Base exception class for application errors."""

    def __init__(
        self,
        message: str = "An error occurred",
        status_code: int = 500,
        details: Optional[Any] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(self.message)


class NotFoundException(AppException):
    """Exception raised when a resource is not found."""

    def __init__(
        self,
        message: str = "Resource not found",
        details: Optional[Any] = None,
    ):
        super().__init__(message=message, status_code=404, details=details)


class ValidationException(AppException):
    """Exception raised when validation fails."""

    def __init__(
        self,
        message: str = "Validation error",
        details: Optional[Any] = None,
    ):
        super().__init__(message=message, status_code=422, details=details)


class DatabaseException(AppException):
    """Exception raised when a database error occurs."""

    def __init__(
        self,
        message: str = "Database error",
        details: Optional[Any] = None,
    ):
        super().__init__(message=message, status_code=500, details=details)


class DuplicateException(AppException):
    """Exception raised when trying to create a duplicate resource."""

    def __init__(
        self,
        message: str = "Resource already exists",
        details: Optional[Any] = None,
    ):
        super().__init__(message=message, status_code=409, details=details)
