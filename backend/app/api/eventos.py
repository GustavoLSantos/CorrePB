from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import verify_api_key
from app.core.database import database
from app.models.evento import EventoCreate, EventoResponse, EventoUpdate

router = APIRouter(prefix="/api/v1/eventos", tags=["eventos"])


async def _generate_id() -> str:
    now = datetime.now()
    prefix = now.strftime("%Y%m")
    collection = database.get_collection()

    last = await collection.find_one(
        {"_id": {"$regex": f"^{prefix}"}},
        sort=[("_id", -1)],
    )

    if last:
        seq = int(last["_id"][6:]) + 1
    else:
        seq = 1

    return f"{prefix}{seq:04d}"


@router.get("", response_model=list[EventoResponse])
async def list_eventos(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    estado: str | None = Query(None),
):
    collection = database.get_collection()
    query: dict = {}
    if estado:
        query["estado"] = estado.upper()

    skip = (page - 1) * size
    cursor = collection.find(query).sort("datas_realizacao", -1).skip(skip).limit(size)
    return [EventoResponse(**doc) async for doc in cursor]


@router.get("/{evento_id}", response_model=EventoResponse)
async def get_evento(evento_id: str):
    collection = database.get_collection()
    doc = await collection.find_one({"_id": evento_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Evento not found")
    return EventoResponse(**doc)


@router.post("", response_model=EventoResponse, status_code=201)
async def create_evento(
    evento: EventoCreate,
    _: str = Depends(verify_api_key),
):
    collection = database.get_collection()
    evento_id = await _generate_id()
    doc = evento.model_dump()
    doc["_id"] = evento_id
    await collection.insert_one(doc)
    return EventoResponse(**doc)


@router.patch("/{evento_id}", response_model=EventoResponse)
async def update_evento(
    evento_id: str,
    evento: EventoUpdate,
    _: str = Depends(verify_api_key),
):
    collection = database.get_collection()
    update_data = evento.model_dump(exclude_none=True)

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = await collection.find_one_and_update(
        {"_id": evento_id},
        {"$set": update_data},
        return_document=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Evento not found")
    return EventoResponse(**result)


@router.delete("/{evento_id}", status_code=204)
async def delete_evento(
    evento_id: str,
    _: str = Depends(verify_api_key),
):
    collection = database.get_collection()
    result = await collection.delete_one({"_id": evento_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Evento not found")
