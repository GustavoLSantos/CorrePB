from fastapi import APIRouter, Depends, Query
from typing import Optional
from datetime import datetime
from fastapi_pagination import Page, Params

from app.schemas import EventoResponseSchema
from app.services.evento_service import EventoService
from app.core.dependencies import get_evento_service

router = APIRouter()


@router.get("/", response_model=Page[EventoResponseSchema])
async def listar_eventos(
    estado: Optional[str] = None,
    cidade: Optional[str] = None,
    nome_evento: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    ordenar_por: str = "datas_realizacao",
    ordem: int = -1,
    params: Params = Depends(),
    service: EventoService = Depends(get_evento_service),
):
    """
    List eventos with filters, sorting, and pagination.

    Args:
        estado: Filter by state
        cidade: Filter by city
        nome_evento: Filter by event name (regex search)
        status_filter: Filter by status ("pendentes", "realizados", or "todos")
        ordenar_por: Field to sort by
        ordem: Sort order (1: ascending, -1: descending)
        params: Pagination parameters
        service: EventoService dependency

    Returns:
        Paginated list of eventos
    """
    # Build filter
    filtro = {}

    if estado:
        filtro["estado"] = estado

    if cidade:
        filtro["cidade"] = cidade

    if nome_evento:
        filtro["nome_evento"] = {"$regex": nome_evento, "$options": "i"}

    # Filter by status (upcoming or past events)
    if status_filter:
        hoje = datetime.now()
        if status_filter == "pendentes":
            filtro["datas_realizacao"] = {"$gte": hoje}
        elif status_filter == "realizados":
            filtro["datas_realizacao"] = {"$lt": hoje}

    # Build sort specification
    order = {ordenar_por: ordem}

    # Get eventos
    return await service.listar_eventos(filtro, order, params)


@router.get("/sem-paginacao", response_model=list[EventoResponseSchema])
async def listar_eventos_sem_paginacao(
    limit: Optional[int] = Query(100, description="Maximum number of eventos to return"),
    service: EventoService = Depends(get_evento_service),
):
    """
    Return a list of eventos without pagination.
    Useful for getting data for filters or selections.

    Args:
        limit: Maximum number of eventos to return
        service: EventoService dependency

    Returns:
        List of eventos
    """
    return await service.listar_eventos_sem_paginacao(limit)


@router.get("/{id}", response_model=EventoResponseSchema)
async def obter_evento(
    id: str,
    service: EventoService = Depends(get_evento_service),
):
    """
    Get an evento by ID.

    Args:
        id: Evento ID
        service: EventoService dependency

    Returns:
        Evento data

    Raises:
        NotFoundException: If evento is not found
    """
    return await service.buscar_evento_por_id(id)
