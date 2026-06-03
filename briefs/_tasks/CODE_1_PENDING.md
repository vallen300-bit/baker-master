---
status: PENDING
brief_id: DOCUMENTS_SEARCH_SEMANTIC_RESTORE_1
dispatch: DOCUMENTS_SEARCH_SEMANTIC_RESTORE_1
to: b1
from: lead
dispatched_by: lead
task_class: bug-fix (high blast radius — Director-approved behavior change)
harness_v2: applies
gate_plan: G0 codex (brief) → G1 lead (literal pytest) → G2 /security-review → G3 codex (code)
---

# B1 dispatch — DOCUMENTS_SEARCH_SEMANTIC_RESTORE_1 (Bug A)

## Context Contract (read before building)

- **Repo:** baker-master, working dir `~/bm-b1`. Test on py3.12 (`/opt/homebrew/bin/python3.12 -m pytest`).
- **Origin:** You flagged this as "Bug A" while fixing INGEST_RETRIEVAL_GAP (#285, merged `a7a0341`). **Director has approved the fix** (chat 2026-06-03 "fix what's needed"). This is a high-blast-radius, Director-ratified behavior change — semantic results will replace keyword (ILIKE) results portfolio-wide.
- **Endpoint:** `GET /api/documents/search` — `outputs/dashboard.py:2213` (handler), Qdrant branch at `~2246-2300`, ILIKE fallback at `~2301+`.

## Problem

The Qdrant semantic branch of `/api/documents/search` has been **dead since DOCUMENTS-REDESIGN-1**. At `outputs/dashboard.py:2248`:
```python
from memory.retriever import Retriever   # ImportError — no such symbol
retriever = Retriever()                  # never runs
hits = retriever.search("baker-documents", q.strip(), limit=qdrant_limit)  # wrong method too
```
`memory/retriever.py` exposes `SentinelRetriever` (not `Retriever`), and its method is `search_collection(query_vector, collection, ...)` (not `search(collection, text, ...)`). The import raises, the `except` swallows it (`logger.warning("Qdrant search failed, falling back to PostgreSQL")`), and every query silently runs a Postgres `filename/full_text ILIKE` keyword match. So "document search" has been dumb substring matching, not semantic, for months.

## Current State (verified by lead)

- `SentinelRetriever` — `memory/retriever.py:148`. Singleton accessor: `SentinelRetriever._get_global_instance()` (`memory/retriever.py:156`). **Use the accessor — do NOT instantiate directly** (CI guard `scripts/check_singletons.sh`).
- `search_collection(query_vector: list[float], collection: str, limit=20, score_threshold=0.3, project=None, role=None) -> list[RetrievedContext]` — `memory/retriever.py:190`. Takes a **pre-computed embedding vector**.
- Query embedding helper used internally: `self._embed_query(query)` (see `search_all_collections`, `memory/retriever.py:~256`). One Voyage call per query.
- Return type is `RetrievedContext` objects (NOT dicts): attributes `.content`, `.source`, `.score`, `.metadata` (dict), `.token_estimate`. The current broken mapping uses dict access (`h.get("metadata")`, `h.get("text")`, `h.get("score")`, `h.get("id")`) — that mapping MUST change to attribute access.

## Implementation

1. **Fix the import + call** in the Qdrant branch (`outputs/dashboard.py:~2247-2249`):
   ```python
   from memory.retriever import SentinelRetriever
   retriever = SentinelRetriever._get_global_instance()
   qdrant_limit = min(offset + limit + 50, 200)
   query_vector = retriever._embed_query(q.strip())
   hits = retriever.search_collection(
       query_vector=query_vector,
       collection="baker-documents",
       limit=qdrant_limit,
       score_threshold=0.3,
   )
   ```
2. **Remap results** from `RetrievedContext` attributes. The filter loop + result dict currently read `h.get("metadata")` / `h.get("text")` / `h.get("score")` / `meta.get("doc_id")` etc. Change to `h.metadata` / `h.content` / `h.score`. **VERIFY the `baker-documents` payload keys exist** before trusting them — pull one live point and confirm which of `doc_id` / `document_id` / `filename` / `matter_slug` / `document_type` / `source_path` / `ingested_at` are actually present in the payload written by `ingest_file`. Map missing keys defensively (`or ""`), and make sure the result `id` resolves to the Postgres `documents.id` (so the UI's open-document link still works) — if the Qdrant payload doesn't carry the PG id, you may need to carry it through `ingest_file`'s payload or resolve by `source_path`/`file_hash`. Flag the chosen approach in the ship report.
3. **KEEP the ILIKE fallback** exactly as-is for: (a) Qdrant error/empty, (b) filter-only queries with no `q`. The semantic branch populates `results`; the existing `if not results ...` fallback must still fire when semantic returns nothing. Do NOT delete the Postgres path — it is the safety net (THREE-TIER pattern).

## Key Constraints

- All DB/API calls wrapped in try/except **with `conn.rollback()`** in except (PG pool poisoning).
- Singleton accessor only (no `SentinelRetriever()` / `SentinelStoreBack()` direct construction).
- Voyage embedding adds ~1 API call per query — acceptable (search is user-initiated, not a loop). Note the per-query cost in the ship report.
- Surgical: only the `/api/documents/search` Qdrant branch + its result mapping. Do NOT touch `/api/ingest` (#285) or the ILIKE fallback logic.
- Score threshold 0.3 is the retriever default — keep it; note that it is why semantic returns fewer, more-relevant hits than ILIKE.

## Verification / Done rubric (answer literally in the ship report — not "tests pass")

1. **Before/after on real queries:** run 3-5 representative queries (e.g. "Mandarin Oriental", a matter name, a concept phrase) against prod BEFORE (ILIKE, current) and AFTER (semantic). Report the result counts + top-5 titles for each. Confirm the semantic results are relevant and a known document is still findable. (Expected: counts drop, relevance rises — e.g. ~635 ILIKE hits → ≤200 semantic.)
2. **Known-doc retrievable:** the AC285 sentinel doc (or any recently-ingested doc) is returned by a semantic query for its content.
3. **Fallback intact:** simulate Qdrant-empty/error → confirm ILIKE fallback still returns; filter-only (no `q`) still works.
4. **Result `id` resolves to a real Postgres `documents.id`** (open-document link works) — show one id round-trip.
5. `bash scripts/check_singletons.sh` = OK; literal `pytest` output (py3.12) for touched tests + a new guard test asserting the handler imports `SentinelRetriever` (not `Retriever`) and calls `search_collection`.

## Files likely modified
- `outputs/dashboard.py` — `/api/documents/search` Qdrant branch + result mapping (~2246-2300).
- `tests/test_documents_search_semantic.py` (new) — guard the import/method + result-mapping + fallback.

## Do NOT touch
- `/api/ingest` handler (#285).
- The PostgreSQL ILIKE fallback block (keep as safety net).
- Other `SentinelRetriever` call sites (slack/waha/cli) — out of scope.

## Gate plan (Harness V2)
- G0 codex brief review (lead dispatches before you start).
- G1 lead — literal pytest + diff review + a live before/after query comparison.
- G2 `/security-review` — endpoint change, mandatory (Lesson #52). (Note: query text already flows to ILIKE params parameterized; semantic path sends it to Voyage embed — no new injection surface, but confirm.)
- G3 codex — code correctness/architecture + payload-key mapping sanity.
- POST_DEPLOY_AC_VERDICT v1 after merge (live before/after query proof on prod).

## Reply target
Bus-post findings + ship report to `lead`. Plain technical prose (NOT Director-facing register — no `Bottom line:` / `Recommendation:` / `Bus:` closers). **Surface the payload-id-resolution decision explicitly** — it's the one real design fork in this fix.
