---
status: PENDING
brief_id: INGEST_SEARCH_DURABILITY_FOLLOWUPS_1
dispatch: INGEST_SEARCH_DURABILITY_FOLLOWUPS_1
to: b1
from: lead
dispatched_by: lead
task_class: hardening + observability (consolidated architect fast-follows from #285/#286/#287)
harness_v2: applies
gate_plan: G0 codex (brief) → G1 lead (literal pytest) → G2 /security-review → G3 codex → architect → POST_DEPLOY_AC
---

# B1 dispatch — INGEST_SEARCH_DURABILITY_FOLLOWUPS_1

## Context Contract

- **Repo:** baker-master, working dir `~/bm-b1`. Test on py3.12 (`/opt/homebrew/bin/python3.12 -m pytest`).
- **Origin:** consolidated fast-follows from the merged document-retrieval arc — #285 (ingest→Postgres), #287 (semantic search restore), #286 (attachment two-write). All architect-flagged, non-blocking, Director-approved (2026-06-03). Read those 3 PRs' merge commits (`a7a0341`, `c969576`, `1831f8f`) + `briefs/_reports/B1_INGEST_COVERAGE_AUDIT_PHASE2_20260603.md` for grounding.
- **Theme:** the ingest↔search two-store contract (Postgres `documents` + Qdrant `baker-documents`) now works, but has two **silent-degradation** risks of the same class as the bug we just fixed. Close them.
- **Ship as TWO PRs** if cleaner: Part A (P1) first, Part B (P2) after. One brief, two coherent clusters.

---

## PART A — observability + repair (P1, ship first)

### A1. Search must report which mode it ran (`/api/documents/search`)
The endpoint silently falls back to ILIKE on any Qdrant/Voyage error (`outputs/dashboard.py` search handler) — exactly the shape of the original Bug A (months of silent keyword fallback). Make it observable:
- Add `"mode": "semantic" | "ilike_fallback" | "filter_only"` to the JSON response dict (alongside `results`/`total`/`offset`).
- **Split the two fallback causes in logs:** "Qdrant/Voyage raised" → `logger.error` (degradation, should alert) vs "semantic returned zero above threshold" → `logger.info` (legitimate last-resort). Today both collapse to one WARNING.
- Add a post-deploy smoke assertion (in `.smoke/` or a test) that a known query returns `mode=semantic` — so a silent regression to keyword can't recur unnoticed.

### A2. `ingest_text` must not seal a partially-embedded doc (`tools/ingest/pipeline.py`)
`_embed_and_upsert` (`pipeline.py:265-267`) swallows a per-batch embed failure (`logger.error; continue`) and returns partial `point_ids`. `ingest_text` then **unconditionally** calls `log_ingestion(...)` with `chunk_count=len(chunks)` (~`pipeline.py:358`). So a large attachment whose batch N failed gets logged as fully ingested → `is_duplicate` returns True on re-run → missing chunks **never retried** → permanent half-index.
- **Fix:** `_embed_and_upsert` must signal partial failure (e.g. return `(point_ids, failed_batches)` or raise a typed partial-failure). If ANY batch failed, `ingest_text` must NOT write `log_ingestion` (let a re-run retry the whole doc), and should set `IngestResult.skipped`/`skip_reason="partial_embed"` so the caller sees it.
- Preserve the full-success path exactly. `ingest_file` shares `_embed_and_upsert` — apply the same no-seal-on-partial logic there (it also calls `log_ingestion`).

### A3. Cross-store reconciliation query (find half-indexed docs)
No way today to find docs where one store landed and the other didn't.
- Add a read-only query/function: `documents` rows with no matching `baker-documents` ingestion (join `documents.source_path`/`filename` ↔ `ingestion_log` for the baker-documents collection). Bounded (LIMIT).
- Wire it into the existing health/sentinel surface (e.g. a count in `/health` or a sentinel) so drift is visible. Returns the list for a manual re-ingest decision.

---

## PART B — durability hardening (P2, ship after Part A)

### B1. Durable Qdrant↔Postgres join (write ids into the payload)
Search currently joins Qdrant→Postgres on `source_path` (enrichment in `memory/retriever.py:~540-617`, falls back to `filename`). Filename/source_path are not globally unique → rare cross-matter mis-attribution (architect #287).
- Going forward, write `document_id` + `matter_slug` into the `baker-documents` Qdrant payload (`_embed_and_upsert` metadata, `tools/ingest/pipeline.py:236`). The two-write callers (`/api/ingest`, dropbox_trigger, `promote_attachment_text_to_document_and_qdrant`) know the `documents.id` after `store_document_full` — thread it into `ingest_text`/`ingest_file` so the payload carries it.
- When the payload has `document_id`, search resolves on it directly (no filename guesswork) and can push the `matter_slug` filter into Qdrant's `query_filter` (the retriever already supports `FieldCondition`). Keep filename/source_path enrichment as the fallback for legacy points.
- **Note:** only NEW ingests get the id; existing points rely on the fallback until re-embedded (the reconciliation re-ingest, A3, can carry the id). State this clearly; do not attempt a full payload migration here.

### B2. `source_path` prefix contract
The search source-filter keys on substrings (`email:`/`whatsapp:`/`clickup:`/`fireflies:`, else `dropbox`) — an implicit, load-bearing convention. Before M365 adds a 3rd prefix (`m365:`/`microsoft:`) and silently falls into the `dropbox` bucket:
- Introduce a `SOURCE_PREFIXES` constant + a single `_derive_source` source of truth; document it as the contract. Add `m365` mapping now (inert until M365 lands).

### B3. `safe_filename` once in `/api/ingest` (codex #1730 nit)
`/api/ingest` strips path separators for the temp path (`Path(file.filename).name`) but still stores `documents.filename = file.filename`. A client sending `folder/Mandarin.pdf` would mismatch the join.
- Compute `safe_filename = Path(file.filename).name` ONCE; reuse for the temp path, `store_document_full` filename/source_path, the response, and logs.

### B4. Document the pagination/total bound (`/api/documents/search`)
Semantic `total` reflects results within the ≤300-chunk over-fetch window, not the true corpus total; deep offsets give a shifting total. Document this in the handler docstring + response (e.g. `"total_is_windowed": true` when semantic), and consider falling back to ILIKE for `offset` beyond the window.

---

## Key Constraints
- All DB calls try/except + `conn.rollback()`; bounded queries (LIMIT).
- Singleton accessors only (`_get_global_instance()`); CI guard `scripts/check_singletons.sh`.
- Surgical; preserve all behavior that the 3 merged PRs established. No re-extraction at text sites.
- No startup embedding storms.

## Verification / Done rubric (answer literally)
1. **A1:** response shows `mode`; force a Qdrant error → `mode=ilike_fallback` + `logger.error`; normal → `mode=semantic`. Smoke assertion present.
2. **A2:** unit — a batch-failure run does NOT call `log_ingestion` and leaves the doc retryable; full-success unchanged. Both `ingest_text` + `ingest_file`.
3. **A3:** reconciliation query returns known half-indexed rows; bounded; wired to health/sentinel.
4. **B1:** new ingest writes `document_id`+`matter_slug` to payload; search resolves on id when present; legacy fallback intact.
5. **B2/B3/B4:** prefix constant + `m365` mapping; safe_filename reused everywhere; pagination bound documented.
6. `scripts/check_singletons.sh` OK; literal `pytest` (py3.12) for every part.

## Gate plan (Harness V2)
G0 codex (this brief) → G1 lead → G2 /security-review → G3 codex → architect → POST_DEPLOY_AC_VERDICT.

## Reply target
Bus-post findings + ship report(s) to `lead`. Plain technical prose (NOT Director-facing register). Ship Part A first; flag if Part B should be a separate PR.
