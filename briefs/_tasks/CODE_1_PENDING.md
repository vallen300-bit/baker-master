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
- **Ship as TWO PRs — MANDATORY** (codex G0 #1743): Part A (ingestion/search durability + observability) ships first as PR1; Part B (durable payload/signature/join contract) ships as PR2 only after Part A is green + smoke-verified. They are different contracts — do not bundle.

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

### B1. Durable Qdrant↔Postgres join (write ids into the payload) — MUST include retriever.py
Search joins Qdrant→Postgres on `source_path`/`filename` (enrichment `memory/retriever.py:540-547`; document fetch by source_path/filename only at `:606-617`). Not globally unique → rare cross-matter mis-attribution (architect #287).
- Write `document_id` + `matter_slug` into the `baker-documents` Qdrant payload (`_embed_and_upsert` metadata, `tools/ingest/pipeline.py:235-242` — today only `source_file`/`source_path`). Thread `document_id` through `ingest_text`/`ingest_file` from the two-write callers.
- **Reorder note (codex):** `/api/ingest` currently calls `ingest_file` BEFORE `store_document_full` (`outputs/dashboard.py:10571-10607`), so it doesn't have `document_id` at Qdrant-write time. Reorder so `store_document_full` runs first (get the id) then the Qdrant write carries it — OR patch the payload after. Same for `promote_attachment_text_to_document_and_qdrant` + `dropbox_trigger`.
- **MUST update `memory/retriever.py`** (codex MEDIUM #2): add `document_id` resolution to the enrichment path (`:540-617`) so search actually uses the new payload field — otherwise the durable join is dead weight. Add tests. If retriever changes are too large, explicitly DEFER B1 as a named standalone fast-follow rather than ship it half-wired.
- Keep filename/source_path enrichment as the fallback for legacy points. Only NEW ingests get the id; existing points rely on fallback until re-embedded (A3 reconciliation re-ingest can carry it). No full payload migration here.

### B2. `source_path` prefix contract — THREE surfaces (codex MEDIUM #3)
The source convention is hardcoded in THREE places that must agree, or M365 will be inconsistent across facets/filters/labels:
- facet CASE — `outputs/dashboard.py:2183-2194`
- SQL source filters — `outputs/dashboard.py:2385-2397`
- Python `_derive_source` — `outputs/dashboard.py:2556-2567`
- Introduce ONE `SOURCE_PREFIXES` constant + a single source-of-truth helper; route all three surfaces through it; document it as the contract. Add `m365` mapping now (inert until M365 lands).

### B3. `safe_filename` once in `/api/ingest` (codex #1730 nit + #1743 #4)
`/api/ingest` strips path separators for the temp path but still uses `file.filename` for: ext derivation (`outputs/dashboard.py:10523`), `store_document_full` source_path/filename (`:10604-10607`), and the response (`:10633`). A client sending `folder/Mandarin.pdf` diverges across temp path / PG row / Qdrant source_file / API response.
- Compute `safe_filename = Path(file.filename).name` ONCE; reuse for ext derivation, temp path, `store_document_full` filename/source_path, the response, and logs — every surface.

### B4. Document the pagination/total bound (`/api/documents/search`)
Semantic `total` reflects results within the ≤300-chunk over-fetch window, not the true corpus total; deep offsets give a shifting total. Document this in the handler docstring + response (e.g. `"total_is_windowed": true` when semantic), and consider falling back to ILIKE for `offset` beyond the window.

---

### B5. Deferred from Part A review (codex #1748 + architect — fold into Part B)
1. **Voyage cardinality guard** — `_embed_and_upsert` trusts `zip(batch, result.embeddings)` (`tools/ingest/pipeline.py:291`); if Voyage returns fewer embeddings than texts WITHOUT raising, `failed_batches` stays empty and the doc gets sealed half-indexed (the exact silent half-index A2 exists to kill, via a side door). Add `if len(result.embeddings) != len(batch):` → treat as a failed batch. + test.
2. **Cross-caller partial-embed posture** — on partial (`result.skipped, skip_reason="partial_embed"`), `/api/ingest` writes NEITHER store (PG write gated on `not result.skipped`), but `dropbox_trigger.py` writes PG `documents` BEFORE `ingest_file` (not gated) → leaves PG-written-but-ingestion_log-empty. Different durability postures for the same failure. Pick one deliberately + make A3 reconciliation detect both. Document the choice.
3. **`semantic + total:0` enrichment-failure sub-signal** — when Qdrant returns hits but PG enrichment fails/filters-drop-all, response is `mode=semantic, total=0` (looks like "ran, found nothing" but enrichment silently failed). Consider a distinct observable sub-signal (e.g. `enrichment_failed: true`) so this new silent surface is visible.

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
