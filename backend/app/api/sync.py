from fastapi import APIRouter, Security

from app.core.auth import verify_api_key
from app.services.bucket_sync import is_sync_in_progress, trigger_bucket_sync

router = APIRouter(prefix="/api/v1", tags=["sync"])


@router.get("/sync-bucket/status")
async def sync_status(_: str = Security(verify_api_key)):
    return {"in_progress": is_sync_in_progress()}


@router.post("/sync-bucket")
async def sync_bucket(_: str = Security(verify_api_key)):
    result = await trigger_bucket_sync()
    return result
