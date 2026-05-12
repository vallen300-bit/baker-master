---
brief: briefs/BRIEF_VAULT_MIRROR_THREAD_LIFECYCLE_HYGIENE_1.md
mailbox: briefs/_tasks/CODE_1_PENDING.md
trigger_class: TIER_B_CONCURRENCY_PRIMITIVE_HYGIENE
target: b1
status: SHIPPED
shipped_at: 2026-05-13
pr: https://github.com/vallen300-bit/baker-master/pull/196
branch: b1/vault-mirror-thread-lifecycle-hygiene-1
commit_sha: 721bff09cb923635b5e5e3c5de6a49c4739a9ee3
ship_gate: PASS (literal pytest 12/12 GREEN, no "by inspection")
mandatory_2nd_pass: TRUE
heartbeat: n/a (~1h single-pass implementation, under 12h cadence)
---

# Ship report — VAULT_MIRROR_THREAD_LIFECYCLE_HYGIENE_1

## Summary

Three small hygiene fixes from the PR #194 + PR #195 fast-follow queue
bundled into one B-code dispatch:

- **Fix 1 (L1)** — `vault_mirror.stop_sync_thread` atomic-swap (detach
  inside lock, join outside lock) + per-thread `threading.Event` per
  `start_sync_thread` spawn (passed into `_sync_loop` via args).
- **Fix 2 (L2)** — `vault_mirror.mirror_status` local-snapshot of
  `_sync_thread` before `is_alive()` — eliminates TOCTOU AttributeError
  under concurrent stop+poll.
- **Fix 3 (MEDIUM)** — `.githooks/pre-commit` Part 3 exclusion regex
  narrowed from `^\.githooks/` to `^\.githooks/pre-commit$`; line 65
  user-facing error message updated to match.

## Hard ship gate — PASS

```
$ python3 -m pytest tests/test_vault_mirror.py -v
...
tests/test_vault_mirror.py::test_start_sync_thread_returns_live_daemon_thread PASSED [  8%]
tests/test_vault_mirror.py::test_start_sync_thread_idempotent PASSED     [ 16%]
tests/test_vault_mirror.py::test_sync_thread_invokes_sync_tick_on_interval PASSED [ 25%]
tests/test_vault_mirror.py::test_stop_sync_thread_joins_and_clears PASSED [ 33%]
tests/test_vault_mirror.py::test_sync_loop_swallows_sync_tick_exceptions PASSED [ 41%]
tests/test_vault_mirror.py::test_vault_sync_tick_no_longer_registered_in_scheduler PASSED [ 50%]
tests/test_vault_mirror.py::test_module_exports_lifecycle_api PASSED     [ 58%]
tests/test_vault_mirror.py::test_start_sync_thread_concurrent_idempotent PASSED [ 66%]
tests/test_vault_mirror.py::test_stop_sync_thread_does_not_block_concurrent_start PASSED [ 75%]
tests/test_vault_mirror.py::test_per_thread_stop_event_isolation PASSED  [ 83%]
tests/test_vault_mirror.py::test_mirror_status_toctou_safety PASSED      [ 91%]
tests/test_vault_mirror.py::test_mirror_status_exposes_thread_liveness PASSED [100%]

============================== 12 passed in 1.66s ==============================
```

Python 3.12.12 / pytest 9.0.3 / platform darwin. No skips. No xfails.
All 9 prior tests still green; 3 new tests for Fix 1 + Fix 2.

## Manual hook verification (Fix 3)

| Case | Stage | Expected | Observed | Result |
|---|---|---|---|---|
| 1 | new `.githooks/post-commit` with `claude-opus-4-20250514` | BLOCK | exit 1 + Part 3 block message naming the file | ✓ |
| 2 | edit to `.githooks/pre-commit` adding retired ID | PASS (in exclusion) | exit 0 | ✓ |
| 3 | new `briefs/_b1_hook_test_2026_05_13.md` with retired ID | PASS (in exclusion) | exit 0 | ✓ |

Case 1's block message shows the narrowed exclusion text: `Exclusions:
briefs/, tasks/lessons.md, docs-site/, .githooks/pre-commit
(historical/audit-trail + enforcement code).`

## Quality checkpoints (brief §Quality Checkpoints)

| # | Check | Result |
|---|---|---|
| 1 | `python3 -c "import py_compile; py_compile.compile('vault_mirror.py', doraise=True)"` | COMPILE_OK |
| 2 | `python3 -m pytest tests/test_vault_mirror.py -v` (literal) | 12/12 PASS |
| 3 | Hook 3-case manual exercise | 3/3 as expected |
| 4 | Local `/health` smoke | Not exercised locally — Render restart on merge will exercise; toctou_safety test loop covers the race-path |
| 5 | `bash scripts/check_singletons.sh` | OK: No singleton violations found. |
| 6 | `git diff` review | 3 files only (`vault_mirror.py`, `tests/test_vault_mirror.py`, `.githooks/pre-commit`) |

## 4-gate readiness (AH1 fires)

- [ ] AH2 static review
- [ ] `/security-review`
- [ ] picker-architect
- [ ] `feature-dev:code-reviewer` (mandatory_2nd_pass — concurrency primitive)

All four to clear before merge.

## Notes for review

- **Fix 1 atomic-swap pattern** follows the architect's verbatim
  caveat from PINNED §I — naïve release-lock-before-join introduces a
  different race where a concurrent start observes
  `_sync_thread.is_alive() == True` mid-join and returns the dying
  handle. The per-thread Event approach (fresh Event allocated inside
  the lock during `start_sync_thread`, passed into `_sync_loop` via
  args) prevents that race because the detach happens inside the lock,
  so a concurrent start sees `_sync_thread is None` immediately and
  spawns a fresh thread.
- **`_sync_thread_stop` remains a module attribute** — reassignment
  inside `start_sync_thread` preserves the attribute name so existing
  fixture code (`vault_mirror._sync_thread_stop.clear()` at
  `tests/test_vault_mirror.py:29, 158`) still works. The clear is
  harmless after `stop_sync_thread` already consumed the Event.
- **Daemon flag + thread name unchanged** (`daemon=True`,
  `name="vault_mirror_sync"`).
- **`_sync_loop` signature change** from `(interval_seconds)` to
  `(interval_seconds, stop_event)`. Grep confirms no external callers.
- **CI-safety pad in `test_stop_sync_thread_does_not_block_concurrent_start`**:
  brief target was <50ms; test threshold set to 200ms to give 4× margin
  against CI host jitter while still failing loud on the regression
  (lock-held-across-join would block ~5s).
- **TOCTOU test uses 500-iter churn** per brief; observed ~1-2s wall
  time, well under the 30s churner timeout guard.
- **No production behavior change visible to users.** Pure hygiene —
  race-window narrowing + future-proofing the hook.

## Anchors

- PR #195 architect 2nd-pass NITs (L1 atomic-swap + L2 TOCTOU) —
  PINNED §I (deleted on dispatch)
- PR #194 PASS-WITH-NITS MEDIUM (`.githooks/` directory-wide exclusion)
- Director directive 2026-05-13 "yes" — bundled brief dispatched
- Lesson #8 (no "by inspection") — literal pytest output captured above
