---
status: PENDING
brief: briefs/BRIEF_BUS_DRAIN_CURSOR_CAP_FIX_1.md
trigger_class: TIER_B_FOLLOWUP_CORRECTNESS_FIX
dispatched_at: 2026-05-11
dispatched_by: ai-head-1 (AH1)
target: b2
director_ratification: Director ruled "ship now, fix later" on parent PR #183 cursor-cap data-loss bug (2026-05-11); Director "fire follow-ups" 2026-05-11 greenlit this dispatch end-to-end.
priority: P3
phase: 1 of 1 (single PR, follow-up to PR #183)
unblocks:
  - Closes confirmed data-loss bug at session-start-bus-drain.sh:377 (silent loss of messages 31-50 in backlog drains)
  - Removes line-161 unused-var nit AH2 flagged
  - Adds regression test for cursor-cap behavior
expected_pr_count: 1 (baker-master)
expected_branch_name: b2/bus-drain-cursor-cap-fix-1
expected_complexity: small (~30 min)
mandatory_2nd_pass: FALSE  # 1-line semantic change in already-reviewed file (PR #183 cleared cross-lane + /security-review); no re-pass needed
last_heartbeat: null
autopoll_eligible: true
gate_to_merge: AH2 cross-lane review per autonomy charter §3 (no Director smoke needed for a 1-line follow-up to already-deployed hook)
---

# CODE_2_PENDING — BRIEF_BUS_DRAIN_CURSOR_CAP_FIX_1 — 2026-05-11

**Brief:** `briefs/BRIEF_BUS_DRAIN_CURSOR_CAP_FIX_1.md` (READ FIRST — short brief, single-line fix + 1 test + 1 nit cleanup)
**Working dir:** `~/bm-b2`
**Working branch:** `b2/bus-drain-cursor-cap-fix-1` (branch from latest main `2cc97a7`)
**Repo:** `vallen300-bit/baker-master`

## Summary

Follow-up to PR #183 (merged 2026-05-10T22:59Z) — fix the cursor-cap data-loss bug AH2 flagged on `/security-review`. When daemon returns 31-50 unread messages, cursor jumps past all of them after rendering only the first 30; messages 31-50 are silently lost.

**One-line fix:** `tests/fixtures/session-start-bus-drain.sh:377` — change `for m in msgs` to `for m in shown`. Cursor now advances to the rendered slice's max `created_at`, not the full fetched slice's max.

**Daemon ASC confirmed** (`bus.py:349`) — so `shown = msgs[:30]` are the 30 oldest unread; next drain `since=msgs[29].created_at` returns `msgs[30:]` correctly.

**Plus:** drop the unused `body_json` at `tests/test_bus_drain_hook.py:647` + add `test_overflow_cursor_advances_to_rendered_max` regression test.

**Plus (post-merge):** re-deploy the user-global hook by cp'ing the fixed fixture to `~/.claude/hooks/session-start-bus-drain.sh`. The drift-detection test you added in PR #183 catches drift, so this step closes the loop.

## Ship gate

1. `bash -n ~/.claude/hooks/session-start-bus-drain.sh` — passes.
2. `pytest tests/test_bus_drain_hook.py -v` — 10/10 (was 9/9 + 1 new regression test).
3. PR description includes literal `pytest` stdout.
4. AH2 cross-lane review — fast turnaround expected (cleared parent PR yesterday).
5. After merge: cp `tests/fixtures/session-start-bus-drain.sh` to `~/.claude/hooks/session-start-bus-drain.sh` + verify drift-detection test passes.

## Files touched

**Modify (in-repo):**
- `tests/fixtures/session-start-bus-drain.sh` — line 377 (`msgs` → `shown`)
- `tests/test_bus_drain_hook.py` — drop line 647 unused var + add 1 regression test

**Modify (user-global, post-merge):**
- `~/.claude/hooks/session-start-bus-drain.sh` — cp from fixed fixture

**Do NOT touch:**
- `~/.claude/settings.json` — unchanged (hook path + timeout same)
- `brisen-lab/` daemon — unchanged
- Anything else in `session-start-bus-drain.sh` beyond line 377

## Estimated complexity

Small · ~30 min · 1 PR · Tier-B correctness follow-up. No `/security-review` re-pass.

## Heartbeat

12h cadence binding. Brief is small enough one heartbeat suffices.

## Prior CODE_2 task (archive reference)

BRIEF_BRISEN_LAB_TERMINAL_BUS_DRAIN_ON_SESSION_START_1 — SHIPPED 2026-05-11 (PR #183 squash-merged at `2cc97a7` 2026-05-10T22:59Z). AH2 cross-lane CLEARED, `/security-review` CLEARED, Director ratified user-global state, Director skipped live smoke. Mailbox hygiene rule applied — overwriting per `_ops/processes/b-code-dispatch-coordination.md` §3.
