# B1 ship report — INGEST_SEARCH_DURABILITY_FOLLOWUPS_1 Part A (PR1)

**Date:** 2026-06-03 · **Author:** B1 · **For:** lead
**PR:** #288 (`b1/ingest-search-durability-followups-A` → `main`), commit `b326ba1`
**Brief:** `INGEST_SEARCH_DURABILITY_FOLLOWUPS_1` (G0 codex #1743 PASS-WITH-CHANGES folded)
**Scope shipped:** Part A only. Part B held for PR2 per the two-PR mandate (#1743).

## What shipped

### A1 — `/api/documents/search` reports retrieval mode
- Response now carries `"mode": "semantic" | "ilike_fallback" | "filter_only"`.
- Split the two silent-fallback causes in logs: a **raised** Qdrant/Voyage error →
  `logger.error` (degradation, should alert); **no hit above threshold** →
  `logger.info` (legitimate last-resort). Previously both collapsed to one WARNING —
  the exact blind spot that hid the original Bug A for months.

### A2 — no seal on a partially-embedded doc (`tools/ingest/pipeline.py`)
- `_embed_and_upsert` now returns `(point_ids, failed_batches)` instead of just
  `point_ids`. A persistently-failing embed batch lands in `failed_batches`.
- Both callers (`ingest_text`, `ingest_file`): if `failed_batches` is non-empty →
  **skip `log_ingestion`** and return `IngestResult(skipped=True,
  skip_reason="partial_embed")`. `(filename, file_hash)` stays out of
  `ingestion_log` → `is_duplicate` False on re-run → the whole doc is retried
  (deterministic point IDs → successful chunks re-upsert idempotently). Full-success
  path byte-for-byte unchanged.
- `_embed_and_upsert` is module-private; only those 2 callers — no external breakage.

### A3 — cross-store reconciliation surface
- `_documents_missing_qdrant(limit)`: read-only, bounded; `documents` rows (PG
  system-of-record) with no `baker-documents` ingestion in `ingestion_log` (join on
  `filename`). Returns `(count, rows)`; `(None, [])` on error.
- `GET /api/documents/reconciliation` (authed): count + capped list for a manual
  re-ingest decision. No auto-repair (by design).
- `/health`: surfaces the count, **TTL-cached 300s** (Render liveness probe must not
  run a COUNT per hit). **Informational — does NOT flip status to degraded**, so
  legacy backlog (docs predating the Qdrant two-write) can't fail the probe or gate
  a deploy.

## Verification (literal, not "tests pass")
- New `tests/test_ingest_partial_embed.py` (7): `_embed_and_upsert` tuple contract +
  flags persistent failure; `ingest_text`/`ingest_file` no-seal-on-partial vs
  seal-on-success (asserts `log_ingestion` call count).
- `tests/test_documents_search_semantic.py` (+10): A1 mode source-guards + functional
  mode (semantic / ilike_fallback / filter_only via TestClient); A3 reconciliation
  endpoint returns count+rows; `/health` source-guard incl. "drift count must not be
  in the degraded condition".
- **25 pass** (py3.12). `check_singletons.sh` OK. py3.12 compile clean.
- **Full-suite diff vs baseline: zero new failures.** 184 pre-existing env-dependent
  fail/errors (gmail ImportError, vault TypeError, live-DB/MCP/network) are identical
  on `main` and this branch — `comm -23` of the failure sets is empty.

## Gate state
G0 codex ✅ (#1743) → **G1 lead (literal pytest) — your gate** → G2 /security-review
(Lesson #52) → G3 codex → architect → POST_DEPLOY_AC.

## Not done here (Part B → PR2, after Part A green + smoke)
B1 durable `document_id`+`matter_slug` Qdrant payload **incl. `memory/retriever.py`
enrichment** (or explicit DEFER if too large); B2 `SOURCE_PREFIXES` single-source
helper across the 3 surfaces (+`m365` mapping); B3 `safe_filename = Path(...).name`
once in `/api/ingest`; B4 windowed-`total` pagination bound documented.

## Notes
- Mailbox `CODE_1_PENDING.md` left at PENDING — the dispatch isn't COMPLETE until
  Part B ships. Flip is lead's call.
- Smoke assertion for A1 (`mode=semantic` on a known prod query) is covered at the
  test layer here; the live prod assertion belongs to POST_DEPLOY_AC after merge.
