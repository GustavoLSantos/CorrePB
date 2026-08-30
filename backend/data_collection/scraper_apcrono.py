"""Scraper dedicado AP Crono — apcrono.com.br

Coleta via:
- WP REST wp/v2/etn (lista) + HTML detalhe (apcrono) + tiquet.com.br (preços/horário)

Segue padrão ScraperCommon (CSV + sync MongoDB).
"""

import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_collection.core.ScraperCommon import run_standard_scraper
from data_collection.sources.Apcrono import get_apcrono_events


def main():
    run_standard_scraper(
        lambda: get_apcrono_events(estado_filter=None, somente_futuros=True),
        "eventos_apcrono.csv",
        "apcrono",
    )


if __name__ == "__main__":
    main()
