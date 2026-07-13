# DESIGN — pdf_extract.sh (RESEARCHER_TRANCHE3 ITEM-10, v1)

**Owner:** b3 · **Dispatch:** deputy #9855 (lead #9853) · **Date:** 2026-07-12
**Scope:** standalone local-PDF text extraction. NO method.md / researcher-pipeline wiring this pass.
**Layout (item-11 pattern):** `scripts/pdf_extract.sh` (tool) + `scripts/tests/test_pdf_extract.sh` (shell tests) + this design report.

## Usage

```bash
scripts/pdf_extract.sh <local-pdf-path>      # extracted UTF-8 text -> STDOUT, exit 0
```

- Exactly one positional argument: a **local** PDF path. No flags, no network.
- Output is **raw text**, UTF-8, on STDOUT — pipe-friendly, no JSON wrapper. All diagnostics go to STDERR.
- Pipe example: `scripts/pdf_extract.sh paper.pdf | grep -i "abstract"`.

## Exit-code table (fail-loud — never exit 0 with empty stdout)

| Code | Name            | Meaning                                                        | STDERR reason token |
|------|-----------------|----------------------------------------------------------------|---------------------|
| 0    | ok              | Text extracted; printed to stdout (guaranteed non-empty)       | —                   |
| 1    | usage           | Wrong arg count, or a flag where a path was expected           | `usage`             |
| 2    | file_error      | Missing / unreadable / corrupt (not a parseable PDF)           | `file_error`        |
| 3    | encrypted_pdf   | Password-protected; empty-password unlock did not grant access | `encrypted_pdf`     |
| 4    | no_text_layer   | Parses, but yields no text (scanned image PDF — needs OCR)     | `no_text_layer`     |

Each failure mode is a **distinct** non-zero code with a stderr token; none silent-empties. In particular, mode 4 (scanned/no-text) is explicitly **not** exit 0 + empty stdout — the exact anti-pattern the brief calls out.

## Engine rationale

- **pypdf** (pinned `pypdf==6.14.2` in requirements.txt) — pure-Python, no system deps, ships text extraction + encryption detection. Matches the brief's specified engine.
- The repo already carries `pdfplumber` and `PyMuPDF`, but the brief pins pypdf for this standalone v1; keeping to one engine keeps the tool dependency-light and the behavior deterministic. Layout/interface choices are v1-only and do not commit the future pipeline to pypdf.
- Encrypted handling attempts an **empty-password** unlock first (many PDFs are flagged `is_encrypted` but readable with `""`); only a genuinely locked doc returns exit 3.

## v1 limits (explicit)

- **No OCR.** A scanned/image-only PDF has no text layer → exit 4 (not a silent empty). OCR re-extraction is a separate concern (repo already has `PyMuPDF` + an `OCR_REEXTRACT_MISSING_1` path for the pipeline; out of scope here).
- **No network / no remote fetch.** Local path only.
- **No structured output.** Raw concatenated page text (`\n`-joined). Layout/columns/tables are not reconstructed — a later shape can add a `--json` mode if the pipeline needs page spans.
- **No password input.** Encrypted-with-a-real-password PDFs fail loud (exit 3) rather than prompting.

## Future method.md wiring (note only — NOT built this pass)

When the researcher pipeline ingests PDFs, `pdf_extract.sh` becomes the local-extraction primitive behind a `method.md` step:
- The pipeline calls it per local PDF; **exit 4** is the signal to route that document to the OCR re-extract path (PyMuPDF raster → OCR), rather than dropping it.
- **exit 2/3** are terminal per-document failures the pipeline should log fail-loud (bad/locked source), not silently skip.
- exit 0 stdout feeds the chunk/embed stage. A `--json` mode (text + per-page offsets) can be added if the pipeline needs provenance spans.
- Wiring itself (method.md edit, pipeline call site, routing table) is a separate brief — deliberately not touched here.

## Test evidence

`bash scripts/tests/test_pdf_extract.sh` → **PASS=17 FAIL=0 SKIP=0**, exit 0. Fixtures generated offline (reportlab text + blank PDFs, pypdf encryption). Covers: arg guards, happy-path (exit 0 + correct non-empty stdout), and all 3 fail-loud modes incl. the explicit "not silent-empty" assertions for encrypted + no-text. Suite SKIPs cleanly (exit 0) if fixture libs are absent, never a false FAIL.
