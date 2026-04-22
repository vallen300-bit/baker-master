# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1
**Task posted:** 2026-04-22 (post PR #38 merge)
**Status:** OPEN — CLAIM_LOOP_ORPHAN_STATES_2 (production-hardening, follow-up to PR #38)

---

## Brief-route note (charter §6A)

This brief is **continuation-of-work** following PR #38's pattern, so it's dispatched in the existing freehand shape rather than going through the full `/write-brief` 6-step route. The PR #38 structure is already proven and this fix is a near-mirror of it applied to 3 additional orphan states.

Future unrelated briefs follow `/write-brief` per charter §6A.

---

## Context

PR #38 (CLAIM_LOOP_OPUS_FAILED_RECLAIM_1) closed the `opus_failed` orphan class with a secondary claim function in `kbl/pipeline_tick.py`. Production self-heals that specific state now — confirmed in prod tonight (`awaiting_opus` count > 0, first time ever).

But three more orphan states exist on the Render side with the same root cause (claim loop only picks `pending`):

- **`awaiting_classify`** — Step 3's `_STATE_NEXT` (flipped at `step3_extract.py:93`). If `_process_signal_remote` crashes between Step 3 commit and Step 4 call, the row orphans here. Also Step 3's `success=False` path routes here (`step3_extract.py:534`).
- **`awaiting_opus`** (pure orphan, not from opus_failed) — Step 4's `_STATE_NEXT` (flipped at `step4_classify.py:60`). Step 4 commits success → awaiting_opus, tick crashes before Step 5 runs. PR #38's `claim_one_opus_failed` only filters `status='opus_failed'` — pure awaiting_opus orphans stay stranded.
- **`awaiting_finalize`** — Step 5's `_STATE_NEXT` (flipped at `step5_opus.py:122`). Step 5 commits success → awaiting_finalize, tick crashes before Step 6 runs. AI Head manually recovered 55 of these in recovery #4 post-PR #36 tonight.

Out of scope:
- **`awaiting_commit`** — Step 6's `_STATE_NEXT`. Mac Mini poller's claim domain (see `kbl/poller.py`). A separate brief covers Mac-Mini-side reclaim if needed.

## Scope — extend the secondary claim chain

### 1. Three new claim functions in `kbl/pipeline_tick.py`

Mirror PR #38's `claim_one_opus_failed` pattern for each of the three states. All use `FOR UPDATE SKIP LOCKED`, commit-before-return, flip to the corresponding `_STATE_RUNNING`:

- **`claim_one_awaiting_classify(conn) -> int | None`** — selects `status='awaiting_classify'`, flips to `classify_running` (Step 4's `_STATE_RUNNING`).
- **`claim_one_awaiting_opus(conn) -> int | None`** — selects `status='awaiting_opus'`, flips to `opus_running` (Step 5's `_STATE_RUNNING`). Note: this is DIFFERENT from PR #38's `claim_one_opus_failed` — that one selects `status='opus_failed'` and flips to `awaiting_opus`. This one handles pure awaiting_opus orphans.
- **`claim_one_awaiting_finalize(conn) -> int | None`** — selects `status='awaiting_finalize'`, flips to `finalize_running` (Step 6's `_STATE_RUNNING`).

**Staleness guard:** each claim filters on `started_at < NOW() - INTERVAL '15 minutes'` (or similar — pick a value safely larger than the longest-running step, Step 5 Opus call is the slowest at ~60s). This prevents claiming a row that's legitimately mid-flight in another tick. B1 to pick the exact interval based on observed Step 5 runtime in prod.

**No budget counter for these** — unlike `opus_failed`, these are crash-recovery states, not retry states. Normal pipeline advances them forward within one tick; only crashes orphan them. Reclaim always attempts continuation.

### 2. Three new dispatch functions

- **`_process_signal_classify_remote(signal_id, conn)`** — runs Steps 4 → 5 → 6. Imports `step4_classify`, `step5_opus`, `step6_finalize`. NOT Steps 1-3 (already done), NOT Step 7 (Mac Mini).
- **`_process_signal_opus_remote(signal_id, conn)`** — runs Steps 5 → 6. Same signature as PR #38's `_process_signal_reclaim_remote` but entered from `awaiting_opus` directly (no pre-flip to awaiting_opus needed, already there).
- **`_process_signal_finalize_remote(signal_id, conn)`** — runs Step 6 only.

Each preserves the tx-boundary contract from PR #38: one `conn.commit()` per successful step, `conn.rollback()` on raise, step-internal commits (terminal-state flips) survive.

### 3. Dispatch order in `pipeline_tick.main()`

Primary claim chain:
1. `claim_one_signal` (pending) → `_process_signal_remote` — unchanged.
2. `claim_one_opus_failed` (PR #38) → `_process_signal_reclaim_remote` — unchanged.
3. **NEW:** `claim_one_awaiting_classify` → `_process_signal_classify_remote`.
4. **NEW:** `claim_one_awaiting_opus` → `_process_signal_opus_remote`.
5. **NEW:** `claim_one_awaiting_finalize` → `_process_signal_finalize_remote`.
6. Empty queue → return 0.

Primary (`pending`) keeps priority — reclaim chain only runs when no new signals are waiting. Same philosophy as PR #38.

### 4. Regression tests (12+ in `tests/test_pipeline_tick.py`)

Mirror PR #38's test scaffold. 3 claim-function tests × 3 states = 9, plus 3 dispatch tests (one per new `_process_signal_*_remote`):

Per claim function:
- `test_claim_one_<state>_returns_eligible_row` — fixture at target status, old started_at → returns id, flips to RUNNING.
- `test_claim_one_<state>_skips_fresh_rows` — fixture at target status, started_at within 15 min → NOT claimed.
- `test_claim_one_<state>_returns_none_when_empty` — no eligible rows → None.

Per dispatch function:
- `test_classify_dispatch_runs_4_5_6_not_1_3_or_7` — mock all 7 step paths, assert call_log == ["step4", "step5", "step6"].
- `test_opus_dispatch_runs_5_6_not_1_4_or_7` — call_log == ["step5", "step6"].
- `test_finalize_dispatch_runs_6_not_others` — call_log == ["step6"].

Reuse PR #38's `_enter_all_steps` / `_STEP_PATHS` scaffold for mock patching.

### 5. Scope discipline

- Only `kbl/pipeline_tick.py` + `tests/test_pipeline_tick.py`. Zero other files.
- No schema changes. Reuse existing `started_at` column.
- No new env vars.
- No changes to existing `claim_one_signal` / `claim_one_opus_failed` / their dispatch functions.
- No Mac Mini poller changes (separate brief if needed).
- No changes to step1-7 internals.

### 6. No-ship-by-inspection gate

Full `pytest tests/` log in ship report. Reproduce the 16-failure pre-existing baseline on main (same as PR #37/#38 verification). Any new failure → REQUEST_CHANGES territory.

## Deliverable

- PR on baker-master, branch `claim-loop-orphan-states-2`, reviewer B3.
- Ship report at `briefs/_reports/B1_claim_loop_orphan_states_2_{YYYYMMDD}.md`.
- Sections: §before/after, §claim-functions, §dispatch-functions, §staleness-guard (chosen interval + rationale), §test-matrix (12 tests), §full pytest output, §production-impact (after merge: no more manual recovery UPDATEs on awaiting_classify / awaiting_opus / awaiting_finalize).

## Constraints

- **Effort: M (~90-120 min).** Three near-identical mirrors of PR #38, plus ~12 tests.
- Timebox: 3 hours.
- Working dir: `~/bm-b1`. `git checkout main && git pull -q` first.

## Why now

AI Head has run 3 recoveries on awaiting_* states this session already (#3, #4, #6). Each one manual UPDATE. The pattern keeps recurring because these orphan states have no automatic reclaim. PR #38 proved the reclaim pattern works. Extending it to the remaining 3 states closes the entire claim-loop orphan class on the Render side.

On APPROVE, AI Head auto-merges (Tier A) and Render redeploys. Production-hardening complete for the Render side of the pipeline.

— AI Head
