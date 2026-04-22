# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3
**Task posted:** 2026-04-22 (post-B1 ship of PR #41)
**Status:** CLOSED — PR #41 APPROVE, Tier A auto-merge greenlit, `*_running` mid-step crash orphan class structurally retired

---

## B3 dispatch back (2026-04-22)

**APPROVE PR #41** — all 9 focus items green, zero gating nits. Closes my own PR #39 N3 nit. Full-suite regression delta reproduced locally with cmp-confirmed identical 16-failure set. `805 + 7 = 812` math matches B1 exactly.

Report: `briefs/_reports/B3_pr41_claim_loop_running_states_3_review_20260422.md`.

### Regression delta (focus 7) — reproduced locally

```
main baseline:       16 failed / 805 passed / 21 skipped / 19 warnings  (12.01s)
pr41 head 5e4e253:   16 failed / 812 passed / 21 skipped / 19 warnings  (12.62s)
Delta:               +7 passed, 0 regressions, 0 new errors
```

`+7 passed` = exactly the 7 new tests. cmp-confirmed identical 16-failure SET.

### Per focus verdict

1. ✅ **`reset_stale_running_orphans`.** Single atomic UPDATE with `CASE status WHEN 'X_running' THEN 'awaiting_X' END` for all 3 states, `WHERE status IN (...)` + staleness guard, `RETURNING id, status` (present but unused, harmless), `cur.rowcount → n`, one commit. No `FOR UPDATE SKIP LOCKED` needed (single statement, atomic). No race with PR #39 claims (filter sets disjoint: `*_running` vs `awaiting_*`).

2. ✅ **`main()` wire-in.** Unconditional call to reset BEFORE claim chain (line 791-794); `if n_reset:` gate suppresses log noise when N=0; same `conn` shared across reset + claim chain so reset's commit is visible to same-tick claims.

3. ✅ **CASE-WHEN completeness.** All 3 states covered. No ELSE clause — safe because `WHERE status IN (...)` constrains input to the 3 enumerated values. Test #3 explicitly asserts the full WHERE clause.

4. ✅ **15-min staleness.** Module constant `_RUNNING_ORPHAN_STALE_INTERVAL = "15 minutes"`, separate from PR #39's constant per spec. 5× margin over Step 5 R3 (~180s) rationale documented in comment.

5. ✅ **Same-tick reset→claim integration.** `test_main_reset_and_reclaim_in_same_tick` pins the full `call_log` through reset → primary → opus_failed → awaiting_classify → awaiting_opus (hit, returns 777) → `_process_signal_opus_remote(777, conn)`. `awaiting_finalize` `call_count==0` (stopped at first hit). Proves reset commit lands before claim reads in the SAME tick.

6. ✅ **7 tests, all non-trivial.** 3 per-state SQL-text inspection (exact `WHEN 'X' THEN 'Y'` substrings + WHERE IN clause) + 2 zero-rowcount (idempotent commit) + 1 pre-chain call-order (`call_log == ["reset", "primary"]`) + 1 full same-tick integration. pipeline_tick.py total: 47 + 7 = 54 (matches B1's claim).

7. ✅ **Regression delta.** +7 passed, 0 regressions, identical failure set.

8. ✅ **Scope.** 2 files, no schema, no env vars, no step-module changes, no changes to PR #39 claim functions or their dispatchers.

9. ✅ **No ship-by-inspection.** Literal counts (16/812/21) + enumerated FAILED rows. "by inspection" phrase absent (grep confirmed).

### N-nits parked (non-blocking)

- **N1:** CASE has no ELSE clause. Safe today because WHERE IN matches the 3 WHEN branches exactly. If a 4th state is added to WHERE IN without matching WHEN, CASE→NULL and UPDATE would NULL the status. Cheap mitigation: add `ELSE status` or a coupling comment. Current code is correct.
- **N2:** Tests #4 + #5 are functionally identical at mock boundary (both rowcount=0). Honest acknowledgement present in docstring. Same pattern as PR #38/#39 boundary tests.
- **N3:** `RETURNING id, status` unused — PG evaluates lazily, no cost. Could be wired to structured-log affected signal_ids in a future follow-up.

Tier A auto-merge proceeds. Combined with PRs #38 + #39, full crash-recovery surface now covered: opus_failed retry (#38) + awaiting_* between-steps (#39) + *_running during-steps (#41). Only remaining non-terminal class is `paused_cost_cap` which is a deliberate hold, not a crash — out of scope for this track.

Tab quitting per §Decision.

— B3

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
