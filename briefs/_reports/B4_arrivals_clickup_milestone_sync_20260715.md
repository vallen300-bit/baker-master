# B4 ship report — ARRIVALS_BOARD_CLICKUP_MILESTONE_SYNC_1

- **Brief:** BRIEF_ARRIVALS_BOARD_CLICKUP_MILESTONE_SYNC_1 (deputy dispatch #11693, lead PASS + riders #11692)
- **PR:** #569 → base `main`, head `b4/arrivals-clickup-sync`
- **Commits:** `da02625c` (feature) + `21f0d415` (codex P1/#4 fix)
- **Class:** production-executed Director-facing surface — HIGH-IMPACT
- **Date:** 2026-07-15

## What shipped
A 15-min scheduler tick (`arrivals_clickup_sync`) auto-derives the arrivals board's
`arrives_on`/`arrives_label` from each flight's ClickUp timetable (next incomplete
task with a due date). Reads ClickUp only; a desk's manual edit wins for 24h.
Self-gating on `project_registry.clickup_list_id` (BB-AUK-001 pilot; other 7 flights
NULL → skipped, activate on backfill with no code change).

- `derive_next_milestone(tasks, today)` — pure; earliest incomplete+due wins; closed/
  no-due excluded; ms-epoch UTC-pinned (R2); same-day ties broken by full timestamp.
- `sync_should_write(row, now)` — pure anti-flap; manual edit <24h never overwritten.
- `run_clickup_milestone_sync()` — per-flight + top-level try/except; no-op suppression;
  terminal-flight skip; per-tick `baker_actions` summary. R1: threads current status
  through `upsert_board_state` (default CHECK-IN) so the status-required upsert never raises.
- `embedded_scheduler.py` — `arrivals_clickup_sync` IntervalTrigger(900s) + liveness.

## Done rubric answered (AC1-AC10)
- AC1 deriver ✅ · AC2 unset-list skip ✅ · AC3 overlay/base-only ✅ · AC4 audited + tick summary ✅
- AC5 24h manual hold ✅ · AC6 no-op suppression ✅ · AC7 per-flight independence + try/except ✅
- AC8 tick registered w/ liveness ✅ · AC9 (R1) status threaded, no ValueError ✅ · AC10 (R2) UTC-pin ✅

## Tests (literal)
`pytest tests/test_arrivals_board.py` → **22 passed, 1 skipped** (live-PG upsert).
16 new tests (pure deriver + anti-flap + monkeypatched orchestration; DB & ClickUp
seams stubbed). Scheduler-liveness AST invariant → **44 passed**.

## Codex verify (mandatory high-impact gate)
Verdict: **PASS-WITH-NOTES** (gpt-5.6-luna, high). 4 findings:
- **P1 (retired flights resurrect)** — RESOLVED `21f0d415`: exclude LANDED/DIVERTED in
  `_sync_candidate_rows` SQL + defensive Python guard (`skipped_terminal`) + test.
- **#4 (same-day non-deterministic order)** — RESOLVED `21f0d415`: sort on full ms-epoch + test.
- **#2 (ClickUp outage reads as "no milestone", fail-loud gap)** and **#3 (no pagination —
  >100-task list could hide an earlier milestone)** — both require a change to
  `clickup_client.get_tasks`, which is **out of this brief's scope** (not in Files Modified;
  shared by all ClickUp consumers). Flagged to lead as follow-up tickets. Impact is bounded:
  on an outage the board keeps its last value (not clobbered); the pilot list is small.
- Implicit PASS on R1/R2/anti-flap/no-op/overlay/scheduler.

## Out of scope (respected)
`effective_status`/overlay, `POST /api/flight-board`, `clickup_client` write paths/kill
switch, `project_registry` write paths — all unmodified.

## Gate chain status
build (TDD) ✅ → codex verify (P1+#4 resolved, #2/#3 flagged) ✅ → **awaiting deputy
cross-lane review → lead merge** → deputy post-deploy live-AC on BB-AUK-001.
