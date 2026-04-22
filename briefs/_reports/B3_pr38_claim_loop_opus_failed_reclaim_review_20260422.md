# B3 Review — PR #38 CLAIM_LOOP_OPUS_FAILED_RECLAIM_1

**Reviewer:** Code Brisen #3
**Date:** 2026-04-22
**PR:** https://github.com/vallen300-bit/baker-master/pull/38
**Branch:** `claim-loop-opus-failed-reclaim-1`
**Head SHA:** `0bfb6ee`
**Author:** B1
**Ship report:** `briefs/_reports/B1_claim_loop_opus_failed_reclaim_20260422.md`

---

## §verdict

**APPROVE.** All 8 focus items green. Full-suite regression delta reproduced locally with cmp-confirmed identical failure set. Retires the recovery-#7 manual UPDATE class by closing the R3-reclaim loop Step 6's docstring always claimed. Tier A auto-merge greenlit.

---

## §focus-verdict

1. ✅ **Secondary claim function correctness.**
2. ✅ **Dispatch path in `pipeline_tick.main()`.**
3. ✅ **Reclaim runs Steps 5 + 6 only; draft overwrite confirmed.**
4. ✅ **Budget-exhaustion semantics unchanged in Step 6.**
5. ✅ **Test matrix — 8 tests, non-trivial invariant coverage.**
6. ✅ **Scope discipline.**
7. ✅ **Concurrency safety.**
8. ✅ **No-ship-by-inspection — full-suite baseline reproduced.**

---

## §1 `claim_one_opus_failed` correctness

`kbl/pipeline_tick.py:108-165`. Verified against dispatch spec:

- **Filter:** `WHERE status = 'opus_failed' AND COALESCE(finalize_retry_count, 0) < %s`, `%s = _MAX_OPUS_REFLIPS` (line 155-156). Budget guard enforced at SELECT. ✓
- **Concurrency shape:** `ORDER BY priority DESC, created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED` (lines 151-154). Identical to `claim_one_signal` (lines 95-102). ✓
- **Flip state:** `UPDATE signal_queue SET status = 'awaiting_opus' WHERE id = %s` (line 161). Correct Step 5 pre-state per `kbl/steps/step5_opus.py:48` state diagram. NOT `processing` / `opus_running` (those are primary-claim / Step 5 internal). ✓
- **Commit-before-return:** `conn.commit()` on line 164, `return signal_id` on line 165. Matches `claim_one_signal:104` contract. ✓
- **Import of `_MAX_OPUS_REFLIPS`:** deferred inside function (line 140) from `kbl.steps.step6_finalize`. Constant confirmed at `kbl/steps/step6_finalize.py:93` as `_MAX_OPUS_REFLIPS = 3`. Not redefined anywhere — single source of truth. ✓
- **Defensive ALTER:** `ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS finalize_retry_count INT NOT NULL DEFAULT 0` (lines 144-147) runs per invocation. Idempotent; matches Step 6's `_fetch_signal_row` / `_increment_retry_count` self-heal pattern. Small per-tick roundtrip overhead; documented as defense-in-depth in function docstring. Not gating.

## §2 Dispatch path in `pipeline_tick.main()`

`kbl/pipeline_tick.py:461-504`. Walked the new flow:

- **Primary first** (line 461): `claim_one_signal(conn)` unchanged. ✓
- **If primary returns id** (line 464): runs `_process_signal_remote(signal_id, conn)` with unchanged error handling; `return 0` on line 480. Reclaim is NOT consulted on this tick. ✓
- **If primary returns None** (line 488): runs `claim_one_opus_failed(conn)`. Outer try/except rolls back and re-raises on claim failure (same shape as primary). ✓
- **If reclaim returns None** (line 493): `return 0` — "both queues empty — normal exit". ✓
- **If reclaim returns id** (line 497): runs `_process_signal_reclaim_remote(reclaim_id, conn)` — NOT `_process_signal_remote`. Error path emits `"unexpected exception in _process_signal_reclaim_remote"` (line 503), re-raises. ✓

Sequential, not concurrent. Disjoint states (`pending` vs `opus_failed`) prevent any primary/reclaim double-claim even under tick overlap.

## §3 Reclaim runs Steps 5 + 6 only + draft overwrite confirmed

`kbl/pipeline_tick.py:375-426` (`_process_signal_reclaim_remote`).

- **Steps 1-4 never called:** only `from kbl.steps import step5_opus, step6_finalize` imported (line 399). No reference to step1/step2/step3/step4 anywhere in the function. `primary_matter`, `triage_score`, `triage_confidence`, `related_matters`, `vedana` preserved from the first attempt — the reclaim path never writes those columns. ✓
- **Step 5 `synthesize()` runs first** (line 402), commits on success, rolls back on raise (line 404-406). ✓
- **Step 5 draft overwrite (B1's claim verified independently):** `kbl/steps/step5_opus.py:326-336` `_write_draft_and_advance` issues `UPDATE signal_queue SET opus_draft_markdown = %s, status = %s WHERE id = %s` — unconditional overwrite of `opus_draft_markdown`, no guard on existing value. Called from both happy path (line 1013) and stub routes (line 931). Stale draft from first attempt is replaced on every reclaim. ✓
- **Status check between Step 5 and Step 6** (lines 413-421): if Step 5 parked at `paused_cost_cap` / `opus_failed` (R3 re-exhausted), row won't be `awaiting_finalize`, Step 6 is skipped via early return. Correct — Step 6 must not run on a row Step 5 didn't advance.
- **Step 6 `finalize()` runs conditionally** (line 423), commits on success, rolls back on raise (line 425-427). ✓
- **Step 7 never called:** no import, no reference. Mac Mini poller's domain, unchanged. ✓
- **Transaction contract mirrors `_process_signal_remote`:** one `conn.commit()` per successful step; step-internal terminal-flip commits (Step 6's fresh-conn writes via `_route_validation_failure`) survive the outer rollback. Docstring explicitly documents this.

## §4 Budget-exhaustion behavior — Step 6 unchanged

Verified by reading `kbl/steps/step6_finalize.py:750-782` directly. Step 6's existing logic (not touched by this PR):

```python
new_count = _increment_retry_count(fresh_conn, row.signal_id)
if new_count >= _MAX_OPUS_REFLIPS:
    target_state = _STATE_FINALIZE_FAILED
_mark_terminal(fresh_conn, row.signal_id, target_state)
fresh_conn.commit()
```

- Pre-bump count=2 → post-bump count=3 → `3 >= 3` → `target_state = finalize_failed` (terminal). ✓
- Pre-bump count<2 → post-bump count<3 → `target_state = opus_failed` (re-claimable next tick). ✓

Consequence: a row at `finalize_retry_count=3` never sits at `opus_failed` (Step 6 terminal-flips to `finalize_failed` first). `claim_one_opus_failed`'s `< _MAX_OPUS_REFLIPS` filter is defense-in-depth for the race where Step 6's terminal flip somehow missed. Documented in `claim_one_opus_failed` docstring (lines 124-127). B1 did not modify Step 6's promote semantics — `git diff` confirms zero `step6_finalize.py` changes in this PR.

## §5 Test matrix — 8 tests

New test block at `tests/test_pipeline_tick.py:728-1028` (5 required + 3 bonus dispatch tests). Read each body:

| # | Test | Invariant pinned | Non-trivial? |
|---|------|------------------|--------------|
| 1 | `test_claim_one_opus_failed_returns_eligible_row` | returns 42, flips to `awaiting_opus`, SELECT contains `status='opus_failed'` + `finalize_retry_count` + `FOR UPDATE SKIP LOCKED`, param = `(_MAX_OPUS_REFLIPS,)`, ALTER runs once, 1 commit / 0 rollback | ✅ SQL text inspected |
| 2 | `test_claim_one_opus_failed_skips_budget_exhausted` | simulates cap-exhausted row via SELECT→None; no UPDATE, no commit; SELECT param = `_MAX_OPUS_REFLIPS` | ✅ honest — acknowledges fixture limit; pins filter presence |
| 3 | `test_claim_one_opus_failed_returns_none_when_empty` | SELECT→None → returns None, no UPDATE, no commit | ✅ exact-shape |
| 4 | `test_reclaim_runs_steps_5_6_not_1_4` | `call_log == ["step5", "step6"]` EXACT order, steps 1/2/3/4/7 `call_count == 0`, 2 commits / 0 rollbacks | ✅ ordering + exclusion |
| 5 | `test_reclaim_budget_exhaustion_routes_to_finalize_failed` | Step 6 raises `FinalizationError`, 2 commits (Step 5 + Step 6 fresh-conn) / 1 rollback (Step 6 fragment), Step 7 `call_count == 0` | ✅ models Step 6 commit-before-raise correctly |
| 6 | `test_main_falls_back_to_reclaim_when_primary_empty` | primary→None + reclaim→909 → `_process_signal_reclaim_remote(909, conn)` called once; `_process_signal_remote` `call_count == 0` | ✅ dispatch pin |
| 7 | `test_main_both_queues_empty_returns_zero` | both→None → rc=0, zero dispatch calls | ✅ both-empty path |
| 8 | `test_main_primary_claim_skips_reclaim` | primary→555 → `_process_signal_remote(555, conn)`, `claim_one_opus_failed` `call_count == 0` | ✅ strict-fallback pin (reclaim is NOT concurrent) |

Plus 1 modification to `test_main_enabled_queue_empty_returns_zero` (now patches both claims + both processors; confirms primary-empty no longer bails).

All 8 helpers verified: `_enter_all_steps` at `tests/test_pipeline_tick.py:104-109` patches all 7 step paths in `_STEP_PATHS` (`tests/test_pipeline_tick.py:93-101`) — so focus 3's "Steps 1-4 NOT called" claim is structurally enforced by the mock scaffold.

## §6 Scope discipline

- **2 files changed:** `kbl/pipeline_tick.py` (+160/-12), `tests/test_pipeline_tick.py` (+314/-?). Confirmed via `git diff $(merge-base)..pr38 --name-only`. Nothing else. ✓
- **No schema migration:** `finalize_retry_count` column is reused. The `ALTER TABLE ... IF NOT EXISTS` inside the new claim function is an idempotent self-heal, not a new migration — matches Step 6's existing pattern. ✓
- **No new env vars:** `grep -n "os.environ\|os.getenv" kbl/pipeline_tick.py` — only the pre-existing `KBL_FLAGS_PIPELINE_ENABLED` read at line 440. ✓
- **No changes to `claim_one_signal`:** primary path at lines 84-105 untouched (verified by diff context — the new function appears after, not within). ✓
- **No Mac Mini poller changes:** no references to `commit_loop`, `poller`, or Step 7 in the diff. ✓
- **No `awaiting_classify` / `awaiting_finalize` / `awaiting_commit` reclaim:** only `opus_failed` → `awaiting_opus` handled. Other orphan-state reclaims deferred to `CLAIM_LOOP_ORPHAN_STATES_2` per brief. ✓
- **`_MAX_OPUS_REFLIPS` single source of truth:** imported from `step6_finalize`, not redefined. Verified via `grep -rn "_MAX_OPUS_REFLIPS =" kbl/` → only `kbl/steps/step6_finalize.py:93`. ✓

## §7 Concurrency safety

- **`FOR UPDATE SKIP LOCKED`** on secondary claim (line 153). Two overlapping ticks calling `claim_one_opus_failed` on the same row cannot both succeed — the second sees the row locked, skips it. ✓
- **Primary vs secondary disjoint:** `claim_one_signal` filters `status='pending'`, `claim_one_opus_failed` filters `status='opus_failed'`. A single row is in exactly one state at a time; cannot appear in both claim queues simultaneously. ✓
- **Sequential in `main()`:** primary runs first; if it returns id, `return 0` before reclaim is called. Reclaim only runs when primary returned None. No same-tick race between the two claims. ✓
- **Claim→process single connection:** both claim functions and their processors run on the same `conn` from the outer `with get_conn() as conn:` block (line 443+). No cross-connection coordination needed.

## §8 Full-suite regression delta

Reproduced locally in `/tmp/b3-venv` (Python 3.12, `pip install -r requirements.txt` + `pytest` + `pytest-asyncio`).

```
main baseline:       16 failed / 774 passed / 21 skipped / 19 warnings  (11.59s)
pr38 head (0bfb6ee): 16 failed / 782 passed / 21 skipped / 19 warnings  (12.61s)
Delta:               +8 passed, 0 regressions, 0 new errors, 0 new skips
```

**Failure-set identity check:** `cmp -s /tmp/b3-main2-failures.txt /tmp/b3-pr38-failures.txt` → exit 0 (IDENTICAL). The 16 pre-existing failures are the same test-name set on both runs.

`+8 passed` matches exactly the 8 new test functions added in `tests/test_pipeline_tick.py` (3 claim-function + 2 reclaim-dispatch + 3 main-dispatch). Zero tests moved from passing to failing.

My absolute 16-failure count again differs from B1's 16 count match — aligned this time because the 3 `test_clickup_integration.py` voyageai failures that B1 doesn't hit are absorbed on both main and pr38 for me. B1's delta claim independently validated on my infrastructure.

Ship report §test-results carries raw pytest output. `memory/feedback_no_ship_by_inspection.md` honored.

---

## §non-gating

- **N1 — fixture-parameter repurposing in tests #4 and #5.** Uses `_mock_conn(post_step1_status="awaiting_finalize", post_step5_status="__unused__", post_step6_status="__unused__")`. The existing `_mock_conn` was designed for the primary 7-step path; the reclaim path does only one `SELECT status` (between Step 5 and Step 6) and reads `queue[0]`, which is labeled `post_step1_status`. Inline NOTE comments in both tests call out the hack. Works correctly; a future tidy-up could add a reclaim-shaped `_reclaim_mock_conn` with a single `status_after_step5` parameter for clarity. Not gating.
- **N2 — `ALTER TABLE ... IF NOT EXISTS` runs on every `claim_one_opus_failed` invocation.** One extra DB roundtrip per tick on the empty-primary branch. Matches Step 6's self-heal pattern; cost is negligible (<1ms). Could be gated by a module-level "migration applied" flag if needed later. Not gating.
- **N3 — deferred import of `_MAX_OPUS_REFLIPS`** inside `claim_one_opus_failed` body (line 140). No actual circular-import risk between `pipeline_tick` and `step6_finalize` (Step 6 does not import `pipeline_tick`). Could hoist to module-level for micro-optimization; defensible as-is for lazy loading. Not gating.

---

## §regression-delta

Raw logs at `/tmp/b3-main2-pytest-full.log` and `/tmp/b3-pr38-pytest-full.log` (local). Failure-set anchors:

```
$ wc -l /tmp/b3-main2-failures.txt /tmp/b3-pr38-failures.txt
      16 /tmp/b3-main2-failures.txt
      16 /tmp/b3-pr38-failures.txt

$ cmp -s /tmp/b3-main2-failures.txt /tmp/b3-pr38-failures.txt && echo IDENTICAL
IDENTICAL
```

---

## §post-merge

- Tier A auto-merge (squash) proceeds.
- AI Head: no manual recovery UPDATE needed. The currently-stranded 1 `opus_failed` row will be picked up organically by the new secondary claim on the next tick after Render redeploys. This is the design-intent "self-healing" behavior.
- Recovery-#7-style manual UPDATEs structurally retired for the `opus_failed` class. Future orphan classes (`awaiting_classify`, `awaiting_finalize`, `awaiting_commit`) remain out of scope until `CLAIM_LOOP_ORPHAN_STATES_2`.

— B3
