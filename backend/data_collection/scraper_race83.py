"""Scraper dedicado da plataforma Race83 (race83.com.br).

Coleta completa direto das APIs oficiais da plataforma, sem depender do
listing do Brasil Que Corre e sem Selenium:

- listEventos: {BASE}/session/{YYYYMMDD}_race83_events.json
- Detalhes por evento: {BASE}/api_evento.php?url={eve_id}/{slug}
  -> preços por lote/categoria, percursos, documentos (edital), local e horário

Produz o mesmo schema CSV dos demais scrapers e sincroniza com a coleção "race83".
"""
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_collection.core.ScraperCommon import run_standard_scraper
from data_collection.sources.Race83 import get_race83_events


def main():
    run_standard_scraper(
        lambda: get_race83_events(estado_filter="PB", somente_futuros=True),
        "eventos_race83.csv",
        "race83",
    )


if __name__ == "__main__":
    main()