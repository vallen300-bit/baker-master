# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3
**Task posted:** 2026-04-22 (post-B1 ship of PR #39)
**Status:** CLOSED — PR #39 APPROVE, Tier A auto-merge greenlit, 3 crash-recovery reclaim paths shipped

---

## B3 dispatch back (2026-04-22)

**APPROVE PR #39** — all 7 focus items green, zero gating nits. Full-suite regression delta reproduced locally with cmp-confirmed identical failure set.

Report: `briefs/_reports/B3_pr39_claim_loop_orphan_states_2_review_20260422.md`.

### Regression delta (focus 7) — reproduced locally

```
main baseline:       16 failed / 782 passed / 21 skipped / 19 warnings  (12.36s)
pr39 head 810c20b:   16 failed / 799 passed / 21 skipped / 19 warnings  (12.94s)
Delta:               +17 passed, 0 regressions, 0 new errors
```

`+17 passed` matches the 17 new test functions (spec said 15 — B1 added 2 extra main-chain integration tests). Pre-existing failure SET identical (`cmp -s` → exit 0). Absolute counts match B1's claim exactly.

### Per focus verdict

1. ✅ **3 claim functions.** Each: `SELECT ... WHERE status='awaiting_X' AND started_at < NOW() - INTERVAL '{_AWAITING_ORPHAN_STALE_INTERVAL}' ... FOR UPDATE SKIP LOCKED`; UPDATE flips to correct `_STATE_RUNNING` (`classify_running` / `opus_running` / `finalize_running` — verified against each step's module constant); `conn.commit()` before return. `_AWAITING_ORPHAN_STALE_INTERVAL = "15 minutes"` is module const, no user input reaches it (grep-audited), f-string embedding is psycopg2-safe. `started_at` is only written by `claim_one_signal:101` (primary); staleness semantics = "primary-claimed >15min ago."

2. ✅ **3 sub-chain dispatchers.** `_process_signal_classify_remote` (4→5→6), `_process_signal_opus_remote` (5→6), `_process_signal_finalize_remote` (6 only). Each imports only its own step modules. Inline `SELECT status` check between Step 5 and Step 6 in the first two skips Step 6 if Step 5 parks at `paused_cost_cap`/`opus_failed`. Tx contract: 1 commit per step, rollback-on-raise.

3. ✅ **`main()` claim-chain ordering.** Strict sequential: primary → opus_failed → awaiting_classify → awaiting_opus → awaiting_finalize. Each stage that returns an id dispatches and `return 0` — later stages NEVER consulted on a hit. Primary has absolute priority. `test_main_primary_hit_skips_all_reclaims` pins all 4 reclaim mocks to `call_count==0`.

4. ✅ **No leapfrog.** Inline 4-5-6 advancement within one tick per orphan. Step 4 always writes `_STATE_NEXT='awaiting_opus'` regardless of decision (SKIP_INBOX/STUB_ONLY/FULL_SYNTHESIS all land at awaiting_opus — verified at step4_classify.py:389). No "Step 4 produces state Step 5 can't consume" risk.

5. ✅ **17 tests, all non-trivial.** 9 claim (3 states × 3 shapes) with SQL-text substring inspection and exact-value assertions + 3 dispatch with exact `call_log` ordering and `call_count==0` exclusions for out-of-scope steps + 5 main-chain (3 fallback hits + both-empty + primary-skips-all). `_enter_all_steps` covers all 7 step paths so exclusion invariants are structurally enforced.

6. ✅ **Scope.** 2 files, no schema migration (reuses `started_at`), no new env vars, no new deps, no changes to `claim_one_signal` or `claim_one_opus_failed`, no Mac Mini poller touch.

7. ✅ **No ship-by-inspection.** Ship report captures `/tmp/b1-pytest-full.log` head+tail; baseline reproduced independently.

### N-nits parked (non-blocking)

- **N1:** `_process_signal_classify_remote` docstring overstates Step 4 terminal survival — `_mark_failed` uses caller's conn and is rolled back on raise. **Code behavior unchanged from pre-existing `_process_signal_remote`**; docstring accuracy only. Future tidy-up: move Step 4's `_mark_failed` to `get_conn()` fresh-conn pattern.
- **N2:** No explicit negative test for Step 5 → `paused_cost_cap` / `opus_failed` parking inside `_process_signal_classify_remote` (status-check-skips-Step-6 branch). Same gap exists in PR #38; carry-over. Logic walked manually; correct.
- **N3:** Orphan scope does not cover `*_running` mid-step crashes. Pre-existing gap; out of scope per brief. Candidate `CLAIM_LOOP_RUNNING_STATES_3`.
- **N4:** Dispatch said 15 tests, actual is 17 (2 extra main-chain integration tests). Informational.

Tier A auto-merge proceeds. Post-deploy: any `awaiting_classify`/`awaiting_opus`/`awaiting_finalize` rows with `started_at > 15min` picked up organically. Recovery-#7-class manual UPDATEs structurally retired for these 3 orphan states.

Tab quitting per §Decision.

— B3

---

## Scope

Review **PR #39** on `claim-loop-orphan-states-2` @ `810c20b`.

- Repo: `vallen300-bit/baker-master`
- URL: https://github.com/vallen300-bit/baker-master/pull/39
- Diff: 2 files, +834 / −14 (`kbl/pipeline_tick.py`, `tests/test_pipeline_tick.py`)
- Ship report: `briefs/_reports/B1_claim_loop_orphan_states_2_20260422.md` (main @ `55c8fe7`)
- Origin brief: `briefs/_tasks/CODE_1_PENDING.md`

## What to verify

Near-mirror of PR #38 pattern, three new orphan states. Focus on:

1. **Claim function correctness** — each `claim_one_awaiting_{classify,opus,finalize}` uses `FOR UPDATE SKIP LOCKED`, commits once on success, flips to the correct `_STATE_RUNNING`. Stale guard `started_at < NOW() - INTERVAL '15 minutes'` is a module constant `_AWAITING_ORPHAN_STALE_INTERVAL`; bare SQL interval literal (psycopg2 does not parametrize INTERVAL). Confirm the literal value + unit + that no user-controlled input reaches it.
2. **Dispatch correctness** — each `_process_signal_*_remote` runs exactly its own sub-chain (classify: 4→5→6, opus: 5→6, finalize: 6 only). No Steps 1-3, no Step 7 (Mac Mini). Tx-boundary contract preserved (one commit per step, rollback on raise), matching PR #38's `_process_signal_reclaim_remote`.
3. **Claim-chain ordering** in `main()` — pending → opus_failed → awaiting_classify → awaiting_opus → awaiting_finalize. Primary has strict priority; reclaim fires only on empty primary. Earliest-stage orphan goes first.
4. **No leapfrog** — a row orphaned at `awaiting_classify` advances through `classify_running → awaiting_opus → opus_running → awaiting_finalize → ...` in one tick via the inline 4-5-6 dispatcher. Confirm this matches the brief's "one tick per orphan, not ladder-climb."
5. **Tests** — 15 new test cases in `tests/test_pipeline_tick.py` (9 claim × 3 states + 3 dispatch + 3 main-chain). Mock scaffold reuses PR #38's `_STEP_PATHS`. Total `test_pipeline_tick.py` = 47 green (32 pre-existing + 15 new).
6. **No schema, no env vars** — confirm diff is limited to the two declared files.
7. **Ship-report pytest log is FULL, not "by inspection"** — full suite `16 failed, 799 passed, 21 skipped`; 16-failure baseline is pre-existing (same set as PR #37/#38). No new regressions. `/tmp/b1-pytest-full.log` head+tail captured in report.

## Decision

- **APPROVE** → reply `APPROVE PR #39` in your review report; AI Head will Tier-A auto-merge (`gh pr merge 39 --squash`).
- **REQUEST_CHANGES** → name the line or logic; B1 loops.

## Report path

`briefs/_reports/B3_pr39_claim_loop_orphan_states_2_review_20260422.md` — commit + push after review. Close this task file with a `## B3 dispatch back` section.

## Charter note (§6A + no-ship-by-inspection)

Charter §6A continuation-of-work exemption applies to B1's brief (mirror of PR #38). Your review MUST still enforce `memory/feedback_no_ship_by_inspection.md`: REQUEST_CHANGES any ship report claiming "pass by inspection." B1's report captures `/tmp/b1-pytest-full.log` head+tail — confirm the baseline delta is zero.

---

**Dispatch timestamp:** 2026-04-22 ~09:25 UTC (AI Head post-refresh)
