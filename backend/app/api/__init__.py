from fastapi import APIRouter

from app.api.eventos import router as eventos_router
from app.api.scrape import router as scrape_router
from app.api.sync import router as sync_router

api_router = APIRouter()

api_router.include_router(eventos_router)
api_router.include_router(scrape_router)
api_router.include_router(sync_router)

__all__ = ["api_router"]
