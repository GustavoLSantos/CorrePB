import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_collection.core.ScraperCommon import run_standard_scraper
from data_collection.sources.Zenite import get_zenite_events


def main():
    run_standard_scraper(
        lambda: get_zenite_events(somente_futuros=True),
        "eventos_zenite.csv",
        "zenite",
    )


if __name__ == "__main__":
    main()