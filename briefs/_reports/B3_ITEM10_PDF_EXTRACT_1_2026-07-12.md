# B3 SHIP REPORT — RESEARCHER_TRANCHE3 ITEM-10 (pdf_extract v1)

**Date:** 2026-07-12 · **Dispatch:** deputy #9855 (lead #9853) · **PR:** baker-master #544 (branch `b3/item10-pdf-extract`)
**Gate:** deputy review → non-author test-run (b1/b2/b4) → lead merge. Reply topic: `gate/item10-pdf-extract`.

## Done rubric — answered (not just "tests pass")

1. **Happy path → UTF-8 text on stdout, exit 0** ✅ — reportlab text fixture extracts "Hello World from ITEM-10" to stdout, exit 0, stdout non-empty.
2. **3 failure modes, distinct exit codes + stderr, none silent-empty** ✅:
   - `1 usage` — wrong arg count / flag (stderr `usage`).
   - `2 file_error` — missing OR corrupt/unparseable PDF (stderr `file_error`).
   - `3 encrypted_pdf` — password-protected, empty-password unlock denied (stderr `encrypted_pdf`).
   - `4 no_text_layer` — parses but no text (scanned) — asserted **exit 4 + empty stdout**, the explicit not-silent-empty case.
3. **Shell tests cover happy + all 3 modes, runnable + green** ✅ — `bash scripts/tests/test_pdf_extract.sh` → **PASS=17 FAIL=0 SKIP=0**, exit 0. Fixtures generated offline (reportlab text/blank + pypdf encryption); suite SKIPs clean (exit 0) if libs absent, never a false FAIL.
4. **pypdf pinned** ✅ — `pypdf==6.14.2` in requirements.txt.
5. **Design report** ✅ — `scripts/tests/DESIGN_pdf_extract_ITEM10.md`: usage, exit-code table, engine rationale, v1 limits (no OCR/network/structured-output), future method.md wiring note.
6. **NO pipeline/method.md wiring** ✅ — standalone tool only.

## Files
- `scripts/pdf_extract.sh` (new) · `scripts/tests/test_pdf_extract.sh` (new) · `scripts/tests/DESIGN_pdf_extract_ITEM10.md` (new) · `requirements.txt` (+1 pin).

## Notes
- Engine pypdf per brief; repo also has pdfplumber/PyMuPDF but v1 stays single-engine + dependency-light. Empty-password unlock attempted before declaring exit 3 (many PDFs flag `is_encrypted` yet read with `""`).
- No network, no OCR. Scanned PDFs route to exit 4 (the pipeline's future OCR-reextract signal — noted in design, not built).
