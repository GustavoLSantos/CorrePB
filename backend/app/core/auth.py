from fastapi import Header, HTTPException

from app.core.config import settings


async def verify_api_key(x_api_key: str = Header(...)) -> str:
    if not settings.API_KEY:
        raise HTTPException(status_code=500, detail="API_KEY not configured")
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key


async def verify_scrapers_api_key(x_api_key: str = Header(...)) -> str:
    if not settings.SCRAPERS_API_KEY:
        raise HTTPException(
            status_code=500, detail="SCRAPERS_API_KEY not configured"
        )
    if x_api_key != settings.SCRAPERS_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key
