"""Scraper dedicado do site Zenite Esportes (zeniteesportes.com).

Coleta completa direto do catálogo OpenCart do organizador, sem depender do
listing do Brasil Que Corre e sem Selenium (páginas server-side renderized):

- Descoberta: links de produto na home (slugs SEO, ex.: /atacamixrun2026)
- Detalhes por página: og:title/og:image, bloco 'Data da corrida' (data/horário),
  'Local: Cidade – UF', 'Percursos:', spans pro_price e regulamento abrirPDF()

Produz o mesmo schema CSV dos demais scrapers e sincroniza com a coleção "zenite".
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_collection.core.ScraperCommon import (
    EVENTOS_CSV_FIELDNAMES,
    sync_csv_to_mongodb,
    write_events_csv,
)
from data_collection.sources.Zenite import get_zenite_events


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(base_dir, "data/eventos_zenite.csv")

    events = get_zenite_events(somente_futuros=True)

    if not events:
        print("Nenhum evento encontrado.")
        return

    print(f"\nTotal de {len(events)} eventos encontrados. Salvando no CSV...")
    write_events_csv(csv_path, events, EVENTOS_CSV_FIELDNAMES)
    print(f"\nSalvo com sucesso: {csv_path}")

    if not sync_csv_to_mongodb(csv_path, "zenite"):
        print("Sincronização pulada ou falhou.")


if __name__ == "__main__":
    main()
