# B1 ship report — INGEST_SEARCH_DURABILITY_FOLLOWUPS_1 Part B (PR2)

**Date:** 2026-06-03 · **Author:** B1 · **For:** lead
**PR:** #290 (`b1/ingest-search-durability-followups-B` → `main`), commit `28e5e65`
**Predecessor:** Part A PR #288 merged `2b6da30` (all gates + architect SHIP-WITH-FOLLOWUPS).
**Brief:** `INGEST_SEARCH_DURABILITY_FOLLOWUPS_1` Part B (B1–B5; B5 = Part-A-review folds from codex #1748 + architect).

## What shipped

### B1 — durable Qdrant↔Postgres join (NOT deferred)
retriever.py work did not balloon, so B1 ships in full.
- `_embed_and_upsert` writes `document_id` + `matter_slug` into the `baker-documents`
  payload; threaded through `ingest_text` / `ingest_file`.
- Embed-time callers pass the id: `promote_attachment` → `ingest_text(document_id=result["doc_id"])`;
  `dropbox_trigger` stores PG first → `ingest_file(document_id=doc_id)` (`doc_id` bound to
  None before the try so 5b threads it even if 5a2 fails).
- `/api/ingest` embeds before it has the PG id → new `pipeline.set_document_payload(...)`
  patches the points' payload after `store_document_full` returns the id.
- `memory/retriever.py`: `_get_full_document_text` gains a `document_id` branch
  (`WHERE id = %s`, priority); enrichment uses `ctx.metadata["document_id"]` when present.
  **Legacy `source_path`/`filename` fallback intact** — only NEW ingests carry the id.

### B2 — `source_path` prefix contract, one place
`SOURCE_PREFIXES` + `_source_ilike_clause()` + `_source_case_sql()` back all three
surfaces (facet CASE, SQL source filter, `_derive_source`). Inert `m365` mapping added.
`%%` is correct on both SQL surfaces (facet no-params → literal `%%` which SQL LIKE
collapses; filter params → psycopg2 un-escapes to `%`). Parity vs old logic verified.

### B3 — `safe_filename` once in `/api/ingest`
`safe_filename = Path(file.filename).name` computed once; reused for ext, temp path,
`store_document_full`, response, logs.

### B4 — windowed-total bound
Semantic `total` documented as windowed (≤300-chunk over-fetch); response carries
`total_is_windowed: true` on the semantic path only.

### B5 (Part-A review folds)
- **B5.1** cardinality guard: `len(embeddings) != len(batch)` → failed batch.
- **B5.2** partial-embed postures made deliberate + documented at both call sites
  (`/api/ingest` neither-on-partial; `dropbox` PG-first; A3 query surfaces dropbox drift).
- **B5.3** `enrichment_failed` flag on semantic responses.

## Verification (literal)
- `tests/test_ingest_search_durability_partb.py` (new, 14) + `tests/test_documents_search_semantic.py` (+5).
- **90 pass** across touched test files (py3.12). `check_singletons.sh` OK. compile clean.
- **Full-suite diff vs baseline (`main`+Part A): zero new failures** (184 = 184; `comm -23` empty).

## Gate state
G1 lead → G2 /security-review → G3 codex → architect → POST_DEPLOY_AC.

## Flag for lead (separate cleanup — NOT this PR)
The suite leaks a `MagicMock` into `sys.modules['memory.store_back']` (conftest.py +
several tests manipulate it without restore), making a behavioural store monkeypatch
order-dependent. I caught this when my promote-attachment behavioural test passed in
isolation but failed under full-suite order; converted it to a deterministic
source-guard. The leak is a real suite-isolation bug worth a small standalone cleanup
brief — it will keep biting behavioural tests that touch `store_back`.

## Dispatch status
Both PRs of the two-PR mandate are now built: Part A merged (#288 / `2b6da30`),
Part B open (#290). Once Part B clears its gate chain + POST_DEPLOY_AC, the
`INGEST_SEARCH_DURABILITY_FOLLOWUPS_1` dispatch is fully complete (mailbox flip is lead's).
