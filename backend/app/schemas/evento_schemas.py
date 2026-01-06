"""Schemas (DTOs) for evento endpoints."""

from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from datetime import datetime


class EventoBaseSchema(BaseModel):
    """Base schema for evento data."""
    nome_evento: str = Field(..., description="Nome do evento")
    datas_realizacao: List[datetime] = Field(..., description="Datas de realização do evento")
    cidade: str = Field(..., description="Cidade do evento")
    estado: str = Field(..., description="Estado do evento")
    organizador: str = Field(..., description="Organizador do evento")
    distancias: str = Field(..., description="Distâncias do evento")
    url_inscricao: str = Field(..., description="URL de inscrição")
    url_imagem: Optional[str] = Field(None, description="URL da imagem do evento")
    categorias_premiadas: Optional[str] = Field(None, description="Categorias premiadas")


class EventoCreateSchema(EventoBaseSchema):
    """Schema for creating a new evento."""
    site_coleta: str = Field(..., description="Site de coleta dos dados")
    data_coleta: datetime = Field(default_factory=datetime.now, description="Data de coleta")


class EventoUpdateSchema(BaseModel):
    """Schema for updating an evento."""
    nome_evento: Optional[str] = Field(None, description="Nome do evento")
    datas_realizacao: Optional[List[datetime]] = Field(None, description="Datas de realização")
    cidade: Optional[str] = Field(None, description="Cidade do evento")
    estado: Optional[str] = Field(None, description="Estado do evento")
    organizador: Optional[str] = Field(None, description="Organizador do evento")
    distancias: Optional[str] = Field(None, description="Distâncias do evento")
    url_inscricao: Optional[str] = Field(None, description="URL de inscrição")
    url_imagem: Optional[str] = Field(None, description="URL da imagem")
    site_coleta: Optional[str] = Field(None, description="Site de coleta")
    data_coleta: Optional[datetime] = Field(None, description="Data de coleta")
    categorias_premiadas: Optional[str] = Field(None, description="Categorias premiadas")


class EventoResponseSchema(EventoBaseSchema):
    """Schema for evento response."""
    id: str = Field(..., alias="_id", description="ID do evento")
    site_coleta: str = Field(..., description="Site de coleta")
    data_coleta: datetime = Field(..., description="Data de coleta")
    importado_em: Optional[datetime] = Field(None, description="Data de importação")
    atualizado_em: Optional[datetime] = Field(None, description="Data de atualização")
    origem: Optional[str] = Field(None, description="Origem dos dados")

    model_config = ConfigDict(
        populate_by_name=True,
        json_encoders={
            datetime: lambda dt: dt.isoformat()
        }
    )


class EventoListFilterSchema(BaseModel):
    """Schema for filtering eventos."""
    estado: Optional[str] = Field(None, description="Filtrar por estado")
    cidade: Optional[str] = Field(None, description="Filtrar por cidade")
    nome_evento: Optional[str] = Field(None, description="Filtrar por nome")
    status: Optional[str] = Field(None, description="Filtrar por status (pendentes, realizados, todos)")
    ordenar_por: str = Field("datas_realizacao", description="Campo para ordenação")
    ordem: int = Field(-1, description="Ordem de classificação (1: crescente, -1: decrescente)")
