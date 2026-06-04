---
status: PENDING
brief_id: REINGEST_ASYNC_OFFLOAD_1
dispatch: REINGEST_ASYNC_OFFLOAD_1
to: b1
from: lead
dispatched_by: lead
task_class: production bug fix (availability)
harness_v2: applies
gate_plan: G0 codex PASS (#1820, e54b2d8) → G1 lead (literal pytest + live health-during-backfill probe) → G2 /security-review → G3 codex (PR) → merge → POST_DEPLOY_AC_VERDICT v1
brief_path: briefs/BRIEF_REINGEST_ASYNC_OFFLOAD_1.md
---

# B1 dispatch — REINGEST_ASYNC_OFFLOAD_1

**Full spec: `briefs/BRIEF_REINGEST_ASYNC_OFFLOAD_1.md` (commit e54b2d8). Read it — this envelope is the pointer + the gate contract, not the spec.**

## Context Contract

You built REINGEST_MISSING_QDRANT_ENDPOINT_1 (#291) last session, so you own the freshest
context on `POST /api/documents/reingest-missing` (`outputs/dashboard.py:1999`), the
`_REINGEST_MISSING_QDRANT_PREDICATE` / `_HAS_EXTRACTED_TEXT` selectors, and
`tools/ingest/pipeline.py:ingest_text()`.

**The bug:** that endpoint is `async def` but calls the **synchronous** `ingest_text()`
directly in a per-candidate loop, blocking the single Uvicorn event-loop thread for the
whole batch. A live `limit=50` run on 2026-06-04 took baker-master fully unresponsive
(`/health` timed out) for ~15 min and needed a Render restart (AH1 incident). This brief
makes it non-blocking + single-runner safe.

## Scope (Option A — minimal; codex G0 v3 PASS at e54b2d8)

1. Move the embed loop into a module-level sync helper `_reingest_embed_batch(candidates)`
   and call it via `await asyncio.to_thread(...)` so the event loop stays free.
2. Single-runner `pg_try_advisory_lock` on a **DEDICATED DIRECT** connection
   (`psycopg2.connect(**config.postgres.direct_dsn_params)`), `lock_conn.autocommit = True`
   **before** the lock SELECT (idle-in-transaction 5min would else drop the lock mid-batch),
   release+close that same conn in finally, never `store._put_conn` it; fail-loud
   `no_direct_dsn` if `host_direct` is unset.
3. Default `limit` 50→10 (cap 500→100).
4. Tests: update the signature source-guard, add the `_reingest_embed_batch` failure-isolation
   unit test, the offload/lock/autocommit source-guards, and the **mandatory** lock-held ⇒
   `backfill_in_progress` endpoint test (do NOT silently skip — escalate to AH1 if the fixture
   can't reach the write path; G3 will not pass on source guards alone).

The exact copy-pasteable diffs, the `Do NOT touch` list, and all line refs are in the brief.

## Gate contract (Harness V2)

- **Done rubric (answer literally — NOT "tests pass"):**
  1. During a live `dry_run=false&limit=10` prod run, a concurrent `GET /health` returns 200 <3s — paste both timestamps.
  2. A concurrent second `POST .../reingest-missing?dry_run=false` returns `{"error":"backfill_in_progress"}`.
  3. `embedded > 0` and `remaining_after` strictly decreases across two sequential calls.
- **Gates:** G0 PASS (codex #1820) → G1 lead literal `pytest tests/test_reingest_missing_qdrant.py -v` + the live health-during-backfill probe → G2 `/security-review` → G3 codex on the PR → AH1 merge → you fill `POST_DEPLOY_AC_VERDICT v1` (AC1/AC2/AC3) on prod after deploy.
- Ship report answers the done rubric literally; bus-post to lead on ship.
