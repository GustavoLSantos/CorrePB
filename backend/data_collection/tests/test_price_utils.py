"""Tests for PriceUtils (English API).

Covers Task 2/Task 4 fixes: parse_price_str locale handling and fmt_entry formatting.
"""

import pytest

from data_collection.utils.PriceUtils import fmt_entry, parse_price_str


class TestParsePriceStr:
    def test_brazilian_format(self):
        assert parse_price_str("1.234,56") == 1234.56
        assert parse_price_str("89,90") == 89.9
        assert parse_price_str("50") == 50.0

    def test_with_currency_symbol(self):
        assert parse_price_str("R$ 1.234,56") == 1234.56
        assert parse_price_str("R$ 89,90") == 89.9

    def test_invalid_returns_none(self):
        assert parse_price_str("") is None
        assert parse_price_str(None) is None
        assert parse_price_str("invalido") is None
        assert parse_price_str("R$ -") is None

    def test_int_float_input(self):
        assert parse_price_str(50) == 50.0
        assert parse_price_str(50.5) == 50.5
        assert parse_price_str(0) == 0.0


class TestFmtEntry:
    def test_with_label_and_price(self):
        entry = {"label": "Geral", "price": 50.0}
        result = fmt_entry(entry)
        assert result["label"] == "Geral"
        assert result["price"] == 50.0
        assert "R$ 50,00" in result["formatted"]
        assert "Geral" in result["formatted"]

    def test_without_label(self):
        entry = {"label": None, "price": 90.0}
        result = fmt_entry(entry)
        assert result["formatted"] == "R$ 90,00"

    def test_with_tax(self):
        entry = {"label": "Geral", "price": 50.0, "tax": 5.0}
        result = fmt_entry(entry)
        assert "R$ 50,00" in result["formatted"]
        assert "5,00" in result["formatted"]
        assert "taxa" in result["formatted"].lower()

    def test_none_price_uses_formatted(self):
        entry = {"label": "Geral", "price": None, "formatted": "Valor não encontrado"}
        result = fmt_entry(entry)
        assert result["formatted"] == "Valor não encontrado"
        assert result["price"] is None

    def test_price_zero(self):
        entry = {"label": None, "price": 0.0}
        result = fmt_entry(entry)
        assert result["formatted"] == "R$ 0,00"
