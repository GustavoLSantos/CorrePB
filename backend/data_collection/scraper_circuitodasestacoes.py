"""Scraper dedicado do Circuito das Estações (circuitodasestacoes.com.br).

Coleta completa via APIs públicas, sem depender do listing do Brasil Que
Corre e sem Selenium:

- Catálogo: hotsites.nortemkt.com/api/v2/events/circuito-das-estacoes/home
  (localizações × etapas: cidade, data, modalidades, url_key)
- Preços: GraphQL RunningLand (getEventProduct -> bundleChildrenItems)
- Horário de largada: components da página de cada etapa

Produz o mesmo schema CSV dos demais scrapers e sincroniza com a coleção
"circuitodasestacoes".
"""
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_collection.core.ScraperCommon import run_standard_scraper
from data_collection.sources.CircuitoDasEstacoes import get_circuito_events


def main():
    run_standard_scraper(
        lambda: get_circuito_events(somente_futuros=True),
        "eventos_circuitodasestacoes.csv",
        "circuitodasestacoes",
    )


if __name__ == "__main__":
    main()