import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.eventos import router as eventos_router
from app.api.sync import router as sync_router
from app.api.scrape import router as scrape_router
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=not is_wildcard,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Requested-With"],
)

app.include_router(eventos_router)
app.include_router(sync_router)
app.include_router(scrape_router)


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, exc: RuntimeError):
    if "Database not connected" in str(exc) or "MongoDB" in str(exc):
        return JSONResponse(status_code=503, content={"detail": "Database unavailable"})
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
async def readiness_check():
    if database.db is None:
        return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "database not connected"})
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
