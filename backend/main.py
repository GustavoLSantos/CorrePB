import uvicorn
import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi_pagination import add_pagination

from app.core.config import settings
from app.core.database import Database
from app.api.eventos import router as eventos_router
from app.exceptions import AppException
from app.middlewares import (
    app_exception_handler,
    validation_exception_handler,
    http_exception_handler,
    unhandled_exception_handler,
)

load_dotenv()

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format=settings.LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join("logs", "api.log")),
    ],
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        await Database.connect()
        logger.info("Database connection established")
    except Exception as e:
        logger.error(f"Error connecting to database: {e}")

    yield

    # Shutdown
    await Database.close()
    logger.info("Database connection closed")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.PROJECT_DESCRIPTION,
    version=settings.VERSION,
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add exception handlers
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# Add pagination
add_pagination(app)

# Add routers
app.include_router(eventos_router, prefix="/api/v1/eventos", tags=["eventos"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Welcome to Corre PB API!",
        "version": settings.VERSION,
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": settings.VERSION,
    }


if __name__ == "__main__":
    # Ensure logs directory exists
    os.makedirs("logs", exist_ok=True)

    # Start server
    uvicorn.run(
        "main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.API_DEBUG,
    )
