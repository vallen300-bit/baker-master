# B3 Review — PR #39 CLAIM_LOOP_ORPHAN_STATES_2

**Reviewer:** Code Brisen #3
**Date:** 2026-04-22
**PR:** https://github.com/vallen300-bit/baker-master/pull/39
**Branch:** `claim-loop-orphan-states-2`
**Head SHA:** `810c20b`
**Author:** B1
**Ship report:** `briefs/_reports/B1_claim_loop_orphan_states_2_20260422.md`

---

## §verdict

**APPROVE PR #39.** All 7 focus items green. Full-suite regression delta reproduced locally with cmp-confirmed identical failure set. Three crash-recovery reclaim paths (`awaiting_classify`, `awaiting_opus`, `awaiting_finalize`) extend PR #38's opus_failed reclaim shape cleanly. Tier A auto-merge greenlit.

---

## §focus-verdict

1. ✅ **3 claim functions — correctness + staleness guard + SKIP LOCKED.**
2. ✅ **3 sub-chain dispatchers — exact steps, no Steps 1-3, no Step 7.**
3. ✅ **`main()` claim-chain ordering — strict priority, stop at first hit.**
4. ✅ **No leapfrog — inline 4-5-6 advancement in one tick per orphan.**
5. ✅ **Test matrix — 17 new tests (spec said 15; 2 bonus main-chain), all non-trivial.**
6. ✅ **Scope — 2 files, no schema, no env vars.**
7. ✅ **No-ship-by-inspection — full-suite baseline reproduced.**

---

## §1 Claim-function correctness

Three new functions at `kbl/pipeline_tick.py:182-316`, each identical in shape modulo state name:

- `claim_one_awaiting_classify` (182-229) — `SELECT ... WHERE status='awaiting_classify' AND started_at < NOW() - INTERVAL '{_AWAITING_ORPHAN_STALE_INTERVAL}' ORDER BY priority DESC, created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED`; UPDATE flips to `classify_running`; `conn.commit()` then `return signal_id`.
- `claim_one_awaiting_opus` (232-270) — same shape; state `awaiting_opus → opus_running`.
- `claim_one_awaiting_finalize` (273-316) — same shape; state `awaiting_finalize → finalize_running`.

Verified:

- **`_AWAITING_ORPHAN_STALE_INTERVAL = "15 minutes"`** declared as module constant at line 180. Literal value + unit present; used only via f-string into the SELECT. No user-controlled input reaches it (grep-audited — only internal references in the 3 claim functions). psycopg2 cannot parametrize `INTERVAL` literals, so f-string with a code-only constant is the accepted pattern. No injection surface.
- **`FOR UPDATE SKIP LOCKED`** on each SELECT — concurrent ticks cannot double-claim.
- **Commit semantics** — one `conn.commit()` per successful claim, after the UPDATE, before returning. Matches `claim_one_signal` (line 104) and `claim_one_opus_failed` (line 164) contract exactly.
- **Correct target `_STATE_RUNNING` per step:** confirmed against each step's module constants — `kbl/steps/step4_classify.py:59` (`classify_running`), `kbl/steps/step5_opus.py:121` (`opus_running`), `kbl/steps/step6_finalize.py:79` (`finalize_running`).
- **Step's own `_mark_running`** on entry is an idempotent same-state UPDATE; no error or drift.
- **Starved-row semantics:** `started_at` is only set once, by `claim_one_signal` at line 101 (primary claim: `started_at = NOW()`). Neither PR #38's reclaim nor PR #39's reclaim resets it. Consequence: `started_at < NOW() - INTERVAL '15 minutes'` means "primary-claimed more than 15 min ago" — exactly the "old enough to be sure it orphaned" semantic the brief wants. `started_at IS NULL` rows (theoretical) are implicitly skipped by the NULL comparison, which is a safe default.

## §2 Sub-chain dispatchers — exact step coverage

Three new functions at `kbl/pipeline_tick.py:576-696`. Each verified against dispatch spec:

- **`_process_signal_classify_remote` (576-643)** — runs **Step 4 → Step 5 → Step 6**. Imports only `step4_classify`, `step5_opus`, `step6_finalize`. Inline `SELECT status` check between Step 5 and Step 6 (lines 621-629) — if Step 5 parked row at `paused_cost_cap` / `opus_failed` (R3 exhausted), Step 6 is skipped. Docstring explicitly excludes Steps 1-3 (trust upstream columns) and Step 7 (Render has no vault per CHANDA Inv 9). Tx contract: one `conn.commit()` per step; `conn.rollback()` on raise.
- **`_process_signal_opus_remote` (646-681)** — runs **Step 5 → Step 6**. Same inline status-check pattern. Shape mirrors PR #38's `_process_signal_reclaim_remote` but entry state is `opus_running` (not `awaiting_opus` pre-flipped by claim); Step 5's `_mark_running` is an idempotent same-state UPDATE, harmless.
- **`_process_signal_finalize_remote` (684-696)** — runs **Step 6 only**. Narrowest shape. Re-running Step 5 would waste a fresh Opus call; Step 6 picks up its stored `opus_draft_markdown` via its own `_fetch_signal_row`.

**Docstring accuracy nit (non-gating):** `_process_signal_classify_remote` docstring (line 595) claims "step-internal terminal-state commits (Step 4's `classify_failed` flip, ...) survive the outer rollback." Verified independently — Step 5's R3-exhausted flip and Step 6's `_route_validation_failure` fresh-conn flip DO survive; **Step 4's `_mark_failed` uses the caller's connection** (`kbl/steps/step4_classify.py:273-278`, `_mark_failed` call sites at lines 368 and 375 followed by `raise`). When the caller rolls back on ClassifyError, Step 4's terminal flip is lost. **This is pre-existing behavior identical to the primary `_process_signal_remote` path** — PR #39 doesn't introduce or worsen it. Doc overstates survival for Step 4 specifically; code behavior is unchanged. Flagged as N-nit.

## §3 `main()` claim-chain ordering

`kbl/pipeline_tick.py:459-833`. Walked the dispatch chain:

```
claim_one_signal            → _process_signal_remote            (primary; pending)
  ↓ None
claim_one_opus_failed       → _process_signal_reclaim_remote    (PR #38; opus_failed retry)
  ↓ None
claim_one_awaiting_classify → _process_signal_classify_remote   (PR #39; crash @ post-Step-3)
  ↓ None
claim_one_awaiting_opus     → _process_signal_opus_remote       (PR #39; crash @ post-Step-4)
  ↓ None
claim_one_awaiting_finalize → _process_signal_finalize_remote   (PR #39; crash @ post-Step-5)
  ↓ None
return 0  (all queues empty)
```

- Each stage that returns an id executes its dispatcher and `return 0` — **later stages NEVER consulted when an earlier stage hits.** Verified by reading lines 755, 779, 799, 819, 830 (one early-return per successful stage).
- Primary has strict priority: if `claim_one_signal` returns an id, reclaim chain is never consulted (test `test_main_primary_hit_skips_all_reclaims` pins all 4 reclaim mocks to `call_count == 0`).
- Stage progression: earliest-stage orphan goes first (`awaiting_classify` before `awaiting_opus` before `awaiting_finalize`). Matches brief's rationale.

## §4 No leapfrog

Each sub-chain dispatcher runs its pipeline segment **inline within a single tick** — no intermediate re-queue. Specifically:

- `_process_signal_classify_remote`: Step 4 `classify()` writes `awaiting_opus` (per `kbl/steps/step4_classify.py:60 _STATE_NEXT = "awaiting_opus"`, line 389 `_write_decision(..., _STATE_NEXT)`). Dispatcher immediately commits and proceeds to Step 5 `synthesize()` on the same connection. Step 5's `_mark_running` reads `awaiting_opus`, flips to `opus_running`, runs, writes `awaiting_finalize`, commits. Dispatcher checks status, proceeds to Step 6 `finalize()`, writes `awaiting_commit`, commits. **One tick, full 4→5→6 advancement; no ladder-climb.** ✓
- Pre-Step-4 decision coverage: Step 4 always writes `_STATE_NEXT = "awaiting_opus"` regardless of decision value (SKIP_INBOX / STUB_ONLY / FULL_SYNTHESIS all land at `awaiting_opus`, line 389). Step 5 branches on `step_5_decision` downstream, handling SKIP_INBOX via stub route (line 931 `_write_draft_and_advance(..., _STATE_NEXT)`). No "Step 4 produces a state Step 5 can't consume" risk. ✓

## §5 Test matrix — 17 new tests + 2 modified

Ship report + dispatch claimed 15; actual count is **17 new test functions** (9 claim × 3 + 3 dispatch + 5 main-chain). Plus 2 existing tests (`test_main_enabled_queue_empty_returns_zero`, `test_main_both_queues_empty_returns_zero`) modified to patch all 5 claim functions + all 5 dispatchers. Net gain = 17; spec undercounted by 2, not a discrepancy.

| # | Test | Pins |
|---|------|------|
| 1 | `test_claim_one_awaiting_classify_returns_eligible_row` | SQL contains `status='awaiting_classify'` + `_AWAITING_ORPHAN_STALE_INTERVAL` + `for update skip locked`; params=None; flip to `classify_running`; 1 commit / 0 rollback; no ALTER |
| 2 | `test_claim_one_awaiting_classify_skips_fresh_rows` | SELECT→None (simulates staleness filter); no UPDATE, no commit; SELECT text still contains interval |
| 3 | `test_claim_one_awaiting_classify_returns_none_when_empty` | None returned; no side effects |
| 4-6 | `test_claim_one_awaiting_opus_{eligible,skips,empty}` | same shape; `awaiting_opus → opus_running` (822) |
| 7-9 | `test_claim_one_awaiting_finalize_{eligible,skips,empty}` | same shape; `awaiting_finalize → finalize_running` (833) |
| 10 | `test_classify_dispatch_runs_4_5_6_not_1_3_or_7` | `call_log == ["step4","step5","step6"]` EXACT; step1/2/3/7 `call_count==0`; 3 commits / 0 rollbacks |
| 11 | `test_opus_dispatch_runs_5_6_not_1_4_or_7` | `call_log == ["step5","step6"]`; step1-4 + step7 `call_count==0`; 2 commits |
| 12 | `test_finalize_dispatch_runs_6_not_others` | `call_log == ["step6"]`; step1-5 + step7 `call_count==0`; 1 commit |
| 13 | `test_main_falls_back_to_classify_reclaim_when_earlier_queues_empty` | primary=None, opus_failed=None, classify=811 → dispatches classify_remote(811, conn); opus+finalize reclaims `call_count==0` |
| 14 | `test_main_falls_back_to_opus_reclaim_when_earlier_queues_empty` | primary/opus_failed/classify all None, opus=822 → dispatches opus_remote(822); finalize NOT consulted |
| 15 | `test_main_falls_back_to_finalize_reclaim_when_earlier_queues_empty` | all earlier None, finalize=833 → dispatches finalize_remote(833) |
| 16 | `test_main_all_queues_empty_returns_zero_without_any_dispatch` | all 5 claim fns called (ordering), all 5 dispatchers `call_count==0` |
| 17 | `test_main_primary_hit_skips_all_reclaims` | primary=444 → dispatches _process_signal_remote(444); all 4 reclaim claim fns `call_count==0` |

All tests use exact-value equality, SQL-text substring inspection, or `call_count==0` exclusions. No presence-only asserts. `_enter_all_steps` (patches all 7 step paths from `_STEP_PATHS`) structurally enforces exclusion invariants.

**Non-gating test coverage gap (N-nit):** no explicit test for Step 5 parking at `paused_cost_cap` / `opus_failed` between Step 4 and Step 6 in `_process_signal_classify_remote` — the status-check-skips-Step-6 branch is only exercised implicitly. Same gap exists in PR #38's test suite for `_process_signal_reclaim_remote`; carry-over, not regression. Logic walked manually and confirmed correct.

## §6 Scope discipline

- **2 files:** `kbl/pipeline_tick.py`, `tests/test_pipeline_tick.py`. `git diff $(merge-base)..pr39 --name-only` confirms. ✓
- **No schema migration:** no `ALTER TABLE` / `CREATE TABLE` / `CREATE INDEX` / `CREATE TYPE`. Reuses existing `started_at` column (written by `claim_one_signal:101`) — grep confirms only two hits of `started_at` in `kbl/`, the writer (pipeline_tick:101) and the three new SELECTs. ✓
- **No new env vars:** `grep "os.environ\|os.getenv" kbl/pipeline_tick.py` shows only pre-existing `KBL_FLAGS_PIPELINE_ENABLED`. ✓
- **No new deps:** no changes to `requirements.txt`. ✓
- **No changes to `claim_one_signal` / `claim_one_opus_failed`:** confirmed via diff context; both pre-existing functions untouched. Primary path and PR #38 reclaim path preserved. ✓
- **No Mac Mini poller touch:** `grep "commit_loop\|poller\|step7" kbl/pipeline_tick.py` — only references are exclusion comments in new docstrings. ✓

## §7 Full-suite regression delta

Reproduced locally in `/tmp/b3-venv` (Python 3.12, `requirements.txt` + `pytest` + `pytest-asyncio`):

```
main baseline:       16 failed / 782 passed / 21 skipped / 19 warnings  (12.36s)
pr39 head (810c20b): 16 failed / 799 passed / 21 skipped / 19 warnings  (12.94s)
Delta:               +17 passed, 0 regressions, 0 new errors, 0 new skips
```

**Failure-set identity check:** `cmp -s /tmp/b3-main3-failures.txt /tmp/b3-pr39-failures.txt` → exit 0 (IDENTICAL). The 16 pre-existing failures are the same test-name set on both runs.

**`+17 passed`** matches the 17 new test functions added in `tests/test_pipeline_tick.py`. Zero tests moved from passing to failing. Spec claim `16 failed / 799 passed / 21 skipped` reproduces exactly on PR #39 head.

My 16-failure absolute count matches B1's claim this time (voyage env delta from my earlier runs was idiosyncratic to a venv state — on the current venv, the 3 clickup_integration tests fail identically on both main and pr39). Pre-existing failure set unchanged across PR #37 → PR #38 → PR #39.

Ship report carries raw pytest `head+tail` capture from `/tmp/b1-pytest-full.log`. `memory/feedback_no_ship_by_inspection.md` honored.

---

## §non-gating

- **N1 — docstring overclaim on Step 4 terminal survival.** `_process_signal_classify_remote` docstring (line 595) lists "Step 4's `classify_failed` flip" among terminal commits that survive outer rollback. Step 4's `_mark_failed` (`step4_classify.py:273-278`) uses the caller's connection, so `conn.rollback()` in the dispatcher's except block DOES lose the mark. Code behavior unchanged from pre-existing primary path (`_process_signal_remote`), so net risk is zero; docstring is inaccurate only. Cheap fix in a future tidy-up: move Step 4's `_mark_failed` to `get_conn()` fresh-conn pattern (matches Step 6's `_route_validation_failure`). Not gating.

- **N2 — missing negative test for Step 5 → `paused_cost_cap` / `opus_failed` parking inside `_process_signal_classify_remote`.** The status-check branch (lines 621-629) that skips Step 6 when Step 5 doesn't land at `awaiting_finalize` is only exercised implicitly. PR #38 has the same gap for `_process_signal_reclaim_remote`; carry-over. Logic walked manually and confirmed correct. Add one test each in a future tidy-up ticket. Not gating.

- **N3 — orphan scope does not cover `*_running` states.** A row crashed mid-Step 4/5/6 (not between steps) sits at `classify_running` / `opus_running` / `finalize_running` and won't be reclaimed by any of the 4 reclaim paths. Pre-existing gap; brief explicitly scopes PR #39 to `awaiting_*` crash orphans only. Potential follow-up `CLAIM_LOOP_RUNNING_STATES_3`. Not gating.

- **N4 — spec/actual test-count discrepancy.** Dispatch claimed "15 new tests (9 + 3 + 3)"; actual is 17 (9 + 3 + 5). B1 added 2 extra main-chain integration tests (`test_main_all_queues_empty_returns_zero_without_any_dispatch`, `test_main_primary_hit_skips_all_reclaims`). More coverage, not less. Informational only.

---

## §regression-delta

Raw logs: `/tmp/b3-main3-pytest-full.log`, `/tmp/b3-pr39-pytest-full.log` (local).

```
$ wc -l /tmp/b3-main3-failures.txt /tmp/b3-pr39-failures.txt
      16 /tmp/b3-main3-failures.txt
      16 /tmp/b3-pr39-failures.txt

$ cmp -s /tmp/b3-main3-failures.txt /tmp/b3-pr39-failures.txt && echo IDENTICAL
IDENTICAL
```

---

## §post-merge

- Tier A auto-merge (squash) proceeds.
- Render redeploys. On next tick, any currently-stranded `awaiting_classify` / `awaiting_opus` / `awaiting_finalize` rows with `started_at` older than 15 min will be picked up by the new claim chain and advanced inline. No manual operator UPDATE needed.
- Recovery #7-style manual UPDATEs for these three orphan states are structurally retired.
- Remaining orphan class (`*_running` mid-step crashes) unresolved — out of scope per brief; candidate for `CLAIM_LOOP_RUNNING_STATES_3`.

**APPROVE PR #39.**

— B3
