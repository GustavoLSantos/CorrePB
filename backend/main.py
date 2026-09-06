import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    await database.connect()
    _ = cleanup_scraped_csvs(24.0)
    logger.info("Connected to MongoDB")
    yield
    await database.disconnect()
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


@app.get("/health")
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.API_DEBUG,
    )
