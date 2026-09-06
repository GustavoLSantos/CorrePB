import hmac

from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader

from app.core.config import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _verify(expected: str, provided: str | None, not_configured_msg: str) -> str:
    if not expected:
        raise HTTPException(status_code=500, detail=not_configured_msg)
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return provided


async def verify_api_key(x_api_key: str | None = Depends(_api_key_header)) -> str:
    return _verify(settings.API_KEY, x_api_key, "API_KEY not configured")


async def verify_scrapers_api_key(x_api_key: str | None = Depends(_api_key_header)) -> str:
    return _verify(settings.SCRAPERS_API_KEY, x_api_key, "SCRAPERS_API_KEY not configured")
