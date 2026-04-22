# B1 — CLAIM_LOOP_RUNNING_STATES_3 — ship report

**From:** Code Brisen #1
**To:** AI Head (reviewer: B3)
**Date:** 2026-04-22
**Branch:** `claim-loop-running-states-3`
**Status:** SHIPPED — PR open, reviewer B3, full-suite pytest captured, zero regressions.

---

## §before/after

### Before (post PR #39)

PR #39 closed the `awaiting_*` orphan class (crashes BETWEEN steps). But crashes DURING a step leave rows at `*_running`:

- `classify_running` — Step 4 mid-flight when worker died.
- `opus_running` — Step 5 mid-flight (Opus API call / R3 ladder).
- `finalize_running` — Step 6 mid-flight (validation / vault write).

These rows were invisible to PR #39's claim chain. Manual `UPDATE signal_queue SET status = ...` was the only recovery.

### After (`kbl/pipeline_tick.py`)

One new module-level SQL constant + one new function. Wired into `main()` before the claim chain.

```python
# kbl/pipeline_tick.py:190
_RUNNING_ORPHAN_STALE_INTERVAL = "15 minutes"

# kbl/pipeline_tick.py:200-210
_RUNNING_RESET_SQL = f"""
UPDATE signal_queue
   SET status = CASE status
     WHEN 'classify_running' THEN 'awaiting_classify'
     WHEN 'opus_running'     THEN 'awaiting_opus'
     WHEN 'finalize_running' THEN 'awaiting_finalize'
   END
 WHERE status IN ('classify_running', 'opus_running', 'finalize_running')
   AND started_at < NOW() - INTERVAL '{_RUNNING_ORPHAN_STALE_INTERVAL}'
RETURNING id, status
"""

# kbl/pipeline_tick.py:213
def reset_stale_running_orphans(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(_RUNNING_RESET_SQL)
        n = cur.rowcount
    conn.commit()
    return n
```

And in `main()` (inside the `with get_conn()` block, BEFORE `claim_one_signal`):

```python
# kbl/pipeline_tick.py:799
try:
    n_reset = reset_stale_running_orphans(conn)
except Exception:
    conn.rollback()
    raise
if n_reset:
    _local.info("[pipeline_tick] reset %d stale *_running orphan(s) to awaiting_*", n_reset)
```

Design distinct from PR #39: one SQL statement, no per-state claim/dispatch. Reset commits on the outer tick connection before the claim chain runs — a stale `opus_running` row reset on this pass becomes eligible for `claim_one_awaiting_opus` in the same tick.

---

## §staleness-guard

Chosen interval: **15 minutes**, exposed as module constant `_RUNNING_ORPHAN_STALE_INTERVAL`. Same value as PR #39's `_AWAITING_ORPHAN_STALE_INTERVAL`.

Rationale (same as PR #39):
- `finalize_running` max legit duration: seconds (Pydantic + YAML serialize, brief terminal flips).
- `opus_running` max legit duration: ~180s (Step 5 R3 ladder × 60s Opus call).
- `classify_running` max legit duration: seconds (Step 4 is local, no LLM).
- Scheduler `IntervalTrigger(seconds=120)` + `max_instances=1` prevents concurrent ticks.
- 15 min is ≥5× the slowest step's legit duration. Safe margin.

Bare SQL interval literal — module constant, no injection surface.

---

## §integration-with-pr39-chain

Same-tick reset→reclaim→dispatch loop closes in one tick. Order inside `main()`:

1. `reset_stale_running_orphans(conn)` — flips stale `*_running` → `awaiting_*`, commits.
2. `claim_one_signal(conn)` — primary `pending` claim.
3. `claim_one_opus_failed(conn)` — PR #38 retry-reclaim.
4. `claim_one_awaiting_classify(conn)` — PR #39 crash-recovery.
5. `claim_one_awaiting_opus(conn)` — PR #39 crash-recovery (picks up just-reset `opus_running` rows).
6. `claim_one_awaiting_finalize(conn)` — PR #39 crash-recovery.

The reset has its own commit, so any row reset on step 1 is visible to steps 4-6 within the same connection and same tick. No "wait for next tick" is needed for organic reclaim.

Zero changes to PR #39's chain. Zero changes to step modules. Zero schema changes.

---

## §test-matrix

7 new regressions in `tests/test_pipeline_tick.py`:

| # | Test | Guards |
|---|------|--------|
| 1 | `test_reset_stale_running_orphans_flips_classify_running` | Stale `classify_running` → `awaiting_classify` via CASE; single UPDATE + commit; asserts SQL shape (CASE mapping, staleness guard, `started_at` column). |
| 2 | `test_reset_stale_running_orphans_flips_opus_running` | Stale `opus_running` → `awaiting_opus`. |
| 3 | `test_reset_stale_running_orphans_flips_finalize_running` | Stale `finalize_running` → `awaiting_finalize`; asserts `status IN (…)` WHERE clause covers all three classes. |
| 4 | `test_reset_stale_running_orphans_skips_fresh_rows` | Fresh row → rowcount=0, UPDATE fires (single statement always runs), commit fires, returns 0. Staleness guard present in SQL. |
| 5 | `test_reset_stale_running_orphans_returns_zero_when_empty` | Empty → rowcount=0, returns 0 — indistinguishable at function boundary from guarded-out (which is the point). |
| 6 | `test_main_calls_reset_before_claim_chain` | Call ordering contract: reset fires BEFORE `claim_one_signal`. Asserts via shared `call_log` side-effect. |
| 7 | `test_main_reset_and_reclaim_in_same_tick` | Full integration: stale `opus_running` reset → claimed by `claim_one_awaiting_opus` → dispatched to `_process_signal_opus_remote` — all within one tick, one connection. |

Result:

```
$ /tmp/b1-venv/bin/pytest tests/test_pipeline_tick.py -q
......................................................                   [100%]
54 passed in 0.37s
```

54 green = 47 pre-existing (PR #39) + 7 new.

---

## §test-results (full pytest — no-ship-by-inspection gate)

Run target: `/tmp/b1-venv/bin/pytest tests/ 2>&1 | tee /tmp/b1-pytest-running-states.log`

**Environment:** Python 3.12.12, pytest 9.0.3, asyncio mode=STRICT. Throwaway venv at `/tmp/b1-venv` (system Python 3.9 fails PEP-604 collection — same setup as PR #37/#38/#39).

**Result:** `16 failed, 812 passed, 21 skipped, 19 warnings in 12.40s`

### Expected baseline match

Brief predicted `16 failed, 812 passed, 21 skipped` (`805 + 7 = 812`). Observed matches exactly. Zero new regressions.

### Failure triage — all 16 pre-existing on main

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

Identical failure set to PR #37 / PR #38 / PR #39 / PR #40 verification runs. All 16 pre-exist on `main` independent of this branch; confirmed via baseline pytest run immediately after branching from main (before any code changes).

### Full log

Saved to `/tmp/b1-pytest-running-states.log` on the B1 box. Head + tail:

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b1
plugins: langsmith-0.7.33, asyncio-1.3.0, anyio-4.13.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 849 items

tests/test_1m_storeback_verify.py FFFF                                   [  0%]
...
=========== 16 failed, 812 passed, 21 skipped, 19 warnings in 12.40s ===========
```

---

## §production-impact

After merge + Render auto-deploy, the `*_running` orphan class self-heals on the Render side. AI Head no longer needs manual `UPDATE signal_queue` to recover rows stuck at `classify_running` / `opus_running` / `finalize_running` after a Render worker crash or scale event.

**Current queue state (per brief):** one row actively `finalize_running` — legitimately mid-flight, not an orphan. Staleness guard (15 min) ensures it is NOT disturbed by this reset path. Future orphans of any of the three classes will be reset within one tick of crossing the 15-minute threshold and reclaimed by PR #39's chain on the same or next tick.

**Scope discipline:**
- No changes to PR #39 chain.
- No changes to step modules (`step4_classify.py`, `step5_opus.py`, `step6_finalize.py`).
- No schema changes — reuses `status` + `started_at` columns.
- No cleanup of pre-existing orphans — the brief is forward-looking; any currently-orphaned `*_running` row is reset + reclaimed organically on the first tick after deploy.

**Out of scope (explicit in brief):** `awaiting_commit` orphans (Mac Mini poller's claim domain), any changes to PR #39 chain.

---

## §delivery checklist

- [x] Branch `claim-loop-running-states-3` pushed
- [x] PR opened on baker-master (reviewer B3) — see §pr-url
- [x] `reset_stale_running_orphans(conn) -> int` implemented in `kbl/pipeline_tick.py`
- [x] Module constants `_RUNNING_ORPHAN_STALE_INTERVAL` + `_RUNNING_RESET_SQL` added (style mirrors PR #39's `_AWAITING_ORPHAN_STALE_INTERVAL`)
- [x] `main()` wires reset BEFORE claim chain; rollback-on-raise contract preserved
- [x] 7 regression tests added per §test-matrix (6 brief-specified + 1 same-tick integration)
- [x] Zero schema changes, zero env vars, zero changes to PR #39 chain or step modules
- [x] Full pytest output captured (`/tmp/b1-pytest-running-states.log`): `16 failed, 812 passed, 21 skipped`
- [x] Expected baseline `16 failed, 812 passed, 21 skipped` matched exactly
- [x] Staleness interval (15 min) chosen + rationale documented
- [x] Timebox: shipped inside 2.5 h window

---

## §pr-url

https://github.com/vallen300-bit/baker-master/pull/41

— B1, 2026-04-22
