from datetime import datetime, timezone
from math import ceil

from fastapi import APIRouter, HTTPException, Query, Request, Security

from app.core.limiter import is_limited, limiter
from pymongo.errors import DuplicateKeyError

from app.core.auth import verify_api_key
from app.core.database import database
from app.core.errors import ErrorResponse
from app.models.evento import EventoCreate, EventoPageResponse, EventoResponse, EventoUpdate
from app.utils.search import build_search_regex

router = APIRouter(prefix="/api/v1/eventos", tags=["eventos"])

SEARCH_FIELDS = ["nome_evento", "cidade", "organizador"]


async def _generate_id() -> str:
    return await database.get_next_evento_id()


@router.get(
    "",
    response_model=EventoPageResponse,
    summary="Listar eventos",
    description="Lista eventos paginados, filtra por UF e busca textual em nome/cidade/organizador.",
)
async def list_eventos(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    estado: str | None = Query(None, min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$", description="UF com 2 letras"),
    q: str | None = Query(None, max_length=80, description="Busca em nome, cidade e organizador"),
):
    collection = database.get_collection()
    query: dict = {}
    if estado:
        query["estado"] = estado.upper()
    if q:
        pattern = build_search_regex(q)
        if pattern:
            query["$or"] = [
                {field: {"$regex": pattern, "$options": "i"}} for field in SEARCH_FIELDS
            ]
    total = await collection.count_documents(query)
    skip = (page - 1) * size
    cursor = collection.find(query).sort("datas_realizacao", -1).skip(skip).limit(size)
    eventos = [EventoResponse(**doc) async for doc in cursor]
    return EventoPageResponse(
        eventos=eventos,
        total=total,
        total_pages=ceil(total / size),
        page=page,
        size=size,
    )


@router.get(
    "/{evento_id}",
    response_model=EventoResponse,
    summary="Obter evento por ID",
    responses={404: {"model": ErrorResponse, "description": "Evento não encontrado"}},
)
async def get_evento(evento_id: str):
    collection = database.get_collection()
    doc = await collection.find_one({"_id": evento_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Evento não encontrado")
    return EventoResponse(**doc)


@router.post(
    "",
    response_model=EventoResponse,
    status_code=201,
    summary="Criar evento",
    responses={401: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
@limiter.limit("10/minute")
async def create_evento(
    request: Request,
    evento: EventoCreate,
    _: str = Security(verify_api_key),
):
    if is_limited(request, limit=10, window_s=60, prefix="create_evento"):
        raise HTTPException(status_code=429, detail="Muitas requisições, tente novamente mais tarde")
    collection = database.get_collection()
    # Retry em caso de colisão residual (legado / concorrência extrema)
    now = datetime.now(timezone.utc)
    last_exc: Exception | None = None
    for _ in range(3):
        evento_id = await _generate_id()
        doc = evento.model_dump()
        doc["_id"] = evento_id
        doc["created_at"] = now
        doc["updated_at"] = now
        try:
            await collection.insert_one(doc)
            return EventoResponse(**doc)
        except DuplicateKeyError as e:
            last_exc = e
            continue
    raise HTTPException(
        status_code=409, detail=f"Falha ao gerar ID único após 3 tentativas: {last_exc}"
    )


@router.patch(
    "/{evento_id}",
    response_model=EventoResponse,
    summary="Atualizar evento",
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def update_evento(
    evento_id: str,
    evento: EventoUpdate,
    _: str = Security(verify_api_key),
):
    collection = database.get_collection()
    update_data = evento.model_dump(exclude_none=True)

    if not update_data:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    campos_editados = [k for k in update_data if k != "campos_protegidos"]
    update_data["updated_at"] = datetime.now(timezone.utc)

    if "campos_protegidos" in update_data:
        update_ops: dict = {"$set": update_data}
    else:
        update_ops: dict = {"$set": update_data}
        if campos_editados:
            update_ops["$addToSet"] = {"campos_protegidos": {"$each": campos_editados}}

    result = await collection.find_one_and_update(
        {"_id": evento_id},
        update_ops,
        return_document=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Evento não encontrado")
    return EventoResponse(**result)


@router.delete(
    "/{evento_id}",
    status_code=204,
    summary="Remover evento",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def delete_evento(
    evento_id: str,
    _: str = Security(verify_api_key),
):
    collection = database.get_collection()
    result = await collection.delete_one({"_id": evento_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Evento não encontrado")
