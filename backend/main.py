import logging
from pathlib import Path
from contextlib import asynccontextmanager

import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router
from app.core.config import settings
from app.core.database import database
from app.services.scraper_runner import cleanup_scraped_csvs

Path("logs").mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/api.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await database.connect()
        if database.db is not None:
            try:
                await database.db.command("ping")
            except Exception as e:
                logger.error(f"MongoDB ping failed: {e}")
                raise RuntimeError(f"MongoDB ping failed: {e}") from e
        await database.ensure_indexes()
        _ = cleanup_scraped_csvs(24.0)
        logger.info("Connected to MongoDB")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        raise
    yield
    try:
        await database.disconnect()
    except Exception as e:
        logger.warning(f"Error disconnecting MongoDB: {e}")
    logger.info("Disconnected from MongoDB")


app = FastAPI(
    title="Circuito API",
    description="API para criar, editar, excluir e listar os eventos de corrida",
    version="1.0.0",
    lifespan=lifespan,
)

cors_origins = settings.cors_origins_list
is_wildcard = len(cors_origins) == 1 and cors_origins[0] == "*"

app.add_middleware(GZipMiddleware, minimum_size=500)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=not is_wildcard,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Requested-With", "X-Request-Id"],
)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response

app.include_router(api_router)


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, exc: RuntimeError):
    if "Database not connected" in str(exc) or "MongoDB" in str(exc):
        return JSONResponse(status_code=503, content={"detail": "Banco de dados indisponível"})
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
async def readiness_check():
    if database.db is None:
        return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "banco não conectado"})
    try:
        await database.db.command("ping")
        return {"status": "ready"}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "not_ready", "reason": str(e)})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.API_DEBUG,
    )
