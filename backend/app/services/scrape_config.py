from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_COLLECTION_DIR = BASE_DIR / "data_collection"
DATA_DIR = DATA_COLLECTION_DIR / "data"

SCRAPERS = [
    "scraper_brasilquecorre.py",
    "scraper_smcrono.py",
    "scraper_race83.py",
    "scraper_zenite.py",
    "scraper_circuitodasestacoes.py",
    "scraper_apcrono.py",
    "scraper_cronoar.py",
]

CSV_MAP = {
    "brasilquecorre": DATA_DIR / "eventos_brasilquecorre.csv",
    "smcrono": DATA_DIR / "eventos_smcrono.csv",
    "race83": DATA_DIR / "eventos_race83.csv",
    "zenite": DATA_DIR / "eventos_zenite.csv",
    "circuitodasestacoes": DATA_DIR / "eventos_circuitodasestacoes.csv",
    "apcrono": DATA_DIR / "eventos_apcrono.csv",
    "cronoar": DATA_DIR / "eventos_cronoar.csv",
}

SCRAPER_PRIORITY: dict[str, int] = {
    "circuitodasestacoes": 50,
    "race83": 40,
    "smcrono": 30,
    "zenite": 20,
    "apcrono": 15,
    "cronoar": 14,
    "brasilquecorre": 10,
}
