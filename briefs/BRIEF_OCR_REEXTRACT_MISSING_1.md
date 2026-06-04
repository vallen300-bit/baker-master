# BRIEF: OCR_REEXTRACT_MISSING_1 — recover ~580 blank-text scanned docs via Gemini 2.5 Pro vision + fail-loud guard

## Context
~580 `documents` rows have NULL/blank `full_text` because they are scanned/image PDFs and
the extractor (`pdfplumber`, no OCR) returns `""` (`tools/ingest/extractors.py:61`,
`_extract_pdf` :71-87). They are invisible to search AND ineligible for the reingest
endpoint (which requires `_HAS_EXTRACTED_TEXT`, `outputs/dashboard.py:1884`). codex profile
(#1792) confirmed 576/580 are recoverable from their Dropbox source files (572 PDF + 4 DOCX,
all under `/Baker-Feed` 560 + `/Baker-Project` 16; 0 re-upload needed).

Two parts: **Part A** = a server-side OCR re-extract endpoint that downloads each blank doc
from Dropbox, reads it with Gemini 2.5 Pro vision (Director-chosen — the strongest reader on
our exact failure cases: tiny text, dense tables), and populates `full_text`. **Part B** =
a fail-loud guard so empty extraction is never silently swallowed again. Once Part A populates
`full_text`, the existing `POST /api/documents/reingest-missing` (3cf00cc) embeds them — this
brief does NOT embed; it is the upstream sibling.

Model choice (Director-ratified 2026-06-04): **Gemini 2.5 Pro** — already wired (Director
Card; `GEMINI_API_KEY` on Render), so no new vendor and no new data-residency exposure
(Baker already ships doc text to Voyage + Anthropic).

### Surface contract: N/A — backend admin JSON endpoint + ingest-path guard; no clickable/dashboard surface.

## Harness V2
- **Routed owner:** B-code (idle: b1, holds freshest ingest/reingest context).
- **Task class:** production-facing recovery feature + reliability guard.
- **Context Contract:** all signatures, file:line, deps, and the Dropbox/Gemini/raster patterns are below; no discovery needed.
- **Done rubric (answer literally — NOT "tests pass"):**
  1. Live `dry_run=false&limit=3` prod run: ≥1 previously-blank doc now has non-empty `full_text`; paste the doc ids + `text_len` before/after.
  2. That same doc then satisfies `_HAS_EXTRACTED_TEXT` and is returned by `reingest-missing?dry_run=true` (proves it feeds the embed path).
  3. A deliberately-unreadable doc is NOT written as empty — it lands in the failure list with a reason, and `full_text` stays NULL (fail-loud, no garbage write).
  4. Concurrent `GET /health` returns 200 <3s during the OCR run (offload holds, like #293).
- **Gate plan:** G0 codex-arch (brief) → G1 lead (literal pytest) → G2 /security-review → G3 codex (PR) → merge → POST_DEPLOY_AC_VERDICT v1.

## Estimated time: ~3-4h
## Complexity: Medium-High
## Prerequisites: PR #293 merged (offload+lock pattern to mirror); `GEMINI_API_KEY` live on Render (verify via a 1-page probe before the batch).

---

## Fix 1 (Part A): `POST /api/documents/ocr-extract-missing`

### Problem
The 580 blank docs need their text recovered from the source files. The lead picker has no
prod creds; a server-side endpoint runs where Dropbox + Gemini keys already live.

### Current State (verified)
- **Blank set:** `documents` rows where `full_text IS NULL OR btrim(full_text) = ''`. Source path = Dropbox absolute path (e.g. `/Baker-Feed/x.pdf`), stored at `triggers/dropbox_trigger.py:249`.
- **Dropbox download (server-side, API — no local mount on Render):** `triggers/dropbox_client.py:198` `DropboxClient.download_file(path: str, dest_dir: Path) -> Path`; singleton via `DropboxClient._get_global_instance()` (pattern: `triggers/dropbox_trigger.py:34-37, 208-219`). Dropbox creds already on Render (the ingest poller uses them).
- **Gemini 2.5 Pro vision client:** `orchestrator/gemini_client.py` — `call_pro(messages: list, max_tokens: int = 2000, system: str = None) -> GeminiResponse` (:148); model id `config.gemini.pro_model == "gemini-2.5-pro"` (`config/settings.py:69`); enabled flag `config.gemini.enabled` (`BAKER_USE_GEMINI`, default true); key `GEMINI_API_KEY` (:67). Vision message part format (:81-92): `{"type":"image","source":{"type":"base64","media_type":"image/jpeg","data": <b64>}}`. Response text via `response.text` (:124).
- **Write target:** `memory/store_back.py:432` `store_document_full(source_path, filename, file_hash, full_text, token_count=0, owner="shared")` — UPSERT `ON CONFLICT (file_hash)`, sets `full_text` + `search_vector` (`outputs`/store_back.py:459-471). Column is `full_text`.
- **Feeds:** once `full_text` non-blank, the doc satisfies `_HAS_EXTRACTED_TEXT` (`outputs/dashboard.py:1884`) → eligible for `reingest-missing`.
- **NEW dependency required:** rasterization. `requirements.txt` has `pdfplumber` + `Pillow` but NO PDF→image backend (no PyMuPDF/pdf2image/Wand), and `pdfplumber.Page.to_image()` needs an external render backend not installed. **Add `PyMuPDF>=1.24.0`** (pure wheel, no system binary): `fitz.open(path)` → `page.get_pixmap(dpi=200)` → `pix.tobytes("jpeg")`.

### Implementation
Add `POST /api/documents/ocr-extract-missing` in `outputs/dashboard.py` (auth `Depends(verify_api_key)`, tag `documents`). First `grep -n "ocr-extract-missing" outputs/dashboard.py` to confirm no shadow route.

**Mirror PR #293's proven concurrency pattern exactly** (it just shipped + passed AC):
- `async def`, `limit: int = Query(3, ge=1, le=25)` (OCR+vision is far heavier than embed — keep batches tiny), `dry_run: bool = Query(True)`.
- Selector (own predicate constant, bounded, `conn.rollback()` in except, `_put_conn` in finally):
  ```sql
  SELECT d.id, d.filename, d.source_path, d.file_hash, d.matter_slug
  FROM documents d
  WHERE (d.full_text IS NULL OR btrim(d.full_text) = '')
    AND lower(d.filename) ~ '\.(pdf|docx)$'
  ORDER BY d.ingested_at DESC NULLS LAST
  LIMIT %s
  ```
- **dry_run:** return `{dry_run:true, blank_count, would_process:[{id, filename, source_path}]}`. No download, no model call, no write.
- **Write path:** single-runner advisory lock on a **dedicated DIRECT** connection (autocommit=True), EXACTLY as PR #293 (`_OCR_ADVISORY_LOCK_KEY = 0x4F435231  # "OCR1"` — distinct from REIN), fail-loud `no_direct_dsn` if `host_direct` unset. Run the blocking per-doc work via `await asyncio.to_thread(_ocr_extract_batch, candidates)` so the event loop stays free.
- **`_ocr_extract_batch(candidates)`** (module-level sync helper, mirror `_reingest_embed_batch`): for each doc, in its own try/except (one failure must not abort batch):
  1. Download: `local = DropboxClient._get_global_instance().download_file(source_path, Path(tmpdir))` (use a `tempfile.mkdtemp(prefix="baker_ocr_")`; clean up in finally).
  2. Rasterize (PDF): `import fitz; doc = fitz.open(local)`; cap at `MAX_OCR_PAGES = 40` (flag `truncated=True` if more — bounds cost/time); per page `pix = page.get_pixmap(dpi=200); jpg = pix.tobytes("jpeg")`; base64-encode.
     - DOCX (only 4): extract text directly via the existing `extract()` path (`tools/ingest/extractors.py`) — they are not image docs; if that still yields empty, treat as a failure (manual).
  3. Gemini per page: `call_pro(messages=[{"role":"user","content":[{"type":"image","source":{"type":"base64","media_type":"image/jpeg","data": b64}}, {"type":"text","text": OCR_PROMPT}]}], max_tokens=4000)`. `OCR_PROMPT` = "Transcribe ALL text on this page verbatim, preserving reading order. Output ONLY the transcribed text, no commentary. If the page has NO legible text (blank, pure image/photo, or an unreadable low-resolution chart), output exactly the token [[UNREADABLE]] and nothing else." Concatenate page outputs with `\n\n`.
  4. **Quality / anti-hallucination guard (fail-loud — vision models fabricate):** compute `legible = result with [[UNREADABLE]] page-markers removed`. Write `full_text` ONLY if `len(legible.strip()) >= MIN_OCR_CHARS (default 20)` AND not every page was `[[UNREADABLE]]`. Otherwise DO NOT write — append `{id, filename, reason}` to `failed` (reason `unreadable` / `empty_ocr` / `download_failed` / `gemini_error` / `rasterize_failed`). Never write `full_text=''`.
  5. On pass: `store._get_store().store_document_full(source_path=source_path, filename=filename, file_hash=file_hash, full_text=legible, token_count=<len//4>, owner="shared")`. (UPSERT on file_hash updates the existing row in place.)
- **Return:** `{dry_run:false, limit, blank_count, attempted, recovered, failed:[{id,reason}], remaining_after}` where `remaining_after` re-counts the blank set.
- **Do NOT embed here.** After a run, the operator calls `reingest-missing` to embed the now-populated docs.

### Key Constraints
- Mirror #293's lock/offload/autocommit/close-dedicated-conn discipline verbatim (don't reinvent; don't `store._put_conn` the lock conn).
- Tiny default limit (3) + `MAX_OCR_PAGES` cap — vision on big scans is slow; pace by small limits, watch `remaining_after`, do NOT rely on the HTTP response (heavy docs exceed the 120s client timeout while the server completes — proven on #293's AC; idempotent, re-poll the count).
- Idempotent: re-running on an already-recovered doc just re-UPSERTs same `full_text` (or skips since it's no longer in the blank set).
- Every DB query has a LIMIT; every except has `conn.rollback()`; temp files cleaned in finally.
- NO secrets in code — `GEMINI_API_KEY` / Dropbox creds are read from env/config only.
- Respect `config.gemini.enabled` — if false, return `{"error":"gemini_disabled"}` (fail loud, don't silently skip).

### Verification
- `pytest tests/test_ocr_reextract_missing.py -v` (new) — mock `DropboxClient.download_file`, `fitz`, `call_pro`, and `store_document_full`; assert: dry_run writes nothing; a good doc writes non-empty full_text; an all-`[[UNREADABLE]]` doc writes NOTHING and lands in `failed`; one doc raising does not abort the batch; lock-held ⇒ `backfill_in_progress`.
- Live: Done rubric AC1-AC4.

---

## Fix 2 (Part B): fail-loud on silent empty extraction

### Problem
Today a scanned PDF flows through ingest, `extract()` returns `""` (`extractors.py:61`,
logged only as `warning`), `store_document_full` writes an empty row with no guard
(`store_back.py:459-471`), and `document_pipeline.py:382-392` silently `return`s (triage
`'empty'`). The 580-doc backlog accumulated invisibly. This must never be silent again.

### Implementation (minimal, no schema migration)
In `tools/document_pipeline.py` where a doc triages `'empty'` (`:388-392`) — i.e. extraction
produced no usable text for a PDF/DOCX that DOES have source bytes — upgrade the silent skip
to a **fail-loud signal**:
1. `logger.error(...)` (not warning) with doc id + filename + source_path + a stable marker
   string `OCR_CANDIDATE` so it is greppable/alertable.
2. Write an alert row via the existing alert mechanism (B-code: `grep -n "INSERT INTO alerts\|def .*alert" outputs/dashboard.py memory/store_back.py triggers/` to find the canonical alert-insert; reuse it — do NOT invent a new table). Alert title e.g. `"Doc {id} extracted empty — OCR candidate"`, category that the dashboard already surfaces, deduped on doc id.
3. This makes the blank set visible going forward; the Part A endpoint is the recovery tool the alert points to.

If no clean alert-insert helper exists, fall back to the ERROR-level `OCR_CANDIDATE` log only,
and flag to AH1 that an alert surface is needed — do NOT add a migration in this brief.

### Key Constraints
- Behavior-preserving for non-empty docs (only the empty-triage branch changes).
- No new DB column / migration in this brief.
- Dedupe alerts (don't re-alert the same doc id every poll).

### Verification
- Unit: feed `triage_document` an empty-text PDF doc → assert ERROR log with `OCR_CANDIDATE` + (if wired) one alert insert; assert a normal doc is unaffected.

---

## Files Modified
- `outputs/dashboard.py` — new `POST /api/documents/ocr-extract-missing` + `_ocr_extract_batch` helper + `_OCR_ADVISORY_LOCK_KEY` (mirror #293's lock/offload).
- `requirements.txt` — add `PyMuPDF>=1.24.0`.
- `tools/document_pipeline.py` — fail-loud on empty-extraction triage (Part B).
- `tests/test_ocr_reextract_missing.py` — new (Part A tests).
- `tests/` — extend the pipeline test for the Part B fail-loud signal.

## Do NOT Touch
- `tools/ingest/extractors.py` extraction logic (the OCR path is a separate recovery surface, not a change to the live extractor — Phase 2 could auto-route, out of scope here).
- The reingest endpoint / `_HAS_EXTRACTED_TEXT` / `_REINGEST_MISSING_QDRANT_PREDICATE` (just shipped, correct).
- `memory/store_back.py` `store_document_full` signature (consume as-is; the empty guard lives in the OCR endpoint, which simply never calls it with empty text).
- `tools/ingest/pipeline.py` `ingest_text`.

## Quality Checkpoints (post-deploy)
1. `GEMINI_API_KEY` verified live with a 1-page probe before the batch.
2. Live `dry_run=false&limit=3`: ≥1 doc recovered (full_text non-empty); ids + text_len pasted.
3. Recovered doc now appears in `reingest-missing?dry_run=true`.
4. An unreadable doc stays NULL + lands in `failed` (no empty/garbage write).
5. Concurrent `GET /health` 200 <3s during the run.
6. Pace the full ~580 by small limits, watching `blank_count` fall (not HTTP response).

## Verification SQL
```sql
-- blank set size (should fall as OCR runs); single COUNT, no LIMIT needed
SELECT COUNT(*) FROM documents
WHERE (full_text IS NULL OR btrim(full_text) = '')
  AND lower(filename) ~ '\.(pdf|docx)$';
```

## POST_DEPLOY_AC_VERDICT v1 (B-code fills on prod after merge+deploy)
- AC1 recovery: PASS/FAIL + recovered doc ids + before/after text_len.
- AC2 feeds-reingest: PASS/FAIL + the doc now in `reingest-missing?dry_run=true`.
- AC3 fail-loud-no-garbage: PASS/FAIL + the unreadable doc still NULL + in `failed`.
- AC4 health-during-OCR: PASS/FAIL + concurrent `/health` timestamp.
- Overall: PASS only if all four pass live.
