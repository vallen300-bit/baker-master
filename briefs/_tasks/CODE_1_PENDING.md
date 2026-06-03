---
status: COMPLETE (merged PR #287 c969576; gates G0/G1/G2-CLEAR/G3-codex PASS-WITH-NIT/architect SHIP-WITH-FOLLOWUPS)
brief_id: DOCUMENTS_SEARCH_SEMANTIC_RESTORE_1
dispatch: DOCUMENTS_SEARCH_SEMANTIC_RESTORE_1
to: b1
from: lead
dispatched_by: lead
task_class: bug-fix (high blast radius — Director-approved behavior change)
harness_v2: applies
gate_plan: G0 codex (brief) → G1 lead (literal pytest) → G2 /security-review → G3 codex (code)
revision: v2 (G0 #1713 FAIL-LIGHT folded — deterministic id-resolution policy + conn-hold fix)
---

# B1 dispatch — DOCUMENTS_SEARCH_SEMANTIC_RESTORE_1 (Bug A) v2

## Context Contract (read before building)

- **Repo:** baker-master, working dir `~/bm-b1`. Test on py3.12.
- **Origin:** You flagged "Bug A" while fixing #285 (merged `a7a0341`). **Director approved** (2026-06-03 "fix what's needed"). High-blast-radius, Director-ratified: semantic replaces keyword (ILIKE) results portfolio-wide.
- **Endpoint:** `GET /api/documents/search` — handler `outputs/dashboard.py:2213`, docstring already states the intended design: *"Qdrant semantic search, then enrich from PostgreSQL."* Qdrant branch ~2245-2291, ILIKE fallback ~2301+.

## Problem

The Qdrant branch is dead since DOCUMENTS-REDESIGN-1: `outputs/dashboard.py:2248` does `from memory.retriever import Retriever` (no such symbol; class is `SentinelRetriever`) and `retriever.search(...)` (wrong method). Import raises → `except` swallows → every query silently runs Postgres `filename/full_text ILIKE` keyword match. Document search has been dumb substring matching for months.

## The hard part — Qdrant↔Postgres id resolution (codex G0 #1713; DECIDED, do not re-open)

The `baker-documents` Qdrant payload is **only** `{"text", "source_file", "source_path"}` (`tools/ingest/pipeline.py:227,263-267`). It carries **no `documents.id`, no `file_hash`, no `matter_slug`, no `document_type`**. Point IDs are deterministic UUIDs from chunk text (`make_point_id`), NOT PG ids. The UI needs a real PG integer id (`outputs/static/app.js:8318-8327` calls `/api/documents/{docId}/text`). So semantic hits MUST be enriched from Postgres — and the only shared join key for the existing corpus is **`source_file` (filename)**.

**DECIDED policy (implement exactly this — it is the design fork, resolved):**
1. Run semantic search on `baker-documents` (fetch generously, e.g. `limit = min((offset+limit)*3 + 50, 300)`, so post-grouping/filtering still fills the page).
2. **Enrich each hit from Postgres by filename**, batched (one query): collect `source_file` values, `SELECT id, filename, document_type, matter_slug, source_path, ingested_at, LEFT(full_text,200) FROM documents WHERE filename = ANY(%s)`.
3. **Group semantic hits → one result per document**, keyed by resolved `documents.id`, keeping the **highest chunk score** per document. (Chunks of the same doc must not appear as duplicate results.)
4. **Resolution rules (deterministic):**
   - Exactly one PG row for a filename → use its `id` + PG fields (PG is authoritative for matter/type/date/snippet).
   - Multiple PG rows (filename collision) → pick the one whose `source_path` also matches the Qdrant `source_path`; if still ambiguous, the most recent `ingested_at`.
   - **Zero PG rows → DROP the hit** (no openable document; never return a Qdrant point_id or null id to the UI).
5. **Apply matter/type/source filters against the PG row fields** (authoritative), NOT the Qdrant payload (which lacks them).
6. Sort surviving results by score desc; paginate `offset/limit`. Each result `id` is a real `documents.id`.
7. **Keep the ILIKE fallback** for: Qdrant error/empty, semantic-returns-nothing, and filter-only (no `q`) queries.

> Future-proofing (OUT OF SCOPE here, note as follow-up): write `document_id`/`file_hash` into the Qdrant payload going forward so future searches can join on id directly instead of filename. Do NOT attempt the payload migration in this brief.

## Connection-hold fix (codex P2 — do this while you're here)

Currently a PG conn is acquired at `outputs/dashboard.py:2229` BEFORE the Qdrant branch, so after restore it would be **held across Voyage embed + Qdrant query** (pool risk). **Restructure:** run the Qdrant semantic call FIRST with no PG conn held; acquire the PG conn only for the enrichment batch query + the ILIKE fallback. Release promptly. Keep `conn.rollback()` in except blocks.

## Implementation (call shapes — verified)

```python
from memory.retriever import SentinelRetriever
retriever = SentinelRetriever._get_global_instance()          # singleton — NOT SentinelRetriever()
query_vector = retriever._embed_query(q.strip())               # 1 Voyage call
hits = retriever.search_collection(                            # returns list[RetrievedContext]
    query_vector=query_vector, collection="baker-documents",
    limit=qdrant_limit, score_threshold=0.3,
)
# hits[i].content / .score / .metadata  (attribute access; metadata has source_file, source_path)
```

## Key Constraints
- Singleton accessors only (CI guard `scripts/check_singletons.sh`).
- All DB calls try/except + `conn.rollback()`; release conn promptly (see conn-hold fix).
- ~1 Voyage call per query — acceptable (user-initiated). Note cost in ship report.
- Surgical: only `/api/documents/search` Qdrant branch + result mapping + conn restructure. Do NOT touch `/api/ingest` (#285) or the ILIKE SQL itself (reuse as fallback).
- score_threshold 0.3 (retriever default) — keep; it's why semantic returns fewer, more-relevant hits.

## Verification / Done rubric (answer literally — not "tests pass")
1. **Before/after on 3-5 real prod queries** ("Mandarin Oriental", a matter name, a concept phrase): report result counts + top-5 titles ILIKE-now vs semantic-after. Confirm relevance up, known doc still found. (Expect ~635 → ≤200 on broad terms.)
2. **Every returned `id` is a real `documents.id`** — open `/api/documents/{id}/text` for one and show it resolves.
3. **No duplicate-chunk results** — a multi-chunk doc returns once.
4. **Filename-collision + zero-match paths** exercised (unit): one-match→id, multi→deterministic pick, zero→dropped.
5. **Fallback intact:** Qdrant-empty/error → ILIKE returns; filter-only (no q) works.
6. `scripts/check_singletons.sh` OK; literal `pytest` (py3.12) + a guard test asserting the handler imports `SentinelRetriever` and calls `search_collection`.

## Files likely modified
- `outputs/dashboard.py` — `/api/documents/search` Qdrant branch, enrichment, grouping, conn restructure (~2229-2300).
- `tests/test_documents_search_semantic.py` (new).

## Do NOT touch
- `/api/ingest` (#285); the ILIKE fallback SQL (keep as net); Qdrant payload schema (future follow-up); other `SentinelRetriever` call sites.

## Gate plan (Harness V2)
- G0 codex (this v2) → G1 lead (literal pytest + live before/after) → G2 /security-review (Lesson #52) → G3 codex → POST_DEPLOY_AC_VERDICT v1 (live before/after on prod).

## Reply target
Bus-post findings + ship report to `lead`. Plain technical prose (NOT Director-facing register).
