import csv
import re
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import TypeAlias, cast

import certifi
from pymongo import MongoClient
from pymongo.database import Database

from app.core.config import settings
from data_collection.evento_de_corrida import EventoDeCorrida

EventoDoc: TypeAlias = dict[str, object]
CSVRow: TypeAlias = dict[str, str]


def _connect() -> tuple[MongoClient[EventoDoc], Database[EventoDoc]]:
    uri = settings.MONGODB_REMOTE_URI or settings.MONGODB_URI

    db_name = (
        settings.MONGODB_REMOTE_DB_NAME
        if settings.MONGODB_REMOTE_URI and settings.MONGODB_REMOTE_DB_NAME
        else settings.MONGODB_DB_NAME
    )

    client = MongoClient[EventoDoc](
        uri,
        tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=10000,
    )

    _ = client["admin"].command("ping")

    return client, client[db_name]


def _buscar_por_nome(
    db: Database[EventoDoc],
    nome_evento: str,
) -> EventoDoc | None:
    if not nome_evento.strip():
        return None

    padrao = f"^{re.escape(nome_evento)}$"

    return db["eventos"].find_one(
        {"nome_evento": {"$regex": padrao, "$options": "i"}},
        sort=[("_id", -1)],
    )


def _generate_id(
    db: Database[EventoDoc],
    prefix: str,
) -> str:
    last = db["eventos"].find_one(
        {"_id": {"$regex": f"^{re.escape(prefix)}"}},
        sort=[("_id", -1)],
    )

    last_id = last.get("_id") if last else None

    last_seq = 0

    if isinstance(last_id, str) and len(last_id) >= len(prefix) + 4:
        with suppress(ValueError):
            last_seq = int(last_id[-4:])

    return f"{prefix}{last_seq + 1:04d}"


def _campos_protegidos(documento: EventoDoc) -> list[str]:
    valor = documento.get("campos_protegidos", [])

    if not isinstance(valor, list):
        return []

    return [campo for campo in cast(list[object], valor) if isinstance(campo, str)]


def _import_csv(
    db: Database[EventoDoc],
    csv_path: Path,
    fonte: str,
) -> tuple[int, int]:
    novos = 0
    atualizados = 0

    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(
            f,
            delimiter=";",
            quoting=csv.QUOTE_ALL,
        )

        for row in reader:
            try:
                csv_row: CSVRow = {
                    key: value or "" for key, value in row.items() if key is not None
                }

                if "Link do Edital" in csv_row:
                    csv_row["link_edital"] = csv_row["Link do Edital"]

                evento = EventoDeCorrida.from_csv_row(
                    csv_row,
                    fonte,
                )

                existente = _buscar_por_nome(
                    db,
                    evento.nome_evento,
                )

                evento_dict = evento.to_dict()

                if existente is None:
                    evento_dict["_id"] = _generate_id(
                        db,
                        datetime.now().strftime("%Y%m"),
                    )

                    _ = db["eventos"].insert_one(evento_dict)
                    novos += 1
                    continue

                existente_dict: EventoDoc = {
                    chave: valor for chave, valor in existente.items() if chave != "_id"
                }

                for campo in (
                    "data_coleta",
                    "patrocinado",
                    "campos_protegidos",
                ):
                    # Anotação explícita de ": object" evita que o linter classifique "_" como "Any"
                    _: object = evento_dict.pop(campo, None)
                    _: object = existente_dict.pop(campo, None)

                campos_protegidos = _campos_protegidos(existente)

                for campo in campos_protegidos:
                    _: object = evento_dict.pop(campo, None)
                    _: object = existente_dict.pop(campo, None)

                if "link_edital" not in evento_dict:
                    evento_dict["link_edital"] = ""
                if "link_edital" not in existente_dict:
                    existente_dict["link_edital"] = ""

                if evento_dict != existente_dict:
                    update_dict = evento.to_dict()

                    for campo in campos_protegidos:
                        _: object = update_dict.pop(campo, None)

                    _ = db["eventos"].update_one(
                        {"_id": existente["_id"]},
                        {"$set": update_dict},
                    )

                    atualizados += 1

            except Exception as exc:
                print(f"Erro ao importar evento da fonte '{fonte}': {exc}")
                continue

    return novos, atualizados


def import_scraped_csvs() -> dict[str, int]:
    from .scraper_runner import CSV_MAP

    client, db = _connect()

    try:
        novos = 0
        atualizados = 0

        for fonte, csv_path in CSV_MAP.items():
            if csv_path.exists():
                n, a = _import_csv(
                    db,
                    csv_path,
                    fonte,
                )

                novos += n
                atualizados += a

        total: int = int(db["eventos"].count_documents({}))

        return {
            "novos": novos,
            "atualizados": atualizados,
            "total": total,
        }

    finally:
        client.close()
