---
status: PENDING
brief_id: REINGEST_MISSING_QDRANT_ENDPOINT_1
dispatch: REINGEST_MISSING_QDRANT_ENDPOINT_1
to: b1
from: lead
dispatched_by: lead
task_class: feature (admin endpoint) + bulk-safe ops
harness_v2: applies
gate_plan: G0 codex (brief) → G1 lead (literal pytest) → G2 /security-review → G3 codex → POST_DEPLOY_AC
---

# B1 dispatch — REINGEST_MISSING_QDRANT_ENDPOINT_1

## Context Contract

You built the entire two-write ingest/search durability arc this session (#285/#287/#286/#288/#290), so you hold the freshest context on `tools/ingest/pipeline.py:ingest_text()`, `set_document_payload()`, the `_documents_missing_qdrant()` reconciliation helper (`outputs/dashboard.py:1853`), and the `/api/documents/reconciliation` endpoint (`outputs/dashboard.py:1928`).

**The gap this closes:** prod reconciliation reports **1,036** rows in the Postgres `documents` table with NO matching `baker-documents` Qdrant ingestion (`ingestion_log` filename join). Total docs = 5,597, so ~81% are concept-searchable and this is the legacy ~19% that is keyword-only (ILIKE) because it predates the Qdrant two-write. There is no tool today that re-embeds an existing PG doc into Qdrant; the only backfill that exists is the email-attachment slice (`scripts/backfill_email_attachments.py`, ~347 of the 1,036). This brief builds the general re-embed surface.

**Why an endpoint, not a script:** the lead picker has no prod creds (DATABASE_URL/QDRANT/VOYAGE all unset). A server-side endpoint runs where prod keys already live; lead triggers it via `X-Baker-Key`. Makes the backlog a repeatable, idempotent one-call fix instead of a fragile manual run.

## Problem

The 1,036 Postgres-only docs are invisible to semantic search. They already have extracted text in the `documents` table (confirm the actual text column name from the schema / `store_document_full` — do NOT guess, do NOT re-extract). They just never got chunked+embedded into Qdrant.

## Current State

- `_documents_missing_qdrant(limit)` (`outputs/dashboard.py:1853`) selects `documents` rows via `NOT EXISTS (SELECT 1 FROM ingestion_log il WHERE il.collection = 'baker-documents' AND il.filename = d.filename)`, returning `id, filename, source_path, matter_slug, ingested_at`. Read-only; does not auto-repair.
- `pipeline.ingest_text(full_text, filename, source_path, collection='baker-documents', file_hash=None, document_id=None, matter_slug=None, skip_dedup=False, ...)` (`tools/ingest/pipeline.py:369`) chunks → embeds → upserts → writes `ingestion_log`. Idempotent: dedup short-circuits on `(filename, file_hash)` in `ingestion_log`; point IDs deterministic. Returns `IngestResult` (`.chunk_count`, `.point_ids`, `.skipped`, `.skip_reason`).

## Implementation

Add **`POST /api/documents/reingest-missing`** in `outputs/dashboard.py` (auth: `Depends(verify_api_key)`, tag `documents`). First `grep -n "reingest-missing" outputs/dashboard.py` to confirm no shadow route.

1. **Params:** `limit: int = Query(50, ge=1, le=500)`, `dry_run: bool = Query(True)`. Default dry_run TRUE (safe-by-default — caller must explicitly pass `dry_run=false` to write).
2. **Select set:** reuse the EXACT `_documents_missing_qdrant` NOT-EXISTS predicate (extract a shared predicate-string helper so the endpoint and the reconciliation report can never diverge). Fetch `id, filename, source_path, matter_slug` + the **extracted-text column**, ordered `ingested_at DESC NULLS LAST`, capped at `limit`. Bounded query (has LIMIT). `conn.rollback()` in every except; `store._put_conn(conn)` in finally.
3. **Dry-run path:** return `{dry_run: true, missing_qdrant_count, would_process: [{id, filename, text_len}]}`. No writes — assert no Qdrant upsert / no `ingestion_log` insert.
4. **Write path (`dry_run=false`):** for each row call `pipeline.ingest_text(full_text=<text>, filename=<filename>, source_path=<source_path or filename>, document_id=<id>, matter_slug=<matter_slug>)`. Each call in its own try/except — one failure must NOT abort the batch (collect `{id, reason}`).
5. **Return counts:** `{dry_run: false, attempted, embedded, skipped_empty, skipped_dedup, failed: [...], remaining_after}` — `remaining_after` re-runs the count query post-batch so the caller sees progress.
6. **Bounded + resumable:** `limit` caps each call; lead calls repeatedly until `remaining_after == 0`. Synchronous, bounded, caller-driven. NO background job, NO scheduler, NO startup hook (avoids the backfill-OOM + concurrent-startup anti-patterns).

## Key Constraints

- Embed only — never re-classify or re-extract (text already in PG).
- Idempotent by construction (rely on `ingest_text` dedup + deterministic point IDs); do NOT pass `skip_dedup=True`.
- Do not touch the search/read path (that arc is merged + AC-passed).
- Every except: `conn.rollback()`. Every query: LIMIT. No unbounded SELECT.

## Acceptance criteria

- **AC1:** `dry_run=true` returns candidate list + total count, writes nothing (assert Qdrant upsert + ingestion_log insert NOT called).
- **AC2:** `dry_run=false&limit=N` embeds N docs via `ingest_text` with `document_id` + `matter_slug` threaded; returns accurate counts; `remaining_after` = total − newly-embedded.
- **AC3:** Idempotent — running the same batch twice does not duplicate Qdrant points and the second run reports `skipped_dedup`.
- **AC4:** A single bad row (empty text / embed failure) is caught, counted in `failed` with reason, and does NOT abort remaining rows.
- **AC5:** Empty-text docs are skipped (`skipped_empty`), not embedded as empty.

## Verification / Done rubric

Literal pytest green on a new `tests/test_reingest_missing_qdrant.py` covering AC1-AC5 (mock store/Qdrant/Voyage — no live calls); `bash scripts/check_singletons.sh` OK; full-suite zero new failures vs baseline (main). Ship report answers each AC with the test name that proves it. Compile-clean ≠ done (Lesson #8).

## Files Modified
- `outputs/dashboard.py` — new `POST /api/documents/reingest-missing` + shared missing-qdrant predicate helper.
- `tests/test_reingest_missing_qdrant.py` — new test file (AC1-AC5).

## Do NOT Touch
- The search/read path (`_resolve_semantic_doc_hits`, `/api/documents/search`) — merged + AC-passed.
- `_documents_missing_qdrant` return shape used by `/api/documents/reconciliation` — only factor the predicate string out, keep behaviour identical.
- `scripts/backfill_email_attachments.py` — separate slice, not this brief.

## Out of scope
- The M365 2-year email backfill (separate epic, lead-scoped).
- Running the actual 1,036-doc backfill on prod — that's lead's POST_DEPLOY op once the endpoint ships.

## Notes
- `ingest_text` already takes `document_id` + `matter_slug` (you added them in Part B).
- Bus-only to lead on ship/blocker/claim. NOT Director-facing register.
