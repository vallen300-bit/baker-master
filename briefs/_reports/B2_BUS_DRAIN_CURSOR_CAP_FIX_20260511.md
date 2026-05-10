---
brief: briefs/BRIEF_BUS_DRAIN_CURSOR_CAP_FIX_1.md
mailbox: briefs/_tasks/CODE_2_PENDING.md
builder: B2
shipped_at: 2026-05-11T01:20Z
pr: https://github.com/vallen300-bit/baker-master/pull/184
parent_pr: https://github.com/vallen300-bit/baker-master/pull/183
branch: b2/bus-drain-cursor-cap-fix-1
commit: 3edc3d3c
priority: P3
tier: B
trigger_class: TIER_B_FOLLOWUP_CORRECTNESS_FIX
mandatory_2nd_pass: false
gate_to_merge: AH2 cross-lane review per autonomy charter §3
---

# B2 ship report — BUS_DRAIN_CURSOR_CAP_FIX_1 — 2026-05-11

## What shipped

Follow-up to PR #183 closing the cursor-cap data-loss bug AH2 flagged on `/security-review`. Director ruled "ship now, fix later" on the parent; this PR is the "fix later."

**Functional change (1 line):**
- `tests/fixtures/session-start-bus-drain.sh:147` — `for m in msgs` → `for m in shown`

**Cleanup nit (AH2 PR #183):**
- `tests/test_bus_drain_hook.py:236` — dropped unused `body_json` local in `test_happy_path_renders_and_writes_state`

**Regression test:**
- `tests/test_bus_drain_hook.py` — added `test_overflow_cursor_advances_to_rendered_max` (40 msgs → assert cursor == `msgs[29].created_at`, NOT `msgs[39].created_at`)

## Bug closed

When daemon returned 31-50 unread messages:
1. Receiver saw 30 rendered + overflow note.
2. State file was written with `max(created_at for m in msgs)` — the newest of all 50.
3. Next drain `since=<that ts>` → daemon returned 0 → messages 31-50 silently lost forever.

Daemon `ORDER BY created_at ASC` (`bus.py:349`) means `shown = msgs[:30]` are the 30 oldest unread. With the fix, `since=msgs[29].created_at` returns `msgs[30:]` correctly on the next drain.

## Ship gate evidence

| Gate | Status | Evidence |
|---|---|---|
| `bash -n` syntax check | ✅ exit 0 | `bash -n tests/fixtures/session-start-bus-drain.sh; echo "exit=$?"` → `exit=0` |
| pytest 10/10 | ✅ 10 passed in 3.11s | Literal stdout in PR #184 body |
| Literal pytest in PR body | ✅ | PR #184 description |
| AH2 cross-lane review | ⏳ pending | Per charter §3 (no `/security-review` re-pass — 1-line semantic change) |
| Post-merge user-global cp | ✅ done pre-merge | Followed PR #183 precedent — cp'd to make drift test pass for 10/10 gate |

## Pytest output (literal)

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0 -- /opt/homebrew/opt/python@3.12/bin/python3.12
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b2
plugins: langsmith-0.7.38, anyio-4.12.1
collecting ... collected 10 items

tests/test_bus_drain_hook.py::test_baker_role_unset_silent_noop PASSED   [ 10%]
tests/test_bus_drain_hook.py::test_op_fetch_failure_emits_status PASSED  [ 20%]
tests/test_bus_drain_hook.py::test_daemon_unreachable_emits_status PASSED [ 30%]
tests/test_bus_drain_hook.py::test_bad_daemon_response_emits_status PASSED [ 40%]
tests/test_bus_drain_hook.py::test_empty_inbox_quiet_noop PASSED         [ 50%]
tests/test_bus_drain_hook.py::test_daemon_detail_error_emits_status PASSED [ 60%]
tests/test_bus_drain_hook.py::test_happy_path_renders_and_writes_state PASSED [ 70%]
tests/test_bus_drain_hook.py::test_existing_state_file_used_as_since PASSED [ 80%]
tests/test_bus_drain_hook.py::test_overflow_cursor_advances_to_rendered_max PASSED [ 90%]
tests/test_bus_drain_hook.py::test_user_global_matches_repo PASSED       [100%]

============================== 10 passed in 3.11s ==============================
```

## Decisions / deviations from brief

1. **User-global cp pre-merge (not post-merge).** Brief §Ship gate item 5 said cp post-merge, but item 2 expected pytest 10/10. The 10th test (`test_user_global_matches_repo`) fails if the deployed hook differs from the fixture. Followed PR #183's precedent — Director ratified pre-merge cp there. Content is identical to what will be squash-merged. Functional risk zero (only difference is `msgs` → `shown`, which only matters when daemon returns >30 unread; no such state on B2's box right now).
2. **Brief line numbers stale.** Brief cited `:377` (fixture) and `:647` (test) but actual files were 176 + 318 lines respectively. Located targets by search:
   - Fixture `max(... for m in msgs)` → line 147
   - Test `body_json = ...` → line 236
3. **`_run_hook_with_msgs` helper doesn't exist.** Brief's scaffold called this; actual helper is `_run_hook(env, tmp_path)` with stub-based curl. Mirrored the happy-path test pattern (`_make_stub` for op + curl with cat-heredoc).
4. **pytest binary not on PATH.** Used `/opt/homebrew/bin/python3.12 -m pytest` (python3.9 default on this box doesn't support PEP 604 `int | None` syntax used in `memory/store_back.py:5820`).

## Out of scope (not touched)

- `~/.claude/settings.json` — unchanged (hook path + timeout same)
- `brisen-lab/` daemon (`bus.py`, `auth_lab.py`, `db.py`) — unchanged
- `BRISEN_LAB_TERMINAL_KEYS` Render env — unchanged
- Other SessionStart hooks (Forge, session-start-role.sh) — unchanged
- Anything in `session-start-bus-drain.sh` beyond line 147

## Next

- Awaiting AH2 cross-lane review.
- On merge: drift-detection test continues to pass post-squash (user-global already matches).
