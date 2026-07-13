#!/usr/bin/env bash
# pdf_extract.sh — researcher local-PDF text extraction (v1).
#
# RESEARCHER_TRANCHE3 ITEM-10 (b3, 2026-07-12; deputy dispatch #9855).
# Standalone tool: NO method.md / pipeline wiring this pass.
#
# INPUT : exactly one positional arg — a LOCAL PDF file path. No network, no flags.
# OUTPUT: extracted plain text, UTF-8, to STDOUT (raw text — pipe-friendly, no JSON
#         wrapper). Nothing else goes to stdout; all diagnostics go to stderr.
# ENGINE: pypdf (pinned in requirements.txt). NO OCR in v1.
#
# FAIL-LOUD — distinct non-zero exit codes, each with a stderr reason token; the
# tool NEVER exits 0 with empty stdout:
#   0  ok            — text extracted, printed to stdout
#   1  usage         — wrong arg count / a flag where a path was expected
#   2  file_error    — missing / unreadable / corrupt (not a parseable PDF)
#   3  encrypted_pdf — password-protected; cannot read without the password
#   4  no_text_layer — parses, but yields no text (scanned image PDF — needs OCR, out of scope v1)
set -u

usage() {
    echo "pdf_extract: usage — exactly one positional PDF path, no flags" >&2
    echo "usage: pdf_extract.sh <local-pdf-path>" >&2
    exit 1
}

# Exactly one arg, and it must not look like a flag (no arg-driven exec / option smuggling).
[ "$#" -eq 1 ] || usage
case "$1" in
    -*) echo "pdf_extract: usage — leading-dash argument rejected (no flags; expected a path)" >&2; usage ;;
esac

PDF_EXTRACT_PATH="$1" python3 - <<'PY'
import os
import sys

# Force UTF-8 stdout regardless of locale so extracted text is emitted cleanly.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

path = os.environ.get("PDF_EXTRACT_PATH", "")

# (2) missing / unreadable before we even reach the parser.
if not path or not os.path.isfile(path):
    sys.stderr.write(f"pdf_extract: file_error — no such file: {path!r}\n")
    sys.exit(2)

try:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError, FileNotDecryptedError
except Exception as exc:  # dependency missing -> loud, not silent
    sys.stderr.write(f"pdf_extract: file_error — pypdf import failed: {exc}\n")
    sys.exit(2)

# (2) corrupt / not a real PDF -> PdfReadError (or other parse failure).
try:
    reader = PdfReader(path)
except (PdfReadError, OSError, ValueError, Exception) as exc:
    sys.stderr.write(f"pdf_extract: file_error — cannot parse PDF: {exc}\n")
    sys.exit(2)

# (3) encrypted -> try an empty-password unlock; if that does not grant access,
# it is genuinely protected and we cannot read it (fail loud, never silent-empty).
if reader.is_encrypted:
    granted = False
    try:
        granted = bool(reader.decrypt(""))
    except Exception:
        granted = False
    if not granted:
        sys.stderr.write("pdf_extract: encrypted_pdf — password-protected, cannot extract without password\n")
        sys.exit(3)

# Extract text across all pages. A per-page failure on an otherwise-readable PDF
# must not crash the whole run — collect what we can, and let the emptiness check
# below decide (a fully-unreadable doc yields "" -> no_text_layer / file_error).
parts = []
try:
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
except FileNotDecryptedError:
    sys.stderr.write("pdf_extract: encrypted_pdf — password-protected, cannot extract without password\n")
    sys.exit(3)
except Exception as exc:
    sys.stderr.write(f"pdf_extract: file_error — extraction failed: {exc}\n")
    sys.exit(2)

text = "\n".join(parts)

# (4) parses but no text layer -> a scanned/image PDF. NOT exit 0 + empty stdout.
if not text.strip():
    sys.stderr.write("pdf_extract: no_text_layer — no extractable text (scanned image PDF? OCR is out of scope in v1)\n")
    sys.exit(4)

sys.stdout.write(text)
if not text.endswith("\n"):
    sys.stdout.write("\n")
sys.exit(0)
PY