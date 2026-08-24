"""Scraper dedicado da plataforma Race83 (race83.com.br).

Coleta completa direto das APIs oficiais da plataforma, sem depender do
listing do Brasil Que Corre e sem Selenium:

- listEventos: {BASE}/session/{YYYYMMDD}_race83_events.json
- Detalhes por evento: {BASE}/api_evento.php?url={eve_id}/{slug}
  -> preços por lote/categoria, percursos, documentos (edital), local e horário

Produz o mesmo schema CSV dos demais scrapers e sincroniza com a coleção "race83".
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_collection.core.ScraperCommon import (
    EVENTOS_CSV_FIELDNAMES,
    sync_csv_to_mongodb,
    write_events_csv,
)
from data_collection.sources.Race83 import get_race83_events


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(base_dir, "data/eventos_race83.csv")

    events = get_race83_events(estado_filter="PB", somente_futuros=True)

    if not events:
        print("Nenhum evento encontrado.")
        return

    print(f"\nTotal de {len(events)} eventos encontrados. Salvando no CSV...")
    write_events_csv(csv_path, events, EVENTOS_CSV_FIELDNAMES)
    print(f"\nSalvo com sucesso: {csv_path}")

    if not sync_csv_to_mongodb(csv_path, "race83"):
        print("Sincronização pulada ou falhou.")


if __name__ == "__main__":
    main()
