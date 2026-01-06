# Clean Architecture - Backend Structure

## Overview

This backend follows **Clean Architecture** principles with clear separation of concerns across different layers. Each layer has a specific responsibility and depends only on layers below it.

## Architecture Layers

```
┌─────────────────────────────────────────────────────────────┐
│                    API Layer (Controllers)                   │
│                   app/api/eventos.py                         │
│          Handles HTTP requests/responses                     │
└──────────────────────┬──────────────────────────────────────┘
                       │ depends on
┌──────────────────────▼──────────────────────────────────────┐
│                   Service Layer                              │
│              app/services/evento_service.py                  │
│          Business logic and orchestration                    │
└──────────────────────┬──────────────────────────────────────┘
                       │ depends on
┌──────────────────────▼──────────────────────────────────────┐
│                 Repository Layer                             │
│           app/repositories/evento_repository.py              │
│          Data access and persistence logic                   │
└──────────────────────┬──────────────────────────────────────┘
                       │ depends on
┌──────────────────────▼──────────────────────────────────────┐
│                   Database Layer                             │
│                app/core/database.py                          │
│            MongoDB connection management                     │
└─────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
backend/
├── app/
│   ├── api/                    # API endpoints (controllers)
│   │   ├── __init__.py
│   │   └── eventos.py          # Evento endpoints
│   │
│   ├── core/                   # Core functionality
│   │   ├── __init__.py
│   │   ├── config.py           # Configuration settings
│   │   ├── database.py         # Database connection
│   │   └── dependencies.py     # Dependency injection
│   │
│   ├── exceptions/             # Custom exceptions
│   │   ├── __init__.py
│   │   └── base_exceptions.py  # Base exception classes
│   │
│   ├── middlewares/            # Middleware components
│   │   ├── __init__.py
│   │   └── error_handler.py    # Global error handling
│   │
│   ├── models/                 # Domain models (entities)
│   │   ├── __init__.py
│   │   └── evento.py           # Evento domain model
│   │
│   ├── repositories/           # Data access layer
│   │   ├── __init__.py
│   │   ├── base_repository.py  # Base repository interface
│   │   └── evento_repository.py # Evento repository
│   │
│   ├── schemas/                # DTOs (Data Transfer Objects)
│   │   ├── __init__.py
│   │   └── evento_schemas.py   # Evento schemas for API
│   │
│   ├── services/               # Business logic layer
│   │   ├── __init__.py
│   │   └── evento_service.py   # Evento business logic
│   │
│   └── utils/                  # Utility functions
│       ├── __init__.py
│       ├── json_utils.py       # JSON conversion utilities
│       └── pagination_utils.py # Pagination helpers
│
├── data_collection/            # Data collection scripts
│   ├── scraper_brasilcorrida.py
│   ├── scraper_brasilquecorre.py
│   └── import_and_sync_to_atlas.py
│
├── logs/                       # Log files
├── main.py                     # Application entry point
├── requirements.txt            # Python dependencies
└── README.md                   # Documentation
```

## Layer Responsibilities

### 1. API Layer (`app/api/`)
- **Responsibility**: Handle HTTP requests and responses
- **Contains**: Route definitions, request/response models
- **Dependencies**: Service layer, schemas
- **Rules**:
  - No business logic
  - No direct database access
  - Use dependency injection for services
  - Handle only HTTP-specific concerns

### 2. Service Layer (`app/services/`)
- **Responsibility**: Business logic and orchestration
- **Contains**: Business rules, validation, coordination
- **Dependencies**: Repository layer, schemas, exceptions
- **Rules**:
  - No HTTP/API concerns
  - No direct database access
  - Coordinate between repositories
  - Throw custom exceptions

### 3. Repository Layer (`app/repositories/`)
- **Responsibility**: Data access abstraction
- **Contains**: CRUD operations, query logic
- **Dependencies**: Database, utils
- **Rules**:
  - No business logic
  - Abstract database details
  - Return plain dictionaries
  - Handle database-specific exceptions

### 4. Schema Layer (`app/schemas/`)
- **Responsibility**: Data transfer objects (DTOs)
- **Contains**: Pydantic models for API contracts
- **Dependencies**: None (pure data models)
- **Rules**:
  - Define API input/output structure
  - Separate from domain models
  - Include validation rules

### 5. Model Layer (`app/models/`)
- **Responsibility**: Domain entities
- **Contains**: Core business objects
- **Dependencies**: Minimal
- **Rules**:
  - Represent business concepts
  - Can contain domain logic
  - Independent of persistence

### 6. Core Layer (`app/core/`)
- **Responsibility**: Infrastructure and configuration
- **Contains**: Database, config, dependency injection
- **Dependencies**: Settings, external libraries
- **Rules**:
  - Manage infrastructure concerns
  - Provide shared utilities
  - Handle application lifecycle

## Key Design Patterns

### 1. Dependency Injection
```python
# In app/core/dependencies.py
async def get_evento_service() -> EventoService:
    repository = await DependencyContainer.get_evento_repository()
    return EventoService(repository)

# In API endpoints
@router.get("/")
async def list_eventos(service: EventoService = Depends(get_evento_service)):
    return await service.listar_eventos(...)
```

### 2. Repository Pattern
```python
# Abstract data access
class BaseRepository(ABC):
    async def find_by_id(self, id: str) -> Optional[Dict]:
        pass

# Concrete implementation
class EventoRepository(BaseRepository):
    async def find_by_id(self, id: str) -> Optional[Dict]:
        # MongoDB-specific implementation
        pass
```

### 3. Exception Handling
```python
# Custom exceptions
class NotFoundException(AppException):
    def __init__(self, message: str = "Resource not found"):
        super().__init__(message=message, status_code=404)

# Global exception handlers
app.add_exception_handler(AppException, app_exception_handler)
```

## Benefits of This Architecture

1. **Separation of Concerns**: Each layer has a single, well-defined responsibility
2. **Testability**: Easy to unit test each layer in isolation
3. **Maintainability**: Changes in one layer don't affect others
4. **Scalability**: Easy to add new features following the same pattern
5. **Flexibility**: Can swap implementations (e.g., change database) without affecting business logic
6. **Readability**: Clear structure makes code easy to understand

## Adding New Features

To add a new resource (e.g., "Users"):

1. **Schema**: Create `app/schemas/user_schemas.py` with DTOs
2. **Repository**: Create `app/repositories/user_repository.py` for data access
3. **Service**: Create `app/services/user_service.py` for business logic
4. **API**: Create `app/api/users.py` for endpoints
5. **Register**: Add router in `main.py`

## Best Practices

1. **Always use dependency injection** for services and repositories
2. **Throw custom exceptions** instead of returning None or error codes
3. **Keep layers independent** - don't skip layers
4. **Use schemas for API contracts** - separate from domain models
5. **Log appropriately** - errors in services, info in API layer
6. **Document endpoints** with docstrings and type hints
7. **Handle errors globally** with exception handlers

## Testing Strategy

```
Unit Tests:
- Repositories: Test database operations with mock database
- Services: Test business logic with mock repositories
- APIs: Test endpoints with mock services

Integration Tests:
- Test full flow from API to database

End-to-End Tests:
- Test complete user scenarios
```

## Migration Notes

The previous architecture mixed concerns (service layer doing data access). The new architecture:
- **Extracted** data access logic into repositories
- **Separated** DTOs (schemas) from domain models
- **Added** dependency injection for better testability
- **Implemented** global exception handling
- **Improved** error messages and logging
