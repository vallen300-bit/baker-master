---
dispatch: INGEST_RETRIEVAL_GAP_DIAGNOSE_FIX_1
to: b1
from: lead
dispatched_by: lead
status: COMPLETE (merged PR #285 a7a0341; all gates PASS — G0 #1702 / G1 lead / G2 security CLEAR / G3 codex #1706 PASS-WITH-NOTES)
dispatched_at: 2026-06-03
authored: 2026-06-03
target_repo: baker-master (vallen300-bit/baker-master)
estimated_time: ~2-4h (diagnosis-heavy)
complexity: Medium-High
reply_to: lead
ship_topic: ship/ingest-retrieval-gap-diagnose-fix-1
anchor_chat: Director 2026-06-03 "Go dispatch B" — /api/ingest reports success but content is not retrievable; affects ALL document ingestion. Surfaced AH1 while ingesting mo-prague appendix data.
---

# B1 dispatch — INGEST_RETRIEVAL_GAP_DIAGNOSE_FIX_1

## Context

`POST /api/ingest` returns `{"status":"success","collection":"baker-documents","chunks":4}`,
but the ingested content is **not retrievable** afterwards. This is a green-but-broken gap
(Lesson #8 / #86 family): the API reports success, nothing is actually queryable. It affects
EVERY document ingested via this path, not one file — so it is a real Baker bug, priority.

**Evidence AH1 captured live (2026-06-03), use it — do not re-derive from scratch:**
- Ingested `~/baker-vault/wiki/matters/mo-prague/00_originals/from-dropbox-deal-folder/appendix-2-3-transcribed.md`
  via `POST /api/ingest` (X-Baker-Key). Response: `status=success, collection=baker-documents, chunks=4, dedup=false`.
- **Re-ingesting the SAME file again ALSO returned `dedup=false`** — dedup never fired on an identical re-upload. Suspicious (suggests the dedup check and/or the upsert is not hitting the store the retriever reads).
- `GET /api/documents/search?q=...` (dashboard.py:2213 → `retriever.search("baker-documents", q, ...)`):
  - `"Mandarin Oriental"` → total **639**; `"renovation"` → 226; `"deal"` → 458. **Collection is live + populated + readable.**
  - Every phrase distinctive to the just-ingested doc → total **0**: `"CITIC renovation business case"`, `"Stage 1 Stage 2 cashflow CZK"`, `"transcribed embedded chart"`, `"appendix 2 3 IRR"`, `"82557265"`.
- So: the retriever reads a populated `baker-documents`, but the doc `/api/ingest` claims it stored is absent from it.

**Context Contract:**
- **Repo / branch:** baker-master, branch off `main` (e.g. `b1/ingest-retrieval-gap-diagnose-fix-1`).
- **Write path (ingest):** `outputs/dashboard.py:10425` `POST /api/ingest` → `ingest_file(...)` in `tools/ingest/pipeline.py` (+ `tools/ingest/extractors.py`). Reports `collection="baker-documents"`, `chunk_count`.
- **Read path (retriever):** `outputs/dashboard.py:2213` `GET /api/documents/search` → `retriever.search("baker-documents", q, limit=...)`. Also used at `dashboard.py:8279`.
- **A SECOND ingest path exists:** `kbl/ingest_endpoint.py:300` upserts to `collection_name="baker-wiki"` (NOT baker-documents) via `models.cortex._embed_text`. Confirm whether `/api/ingest` actually routes through the tools/ingest pipeline or kbl path, and which Qdrant client each uses.
- **Embedding:** Voyage `voyage-3`, 1024-d (`kbl/voyage_client.py`). A dimension/model mismatch between write and read silently breaks retrieval.
- **Singletons:** never instantiate `SentinelRetriever()` / `SentinelStoreBack()` directly — use `_get_global_instance()` (CI guard `scripts/check_singletons.sh`).
- **Task class:** production bug-fix + investigation.
- **Surface contract: N/A — backend ingest/retrieval pipeline, no clickable surface.**

## Hypotheses (test in order, cheapest first; confirm with evidence, don't guess)
1. **Qdrant client divergence (most likely):** the ingest upsert client and the retriever read client use a DIFFERENT Qdrant URL / API key / cluster. Memory: the `baker-memory` Qdrant cluster was upgraded free→paid recently (cluster 38c16dc6) — an old vs new URL/key could be split across the two paths. Compare the exact `QDRANT_URL` / `QDRANT_API_KEY` (and any per-module override) each path resolves at runtime.
2. **Collection mismatch:** write goes to a different collection name (e.g. `baker-wiki` vs `baker-documents`) or a stale duplicate collection with the same name on a different cluster.
3. **Silent upsert failure (green-but-broken):** `ingest_file` returns `chunk_count` computed BEFORE/independent of the Qdrant upsert, and the upsert raises + is swallowed → success reported, nothing stored. Trace whether `chunk_count` is post-upsert-confirmed.
4. **Embedding dim/model mismatch:** write embeds with a different model/dim than the collection expects → upsert silently rejected.

## Deliverable
1. **Root cause, evidenced** — which client/collection/key/dim each path uses; the exact divergence, quoted from runtime config (not assumed).
2. **Fix** so a doc ingested via `/api/ingest` IS retrievable via `/api/documents/search`.
3. **Round-trip self-test (load-bearing, Lesson #86):** an end-to-end test that ingests a sentinel doc carrying a unique token, then asserts the retriever returns it. Wire it so `/api/ingest` "success" can never again mean "not stored" — at minimum a test; ideally the endpoint confirms the upsert (point exists) before returning success.
4. **Re-land the mo-prague doc:** after the fix, ensure `appendix-2-3-transcribed.md` is ingested + retrievable (and clean up the 2 duplicate ingest attempts AH1 made if they landed anywhere). Confirm `"82557265"` / `"Stage 1 Stage 2 cashflow CZK"` now return it.

## Phase 2 — ingestion COVERAGE audit (Director extension; scope as a short report, do NOT build M365 poll)
Director's ask: once ingest is trustworthy, verify OTHER material — including M365 mail + attachments — actually reaches Qdrant + Postgres.
- Map the CURRENT attachment-ingestion path: do email/WhatsApp/transcript ATTACHMENTS (PDFs, images, docx) get extracted + embedded into Qdrant + written to Postgres today? Where, and via which trigger?
- Document the GAP for M365: the M365 mail/attachment poll is gated on Azure creds (M365 program Phase 2+, not yet live) — so this is a coverage MAP + gap-list, NOT a build. Output: a short markdown report (what's covered, what isn't, what M365 Phase 2+ must wire to ingest attachments). File it under `briefs/_reports/` and bus it to lead.
- Keep Phase 2 separate from the Phase-1 fix PR so the fix can merge independently.

## Key Constraints
- Read-only diagnosis FIRST; propose the fix with evidence before mutating prod config.
- Do NOT delete/recreate Qdrant collections destructively. If a collection must be created/migrated, propose it to lead first.
- Wrap all DB/Qdrant calls in try/except (fault-tolerant).
- Use `_get_global_instance()` for retriever/store-back. Pass `bash scripts/check_singletons.sh`.
- Render env: if a Qdrant URL/key is wrong, surface it to lead — do NOT raw-PUT Render env (use the guard / lead handles env flips as Tier-B).

## Files likely touched
- `tools/ingest/pipeline.py` and/or `kbl/ingest_endpoint.py` (whichever `/api/ingest` actually uses) — fix the write target / confirm upsert.
- `kbl/` retriever module — only if the read client is the wrong one.
- `tests/` — new round-trip ingest→retrieve test.
- Possibly `outputs/dashboard.py:10425` — make `/api/ingest` confirm-before-success.

## Do NOT Touch
- `scripts/bus_post.*`, the drain fixture, unrelated triggers.
- `migrations/` already-applied files.

## Verification
```bash
python3 -c "import py_compile; py_compile.compile('tools/ingest/pipeline.py', doraise=True)"
pytest -q   # plus the new round-trip test
bash scripts/check_singletons.sh
```
**Live round-trip (mandatory, Lesson #86):** ingest a sentinel doc via the live `/api/ingest`, then `/api/documents/search` for its unique token and confirm it returns. Capture the token + result in the ship report. Mock-green alone is NOT acceptance for this bug.

## Quality Checkpoints (Acceptance criteria)
1. Root cause documented with runtime-config evidence (which divergence).
2. A doc ingested via `/api/ingest` is retrievable via `/api/documents/search` (live-proven).
3. Round-trip self-test added + green on literal `pytest`.
4. mo-prague `appendix-2-3-transcribed.md` retrievable post-fix (token `82557265` returns it).
5. `scripts/check_singletons.sh` passes.
6. Phase-2 coverage report filed + bus-posted (separate from the fix PR).

## Done rubric (required final state)
PR open against baker-master `main`: `/api/ingest` writes land where `/api/documents/search` reads;
round-trip test proves it; mo-prague doc retrievable; Phase-2 coverage report filed. Answer this
rubric in the ship report (not just "tests passed").

## Gate plan
- **G0 codex-arch** — review the root-cause diagnosis + fix BEFORE merge (this one is subtle; pre-merge codex is worth it).
- **G1 lead** — literal `pytest` + the live round-trip re-run + singleton guard.
- **G2 /security-review** — light (no new external surface; config/pipeline).
- Merge on green → lead flips mailbox COMPLETE + bus-posts. Phase-2 report reviewed separately.

Harness-V2: applies (production pipeline bug-fix + investigation) — Context Contract, task class, done rubric, gate plan all above.
