"""Universal attachment text-read service for Baker desks.

One desk-facing wrapper over Baker's file extractors. It decides the extraction
path by file type (text PDF, scanned PDF OCR fallback, image vision, DOCX, XLSX,
CSV, JSON, text) and returns a small status envelope instead of making every
desk know extractor details.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger("baker.tools.attachment_read_service")


def _method_for_ext(ext: str) -> str:
    if ext == ".pdf":
        return "pdf_text_or_ocr"
    if ext in {".jpg", ".jpeg", ".png", ".heic", ".webp"}:
        return "image_vision"
    if ext == ".docx":
        return "docx_text"
    if ext == ".xlsx":
        return "xlsx_text"
    if ext in {".csv", ".txt", ".md", ".json"}:
        return "plain_text"
    return "unsupported"


def extract_attachment_text(
    file_bytes: bytes,
    filename: str,
    mime_type: str | None = None,
) -> dict[str, Any]:
    """Extract text from attachment bytes using Baker's common extractor stack.

    Fault-tolerant: never raises to the caller.
    """
    filename = filename or "attachment"
    ext = Path(filename).suffix.lower()
    method = _method_for_ext(ext)
    if method == "unsupported":
        return {
            "text": "",
            "text_extracted": False,
            "extraction_status": "unsupported",
            "extraction_method": method,
            "text_error": f"unsupported attachment type: {ext or '<none>'}",
        }

    try:
        from tools.ingest.extractors import SUPPORTED_EXTENSIONS, extract
        if ext not in SUPPORTED_EXTENSIONS:
            return {
                "text": "",
                "text_extracted": False,
                "extraction_status": "unsupported",
                "extraction_method": method,
                "text_error": f"unsupported attachment type: {ext}",
            }

        with tempfile.NamedTemporaryFile(suffix=ext, delete=True) as tmp:
            tmp.write(file_bytes)
            tmp.flush()
            text = extract(Path(tmp.name)) or ""
    except Exception as e:
        logger.warning("attachment extraction failed (%s): %s", filename, type(e).__name__)
        return {
            "text": "",
            "text_extracted": False,
            "extraction_status": "error",
            "extraction_method": method,
            "text_error": str(e),
        }

    text = text.strip()
    return {
        "text": text,
        "text_extracted": bool(text),
        "extraction_status": "extracted" if text else "no_text",
        "extraction_method": method,
    }
