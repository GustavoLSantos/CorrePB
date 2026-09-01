"""Tests for scraper_smcrono kit extraction (English API).

Covers Task 4 fix: MAX_PDF_BYTES=10MB with stream=True + iter_content.
"""

from unittest.mock import MagicMock, patch

import pytest

from data_collection.scraper_smcrono import MAX_PDF_BYTES, _extract_pdf_text, _parse_kit_info, extract_kits_from_pdf


def _mock_response(content: bytes, content_length: str | None = None, iter_chunks: list[bytes] | None = None):
    """Helper to mock SESSION.get response."""
    mock_resp = MagicMock()
    mock_resp.headers = {}
    if content_length:
        mock_resp.headers["Content-Length"] = content_length
    mock_resp.raise_for_status = MagicMock()
    if iter_chunks is not None:
        mock_resp.iter_content = MagicMock(return_value=iter_chunks)
    else:
        mock_resp.iter_content = MagicMock(return_value=[content[i : i + 8192] for i in range(0, len(content), 8192)])
    mock_resp.content = content
    return mock_resp


class TestExtractPdfText:
    def test_success_small_pdf(self):
        content = b"%PDF-1.4 fake content"
        mock_resp = _mock_response(content, content_length=str(len(content)))
        with patch("data_collection.scraper_smcrono.SESSION.get", return_value=mock_resp):
            with patch("data_collection.scraper_smcrono.PdfReader") as mock_reader:
                mock_reader.return_value.pages = [MagicMock(extract_text=lambda: "KIT\ncamiseta medalha")]
                text = _extract_pdf_text("https://example.com/a.pdf")
                assert "camiseta" in text.lower()

    def test_too_large_content_length(self):
        mock_resp = _mock_response(b"x" * 100, content_length=str(MAX_PDF_BYTES + 1))
        with patch("data_collection.scraper_smcrono.SESSION.get", return_value=mock_resp):
            with pytest.raises(ValueError, match="PDF too large"):
                _extract_pdf_text("https://example.com/big.pdf")

    def test_exceeds_during_stream(self):
        # Content-Length says small, but iter_content yields >10MB
        big_chunks = [b"x" * 8192] * (MAX_PDF_BYTES // 8192 + 2)
        mock_resp = _mock_response(b"", content_length="1000", iter_chunks=big_chunks)
        with patch("data_collection.scraper_smcrono.SESSION.get", return_value=mock_resp):
            with pytest.raises(ValueError, match="PDF exceeded"):
                _extract_pdf_text("https://example.com/stream_big.pdf")


class TestParseKitInfo:
    def test_parse_kit_with_items_and_local(self):
        text = """
        5. COMPOSIÇÃO DOS KITS
        Kit contém: camiseta, medalha, chip e número de peito
        Local de entrega: Ginásio Municipal, Rua X, 123
        Data: 10 de setembro de 2026
        """
        result = _parse_kit_info(text)
        assert result is not None
        assert result[0]["nome"] == "Kit"
        assert "camiseta" in result[0]["itens"]
        assert "medalha" in result[0]["itens"]

    def test_no_kit_section_returns_none(self):
        text = "Regulamento geral sem menção a kits."
        assert _parse_kit_info(text) is None


class TestExtractKitsFromPdf:
    def test_success(self):
        pdf_text = "KIT\ncamiseta, chip\nLocal: Ginásio\n"
        with patch("data_collection.scraper_smcrono._extract_pdf_text", return_value=pdf_text):
            result = extract_kits_from_pdf("https://example.com/kit.pdf")
            assert result is not None
            assert result[0]["nome"] == "Kit"

    def test_empty_url_returns_none(self):
        assert extract_kits_from_pdf("") is None
        assert extract_kits_from_pdf("edital não encontrado") is None

    def test_download_failure_returns_none(self):
        with patch("data_collection.scraper_smcrono._extract_pdf_text", side_effect=Exception("network")):
            assert extract_kits_from_pdf("https://example.com/bad.pdf") is None
