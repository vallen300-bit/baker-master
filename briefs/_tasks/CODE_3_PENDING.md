# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3
**Task posted:** 2026-04-22 (post-B1 ship of PR #41)
**Status:** OPEN — review PR #41 `CLAIM_LOOP_RUNNING_STATES_3`

---

## Scope

Review **PR #41** on `claim-loop-running-states-3` @ `5e4e253`.

- URL: https://github.com/vallen300-bit/baker-master/pull/41
- Diff: 2 files, +329 / −0 (`kbl/pipeline_tick.py`, `tests/test_pipeline_tick.py`)
- Ship report: `briefs/_reports/B1_claim_loop_running_states_3_20260422.md` (main @ `0917e43`)
- Origin brief: `briefs/_tasks/CODE_1_PENDING.md`

## Continuation of your PR #39 review

This closes the N3 nit you flagged on PR #39: "Orphan scope does not cover `*_running` mid-step crashes. Candidate `CLAIM_LOOP_RUNNING_STATES_3`." Single reset function, wired before PR #39's chain.

## What to verify

1. **`reset_stale_running_orphans(conn)` correctness** — single UPDATE SQL over all three `*_running` states, CASE-WHEN to the corresponding `awaiting_*`. Staleness guard `started_at < NOW() - INTERVAL '15 minutes'` as module constant. One commit on success. Returns `rowcount`. Confirm: no `FOR UPDATE SKIP LOCKED` needed on a CASE-UPDATE (single statement is atomic) — but verify there's no race with PR #39's claim functions reading the same rows.

2. **`main()` wire-in ordering** — reset MUST fire BEFORE the claim chain on every tick. Confirm the call is unconditional (not inside an `if`), and log line "`reset N stale running orphans`" only fires when N>0.

3. **CASE-WHEN completeness** — all three states covered (`classify_running`, `opus_running`, `finalize_running`). No `ELSE` clause orphaning an unexpected state. `WHERE status IN (...)` filters so only the three intended states are touched.

4. **15-min staleness rationale** — 5× margin over the slowest legit running state (Step 5 R3 at ~180s). Same interval constant style as PR #39's `_AWAITING_ORPHAN_STALE_INTERVAL` (separate constant; don't share).

5. **Same-tick reset→claim integration** — B1 shipped `test_main_reset_and_reclaim_in_same_tick`. Confirm the mock shape: reset flips `opus_running` → `awaiting_opus`, same-tick `claim_one_awaiting_opus` picks it up, same-tick `_process_signal_opus_remote` dispatches. Asserts end state is downstream of Step 6.

6. **Tests — 7 new in `tests/test_pipeline_tick.py`:**
   - 3 per-state reset tests (classify / opus / finalize_running → awaiting_*)
   - 1 fresh-row skip test
   - 1 empty-return test
   - 1 `main()` call-order test (reset BEFORE claim)
   - 1 integration test (same-tick reset + reclaim + dispatch)
   Total pipeline_tick.py: 54 (was 47 after PR #39). Matches B1's claim.

7. **Regression delta** — reproduce locally if practical. B1 reports `16 failed, 812 passed, 21 skipped`. 16 failures byte-identical to post-PR-40 baseline (`805 + 7 = 812` math holds). Same rigor as your PR #39 / #40 reviews.

8. **Scope** — 2 files only. NO schema, NO env vars, NO step module changes, NO changes to PR #39 claim functions. Confirm diff boundary.

9. **Ship-report pytest log is FULL, not "by inspection"** — literal counts quoted, head+tail captured. REQUEST_CHANGES on any "by inspection" phrasing.

## Decision

- **APPROVE** → reply `APPROVE PR #41` in your review report; AI Head will Tier-A auto-merge (`gh pr merge 41 --squash`).
- **REQUEST_CHANGES** → name the line/logic; B1 loops.

## Report path

`briefs/_reports/B3_pr41_claim_loop_running_states_3_review_20260422.md` — commit + push after review. Close this task file with a `## B3 dispatch back` section.

## Note

B2 is running STEP5_EMPTY_DRAFT_INVESTIGATION_1 in parallel. Expect a second review dispatch when that PR opens. Both will need your rigor; no batching.

---

**Dispatch timestamp:** 2026-04-22 ~12:05 UTC (post-B1 ship)
