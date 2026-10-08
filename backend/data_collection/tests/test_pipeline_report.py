"""Tests for pipeline_agent.save_frontend_report (ScrapeReport contract).

The frontend modal reads report.scrapers[] and report.csvs[] with exact
keys; anything else renders as empty sections. These tests lock the shape.
"""

from data_collection.pipeline_agent import (
    CsvSummary,
    StepResult,
    save_frontend_report,
)


def _scraper(name="scraper_brasilquecorre.py", ok=True):
    return StepResult(
        name=name,
        ok=ok,
        duration=4.5,
        stdout="L" * 9000,
        stderr="E" * 3000,
    )


def _csv(fonte="brasilquecorre"):
    summary = CsvSummary(fonte=fonte, ok=True)
    summary.total = 2
    summary.duplicados = 1
    summary.sem_preco = 0
    summary.eventos_passados = 0
    summary.sem_imagem = 0
    summary.erros_encoding = 0
    summary.erros = [f"erro {i}" for i in range(15)]
    return summary


def test_report_has_contract_keys():
    report = save_frontend_report([_scraper()], [_csv()], "2026-10-08T02:00:00+00:00")

    assert set(report.keys()) == {"started_at", "finished_at", "scrapers", "csvs"}
    assert report["started_at"] == "2026-10-08T02:00:00+00:00"
    assert report["finished_at"] is not None

    scraper = report["scrapers"][0]
    assert set(scraper.keys()) == {"nome", "ok", "duration_s", "detail", "stderr"}
    assert scraper["nome"] == "scraper_brasilquecorre.py"
    assert scraper["ok"] is True
    assert scraper["duration_s"] == 4.5

    csv = report["csvs"][0]
    assert set(csv.keys()) == {
        "fonte",
        "ok",
        "total",
        "duplicados",
        "sem_preco",
        "eventos_passados",
        "sem_imagem",
        "erros_encoding",
        "erros",
    }
    assert csv["fonte"] == "brasilquecorre"
    assert csv["total"] == 2


def test_report_truncates_long_texts():
    report = save_frontend_report([_scraper()], [_csv()], "2026-10-08T02:00:00+00:00")

    scraper = report["scrapers"][0]
    assert len(scraper["detail"]) == 8000
    assert len(scraper["stderr"]) == 2000
    assert scraper["detail"] == "L" * 8000

    assert len(report["csvs"][0]["erros"]) == 10


def test_report_empty_inputs():
    report = save_frontend_report([], [], "2026-10-08T02:00:00+00:00")

    assert report["scrapers"] == []
    assert report["csvs"] == []
    assert report["finished_at"] is not None
