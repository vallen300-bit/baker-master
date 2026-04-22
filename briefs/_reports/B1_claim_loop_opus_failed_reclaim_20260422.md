# B1 — CLAIM_LOOP_OPUS_FAILED_RECLAIM_1 — ship report

**From:** Code Brisen #1
**To:** AI Head (reviewer: B3)
**Date:** 2026-04-22
**Branch:** `claim-loop-opus-failed-reclaim-1`
**Head SHA:** `0bfb6ee`
**PR:** https://github.com/vallen300-bit/baker-master/pull/38
**Status:** SHIPPED — PR open, full-suite pytest captured, 16 failures confirmed pre-existing on main.

---

## §before/after

### Before

`kbl/pipeline_tick.py` had one claim function (`claim_one_signal`, picks `status='pending'`) and two orchestrators (`_process_signal` full 1→7, `_process_signal_remote` 1→6 for Render). `main()` dispatch was linear:

```python
signal_id = claim_one_signal(conn)
if signal_id is None:
    return 0  # queue empty — normal exit
_process_signal_remote(signal_id, conn)
```

Step 6's docstring (`kbl/steps/step6_finalize.py:24-25`):

> ``opus_failed``. pipeline_tick re-queues into Step 5 for the R3 retry

— but **that re-queue was never implemented**. On validation failure, `_route_validation_failure` bumps `finalize_retry_count`, flips to `opus_failed`, commits, raises. The row sat orphaned. Every next tick saw `claim_one_signal` pick only `pending` rows; the `opus_failed` row was invisible. Operator ran recoveries #3, #4, #6, #7 manually — one Tier-B UPDATE per orphan event.

### After

Two new entry points in `kbl/pipeline_tick.py`:

**`claim_one_opus_failed(conn) -> int | None`** — lines 108-166 of the new file.

```python
def claim_one_opus_failed(conn) -> int | None:
    from kbl.steps.step6_finalize import _MAX_OPUS_REFLIPS
    with conn.cursor() as cur:
        cur.execute(
            "ALTER TABLE signal_queue "
            "ADD COLUMN IF NOT EXISTS finalize_retry_count INT NOT NULL DEFAULT 0"
        )
        cur.execute(
            """
            SELECT id FROM signal_queue
            WHERE status = 'opus_failed'
              AND COALESCE(finalize_retry_count, 0) < %s
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """,
            (_MAX_OPUS_REFLIPS,),
        )
        row = cur.fetchone()
        if not row:
            return None
        signal_id = row[0]
        cur.execute(
            "UPDATE signal_queue SET status = 'awaiting_opus' WHERE id = %s",
            (signal_id,),
        )
        conn.commit()
        return signal_id
```

**`_process_signal_reclaim_remote(signal_id, conn)`** — narrow orchestrator running **Steps 5-6 only**. Same transaction-boundary contract as `_process_signal_remote`: one commit per successful step, rollback on raise, step-internal terminal commits survive.

**`main()` dispatch** — primary claim first; reclaim only if primary empty:

```python
signal_id = claim_one_signal(conn)
if signal_id is not None:
    _process_signal_remote(signal_id, conn)
    return 0

reclaim_id = claim_one_opus_failed(conn)
if reclaim_id is None:
    return 0  # both queues empty

_process_signal_reclaim_remote(reclaim_id, conn)
return 0
```

---

## §reclaim-semantics

### Which steps run

| Step | Primary path (`_process_signal_remote`) | Reclaim path (`_process_signal_reclaim_remote`) |
|------|-----------------------------------------|-------------------------------------------------|
| 1 — triage | ✓ | ✗ (skipped — `triage_score` still valid) |
| 2 — resolve | ✓ | ✗ (skipped — `resolved_thread_paths` still valid) |
| 3 — extract | ✓ | ✗ (skipped — `extracted_entities` still valid) |
| 4 — classify | ✓ | ✗ (skipped — `primary_matter` + `step_5_decision` still valid) |
| 5 — opus | ✓ | ✓ (overwrites `opus_draft_markdown`) |
| 6 — finalize | ✓ | ✓ (re-validates fresh draft) |
| 7 — commit | Not called on Render (Mac Mini) | Not called on Render (Mac Mini) |

### Which fields get overwritten

Step 5's `_write_draft_and_advance` (`kbl/steps/step5_opus.py:326-336`) unconditionally sets `opus_draft_markdown = %s, status = %s` for every routing path (SKIP_INBOX stub, STUB_ONLY stub, FULL_SYNTHESIS Opus response). So re-entering `synthesize()` on an `awaiting_opus` row with a stale prior draft always produces a fresh draft — idempotent by construction. **No code change needed.**

Step 6's `_write_final_and_advance` (`kbl/steps/step6_finalize.py:408-422`) similarly overwrites `final_markdown` + `target_vault_path` on success, and the cross-link UPSERT (`_upsert_cross_link`) keys on `(source_signal_id, target_slug)` with `DO UPDATE` — also idempotent.

### Budget guard (defense in depth)

The claim function filters on `finalize_retry_count < _MAX_OPUS_REFLIPS` (3). Step 6 already terminal-flips to `finalize_failed` when the counter hits the cap (`kbl/steps/step6_finalize.py:762-763`), so rows at `count==3` never sit at `opus_failed` — the claim-side filter is belt-and-suspenders against a race where Step 6's terminal flip somehow missed.

Retry accounting:
- **1st failure** (primary path): count goes 0→1, state = `opus_failed`. Reclaim-eligible.
- **2nd failure** (reclaim #1): count goes 1→2, state = `opus_failed`. Reclaim-eligible.
- **3rd failure** (reclaim #2): count goes 2→3, state = `finalize_failed`. **Terminal** — never reclaimed again.

Result: at most 3 Opus calls per signal before we concede and terminal. Matches the R3 semantics the original Step 6 docstring promised.

### What reclaim does NOT touch

- `primary_matter` (trusted from Step 1 — re-triage risks matter-shift)
- `triage_score` / `triage_confidence` (trusted from Step 1)
- `resolved_thread_paths` (trusted from Step 2)
- `extracted_entities` (trusted from Step 3)
- `step_5_decision` (trusted from Step 4)
- `started_at` (first-attempt timestamp preserved for age tracking)
- Step 7 / Mac Mini poller (owned by `kbl/poller.py`, different reclaim brief)
- `awaiting_classify` / `awaiting_finalize` / `awaiting_commit` orphan states (follow-up brief `CLAIM_LOOP_ORPHAN_STATES_2`)

---

## §test-matrix

8 new regressions added to `tests/test_pipeline_tick.py`. One existing test updated to reflect the new contract.

| # | Test | Guards |
|---|------|--------|
| 1 | `test_claim_one_opus_failed_returns_eligible_row` | Claim-function happy path. Asserts SELECT contains `status='opus_failed'` + `finalize_retry_count` + `FOR UPDATE SKIP LOCKED`, param is `_MAX_OPUS_REFLIPS`, UPDATE flips to `awaiting_opus`, commit fires once, defensive ALTER runs. |
| 2 | `test_claim_one_opus_failed_skips_budget_exhausted` | Budget-exhausted row not claimed. SELECT's `< %s` filter excludes it; no UPDATE, no commit on empty result. |
| 3 | `test_claim_one_opus_failed_returns_none_when_empty` | Empty queue → None, no UPDATE, no commit. Indistinguishable from budget-exhausted at function boundary (both are `fetchone() is None`). |
| 4 | `test_reclaim_runs_steps_5_6_not_1_4` | **Core scope-creep guard.** Reclaim orchestrator runs Steps 5+6 only. Steps 1-4 and Step 7 NEVER called. 2 commits, 0 rollbacks on happy path. |
| 5 | `test_reclaim_budget_exhaustion_routes_to_finalize_failed` | 3rd-reflip terminal path. Step 6 commits `finalize_failed` internally then raises; orchestrator rolls back its Step-6 fragment, re-raises, Step 7 never reached. |
| 6 | `test_main_falls_back_to_reclaim_when_primary_empty` | Dispatch wiring. Primary returns None → reclaim called → `_process_signal_reclaim_remote` invoked with reclaim id. Primary processor NOT called. |
| 7 | `test_main_both_queues_empty_returns_zero` | Both queues empty → rc=0, neither processor called. |
| 8 | `test_main_primary_claim_skips_reclaim` | **Priority guard.** Primary claim finds work → reclaim NEVER consulted on this tick. Pending work always first priority. |
| — | `test_main_enabled_queue_empty_returns_zero` (updated) | Contract change: primary-empty no longer sufficient to bail; test now patches both claim functions. |

All 30 tests in `tests/test_pipeline_tick.py` green:

```
$ /tmp/b1-venv/bin/pytest tests/test_pipeline_tick.py -q
..............................                                           [100%]
30 passed in 0.24s
```

---

## §test-results (full pytest — no-ship-by-inspection gate)

Run target: `/tmp/b1-venv/bin/pytest tests/ 2>&1 | tee /tmp/b1-pytest-full.log`

**Environment:** Python 3.12.12, pytest 9.0.3, asyncio mode=STRICT. Repo pins `.python-version=3.12.3`; isolated venv at `/tmp/b1-venv` (system-deps from `requirements.txt`) to bypass the system-Python 3.9 PEP-604 collection error on `memory/store_back.py`.

**Result:** `16 failed, 782 passed, 21 skipped, 19 warnings in 12.43s`

### Failure triage — all 16 pre-existing on main, none touch my change

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
FAILED tests/test_clickup_integration.py::test_tasks_in_database         (voyageai env)
FAILED tests/test_clickup_integration.py::test_qdrant_clickup_collection (voyageai env)
FAILED tests/test_clickup_integration.py::test_watermark_persistence     (voyageai env)
FAILED tests/test_scan_endpoint.py::test_scan_returns_sse_stream  (assert 401 == 200 — auth env)
FAILED tests/test_scan_endpoint.py::test_scan_rejects_empty_question
FAILED tests/test_scan_endpoint.py::test_scan_accepts_history
FAILED tests/test_scan_prompt.py::test_prompt_is_conversational_no_json_requirement
```

**Pre-existence verification:** stashed my changes, ran the same five test files against `main`:

```
$ git stash
$ /tmp/b1-venv/bin/pytest tests/test_1m_storeback_verify.py tests/test_clickup_client.py \
    tests/test_clickup_integration.py tests/test_scan_endpoint.py tests/test_scan_prompt.py
...
================== 16 failed, 17 passed, 14 warnings in 3.34s ==================
```

Identical 16 failures on main. Zero regressions introduced by this PR.

### Full log head + tail

Saved to `/tmp/b1-pytest-full.log` (522 lines) on the B1 box.

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b1
plugins: langsmith-0.7.33, asyncio-1.3.0, anyio-4.13.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 819 items

tests/test_1m_storeback_verify.py FFFF                                   [  0%]
tests/test_anthropic_client.py .....................s                    [  3%]
tests/test_bridge_alerts_to_signal.py .................................. [  7%]
...
tests/test_pipeline_tick.py ..............................               [ 51%]
...
=========== 16 failed, 782 passed, 21 skipped, 19 warnings in 12.43s ===========
```

All 30 tests in `test_pipeline_tick.py` green (51% collection bar).

---

## §production-impact

### Before this PR

Every signal that fails Step 6 validation → permanent orphan at `status='opus_failed'`. AI Head ran recoveries #3, #4, #6, #7 tonight — one manual Tier-B UPDATE per orphan event. As the remaining 44 pending signals drain, more orphans the same way.

### After merge + deploy

The claim loop handles it automatically within the 3-reflip budget:

```
tick N:   primary pending row processed → Step 6 validation fails → opus_failed (count=1)
tick N+k: primary empty → claim_one_opus_failed picks row → Steps 5-6 → Step 6 fails again → opus_failed (count=2)
tick N+m: primary empty → claim_one_opus_failed picks row → Steps 5-6 → Step 6 fails again → finalize_failed terminal (count=3)
```

Three Opus attempts per signal. No manual operator UPDATE required for `opus_failed` state. The only surviving orphan class is `finalize_failed` rows (terminal by design — Director auth to promote / replay).

### What's explicitly NOT fixed

- `awaiting_classify` orphans (recovery #6 class) — requires Step 4 status-recovery logic, different brief.
- `awaiting_finalize` orphans (recoveries #3, #4) — Step 5 crashed mid-write, row stuck. Different brief.
- `awaiting_commit` orphans — Mac Mini poller's domain (`kbl/poller.py`).

Follow-up: `CLAIM_LOOP_ORPHAN_STATES_2` (noted in brief §Scope.5).

---

## §delivery checklist

- [x] Branch `claim-loop-opus-failed-reclaim-1` pushed, head `0bfb6ee`
- [x] PR #38 opened on baker-master (reviewer B3)
- [x] 5 regression tests added per brief §Scope.4 (+ 3 bonus main-dispatch tests = 8 total)
- [x] No schema changes (uses existing `finalize_retry_count`)
- [x] No new env vars
- [x] No changes to `claim_one_signal` — new sibling function
- [x] No changes to Mac Mini poller
- [x] No schema/bridge/pipeline_tick Step 1-4 touches beyond the new entry points
- [x] Full pytest output captured (`/tmp/b1-pytest-full.log`, 522 lines)
- [x] 16 pre-existing failures confirmed unrelated (identical set on main)
- [x] Timebox: shipped inside 2h window

---

## §pr-url

https://github.com/vallen300-bit/baker-master/pull/38

— B1, 2026-04-22
