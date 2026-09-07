import re
from typing import Any


def normalize_distancias(value: Any) -> list[str]:
    if isinstance(value, str):
        return [d.strip() for d in value.split(",") if d.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(d).strip() for d in value if str(d).strip()]
    return []


def normalize_distancias_nullable(value: Any) -> list[str] | None:
    if value is None:
        return None
    return normalize_distancias(value)


def validate_horario_format(value: str | None) -> str | None:
    if value is not None and not re.match(r"^\d{2}:\d{2}$", value):
        raise ValueError("horario must match HH:MM format")
    return value
