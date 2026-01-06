# Corre PB - Backend API

A scalable and well-architected FastAPI backend for managing running events in Paraíba, Brazil.

## 🏗️ Architecture

This project follows **Clean Architecture** principles with clear separation of concerns:

- **API Layer** (`app/api/`): HTTP endpoints and request/response handling
- **Service Layer** (`app/services/`): Business logic and orchestration
- **Repository Layer** (`app/repositories/`): Data access abstraction
- **Schema Layer** (`app/schemas/`): DTOs (Data Transfer Objects) for API contracts
- **Model Layer** (`app/models/`): Domain entities
- **Core Layer** (`app/core/`): Configuration, database, and dependency injection

See [ARCHITECTURE.md](./ARCHITECTURE.md) for detailed documentation.

## 📁 Project Structure

```
backend/
├── app/
│   ├── api/                    # API endpoints (controllers)
│   ├── core/                   # Configuration & infrastructure
│   ├── exceptions/             # Custom exception classes
│   ├── importers/              # Data import modules
│   ├── middlewares/            # Middleware components
│   ├── models/                 # Domain models
│   ├── repositories/           # Data access layer
│   ├── schemas/                # DTOs for API
│   ├── scrapers/               # Web scraping modules
│   ├── services/               # Business logic
│   └── utils/                  # Utility functions
├── data_collection/            # Legacy data collection scripts
├── tests/
│   ├── unit/                   # Unit tests
│   └── integration/            # Integration tests
├── logs/                       # Log files
├── main.py                     # Application entry point
├── requirements.txt            # Python dependencies
├── pyproject.toml              # Project configuration
└── README.md                   # This file
```

## 🚀 Getting Started

### Prerequisites

- Python 3.10+ (tested with 3.12)
- MongoDB (local or Atlas)

### Installation

1. **Create and activate a virtual environment:**

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

2. **Install dependencies:**

```bash
pip install -r requirements.txt
```

3. **Configure environment variables:**

Create a `.env` file in the backend directory:

```env
# API Configuration
API_HOST=0.0.0.0
API_PORT=8181
API_DEBUG=True

# Database Configuration
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB_NAME=correpb

# Logging
LOG_LEVEL=INFO

# Optional: Remote MongoDB (Atlas)
MONGODB_REMOTE_URI=mongodb+srv://...
```

4. **Start the API:**

```bash
# From the backend directory
python main.py

# Or using uvicorn directly
uvicorn main:app --host 0.0.0.0 --port 8181 --reload
```

The API will be available at:
- **API**: http://localhost:8181
- **Interactive Docs**: http://localhost:8181/docs
- **Alternative Docs**: http://localhost:8181/redoc

## 🧪 Testing

Run tests with pytest:

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test types
pytest -m unit          # Unit tests only
pytest -m integration   # Integration tests only

# Run specific test file
pytest tests/unit/test_evento_service.py

# Run with verbose output
pytest -v
```

Coverage report will be generated in `htmlcov/index.html`.

## 📚 API Endpoints

### Eventos

- `GET /api/v1/eventos/` - List eventos with filters and pagination
  - Query params: `estado`, `cidade`, `nome_evento`, `status`, `ordenar_por`, `ordem`
- `GET /api/v1/eventos/sem-paginacao` - List eventos without pagination
  - Query params: `limit`
- `GET /api/v1/eventos/{id}` - Get a specific evento by ID

### Health & Info

- `GET /` - Root endpoint with API info
- `GET /health` - Health check endpoint

## 🔧 Development

### Code Style

The project follows PEP 8 style guidelines. Key conventions:

- Use type hints for all function parameters and return values
- Document all classes and functions with docstrings
- Keep functions small and focused
- Follow SOLID principles

### Adding New Features

To add a new resource (e.g., "Users"):

1. **Schema**: Create `app/schemas/user_schemas.py` with DTOs
2. **Repository**: Create `app/repositories/user_repository.py` for data access
3. **Service**: Create `app/services/user_service.py` for business logic
4. **API**: Create `app/api/users.py` for endpoints
5. **Tests**: Add unit tests in `tests/unit/`
6. **Register**: Add router in `main.py`

### Error Handling

The application uses custom exceptions with global error handlers:

```python
from app.exceptions import NotFoundException, ValidationException

# In your service
raise NotFoundException("Evento not found")

# In your business logic
raise ValidationException("Invalid data", details={"field": "error"})
```

## 🐳 Docker

Build and run with Docker:

```bash
# From the backend directory
docker build -t correpb-api .
docker run -p 8181:8181 --env-file .env correpb-api
```

Or use docker-compose from the root:

```bash
docker-compose up backend
```

## 📊 Database Schema

### Eventos Collection

| Field | Type | Description |
|-------|------|-------------|
| _id | ObjectId | Unique identifier |
| nome_evento | string | Event name |
| datas_realizacao | array[datetime] | Event dates |
| cidade | string | City |
| estado | string | State |
| organizador | string | Organizer |
| distancias | string | Available distances |
| url_inscricao | string | Registration URL |
| url_imagem | string | Event image URL |
| categorias_premiadas | string | Prize categories |
| site_coleta | string | Source website |
| data_coleta | datetime | Collection date |
| importado_em | datetime | Import timestamp |
| atualizado_em | datetime | Last update timestamp |
| origem | string | Data origin (api, scraper, etc) |

## 🤝 Contributing

1. Follow the existing code structure and patterns
2. Write tests for new features
3. Update documentation when adding new functionality
4. Ensure all tests pass before committing
5. Follow clean architecture principles

## 📝 License

[Add your license here]

## 📧 Contact

[Add contact information]
