from fastapi import HTTPException
from pydantic import BaseModel


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None


def not_found(detail: str = "Evento não encontrado") -> HTTPException:
    return HTTPException(status_code=404, detail=detail)


def bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


def unauthorized(detail: str = "Chave API inválida") -> HTTPException:
    return HTTPException(status_code=401, detail=detail)


def conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=409, detail=detail)


def internal(detail: str) -> HTTPException:
    return HTTPException(status_code=500, detail=detail)


def service_unavailable(detail: str = "Serviço indisponível") -> HTTPException:
    return HTTPException(status_code=503, detail=detail)
