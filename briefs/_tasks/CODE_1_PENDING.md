---
status: COMPLETE
brief_id: OCR_REEXTRACT_MISSING_1
merged_pr: 294
merged_sha: a34f1ed
gates: G0 #1843 / G1 #1856 / G2 CLEAR / G3 #1879 (after #1865 fold)
post_deploy_ac: PENDING — b1 runs once Render deploys a34f1ed
dispatch: OCR_REEXTRACT_MISSING_1
to: b1
from: lead
dispatched_by: lead
task_class: production recovery feature + reliability guard
harness_v2: applies
gate_plan: G0 codex PASS (#1843, b92c31d) → G1 lead (literal pytest) → G2 /security-review → G3 codex (PR) → merge → POST_DEPLOY_AC_VERDICT v1
brief_path: briefs/BRIEF_OCR_REEXTRACT_MISSING_1.md
---

# B1 dispatch — OCR_REEXTRACT_MISSING_1

**Full spec: `briefs/BRIEF_OCR_REEXTRACT_MISSING_1.md` (commit b92c31d). codex G0 v2 PASS (#1843). Read the brief — this envelope is the pointer + gate contract.**

## Context Contract
Recover ~580 blank-`full_text` scanned PDFs/DOCX via **Gemini 2.5 Pro vision** (Director-ratified reader). You hold the freshest reingest/ingest context (#291/#293). The brief carries every signature + file:line: `DropboxClient.download_file` (triggers/dropbox_client.py:198), `call_pro` vision (orchestrator/gemini_client.py:148, message image-part format :81-92), `_get_store`, the targeted-UPDATE write, and the document_pipeline fail-loud branch.

## Scope (Option A — codex PASS at b92c31d)
1. **Part A:** `POST /api/documents/ocr-extract-missing` — select blank PDF/DOCX, download from Dropbox, rasterize via **new dep PyMuPDF@200dpi**, `call_pro` vision per page (verbatim-transcribe prompt, `[[UNREADABLE]]` for illegible), anti-hallucination guard (write only if legible≥20 chars & not all-unreadable, else fail into `failed` — NEVER write empty). **Write = targeted `UPDATE documents SET full_text/token_count/search_vector/ingested_at WHERE id=%s` (NOT store_document_full — preserves owner, exact row; codex folds 1/3/4). Verify rowcount==1.** Mirror #293's offload+direct-conn advisory lock (key `OCR1`, autocommit=True). Default limit=3, MAX_OCR_PAGES=40. Does NOT embed — feeds the reingest endpoint.
2. **Part B:** fail-loud at `tools/document_pipeline.py:381-384` (the `if not full_text:` early return — NOT the triage branch; codex fold 2): ERROR + `OCR_CANDIDATE` marker + alert (reuse existing alert-insert, no migration).
3. Tests: targeted-UPDATE happy path, **owner-preserved (dimitry-owned blank stays dimitry)**, all-`[[UNREADABLE]]`→no write+failed, one-doc-raise doesn't abort, lock-held⇒backfill_in_progress, Part B via `run_pipeline` with empty `_get_document_text` (mandatory).

Copy-pasteable diffs + Do-NOT-touch + line refs are in the brief. codex left an "implementation note for B-code" on bus #1843 — read it.

## Gate contract (Harness V2)
- **Done rubric (literal):** (1) live `dry_run=false&limit=3` recovers ≥1 doc — paste ids + before/after text_len; (2) that doc then appears in `reingest-missing?dry_run=true`; (3) an unreadable doc stays NULL + in `failed`; (4) concurrent `GET /health` 200 <3s during the run.
- **Gates:** G0 PASS (#1843) → G1 lead literal `pytest tests/test_ocr_reextract_missing.py -v` → G2 `/security-review` → G3 codex on PR → AH1 merge → you fill `POST_DEPLOY_AC_VERDICT v1`.
- Ship report answers the done rubric literally; bus to lead on ship.
- **NOTE: baker-master scheduler is currently DOWN (separate incident, lead's lane). Your OCR endpoint is request-path, unaffected — proceed; do not touch the scheduler.**
