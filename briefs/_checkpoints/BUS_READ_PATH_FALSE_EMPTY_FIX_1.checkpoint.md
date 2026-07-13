# CHECKPOINT — BUS_READ_PATH_FALSE_EMPTY_FIX_1 (E27, Plan v3 A1)

attempt: 1
seat: b1 (fresh seat resumed on lead ping #10680; prior seat left NO checkpoint for this arc)
branch: b1/bus-read-path-false-empty-fix-1 (brisen-lab, in ~/bm-b1/brisen-lab) — 5 ahead / 5 behind origin/main
created: 2026-07-13
updated: 2026-07-13

## Brief id
BUS_READ_PATH_FALSE_EMPTY_FIX_1 (E27) — PR brisen-lab #130. Dispatch/rulings: lead #10460
(REVERSED the A1.5 split: gate ALL DB to_thread sites in this PR, not the narrowed ~35).
Status ping: lead #10680. My status posts: #10697, verdict #10703 (topic case-one/plan-v3-a1-status).

## STATUS: BUILT + VERIFIED GREEN — awaiting lead review gate
- Branch head 46609b0 (pushed) = full DB-concurrency sweep (93 to_thread -> db_gate.db_call).
  Message still says "DO NOT MERGE — unverified" but it IS now verified. Not reworded (no force-push).
- Read-path tests: 19/19 pass.
- Full brisen-lab suite (local throwaway PG): 586 passed, 1 skipped, 27 failed = documented
  pre-existing autowake/identity baseline (env/registry drift), ZERO new failures from the sweep.
- Sweep complete: 98 db_gate.db_call sites across app/bus/lifecycle/job_queue/research_bus;
  zero ungated DB to_thread remain (only comments + db_gate's own fallback).
- PR #130 body updated with the verification section.

## What's left
- Lead review gate: open routing question posted in #10703 — re-request codex (per #10460) OR
  lead takes Claude-side review (codex suspended per P4 note #9711). Lead's call.
- On merge: nothing further from b1 for this PR (no post-deploy AC named for E27 in scope here).

## Scratch to flag
- ~/bm-b1/brisen-lab has untracked prior-seat scratch: doc_backfill_driver*.sh, driver_*_stdout.log,
  doc_backfill_run.log, tests/test_agent_queue_drill.py (in the sibling ~/bm-b1-brisen-lab). Untracked,
  NOT committed. Left in place; flag for cleanup, do not blind-delete.

## Next concrete step
Wait for lead's gate ruling on #10703. If lead says re-request codex, post the PR ref to codex bus
and re-run suites if codex requests changes. If lead reviews Claude-side, address any change requests
as a NEW commit (never amend the pushed sweep).

## Claim discipline
Successor claims by the attempt:-bump commit on THIS checkpoint. If attempt already bumped, stand down.
At attempt >= 3, stop resuming + escalate to lead with this path + last error.
