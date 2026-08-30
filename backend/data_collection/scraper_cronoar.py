"""Scraper dedicado Cronoar — cronoar.com.br

Coleta via:
- WP REST wp/v2/etn (lista) + /api/provas?slug= (detalhe completo com lotes/preços)

Segue padrão ScraperCommon (CSV + sync MongoDB).
"""

import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_collection.core.ScraperCommon import run_standard_scraper
from data_collection.sources.Cronoar import get_cronoar_events


def main():
    run_standard_scraper(
        lambda: get_cronoar_events(estado_filter=None, somente_futuros=True),
        "eventos_cronoar.csv",
        "cronoar",
    )


if __name__ == "__main__":
    main()
