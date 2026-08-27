"""Scraper dedicado Cronoar — cronoar.com.br

Coleta via:
- WP REST wp/v2/etn (lista) + /api/provas?slug= (detalhe completo com lotes/preços)

Segue padrão ScraperCommon (CSV + sync MongoDB).
"""

import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_collection.core.ScraperCommon import (
    EVENTOS_CSV_FIELDNAMES,
    sync_csv_to_mongodb,
    write_events_csv,
)
from data_collection.sources.Cronoar import get_cronoar_events


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(base_dir, "data/eventos_cronoar.csv")

    events = get_cronoar_events(estado_filter=None, somente_futuros=True)

    if not events:
        print("Nenhum evento encontrado.")
        return

    for ev in events:
        precos = ev.get("precos_entries", "[]")
        try:
            import json as _json
            qtd = len(_json.loads(precos)) if precos.strip().startswith("[") else 1
        except Exception:
            qtd = 1
        print(
            f" - {ev.get('Nome do Evento','?')} | {ev.get('Data','')} {ev.get('Horário','')}"
            f" | {ev.get('Cidade','')} | {ev.get('Distância','')} | Preços: {qtd} entradas"
        )

    print(f"\nTotal de {len(events)} eventos encontrados. Salvando no CSV...")
    write_events_csv(csv_path, events, EVENTOS_CSV_FIELDNAMES)
    print(f"\nSalvo com sucesso: {csv_path}")

    if not sync_csv_to_mongodb(csv_path, "cronoar"):
        print("Sincronização pulada ou falhou.")


if __name__ == "__main__":
    main()
