# B4 ship report — CLICKUP_GET_TASKS_ROBUSTNESS_1 (+ folded lead #11775)

- **Brief:** CLICKUP_GET_TASKS_ROBUSTNESS_1 (deputy spec #11737 / relay #11771; lead #11768). Priority-insert lead #11775 folded in.
- **PR:** #572 → base `main`, head `b4/clickup-get-tasks-robustness`
- **Commits:** `2f28970f` (F1+F2) + `ca325ed3` (codex fix + lead #11775 done-type fix)
- **Class:** ClickUp-read robustness + Director-facing board correctness
- **Date:** 2026-07-15

## What shipped
**F1 — outage vs empty (fail-loud).** `get_tasks` mapped both a ClickUp outage
(`_request`→None) and a genuinely empty list to `[]`. Now a new typed
`ClickUpUnavailable` is raised on a failed request AND on a malformed-but-truthy
200 body (`{}`, `{"tasks": null}`, missing key, non-dict); a real empty list
(`{"tasks": []}`) still returns `[]`. Arrivals sync catches it → `skipped_outage`
+ fail-loud log, never overwriting a live arrival with an outage-derived empty.

**F2 — pagination.** `get_tasks` read page 0 only; a >100-task list truncated
silently. Now loops until ClickUp's `last_page` (or a short/empty page), preserving
`include_closed` + `date_updated_gt` per page, with a `_TASKS_PAGE_CAP` guard that
fails loud instead of looping on a malformed response.

**Folded — lead #11775 (Director-facing board defect).** `derive_next_milestone`
excluded only `status.type=="closed"`, but the BB-AUK-001 connector list marks
completions type **`"done"`** — so finished tasks (B18 + ~19 [VALID] + Bauschatz)
still derived as the next milestone and the board stayed DELAYED on a past date.
Now excludes type in `{"closed","done"}`.

## Blast radius (get_tasks is shared) — verified no regression
- `triggers/clickup_trigger.py:293` — per-list `try/except` → log + continue.
- `orchestrator/dispatcher_relay.py:755` — propagates to `run_tick` top-level
  `except` → log + `{"ok": false}`.
Both already exception-safe; F1's raise makes them fail-loud on outage instead of
silent-empty (strict improvement). Sibling methods `get_task_comments`/`search_tasks`
unchanged.

## Acceptance criteria (TDD)
AC1 outage→raise ✅ · AC1b malformed-200-body→raise ✅ · AC2 genuine empty→[] ✅ ·
AC3 multi-page accumulation + per-page params preserved ✅ · AC4 page-cap fail-loud ✅ ·
AC5 siblings unchanged ✅ · + arrivals `skipped_outage` ✅ · + done-type exclusion (#11775) ✅

## Tests (literal)
`pytest tests/test_clickup_client.py::TestGetTasksRobustness tests/test_arrivals_board.py`
→ **30 passed, 1 skipped** (live-PG). 8 new tests.

## Codex verify (mandatory gate)
First pass: **FAIL** — found the malformed-200-body silent-`[]` gap (only literal
None raised). Fixed in `ca325ed3` (require a dict with a list-valued `tasks`, else
raise) + a test over `{}`/`tasks:null`/missing/non-dict. Re-verify: **PASS** (flips
the FAIL; codex ran the tests live, both fixes correct, no residual gap).

## Observations (not scope — per lead #11775)
- Desk reports MCP ClickUp `filter_tasks` + `search` return 0 for this connector
  list, while REST (`get_tasks`) works. Flagging for lead — may be an MCP-side
  filter/index issue on that list, worth a separate look.
- **Pre-existing (NOT this change):** 5 `TestWriteSafety` tests fail on clean
  `origin/main` — they expect wrong-space writes to raise, but the client is
  all-spaces-writable per the 2026-03-25 Director ratification. Stale tests, out of
  scope for this PR.

## Gate chain status
build (TDD) ✅ → codex verify (FAIL→fixed→PASS) ✅ → **awaiting deputy cross-lane
review → lead merge**. Non-blocking / not on the ENFORCE ladder.
