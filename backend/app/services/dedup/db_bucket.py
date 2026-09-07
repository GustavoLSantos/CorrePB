import re

from app.core.database import database
from app.services.dedup.csv import _has_collected_value, _normalize_cidade, _normalize_nome, _parse_data_key
from app.services.scrape_config import SCRAPER_PRIORITY


def _db_fingerprint(doc: dict) -> tuple[str, str, str]:
    nome = _normalize_nome(str(doc.get("nome_evento") or ""))
    cidade = _normalize_cidade(str(doc.get("cidade") or ""))
    datas = doc.get("datas_realizacao") or []
    data_key = ""
    if isinstance(datas, list) and datas:
        try:
            d = datas[0]
            if hasattr(d, "year"):
                data_key = f"{d.year:04d}-{d.month:02d}-{d.day:02d}"
            else:
                data_key = _parse_data_key(str(d))
        except Exception:
            data_key = ""
    if not data_key:
        data_key = _parse_data_key(str(doc.get("data_realizacao") or ""))
    if not nome:
        link = str(doc.get("url_inscricao") or "").strip().lower()
        link = re.sub(r"\?.*$", "", link)
        link = re.sub(r"https?://", "", link).strip("/")
        return (link, data_key, cidade)
    return (nome, data_key, cidade)


def _db_completeness(doc: dict) -> int:
    fields = (
        "nome_evento",
        "datas_realizacao",
        "cidade",
        "url_inscricao",
        "url_imagem",
        "distancias",
        "organizador",
        "horario",
        "link_edital",
        "precos_entries",
        "percurso",
        "kits",
    )
    return sum(1 for key in fields if _has_collected_value(doc.get(key)))


async def deduplicate_db_and_bucket() -> dict | None:
    from app.core.config import settings as _settings

    _uri = (_settings.MONGODB_REMOTE_URI or _settings.MONGODB_URI or "").strip()
    _is_local_uri = any(host in _uri.lower() for host in ("localhost", "127.0.0.1", "::1"))
    if not _uri or _is_local_uri:
        print("[dedup][DB] skip - Atlas não configurado (URI local ou vazia)")
        return None

    try:
        if database.db is None:
            await database.connect()
        collection = database.get_collection("eventos")
        if collection is None:
            print("[dedup][DB] skip - coleção indisponível (db=None)")
            return None
        await collection.find_one({})
    except Exception as e:
        print(f"[dedup][DB] skip - falha ao conectar Atlas: {e}")
        return None

    try:
        docs = await collection.find({}).to_list(length=None)
    except Exception as e:
        print(f"[dedup][DB] falha ao listar: {e}")
        return None

    if not docs:
        return {"removidos_db": 0, "removidos_bucket": 0}

    groups: dict[tuple[str, str, str], list[dict]] = {}
    for doc in docs:
        fp = _db_fingerprint(doc)
        if fp == ("", "", ""):
            continue
        groups.setdefault(fp, []).append(doc)

    to_delete_ids = []
    winner_slugs: set[str] = set()
    loser_slugs: list[tuple[str, str]] = []

    for fp, group in groups.items():
        if len(group) <= 1:
            continue

        def _sort_key(d: dict):
            score = _db_completeness(d)
            prio = SCRAPER_PRIORITY.get(str(d.get("site_coleta") or ""), 0)
            oid = str(d.get("_id") or "")
            return (-score, -prio, oid)

        group_sorted = sorted(group, key=_sort_key)
        winner = group_sorted[0]
        try:
            from data_collection.utils.ProcessImages import _slugify  # type: ignore

            winner_slugs.add(_slugify(str(winner.get("nome_evento") or "")))
        except Exception:
            pass
        for loser in group_sorted[1:]:
            to_delete_ids.append(loser["_id"])
            try:
                from data_collection.utils.ProcessImages import _slugify

                loser_slugs.append(
                    (_slugify(str(loser.get("nome_evento") or "")), str(loser.get("_id")))
                )
            except Exception:
                pass

    stats = {
        "removidos_db": 0,
        "removidos_bucket": 0,
        "grupos": len([g for g in groups.values() if len(g) > 1]),
    }

    if to_delete_ids:
        try:
            res = await collection.delete_many({"_id": {"$in": to_delete_ids}})
            stats["removidos_db"] = getattr(res, "deleted_count", len(to_delete_ids))
            print(
                f"[dedup][DB] {stats['removidos_db']} duplicatas removidas em {stats['grupos']} grupos"
            )
        except Exception as e:
            print(f"[dedup][DB] falha ao deletar: {e}")

        try:
            from app.core.config import settings as _settings

            if _settings.AWS_BUCKET_NAME:
                import boto3  # type: ignore

                s3 = boto3.client(
                    "s3",
                    region_name=_settings.AWS_REGION,
                    aws_access_key_id=_settings.AWS_ACCESS_KEY_ID or None,
                    aws_secret_access_key=_settings.AWS_SECRET_ACCESS_KEY or None,
                )
                for slug, _id in loser_slugs:
                    if slug in winner_slugs:
                        continue
                    for ext in [".jpg", ".jpeg", ".png", ".webp"]:
                        key = f"images/{slug}{ext}"
                        try:
                            s3.delete_object(Bucket=_settings.AWS_BUCKET_NAME, Key=key)
                            stats["removidos_bucket"] += 1
                            print(f"[dedup][S3] removido {key}")
                            break
                        except Exception:
                            continue
        except Exception as e:
            print(f"[dedup][S3] skip/falha: {e}")

    return stats
