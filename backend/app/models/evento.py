import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class Percurso(BaseModel):
    local_largada: str
    trajeto: str | None = None


class Kit(BaseModel):
    nome: str
    itens: list[str] = []
    local_retirada: str | None = None
    data_retirada: datetime | None = None


class EventoResponse(BaseModel):
    id: str = Field(alias="_id")
    nome_evento: str
    datas_realizacao: list[datetime] = []
    cidade: str = ""
    estado: str = ""
    organizador: str = ""
    site_coleta: str = ""
    data_coleta: datetime | None = None
    distancias: str = ""
    horario: str | None = None
    url_inscricao: str | None = None
    url_imagem: str | None = None
    categoria: str | None = None
    link_edital: str | None = None
    categorias_premiadas: str | None = None
    preco: str | None = None
    precos_entries: list[Any] | None = None
    patrocinado: bool = False
    percurso: Percurso | None = None
    kits: list[Kit] | None = None

    model_config = {"populate_by_name": True}


class EventoCreate(BaseModel):
    nome_evento: str
    datas_realizacao: list[datetime]
    cidade: str
    estado: str = "PB"
    organizador: str = ""
    site_coleta: str = ""
    data_coleta: datetime = Field(default_factory=datetime.now)
    distancias: str = ""
    horario: str | None = None
    url_inscricao: str | None = None
    url_imagem: str | None = None
    categoria: str | None = None
    link_edital: str | None = None
    categorias_premiadas: str | None = None
    preco: str | None = None
    precos_entries: list[Any] | None = None
    patrocinado: bool = False
    percurso: Percurso | None = None
    kits: list[Kit] | None = None

    @field_validator("horario")
    @classmethod
    def validate_horario(cls, v: str | None) -> str | None:
        if v is not None and not re.match(r"^\d{2}:\d{2}$", v):
            raise ValueError("horario must match HH:MM format")
        return v


class EventoUpdate(BaseModel):
    nome_evento: str | None = None
    datas_realizacao: list[datetime] | None = None
    cidade: str | None = None
    estado: str | None = None
    organizador: str | None = None
    site_coleta: str | None = None
    distancias: str | None = None
    horario: str | None = None
    url_inscricao: str | None = None
    url_imagem: str | None = None
    categoria: str | None = None
    link_edital: str | None = None
    categorias_premiadas: str | None = None
    preco: str | None = None
    precos_entries: list[Any] | None = None
    patrocinado: bool | None = None
    percurso: Percurso | None = None
    kits: list[Kit] | None = None

    @field_validator("horario")
    @classmethod
    def validate_horario(cls, v: str | None) -> str | None:
        if v is not None and not re.match(r"^\d{2}:\d{2}$", v):
            raise ValueError("horario must match HH:MM format")
        return v

    @model_validator(mode="before")
    @classmethod
    def check_at_least_one_field(cls, values: dict) -> dict:
        if not any(v is not None for v in values.values()):
            raise ValueError("At least one field must be provided")
        return values
