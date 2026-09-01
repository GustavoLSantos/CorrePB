"""Tests for ScraperCommon date helpers (English API).

Covers Task 1 unification: MONTHS_PT, parse_date_string, format_date_string,
parse_long_date_string, parse_long_multi_dates, format_datetime_to_br.
"""

from datetime import datetime

from data_collection.core.ScraperCommon import (
    MONTH_BY_NAME,
    MONTHS_CAPITALIZED,
    MONTHS_PT,
    format_date_string,
    format_datetime_to_br,
    parse_date_string,
    parse_long_date_string,
    parse_long_multi_dates,
)


class TestMonthsConstants:
    def test_months_pt(self):
        assert MONTHS_PT[1] == "janeiro"
        assert MONTHS_PT[3] == "março"
        assert MONTHS_PT[12] == "dezembro"

    def test_month_by_name(self):
        assert MONTH_BY_NAME["janeiro"] == 1
        assert MONTH_BY_NAME["março"] == 3
        assert MONTH_BY_NAME["dezembro"] == 12

    def test_months_capitalized(self):
        assert MONTHS_CAPITALIZED[1] == "Janeiro"
        assert MONTHS_CAPITALIZED[3] == "Março"


class TestParseDateString:
    def test_ddmmyyyy(self):
        dt = parse_date_string("15/08/2026")
        assert dt == datetime(2026, 8, 15)

    def test_yyyymmdd(self):
        dt = parse_date_string("2026-08-15")
        assert dt == datetime(2026, 8, 15)

    def test_invalid_returns_none(self):
        assert parse_date_string("") is None
        assert parse_date_string(None) is None
        assert parse_date_string("invalid") is None
        assert parse_date_string("32/13/2026") is None


class TestFormatDateString:
    def test_valid(self):
        assert format_date_string("15/08/2026") == "15 de agosto de 2026"
        assert format_date_string("01/01/2026") == "1 de janeiro de 2026"

    def test_invalid_returns_input(self):
        assert format_date_string("invalid") == "invalid"
        assert format_date_string("") == ""
        assert format_date_string(None) == ""


class TestParseLongDateString:
    def test_single(self):
        dt = parse_long_date_string("15 de agosto de 2026")
        assert dt == datetime(2026, 8, 15)

    def test_multi_first(self):
        dt = parse_long_date_string("02, 03 e 15 de Agosto de 2025")
        assert dt == datetime(2025, 8, 2)

    def test_capitalized_month(self):
        dt = parse_long_date_string("02 de Agosto de 2025")
        assert dt == datetime(2025, 8, 2)

    def test_invalid(self):
        assert parse_long_date_string("") is None
        assert parse_long_date_string("invalid") is None
        assert parse_long_date_string(None) is None


class TestParseLongMultiDates:
    def test_multi(self):
        dates = parse_long_multi_dates("02, 03 e 15 de Agosto de 2025")
        assert len(dates) == 3
        assert {d.day for d in dates} == {2, 3, 15}
        assert all(d.month == 8 and d.year == 2025 for d in dates)

    def test_single(self):
        dates = parse_long_multi_dates("15 de agosto de 2026")
        assert len(dates) == 1
        assert dates[0] == datetime(2026, 8, 15)

    def test_empty(self):
        assert parse_long_multi_dates("") == []
        assert parse_long_multi_dates(None) == []
        assert parse_long_multi_dates("invalid") == []


class TestFormatDatetimeToBr:
    def test_datetime(self):
        assert format_datetime_to_br(datetime(2026, 8, 15)) == "15 de Agosto de 2026"
        assert format_datetime_to_br(datetime(2026, 1, 1)) == "1 de Janeiro de 2026"

    def test_iso_string(self):
        assert format_datetime_to_br("2026-08-15T00:00:00") == "15 de Agosto de 2026"

    def test_string_passthrough(self):
        assert format_datetime_to_br("15 de agosto de 2026") == "15 de agosto de 2026"

    def test_empty(self):
        assert format_datetime_to_br(None) == ""
        assert format_datetime_to_br("") == ""
