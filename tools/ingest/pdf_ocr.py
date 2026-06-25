"""Shared PDF OCR fallback — PyMuPDF raster + Gemini 2.5 Pro vision.

BAKER_M365_ATTACHMENT_PDF_OCR_FALLBACK_1. Factored out of
``outputs/dashboard.py:_ocr_extract_batch`` so the same hardened core can be
reused by ``tools/ingest/extractors._extract_pdf`` (the path
``baker_email_attachment_read`` flows through) without importing the 11.7k-line
dashboard module.

Engine: PyMuPDF (``fitz``) rasterizes each page @200dpi → JPEG → base64 →
Gemini 2.5 Pro vision (``orchestrator.gemini_client.call_pro``). This is the
SAME stack already proven live on Render Linux via
``POST /api/documents/ocr-extract-missing`` — no Apple Vision, no tesseract, no
poppler, no Dockerfile/apt change. PyMuPDF ships its own native libs as a wheel.

OCR is expensive: callers must invoke this ONLY when the cheap text-layer path
(pdfplumber) yields nothing — never on a digital PDF.

The dashboard batch can later adopt ``ocr_pdf_file`` (follow-up, out of scope
here); the result object carries everything that path needs (truncation flag +
terminal reason) so the adoption is mechanical.
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("baker.ingest.pdf_ocr")

# Mirrors the dashboard batch constants (kept identical so behaviour is uniform
# across the OCR surfaces). Tunable here once both surfaces read this module.
OCR_MAX_PAGES = 40                   # cap vision cost/time on big scans
OCR_MIN_CHARS = 20                   # anti-hallucination floor: keep only if legible
OCR_PROMPT = (
    "Transcribe ALL text on this page verbatim, preserving reading order. "
    "Output ONLY the transcribed text, no commentary. If the page has NO legible "
    "text (blank, pure image/photo, or an unreadable low-resolution chart), output "
    "exactly the token [[UNREADABLE]] and nothing else."
)
_UNREADABLE = "[[UNREADABLE]]"


@dataclass
class PdfOcrResult:
    """Outcome of an OCR fallback attempt. Never carries a partial write.

    text:      legible transcription ("" when nothing usable was recovered).
    truncated: True iff the PDF exceeded OCR_MAX_PAGES (only the cap was read).
    reason:    None on success; otherwise a terminal/transient marker —
               'rasterize_failed' | 'cost_breaker' | 'gemini_error' |
               'unreadable' | 'empty_ocr'. (cost_breaker / gemini_error are
               transient; the rest are deterministic-terminal.)
    """

    text: str = ""
    truncated: bool = False
    reason: str | None = None


def ocr_pdf_file(filepath: str | Path) -> PdfOcrResult:
    """Best-effort OCR of a PDF on disk. NEVER raises.

    Returns a :class:`PdfOcrResult`. ``text`` is "" unless the recovered,
    legible transcription is at least ``OCR_MIN_CHARS`` and not every page was
    ``[[UNREADABLE]]`` (anti-hallucination guard — better empty than invented).
    """
    # fitz (PyMuPDF) — rasterizer. Import here so a missing wheel degrades to a
    # clean reason instead of breaking module import for non-OCR callers.
    try:
        import fitz  # PyMuPDF
    except Exception as imp_err:  # pragma: no cover - dep is in requirements.txt
        logger.error("pdf_ocr: PyMuPDF (fitz) unavailable: %s", type(imp_err).__name__)
        return PdfOcrResult(reason="rasterize_failed")

    try:
        from orchestrator.gemini_client import call_pro
    except Exception as imp_err:  # pragma: no cover
        logger.error("pdf_ocr: gemini_client unavailable: %s", type(imp_err).__name__)
        return PdfOcrResult(reason="gemini_error")

    # Cost governor — FAIL-OPEN: an instrumentation import error must only drop
    # the governor for this call, never abort recovery (repo lesson #68;
    # precedent dashboard.py:_ocr_extract_batch).
    governor = None
    try:
        from orchestrator.cost_monitor import check_circuit_breaker, log_api_cost
        governor = (check_circuit_breaker, log_api_cost)
    except Exception as imp_err:
        logger.warning("pdf_ocr: cost_monitor unavailable (fail-open, no governor): %s",
                       type(imp_err).__name__)

    try:
        pdf = fitz.open(str(filepath))
    except Exception as rz_err:
        logger.error("pdf_ocr: rasterize open failed: %s", type(rz_err).__name__)
        return PdfOcrResult(reason="rasterize_failed")

    page_texts: list[str] = []
    truncated = False
    try:
        n_pages = pdf.page_count
        truncated = n_pages > OCR_MAX_PAGES
        if truncated:
            logger.warning("pdf_ocr: %d pages > cap %d; transcribing first %d only "
                           "(truncated=true)", n_pages, OCR_MAX_PAGES, OCR_MAX_PAGES)
        for pno in range(min(n_pages, OCR_MAX_PAGES)):
            # Cost governor: check BEFORE each call. Trip ⇒ stop this doc and
            # write NOTHING (partial OCR is worse than none — a later un-throttled
            # caller re-recovers in full). Fail-open on a check error.
            if governor is not None:
                try:
                    allowed, daily_cost = governor[0]()
                except Exception as cb_err:
                    logger.warning("pdf_ocr: breaker check failed (fail-open): %s",
                                   type(cb_err).__name__)
                    allowed, daily_cost = True, 0.0
                if not allowed:
                    logger.error("pdf_ocr: blocked by circuit breaker (€%.2f) at page %d "
                                 "— writing nothing", daily_cost, pno)
                    return PdfOcrResult(truncated=truncated, reason="cost_breaker")
            page = pdf.load_page(pno)
            pix = page.get_pixmap(dpi=200)
            jpg = pix.tobytes("jpeg")
            b64 = base64.b64encode(jpg).decode("ascii")
            resp = call_pro(
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": OCR_PROMPT},
                ]}],
                max_tokens=4000,
            )
            page_texts.append((getattr(resp, "text", "") or "").strip())
            # Log cost AFTER each call. getattr-safe + fail-open.
            if governor is not None:
                try:
                    usage = getattr(resp, "usage", None)
                    in_tok = getattr(usage, "input_tokens", 0) or 0
                    out_tok = getattr(usage, "output_tokens", 0) or 0
                    governor[1]("gemini-2.5-pro", in_tok, out_tok,
                                source="pdf_ocr", capability_id="ocr_extract")
                except Exception as lc_err:
                    logger.warning("pdf_ocr: cost-log failed (fail-open): %s",
                                   type(lc_err).__name__)
    except Exception as g_err:
        logger.error("pdf_ocr: gemini vision failed: %s", type(g_err).__name__)
        return PdfOcrResult(truncated=truncated, reason="gemini_error")
    finally:
        try:
            pdf.close()
        except Exception:
            pass

    # Anti-hallucination guard: every page blank/unreadable ⇒ recover nothing.
    all_unreadable = (
        all(pt in ("", _UNREADABLE) for pt in page_texts) if page_texts else True
    )
    if all_unreadable:
        return PdfOcrResult(truncated=truncated, reason="unreadable")
    legible = "\n\n".join(page_texts).replace(_UNREADABLE, "").strip()
    if len(legible) < OCR_MIN_CHARS:
        # Sub-threshold extraction is deterministic-terminal (near-empty scan).
        return PdfOcrResult(truncated=truncated, reason="empty_ocr")
    return PdfOcrResult(text=legible, truncated=truncated, reason=None)
