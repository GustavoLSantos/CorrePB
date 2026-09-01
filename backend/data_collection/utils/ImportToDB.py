import csv
import logging
import os
import re
import sys
import unicodedata
from datetime import datetime

# Configurar caminho
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../.."))
sys.path.insert(0, backend_dir)

import certifi
from dotenv import load_dotenv
from data_collection.evento_de_corrida import EventoDeCorrida
from pymongo import MongoClient, ReturnDocument

load_dotenv(os.path.abspath(os.path.join(current_dir, "../..", ".env")))

MONGO_URI = os.getenv("MONGODB_REMOTE_URI") or os.getenv("MONGODB_URI")
DB_NAME = os.getenv("MONGODB_REMOTE_DB_NAME") or os.getenv("MONGODB_DB_NAME") or "correpb"
COLLECTION_NAME = "eventos"

logger = logging.getLogger(__name__)

# ─── Fingerprint composto (nome + cidade + data) ──────────────────────────────
# Mesma lógica de pipeline_agent.validate_csv: normaliza acentos/caixa/espaços
# e canonicaliza a data para YYYY-MM-DD. Troca T1: evita colisão por nome apenas.


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _normalize_str(s: str | None) -> str:
    if not s:
        return ""
    s = _strip_accents(s).lower().strip()
    return re.sub(r"\s+", " ", s)


def _fingerprint_from_evento(evento) -> tuple[str, str, str]:
    nome_fp = _normalize_str(evento.nome_evento)
    cidade_fp = _normalize_str(evento.cidade)
    datas = getattr(evento, "datas_realizacao", None) or []
    data_fp = ""
    if datas:
        try:
            # primeira data é a canônica (multi-datas: "02, 03 e 15 de Agosto")
            dt = datas[0]
            if isinstance(dt, datetime):
                data_fp = dt.strftime("%Y-%m-%d")
            elif isinstance(dt, str) and dt.strip():
                # fallback: tenta parsear string já formatada
                from data_collection.core.ScraperCommon import parse_long_date_string, parse_date_string

                parsed = parse_long_date_string(dt) or parse_date_string(dt)
                data_fp = parsed.strftime("%Y-%m-%d") if parsed else dt.strip().lower()
        except Exception:
            data_fp = ""
    return (nome_fp, cidade_fp, data_fp)


def _fingerprint_from_doc(doc: dict) -> tuple[str, str, str]:
    nome_fp = _normalize_str(doc.get("nome_evento", ""))
    cidade_fp = _normalize_str(doc.get("cidade", ""))
    datas = doc.get("datas_realizacao") or []
    data_fp = ""
    if datas:
        try:
            dt = datas[0]
            if isinstance(dt, datetime):
                data_fp = dt.strftime("%Y-%m-%d")
            elif isinstance(dt, str) and dt.strip():
                from data_collection.core.ScraperCommon import parse_long_date_string, parse_date_string

                parsed = parse_long_date_string(dt) or parse_date_string(dt)
                data_fp = parsed.strftime("%Y-%m-%d") if parsed else dt.strip().lower()
        except Exception:
            data_fp = ""
    else:
        # fallback para campo legado "Data" string se existir
        raw = doc.get("Data") or doc.get("data") or ""
        if raw:
            try:
                from data_collection.core.ScraperCommon import parse_long_date_string

                parsed = parse_long_date_string(str(raw))
                data_fp = parsed.strftime("%Y-%m-%d") if parsed else str(raw).strip().lower()
            except Exception:
                data_fp = str(raw).strip().lower()
    return (nome_fp, cidade_fp, data_fp)


def _find_existing_event(db, evento) -> dict | None:
    """Busca evento existente pelo fingerprint composto (nome+cidade+data).

    Estratégia: busca candidatos por nome normalizado via regex (índice ajuda),
    depois filtra em Python pelo fingerprint completo. Evita varredura total
    e tolera variações de caixa/acentos.
    """
    fp_target = _fingerprint_from_evento(evento)
    if not fp_target[0]:
        return None

    # Candidato por nome: regex case-insensitive ancorado no nome normalizado
    # não é perfeito para acentos, então fallback para scan se não achar
    try:
        # tenta busca exata no primeiro nível (mais rápido se índice existir)
        # usa primeiro token do nome para reduzir candidatos
        nome_raw = (evento.nome_evento or "").strip()
        primeiro_token = re.escape(nome_raw.split()[0]) if nome_raw else ""
        candidatos = []
        if primeiro_token:
            # busca ampla mas indexável: nome começa com mesmo prefixo
            candidatos = list(
                db.eventos.find({"nome_evento": {"$regex": f"^{primeiro_token}", "$options": "i"}})
            )
        if not candidatos:
            # fallback: varredura total (coleção pequena < 10k, custo aceitável)
            candidatos = list(db.eventos.find({}))

        for doc in candidatos:
            if _fingerprint_from_doc(doc) == fp_target:
                return doc
        return None
    except Exception as exc:
        logger.debug(f"_find_existing_event fallback scan: {exc}", exc_info=True)
        try:
            for doc in db.eventos.find({}):
                if _fingerprint_from_doc(doc) == fp_target:
                    return doc
        except Exception:
            pass
        return None


def _ensure_event_indexes(db) -> None:
    """Garante índices para a nova chave composta. Não cria unique para não quebrar
    dados legados já duplicados — unicidade é garantida em aplicação via fingerprint.
    """
    try:
        # Índice simples para acelerar busca por nome (usado em _find_existing_event)
        db.eventos.create_index([("nome_evento", 1)], background=True)
        # Índice composto cru (para debug/inspeção); fingerprint normalizado fica em app
        db.eventos.create_index(
            [("cidade", 1), ("estado", 1), ("datas_realizacao", 1)], background=True
        )
    except Exception as exc:
        logger.debug(f"_ensure_event_indexes failed: {exc}", exc_info=True)


print("Conectando ao MongoDB Atlas\n")

try:
    print("Conectando ao Atlas...")
    remote_client = MongoClient(
        MONGO_URI, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=10000
    )
    remote_client.admin.command("ping")
    print("MongoDB Atlas conectado com sucesso!")

    remote_db = remote_client[DB_NAME]
    remote_collection = remote_db[COLLECTION_NAME]

    total_atual = remote_collection.count_documents({})
    print(f"Eventos ja cadastrados: {total_atual}\n")

except Exception as e:
    print(f"ERRO ao conectar ao Atlas: {e}")
    remote_client = None
    remote_db = None
    remote_collection = None


def import_csv_to_mongodb(db, csv_file, fonte):
    if db is None:
        print(
            "ERRO: Mongo NÃO conectado ao Atlas. Verifique MONGODB_REMOTE_URI/"
            "MONGODB_REMOTE_DB_NAME no arquivo backend/.env e que o IP está liberado "
            "em Network Access. Dados não foram sincronizados."
        )
        return
    # Garante índices da T1 (idempotente)
    _ensure_event_indexes(db)
    try:
        with open(csv_file, "r", encoding="utf-8") as file:
            reader = csv.DictReader(file, delimiter=";", quoting=csv.QUOTE_ALL)
            novos_eventos = 0
            eventos_atualizados = 0
            for row in reader:
                try:
                    # Garante que o campo link_edital será passado, se existir no CSV
                    if "Link do Edital" in row:
                        row["link_edital"] = row["Link do Edital"]
                    # O campo 'Categorias Premiadas' será tratado automaticamente pelo EventoDeCorrida
                    evento = EventoDeCorrida.from_csv_row(row, fonte)

                    # T1: checa existência pelo fingerprint composto (nome+cidade+data)
                    evento_existente = _find_existing_event(db, evento)
                    if not evento_existente:
                        # Gerar _id atômico no formato YYYYMMXXXX via counters (evita race com find_one+regex)
                        now = datetime.now()
                        prefix = f"{now.year}{now.month:02d}"
                        try:
                            counters = db.counters
                            # Inicializa contador com max existente se ainda não existe
                            existing = counters.find_one({"_id": prefix})
                            if not existing:
                                last = db.eventos.find_one(
                                    {"_id": {"$regex": f"^{prefix}"}}, sort=[("_id", -1)]
                                )
                                init_seq = 0
                                if (
                                    last
                                    and isinstance(last.get("_id"), str)
                                    and len(last["_id"]) >= len(prefix) + 4
                                ):
                                    try:
                                        init_seq = int(last["_id"][-4:])
                                    except Exception:
                                        init_seq = 0
                                if init_seq > 0:
                                    counters.insert_one({"_id": prefix, "seq": init_seq})
                            doc = counters.find_one_and_update(
                                {"_id": prefix},
                                {"$inc": {"seq": 1}},
                                upsert=True,
                                return_document=ReturnDocument.AFTER,
                            )
                            new_seq = doc["seq"] if doc else 1
                        except Exception:
                            # Fallback não-atômico (mantém compatibilidade se counters falhar)
                            last = db.eventos.find_one(
                                {"_id": {"$regex": f"^{prefix}"}}, sort=[("_id", -1)]
                            )
                            if (
                                last
                                and isinstance(last.get("_id"), str)
                                and len(last["_id"]) >= len(prefix) + 4
                            ):
                                try:
                                    last_seq = int(last["_id"][-4:])
                                except Exception:
                                    last_seq = 0
                            else:
                                last_seq = 0
                            new_seq = last_seq + 1
                        new_id = f"{prefix}{new_seq:04d}"

                        evento_dict = evento.to_dict()
                        evento_dict["_id"] = new_id

                        db.eventos.insert_one(evento_dict)
                        novos_eventos += 1
                    else:
                        evento_dict = evento.to_dict()
                        evento_existente_dict = {
                            k: v for k, v in evento_existente.items() if k != "_id"
                        }
                        # T2: campos transientes/imutáveis não entram na comparação
                        # data_coleta = quando coletou (sempre now), site_coleta = fonte do primeiro insert
                        # patrocinado/campos_protegidos = edição manual
                        campos_nao_comparaveis = [
                            "data_coleta",
                            "site_coleta",
                            "patrocinado",
                            "campos_protegidos",
                        ]
                        for campo in campos_nao_comparaveis:
                            evento_dict.pop(campo, None)
                            evento_existente_dict.pop(campo, None)

                        # Remover campos protegidos da comparação e do update
                        campos_protegidos = evento_existente.get("campos_protegidos", [])
                        for campo in campos_protegidos:
                            evento_dict.pop(campo, None)
                            evento_existente_dict.pop(campo, None)

                        if campos_protegidos:
                            print(
                                f"  Campos protegidos em '{evento.nome_evento}': {campos_protegidos}"
                            )

                        # Normalize edital placeholder "edital não encontrado" → "" for fair comparison
                        def _normalize_edital(v):
                            if not v:
                                return ""
                            s = str(v).strip()
                            if not s:
                                return ""
                            import unicodedata

                            norm = "".join(
                                c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c)
                            )
                            if norm in ("edital nao encontrado", "edital não encontrado"):
                                return ""
                            return s

                        for d in (evento_dict, evento_existente_dict):
                            # Ensure key exists and is normalized
                            raw = d.get("link_edital", "")
                            d["link_edital"] = _normalize_edital(raw)
                            # Also normalize empty vs missing for other optional string fields that may be ""
                            for k in ("preco", "categoria", "horario"):
                                if k in d and isinstance(d[k], str) and not d[k].strip():
                                    d[k] = ""

                        if evento_dict != evento_existente_dict:
                            # T2: montar dict de update sem campos imutáveis/transientes
                            # antes: update_dict incluía data_coleta=now() e site_coleta,
                            # causando churn (todo run parecia "atualizado")
                            update_dict = evento.to_dict()
                            # _id nunca vai no $set
                            update_dict.pop("_id", None)
                            for campo in campos_protegidos:
                                update_dict.pop(campo, None)
                            for campo in campos_nao_comparaveis:
                                update_dict.pop(campo, None)

                            if not update_dict:
                                # só mudaram campos imutáveis -> nada a persistir
                                continue

                            print(f"Atualizando evento: {evento.nome_evento}")
                            print(f"Antes: {evento_existente_dict}")
                            print(f"Depois: {evento_dict}")
                            # T1: atualiza pelo _id do documento encontrado (chave composta), não só por nome
                            db.eventos.update_one(
                                {"_id": evento_existente["_id"]}, {"$set": update_dict}
                            )
                            eventos_atualizados += 1
                except Exception as e:
                    print(f"Erro ao processar linha do CSV: {str(e)}")
                    print(f"Conteudo da linha: {row}")
                    continue
        print(f"Dados de {fonte} processados com sucesso")
        print(f"{novos_eventos} novos eventos adicionados")
        print(f"{eventos_atualizados} eventos atualizados")
    except Exception as e:
        print(f"Erro ao importar dados de {fonte}: {str(e)}")


def main():
    if remote_db is None:
        print("MongoDB nao conectado. Encerrando.\n")
        return
    try:
        db = remote_db
        base_dir = os.path.dirname(os.path.abspath(__file__))
        csv_files = [
            (os.path.join(base_dir, "../data/eventos_brasilquecorre.csv"), "brasilquecorre"),
            (os.path.join(base_dir, "../data/eventos_smcrono.csv"), "smcrono"),
            (os.path.join(base_dir, "../data/eventos_race83.csv"), "race83"),
            (os.path.join(base_dir, "../data/eventos_zenite.csv"), "zenite"),
            (
                os.path.join(base_dir, "../data/eventos_circuitodasestacoes.csv"),
                "circuitodasestacoes",
            ),
            (os.path.join(base_dir, "../data/eventos_apcrono.csv"), "apcrono"),
            (os.path.join(base_dir, "../data/eventos_cronoar.csv"), "cronoar"),
        ]
        for csv_path, fonte in csv_files:
            if os.path.exists(csv_path):
                import_csv_to_mongodb(db, csv_path, fonte)
            else:
                print(f"Arquivo nao encontrado: {csv_path}")
        total = db.eventos.count_documents({})
        print(f"\nTotal de eventos no Atlas: {total}")
    except Exception as e:
        print(f"Erro geral: {str(e)}")


if __name__ == "__main__":
    main()
