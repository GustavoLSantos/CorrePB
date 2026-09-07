import csv
import re
import unicodedata
from pathlib import Path
from typing import TypedDict

from app.services.scrape_config import CSV_MAP, SCRAPER_PRIORITY

_MESES_PT = {
    "janeiro": 1,
    "fevereiro": 2,
    "março": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _normalize_nome(nome: str) -> str:
    s = _strip_accents(nome).lower().strip()
    s = re.sub(r"\b\d{4}\b", " ", s)
    s = re.sub(r"\s*[-–]\s*[a-z][a-z\s]*$", " ", s)
    s = re.sub(r"\betapa\b", " ", s)
    s = re.sub(r"\b\d+\s*º?\s*(edicao|ed\.?)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _normalize_cidade(cidade: str) -> str:
    s = _strip_accents(cidade).lower().strip()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_data_key(data_str: str) -> str:
    raw = (data_str or "").strip()
    if not raw:
        return ""
    try:
        low = raw.lower().replace("  ", " ").replace(" e ", ", ")
        partes = low.split(" de ")
        if len(partes) == 3:
            dia = partes[0].split(",")[0].strip()
            mes = _MESES_PT.get(partes[1].strip())
            ano = partes[2].strip()
            if mes:
                return f"{int(ano):04d}-{mes:02d}-{int(dia):02d}"
    except Exception:
        pass
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)
    if m:
        return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return _strip_accents(raw).lower().strip()


def _event_fingerprint(row: dict[str, str]) -> tuple[str, str, str]:
    nome = _normalize_nome(row.get("Nome do Evento", ""))
    cidade = _normalize_cidade(row.get("Cidade", ""))
    data_key = _parse_data_key(row.get("Data", ""))
    if not nome:
        link = (row.get("Link de Inscrição") or "").strip().lower()
        link = re.sub(r"\?.*$", "", link)
        link = re.sub(r"https?://", "", link).strip("/")
        return (link, data_key, cidade)
    return (nome, data_key, cidade)


class DedupStats(TypedDict):
    fonte: str
    mantidos: int
    removidos: int
    duplicatas: list[str]


def _completeness_score(row: dict[str, str]) -> int:
    fields = (
        "Nome do Evento",
        "Data",
        "Cidade",
        "Link de Inscrição",
        "Link da Imagem",
        "Distância",
        "Organizador",
        "Horário",
        "Link do Edital",
        "precos_entries",
        "Percurso",
        "Kits",
    )
    return sum(1 for key in fields if _has_collected_value(row.get(key)))


def _has_collected_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        normalized = _strip_accents(value).strip().lower()
        return normalized not in {
            "",
            "[]",
            "{}",
            "edital nao encontrado",
            "valor nao encontrado",
            "null",
            "none",
        }
    if isinstance(value, (list, tuple, set)):
        return any(_has_collected_value(item) for item in value)
    if isinstance(value, dict):
        return any(_has_collected_value(item) for item in value.values())
    return True


def deduplicate_csvs(
    csv_map: dict[str, Path] | None = None,
    *,
    rewrite_files: bool = True,
) -> list[DedupStats]:
    target_map = csv_map or CSV_MAP

    headers: dict[str, list[str] | None] = {f: None for f in target_map}
    groups: dict[tuple[str, str, str], list[tuple[str, dict[str, str], int, int, int]]] = {}
    order_counter = 0

    for fonte in target_map:
        path = target_map[fonte]
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8-sig", errors="replace") as f:
                reader = csv.DictReader(f, delimiter=";", quoting=csv.QUOTE_ALL)
                headers[fonte] = reader.fieldnames
                for row in reader:
                    clean = {k: (v or "") for k, v in row.items() if k is not None}
                    fp = _event_fingerprint(clean)
                    if fp == ("", "", ""):
                        fp = (f"__empty_{fonte}_{order_counter}", "", "")
                    score = _completeness_score(clean)
                    priority = SCRAPER_PRIORITY.get(fonte, 0)
                    groups.setdefault(fp, []).append((fonte, clean, score, priority, order_counter))
                    order_counter += 1
        except Exception:
            continue

    stats: dict[str, DedupStats] = {
        f: {"fonte": f, "mantidos": 0, "removidos": 0, "duplicatas": []} for f in target_map
    }
    kept_rows: dict[str, list[dict[str, str]]] = {f: [] for f in target_map}

    for fp, candidates in groups.items():
        if len(candidates) == 1:
            fonte, row, _, _, _ = candidates[0]
            kept_rows[fonte].append(row)
            stats[fonte]["mantidos"] += 1
            continue
        candidates.sort(key=lambda x: (-x[2], -x[3], x[4]))
        winner = candidates[0]
        winner_fonte, _, winner_score, _, _ = winner
        for fonte, row, score, _, _ in candidates:
            is_winner = row is winner[1] and fonte == winner_fonte
            if is_winner:
                kept_rows[fonte].append(row)
                stats[fonte]["mantidos"] += 1
            else:
                stats[fonte]["removidos"] += 1
                if len(stats[fonte]["duplicatas"]) < 5:
                    stats[fonte]["duplicatas"].append(
                        f"'{row.get('Nome do Evento', '')[:40]}' duplicado de '{winner_fonte}' (score {score} < {winner_score})"
                    )

    if rewrite_files:
        for fonte, path in target_map.items():
            if not path.exists() or headers[fonte] is None:
                continue
            if stats[fonte]["removidos"] == 0:
                continue
            tmp = path.with_suffix(".dedup.tmp")
            try:
                with tmp.open("w", encoding="utf-8", newline="") as out:
                    writer = csv.DictWriter(
                        out,
                        fieldnames=headers[fonte] or [],
                        delimiter=";",
                        quoting=csv.QUOTE_ALL,
                    )
                    writer.writeheader()
                    writer.writerows(kept_rows[fonte])
                tmp.replace(path)
            except Exception:
                if tmp.exists():
                    with __import__("contextlib").suppress(Exception):
                        tmp.unlink()
                raise

    fontes_ordenadas = sorted(
        target_map.keys(), key=lambda k: SCRAPER_PRIORITY.get(k, 0), reverse=True
    )
    return [stats[f] for f in fontes_ordenadas if f in target_map]
