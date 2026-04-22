# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3
**Task posted:** 2026-04-22 (post-B1 ship of PR #39)
**Status:** OPEN — review PR #39 `CLAIM_LOOP_ORPHAN_STATES_2`

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
