# B1 — CLAIM_LOOP_ORPHAN_STATES_2 — ship report

**From:** Code Brisen #1
**To:** AI Head (reviewer: B3)
**Date:** 2026-04-22
**Branch:** `claim-loop-orphan-states-2`
**Status:** SHIPPED — PR open, reviewer B3, full-suite pytest captured, zero regressions against main.

---

## §before/after

### Before (`kbl/pipeline_tick.py`)

Claim chain was two-deep after PR #38:

1. `claim_one_signal` → `_process_signal_remote` (pending)
2. `claim_one_opus_failed` → `_process_signal_reclaim_remote` (opus_failed retry state)

Three crash-recovery orphan classes had no programmatic reclaim:
- **`awaiting_classify`** — Step 3 committed extraction, tick crashed before Step 4 started.
- **`awaiting_opus`** — Step 4 committed decision, tick crashed before Step 5 started. (Distinct from `claim_one_opus_failed`'s pre-flip target — that claims `opus_failed`, this state is a different orphan class.)
- **`awaiting_finalize`** — Step 5 committed Opus draft, tick crashed before Step 6 started. AI Head had manually UPDATEd 55 of these in recovery #4 post-PR #36 tonight, and that pattern had already recurred three times this session (#3, #4, #6) before this brief.

### After (`kbl/pipeline_tick.py`)

Claim chain now five-deep, ordered earliest-crash-stage first so orphans advance one step per tick:

1. `claim_one_signal` → `_process_signal_remote` (pending)
2. `claim_one_opus_failed` → `_process_signal_reclaim_remote` (opus_failed retry state)
3. **NEW** `claim_one_awaiting_classify` → `_process_signal_classify_remote` (Steps 4-5-6)
4. **NEW** `claim_one_awaiting_opus` → `_process_signal_opus_remote` (Steps 5-6)
5. **NEW** `claim_one_awaiting_finalize` → `_process_signal_finalize_remote` (Step 6)

Primary claim retains strict priority — reclaim chain only runs when no new `pending` signal is waiting, and within the chain, the earliest-stage orphan goes first per tick. A row orphaned at `awaiting_classify` advances `classify_running → awaiting_opus → opus_running → awaiting_finalize → ...` in one tick via `_process_signal_classify_remote` (which inlines Steps 4-5-6) — no leapfrog, no per-tick ladder-climb overhead.

---

## §claim-functions

All three mirror PR #38's `claim_one_opus_failed` shape. Differences vs PR #38:

| Facet | PR #38 `claim_one_opus_failed` | This brief — `claim_one_awaiting_*` |
|---|---|---|
| State selector | `status = 'opus_failed'` | `status = 'awaiting_{classify,opus,finalize}'` |
| Budget guard | `finalize_retry_count < _MAX_OPUS_REFLIPS` | *(none — crash-recovery, not retry)* |
| Staleness guard | *(none — retry can fire immediately)* | `started_at < NOW() - INTERVAL '15 minutes'` |
| Defensive ALTER | `ADD COLUMN IF NOT EXISTS finalize_retry_count…` | *(none — reuses existing `started_at` column)* |
| Target state after flip | `awaiting_opus` (re-enters Step 5) | `{classify,opus,finalize}_running` (re-enters the skipped step) |
| Concurrency | `FOR UPDATE SKIP LOCKED` | `FOR UPDATE SKIP LOCKED` |
| Commit | 1 commit (success only) | 1 commit (success only) |

No schema changes. No env vars.

---

## §staleness-guard

Chosen interval: **15 minutes**, exposed as module constant `_AWAITING_ORPHAN_STALE_INTERVAL`.

Rationale:
- Step 5 Opus call is the slowest step in the pipeline. Observed prod runtime ~60s per call. With the R3 retry ladder (`_R3_MAX_ATTEMPTS = 3`) a single Step 5 run can span ~180s (3 × 60s).
- APScheduler registers `kbl_pipeline_tick` with `IntervalTrigger(seconds=120)` and `max_instances=1` (`triggers/embedded_scheduler.py:558-560`). No two ticks can run concurrently under normal operation.
- 15 minutes gives a ~5× safety margin over the slowest observed step and absorbs any pathological hang in a primary tick that hasn't yet crashed + been observed.
- Short enough that operator lag on a legitimate orphan is bounded at under an hour; long enough that no legitimate mid-flight row is ever double-claimed.

SQL shape (all three claim functions use the same literal constant):

```sql
SELECT id FROM signal_queue
WHERE status = '<state>'
  AND started_at < NOW() - INTERVAL '15 minutes'
ORDER BY priority DESC, created_at ASC
LIMIT 1
FOR UPDATE SKIP LOCKED
```

The `'15 minutes'` literal is a bare SQL interval — psycopg2 does not parametrize `INTERVAL`, and the value is a module constant with no injection surface.

`started_at` is set only by `claim_one_signal` (never by the reclaim functions). This is intentional: if a reclaim succeeds, the row advances out of `awaiting_*` naturally; if the reclaim itself crashes mid-step, the row sits at `*_running` (not in any claim filter) and requires the future `*_running` brief to recover. A re-orphaning that lands at a later `awaiting_*` state remains eligible immediately on the next tick — desirable behavior, since the row genuinely needs to advance.

---

## §dispatch-functions

Each mirrors `_process_signal_remote`'s tx-boundary contract: one `conn.commit()` per successful step, `conn.rollback()` on raise, step-internal terminal flips survive the outer rollback.

| Function | Steps run | Post-Step-5 status gate | Commits on happy path |
|---|---|---|---|
| `_process_signal_classify_remote` | 4 → 5 → 6 | yes (skip Step 6 on `paused_cost_cap`/`opus_failed`) | 3 |
| `_process_signal_opus_remote` | 5 → 6 | yes (same gate) | 2 |
| `_process_signal_finalize_remote` | 6 only | n/a | 1 |

Step 7 is NOT imported in any of the three — Render has no vault clone (CHANDA Inv 9). Steps 1-3 are never re-run on any reclaim path — the row's upstream columns (`triage_score`, `primary_matter`, `related_matters`, `resolved_thread_paths`, `extracted_entities`) are already valid from the first attempt; re-running would waste LLM tokens and risk deterministic drift that the retry-counter accounting cannot model.

`_mark_running` inside each step is an idempotent same-state UPDATE when the caller has pre-flipped to `*_running` — harmless.

---

## §test-matrix

15 new regressions in `tests/test_pipeline_tick.py`. 2 pre-existing PR #38 tests updated to patch the expanded claim chain.

**Claim-function coverage (9 tests, 3 per state):**

| # | Test | Guards |
|---|------|--------|
| 1 | `test_claim_one_awaiting_classify_returns_eligible_row` | Stale `awaiting_classify` → flips to `classify_running`, commits once; SQL shape asserts state + staleness interval + SKIP LOCKED. |
| 2 | `test_claim_one_awaiting_classify_skips_fresh_rows` | Fresh row filtered out by `started_at < NOW() - INTERVAL '15 minutes'` — no UPDATE, no commit. |
| 3 | `test_claim_one_awaiting_classify_returns_none_when_empty` | Empty queue → None, no side effects. |
| 4 | `test_claim_one_awaiting_opus_returns_eligible_row` | Stale `awaiting_opus` → `opus_running`; distinct from PR #38's `opus_failed → awaiting_opus`. |
| 5 | `test_claim_one_awaiting_opus_skips_fresh_rows` | Fresh row filtered by staleness guard. |
| 6 | `test_claim_one_awaiting_opus_returns_none_when_empty` | Empty → None. |
| 7 | `test_claim_one_awaiting_finalize_returns_eligible_row` | Stale `awaiting_finalize` → `finalize_running`; this is the state AI Head has been manually recovering. |
| 8 | `test_claim_one_awaiting_finalize_skips_fresh_rows` | Fresh row filtered by staleness guard. |
| 9 | `test_claim_one_awaiting_finalize_returns_none_when_empty` | Empty → None. |

**Dispatch-function coverage (3 tests):**

| # | Test | Guards |
|---|------|--------|
| 10 | `test_classify_dispatch_runs_4_5_6_not_1_3_or_7` | `call_log == ["step4","step5","step6"]`; Steps 1-3 + 7 never called; 3 commits, 0 rollbacks. |
| 11 | `test_opus_dispatch_runs_5_6_not_1_4_or_7` | `call_log == ["step5","step6"]`; Steps 1-4 + 7 never called; 2 commits, 0 rollbacks. |
| 12 | `test_finalize_dispatch_runs_6_not_others` | `call_log == ["step6"]`; Steps 1-5 + 7 never called; 1 commit, 0 rollbacks. |

**`main()` dispatch-chain integration (3 new + 2 updated):**

| # | Test | Guards |
|---|------|--------|
| 13 | `test_main_falls_back_to_classify_reclaim_when_earlier_queues_empty` | Primary + opus_failed empty, awaiting_classify hit → dispatches to classify_remote; later reclaims never consulted. |
| 14 | `test_main_falls_back_to_opus_reclaim_when_earlier_queues_empty` | …awaiting_classify empty, awaiting_opus hit → dispatches to opus_remote; finalize reclaim never consulted. |
| 15 | `test_main_falls_back_to_finalize_reclaim_when_earlier_queues_empty` | All earlier empty, awaiting_finalize hit → dispatches to finalize_remote. |
| 16 | `test_main_all_queues_empty_returns_zero_without_any_dispatch` | All 5 claim functions empty → rc=0, zero dispatch calls. |
| 17 | `test_main_primary_hit_skips_all_reclaims` | Primary returns id → dispatches immediately; NONE of the 4 reclaim claim functions consulted. |
| — | `test_main_enabled_queue_empty_returns_zero` *(updated)* | Expanded to patch all 5 claim functions + all 5 dispatch functions. |
| — | `test_main_both_queues_empty_returns_zero` *(updated)* | Same expansion — was a 2-queue check, now a 5-queue check. |

**Result on this file:**

```
$ /tmp/b1-venv/bin/pytest tests/test_pipeline_tick.py -q
...............................................                          [100%]
47 passed in 0.26s
```

47 green — 32 pre-existing + 15 new.

---

## §test-results (full pytest — no-ship-by-inspection gate)

Run target: `/tmp/b1-venv/bin/pytest tests/ 2>&1 | tee /tmp/b1-pytest-full.log`

**Environment:** Python 3.12.12, pytest 9.0.3, asyncio mode=STRICT. Repo pins `.python-version=3.12.3`; system Python 3.9 fails collection on `memory/store_back.py` PEP-604 unions, hence the throwaway venv at `/tmp/b1-venv` (same as PR #37/#38).

**Result:** `16 failed, 799 passed, 21 skipped, 19 warnings in 11.80s`

### Failure triage — all 16 pre-existing on main, none touch this change

```
FAILED tests/test_1m_storeback_verify.py::test_1_dry_run          (FileNotFoundError — storeback checkpoint fixture)
FAILED tests/test_1m_storeback_verify.py::test_2_mock_analysis    (ModuleNotFoundError)
FAILED tests/test_1m_storeback_verify.py::test_3_chunking         (ModuleNotFoundError)
FAILED tests/test_1m_storeback_verify.py::test_4_failure_resilience (ModuleNotFoundError)
FAILED tests/test_clickup_client.py::TestWriteSafety::test_add_tag_wrong_space_raises
FAILED tests/test_clickup_client.py::TestWriteSafety::test_create_task_wrong_space_raises
FAILED tests/test_clickup_client.py::TestWriteSafety::test_post_comment_wrong_space_raises
FAILED tests/test_clickup_client.py::TestWriteSafety::test_remove_tag_wrong_space_raises
FAILED tests/test_clickup_client.py::TestWriteSafety::test_update_task_wrong_space_raises
FAILED tests/test_clickup_integration.py::test_tasks_in_database    (voyageai env)
FAILED tests/test_clickup_integration.py::test_qdrant_clickup_collection (voyageai env)
FAILED tests/test_clickup_integration.py::test_watermark_persistence (voyageai env)
FAILED tests/test_scan_endpoint.py::test_scan_returns_sse_stream  (assert 401 — auth env)
FAILED tests/test_scan_endpoint.py::test_scan_rejects_empty_question
FAILED tests/test_scan_endpoint.py::test_scan_accepts_history
FAILED tests/test_scan_prompt.py::test_prompt_is_conversational_no_json_requirement
```

**Pre-existence verification:** stashed this branch's changes, ran the same five test files against `main`:

```
$ git stash
Saved working directory and index state WIP on claim-loop-orphan-states-2

$ /tmp/b1-venv/bin/pytest tests/test_1m_storeback_verify.py tests/test_clickup_client.py \
    tests/test_clickup_integration.py tests/test_scan_endpoint.py tests/test_scan_prompt.py
================== 16 failed, 17 passed, 14 warnings in 3.58s ==================

$ git stash pop
```

Identical 16-failure baseline. Zero regressions introduced by this PR.

### Full log

Saved to `/tmp/b1-pytest-full.log` (≈360 lines) on the B1 box. Head + tail:

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b1
plugins: langsmith-0.7.33, asyncio-1.3.0, anyio-4.13.0
asyncio: mode=Mode.STRICT, ...
collected 836 items

tests/test_1m_storeback_verify.py FFFF                                   [  0%]
tests/test_anthropic_client.py .....................s                    [  3%]
tests/test_bridge_alerts_to_signal.py .................................. [  7%]
...
tests/test_pipeline_tick.py ...............................................   [81%]
...
=========== 16 failed, 799 passed, 21 skipped, 19 warnings in 11.80s ===========
```

`tests/test_pipeline_tick.py` (our file) at 81% bar — all 47 green on this line.

---

## §production-impact

After merge + Render auto-deploy, the Render-side claim-loop orphan class is closed. Operator no longer needs manual `UPDATE signal_queue SET status = ... WHERE status = 'awaiting_{classify,opus,finalize}' AND ...` during session-end cleanup.

**Direct impact on observed issues this session:**
- Recovery #3 (awaiting_classify rows) — would auto-recover on next tick.
- Recovery #4 (55 awaiting_finalize rows post-PR #36) — would have auto-recovered across 55 ticks (≈110 min) without operator intervention.
- Recovery #6 (awaiting_opus rows) — would auto-recover on next tick.

**Out-of-scope orphan class (not covered here):** `*_running` states (`processing`, `extract_running`, `classify_running`, `opus_running`, `finalize_running`) — these represent crashes *during* a step, not between steps, and require a different recovery shape (stuck-claim detection by age of `*_running` state, not by `started_at`). Also out of scope: `awaiting_commit` is the Mac Mini poller's claim domain (`kbl.poller`); a separate brief covers Mac-Mini-side reclaim if ever needed.

**Short-term fallback (if PR sits in review):** the existing manual-UPDATE pattern still works. No operational change required until merge.

---

## §delivery checklist

- [x] Branch `claim-loop-orphan-states-2` pushed
- [x] PR opened on baker-master (reviewer B3) — see §pr-url below
- [x] 3 new claim functions (`claim_one_awaiting_{classify,opus,finalize}`) with staleness guard + SKIP LOCKED
- [x] 3 new dispatch functions (`_process_signal_{classify,opus,finalize}_remote`) with tx-boundary contract preserved
- [x] `main()` claim chain extended from 2→5 deep, earliest-stage-first ordering
- [x] 15 new regression tests covering the brief's 12-test spec (+3 `main()` integration tests)
- [x] 2 updated PR-#38 tests (expanded patches for new claim/dispatch functions)
- [x] Zero schema changes, zero env vars, zero other-file changes (only `kbl/pipeline_tick.py` + `tests/test_pipeline_tick.py`)
- [x] Full pytest output captured (`/tmp/b1-pytest-full.log`) — 16 pre-existing failures confirmed vs main
- [x] Staleness interval chosen + rationale documented (15 min, module constant `_AWAITING_ORPHAN_STALE_INTERVAL`)
- [x] Timebox: shipped inside 3 h window (effort M)

---

## §pr-url

https://github.com/vallen300-bit/baker-master/pull/39

— B1, 2026-04-22
