import json
import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.utils.price_formatting import formatar_lista_precos


class Percurso(BaseModel):
    local_largada: str
    trajeto: str | None = None


class Kit(BaseModel):
    nome: str
    itens: list[str] = []
    local_retirada: str | None = None
    data_retirada: datetime | None = None


MESES_PT = [
    "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


class EventoResponse(BaseModel):
    id: str = Field(alias="_id")
    nome_evento: str
    datas_realizacao: list[datetime] = Field(default=[], exclude=True)
    data_realizacao: str = ""
    cidade: str = ""
    estado: str = ""
    organizador: str = ""
    site_coleta: str = ""
    data_coleta: datetime | None = None
    distancias: list[str] = []
    horario: str | None = None
    url_inscricao: str | None = None
    url_imagem: str | None = None
    categoria: str | None = Field(default=None, exclude=True)
    categorias: list[str] = []
    link_edital: str | None = None
    categorias_premiadas: str | None = None
    preco: str | None = None
    precos_entries: list[Any] | None = None
    patrocinado: bool = False
    percurso: Percurso | None = None
    kits: list[Kit] | None = None
    campos_protegidos: list[str] = []
    lista_precos: list[str] = []

    model_config = {"populate_by_name": True}

    @field_validator("distancias", mode="before")
    @classmethod
    def parse_distancias(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [d.strip() for d in v.split(",") if d.strip()] if v.strip() else []
        if isinstance(v, list):
            return [str(d).strip() for d in v if str(d).strip()]
        return []

    @field_validator("precos_entries", mode="before")
    @classmethod
    def parse_precos_entries(cls, v: Any) -> list[Any] | None:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return []
        return v

    @model_validator(mode="after")
    def compute_fields(self) -> "EventoResponse":
        if self.datas_realizacao and not self.data_realizacao:
            dt = self.datas_realizacao[0]
            self.data_realizacao = f"{dt.day:02d} de {MESES_PT[dt.month]} de {dt.year}"
        if self.categoria and not self.categorias:
            self.categorias = [c.strip() for c in self.categoria.split(",") if c.strip()]
        if not self.lista_precos:
            self.lista_precos = formatar_lista_precos(self.precos_entries, self.preco)
        return self


class EventoPageResponse(BaseModel):
    eventos: list[EventoResponse]
    total: int
    total_pages: int
    page: int
    size: int


class EventoCreate(BaseModel):
    nome_evento: str
    datas_realizacao: list[datetime]
    cidade: str
    estado: str = "PB"
    organizador: str = ""
    site_coleta: str = ""
    data_coleta: datetime = Field(default_factory=datetime.now)
    distancias: list[str] = []
    horario: str | None = None

    @field_validator("distancias", mode="before")
    @classmethod
    def parse_distancias(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [d.strip() for d in v.split(",") if d.strip()] if v.strip() else []
        if isinstance(v, list):
            return [str(d).strip() for d in v if str(d).strip()]
        return []
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
    distancias: list[str] | None = None
    horario: str | None = None

    @field_validator("distancias", mode="before")
    @classmethod
    def parse_distancias(cls, v: Any) -> list[str] | None:
        if v is None:
            return None
        if isinstance(v, str):
            return [d.strip() for d in v.split(",") if d.strip()] if v.strip() else []
        if isinstance(v, list):
            return [str(d).strip() for d in v if str(d).strip()]
        return []
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
    campos_protegidos: list[str] | None = None

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