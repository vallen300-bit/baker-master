# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3
**Task posted:** 2026-04-22 (post-B1 ship of PR #38)
**Status:** OPEN — review PR #38 CLAIM_LOOP_OPUS_FAILED_RECLAIM_1 (production-hardening)

---

## Context

B1 shipped the permanent fix for the opus_failed orphan class. This retires recovery #7-style manual UPDATEs. AI Head has run 4 Tier B recoveries in the last 24h (including #7 on 16 rows tonight), each tracing to the same root cause: `kbl/pipeline_tick.py:84-105` only claims `status='pending'`, so Step 6 validation failures orphan at `opus_failed` despite Step 6's docstring claiming `pipeline_tick re-queues into Step 5 for the R3`.

Tier A auto-merge on your APPROVE. No post-merge Tier B needed — the fix is self-healing.

## PR

- **PR #38:** https://github.com/vallen300-bit/baker-master/pull/38
- **Branch:** `claim-loop-opus-failed-reclaim-1`
- **Head SHA:** `0bfb6ee`
- **Ship report:** `briefs/_reports/B1_claim_loop_opus_failed_reclaim_20260422.md` (on main at `023fd55`)
- **Scope:** 2 files — `kbl/pipeline_tick.py` (+150/-10), `tests/test_pipeline_tick.py` (+312/-2). Nothing else.

## Focus items (in order)

### 1. Secondary claim function correctness

New `claim_one_opus_failed(conn) -> int | None`. Must:

- `SELECT ... WHERE status='opus_failed' AND finalize_retry_count < _MAX_OPUS_REFLIPS` — budget guard enforced at SELECT.
- `ORDER BY priority DESC, created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED` — same concurrency shape as `claim_one_signal`.
- Flip row to `awaiting_opus` (Step 5's pre-state per `kbl/steps/step5_opus.py:49`) before returning signal_id. NOT `processing` — that's the primary-claim state.
- COMMIT before returning (consistent with `claim_one_signal` line 104).
- Imports `_MAX_OPUS_REFLIPS` from `step6_finalize` — confirm the constant exists and is still 3.

### 2. Dispatch path in `pipeline_tick.main()`

- Primary `claim_one_signal` runs first. No change.
- If returns None, call `claim_one_opus_failed`. If returns None too, normal empty-queue exit.
- If returns a signal_id, call a new `_process_signal_reclaim_remote` (NOT `_process_signal_remote`). Reclaim path starts at Step 5 only — Steps 1-4 must NOT run.
- Verify: `primary_matter`, `triage_score`, `triage_confidence`, `related_matters`, `vedana` are NOT overwritten on reclaim. Walk the reclaim dispatch and confirm Step 1 / Step 3 are never invoked.

### 3. Reclaim runs Steps 5 + 6 only

- Step 5 `synthesize()` called on `awaiting_opus` row. Step 5 internal R3 ladder (IDENTICAL → PARED → MINIMAL) runs fresh.
- Step 5 overwrites `opus_draft_markdown` unconditionally. B1 audited `_write_draft_and_advance` and claims it already does this — verify by reading the code yourself (don't take their word).
- Step 5 flips to `awaiting_finalize` on success. Same-invocation dispatch to Step 6 (same transaction-boundary contract as primary path).
- Step 6 re-validates. On success → `awaiting_commit` (Mac Mini poller's domain). On failure → Step 6's existing code bumps `finalize_retry_count` and flips to `opus_failed` (or `finalize_failed` terminal if budget exhausted).
- Step 7 is NOT called (Mac Mini poller's domain, unchanged).

### 4. Budget-exhaustion behavior

- Row at `finalize_retry_count = _MAX_OPUS_REFLIPS` (=3) must NOT be claimed by `claim_one_opus_failed`. Stays at `opus_failed` (or `finalize_failed` per Step 6's existing promote logic).
- 3rd reflip: Step 6 detects `retry_count == _MAX_OPUS_REFLIPS - 1` pre-bump, bumps to `_MAX_OPUS_REFLIPS`, flips to `finalize_failed` (terminal). Existing Step 6 code — verify B1 didn't change its semantics.

### 5. Test matrix (5 per brief + 3 bonus = 8 tests)

- `test_claim_one_opus_failed_returns_eligible_row` — fixture at `opus_failed`, `retry_count=1`, returns id, flips to `awaiting_opus`.
- `test_claim_one_opus_failed_skips_budget_exhausted` — `retry_count=3` row not claimed.
- `test_claim_one_opus_failed_returns_none_when_empty` — no eligible rows → None.
- `test_reclaim_runs_steps_5_6_not_1_4` — primary_matter/triage preserved on reclaim; Step 1 never called.
- `test_reclaim_budget_exhaustion_routes_to_finalize_failed` — 3rd reflip promotes to `finalize_failed`.
- Plus 3 bonus dispatch tests B1 added. Read them, confirm they cover additional edge cases (not just repaint of the 5 above).

Verify each test actually exercises its claimed invariant — read the bodies.

### 6. Scope discipline

- Only 2 files changed. No schema (confirm `finalize_retry_count` reused). No new env vars. No changes to `claim_one_signal` (primary path). No Mac Mini poller changes. No `awaiting_classify` / `awaiting_finalize` / `awaiting_commit` reclaim — that's deferred to `CLAIM_LOOP_ORPHAN_STATES_2`.
- `_MAX_OPUS_REFLIPS` is reused (not redefined) — one source of truth for the budget constant.

### 7. Concurrency safety

- `FOR UPDATE SKIP LOCKED` on the secondary claim prevents double-claim if primary + secondary ticks overlap.
- Primary tick and secondary tick cannot claim the same row (primary is `pending`, secondary is `opus_failed` — disjoint states).
- No new race conditions introduced by running both claims in the same `main()` invocation (they're sequential, not concurrent).

### 8. No-ship-by-inspection gate

B1 claims 16 failed / 782 passed / 21 skipped, same 16 failures pre-existing on main. You MUST independently reproduce:

- Spin up Python 3.12 venv (your own, not B1's `/tmp/b1-venv`).
- `pip install -r requirements.txt`.
- `pytest tests/ 2>&1 | tee /tmp/b3-pr38-pytest-full.log`.
- Stash B1's changes, checkout main, re-run same 4 offending test files.
- `cmp -s /tmp/b3-main-failures.txt /tmp/b3-pr38-failures.txt` → exit 0 expected.

Anchor: `memory/feedback_no_ship_by_inspection.md`. PR #35 was the incident.

## Deliverable

- PR review on #38: **APPROVE** or **REQUEST_CHANGES**.
- Review report: `briefs/_reports/B3_pr38_claim_loop_opus_failed_reclaim_review_20260422.md`.
- Sections: §focus-verdict (one line per focus item 1-8), §regression-delta (cmp-confirmed), §non-gating (nits for follow-up), §verdict.

## On APPROVE

AI Head auto-merges (squash). Render redeploys. Post-deploy: current 1 stranded `opus_failed` row (older batch) will be picked up by the new secondary claim. No manual recovery needed.

## Working dir

`~/bm-b3`. `git checkout main && git pull -q` before starting.

— AI Head
