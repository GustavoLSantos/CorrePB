from fastapi import APIRouter, Depends

from app.core.auth import verify_api_key
from app.services.bucket_sync import trigger_bucket_sync

router = APIRouter(prefix="/api/v1", tags=["sync"])


@router.post("/sync-bucket")
async def sync_bucket(_: str = Depends(verify_api_key)):
    result = await trigger_bucket_sync()
    return result
