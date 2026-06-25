"""BAKER_M365_ATTACHMENT_PDF_OCR_FALLBACK_1 — OCR fallback in _extract_pdf.

No network. Gemini (call_pro) is mocked. Fixtures are generated with PyMuPDF
(fitz, already a dep) at test time:
  - a DIGITAL PDF (real text layer)  -> pdfplumber extracts it, OCR NOT called.
  - a SCANNED PDF (blank/no text)    -> pdfplumber returns "", OCR fallback fires.
"""
from pathlib import Path
from unittest import mock

import pytest

fitz = pytest.importorskip("fitz")          # PyMuPDF
pytest.importorskip("pdfplumber")

from tools.ingest.extractors import _extract_pdf
from tools.ingest import pdf_ocr


def _digital_pdf(path: Path) -> Path:
    """A PDF with a real, extractable text layer."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Quarterly report digital text layer content.")
    doc.save(str(path))
    doc.close()
    return path


def _scanned_pdf(path: Path) -> Path:
    """A PDF with NO text layer (blank page) — stands in for an image-only scan."""
    doc = fitz.open()
    doc.new_page()                          # no insert_text -> no text layer
    doc.save(str(path))
    doc.close()
    return path


def _fake_resp(text):
    r = mock.MagicMock()
    r.text = text
    r.usage = mock.MagicMock(input_tokens=10, output_tokens=20)
    return r


def test_digital_pdf_uses_pdfplumber_no_ocr(tmp_path):
    """A text-layer PDF returns pdfplumber text and NEVER triggers OCR (no spend)."""
    pdf = _digital_pdf(tmp_path / "digital.pdf")
    with mock.patch.object(pdf_ocr, "ocr_pdf_file") as m_ocr:
        out = _extract_pdf(pdf)
    assert "digital text layer" in out
    m_ocr.assert_not_called()               # cost-aware: no needless OCR


def test_scanned_pdf_falls_back_to_ocr(tmp_path):
    """A no-text-layer PDF returns OCR-recovered text via the Gemini fallback."""
    pdf = _scanned_pdf(tmp_path / "scanned.pdf")
    transcription = "RECOVERED SCANNED INVOICE TOTAL 1234 EUR"   # >= OCR_MIN_CHARS
    with mock.patch("orchestrator.gemini_client.call_pro", return_value=_fake_resp(transcription)) as m_pro:
        out = _extract_pdf(pdf)
    assert transcription in out
    assert m_pro.called                     # OCR engine actually invoked


def test_scanned_pdf_all_unreadable_returns_empty(tmp_path):
    """If every page is [[UNREADABLE]], the anti-hallucination guard returns ""."""
    pdf = _scanned_pdf(tmp_path / "blank.pdf")
    with mock.patch("orchestrator.gemini_client.call_pro", return_value=_fake_resp("[[UNREADABLE]]")):
        out = _extract_pdf(pdf)
    assert out == ""


def test_ocr_failure_is_non_fatal(tmp_path):
    """An OCR exception must degrade to "" — never propagate to the read tool."""
    pdf = _scanned_pdf(tmp_path / "boom.pdf")
    with mock.patch("orchestrator.gemini_client.call_pro", side_effect=RuntimeError("gemini down")):
        out = _extract_pdf(pdf)               # must not raise
    assert out == ""


def test_ocr_pdf_file_never_raises_on_bad_path():
    """ocr_pdf_file is fault-tolerant on a non-existent file."""
    result = pdf_ocr.ocr_pdf_file("/no/such/file.pdf")
    assert result.text == ""
    assert result.reason == "rasterize_failed"
