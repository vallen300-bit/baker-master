"""Baker AI — File-type text extractors.

Each extractor takes a file path and returns extracted text as a string.
Supported: .txt, .md, .pdf, .csv, .xlsx, .json
"""
import csv
import io
import json
import logging
from pathlib import Path

logger = logging.getLogger("baker.ingest.extractors")

# Supported extensions mapped to their extractor functions
SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".csv", ".xlsx", ".json"}


def extract(filepath: Path) -> str:
    """Extract text from a file based on its extension.

    Args:
        filepath: Path to the file to extract text from.

    Returns:
        Extracted text content as a string.

    Raises:
        ValueError: If file type is not supported.
        FileNotFoundError: If file doesn't exist.
    """
    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    ext = filepath.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    extractor = _EXTRACTORS[ext]
    text = extractor(filepath)

    if not text or not text.strip():
        logger.warning("Extracted empty text from %s", filepath.name)
        return ""

    return text.strip()


def _extract_text(filepath: Path) -> str:
    """Extract plain text / markdown files."""
    return filepath.read_text(encoding="utf-8", errors="replace")


def _extract_pdf(filepath: Path) -> str:
    """Extract text from PDF using pdfplumber."""
    try:
        import pdfplumber
    except ImportError:
        raise ImportError(
            "pdfplumber is required for PDF extraction. "
            "Install it: pip install pdfplumber"
        )

    pages = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n\n".join(pages)


def _extract_csv(filepath: Path) -> str:
    """Extract CSV as row-per-line text with headers."""
    with open(filepath, "r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        return ""

    headers = rows[0]
    lines = []
    for row in rows[1:]:
        pairs = []
        for h, v in zip(headers, row):
            if v.strip():
                pairs.append(f"{h}: {v}")
        if pairs:
            lines.append("; ".join(pairs))

    return "\n".join(lines)


def _extract_xlsx(filepath: Path) -> str:
    """Extract Excel spreadsheet as text (all sheets)."""
    try:
        import openpyxl
    except ImportError:
        raise ImportError(
            "openpyxl is required for Excel extraction. "
            "Install it: pip install openpyxl"
        )

    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    parts = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue

        headers = [str(h) if h is not None else "" for h in rows[0]]
        lines = [f"[Sheet: {sheet_name}]"]

        for row in rows[1:]:
            pairs = []
            for h, v in zip(headers, row):
                if v is not None and str(v).strip():
                    pairs.append(f"{h}: {v}")
            if pairs:
                lines.append("; ".join(pairs))

        parts.append("\n".join(lines))

    wb.close()
    return "\n\n".join(parts)


def _extract_json(filepath: Path) -> str:
    """Extract JSON — handles Baker's {texts: [...]} format and generic JSON."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Baker-native format: {"texts": [{"text": "...", "metadata": {...}}, ...]}
    if isinstance(data, dict) and "texts" in data:
        items = data["texts"]
        parts = []
        for item in items:
            if isinstance(item, dict) and "text" in item:
                parts.append(item["text"])
        if parts:
            return "\n\n".join(parts)

    # Generic JSON — pretty-print
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


# Extension → extractor mapping
_EXTRACTORS = {
    ".txt": _extract_text,
    ".md": _extract_text,
    ".pdf": _extract_pdf,
    ".csv": _extract_csv,
    ".xlsx": _extract_xlsx,
    ".json": _extract_json,
}
