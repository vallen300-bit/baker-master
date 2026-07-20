# B1 ship report — COCKPIT_SWEEP_INTERVAL_PERSISTENCE_GUARD_1

- **Brief:** dispatch #14075 (dup #14076) from `lead`, topic `cockpit-sweep-interval-guard-1`. Both acked.
- **Branch:** `b1/cockpit-sweep-interval-guard-1` off main @a37f8bcb.
- **Task class:** feature-build (local cockpit controller config; NOT baker-master service).

## Problem (confirmed on live host)
Director ruled the backlog-sweep interval is **120s**. It lived ONLY as a hand-injected
`COCKPIT_BACKLOG_SWEEP_SECONDS=120` in the live launchd plist
(`~/Library/LaunchAgents/com.baker.cockpit-controller.plist`, verified present today;
controller running pid 27087). The repo default was **600** (`scripts/cockpit_controller.py:316`),
and the plist **template** (`scripts/launchd/com.baker.cockpit-controller.plist`) carries no
sweep-seconds key. So any plist regeneration/reinstall via `install_cockpit_controller.sh`
drops the hand-injected 120 and silently reverts the Director ruling to 600.

## Chosen mechanism (of the two the brief offered)
**Make 120 the repo default** — changed the constant `BACKLOG_SWEEP_SECONDS = 600.0 → 120.0`.
NOT the plist-inject option.

**Justification.** The default is the single source of truth. The brief names "repo default is
still 600" as the defect; fixing the default fixes the root cause directly. Code-default 120
defends **every** launch path — plist regenerate, env-less run, and direct invocation — whereas
injecting 120 into the plist template would leave a latent 600 in code that still reverts anywhere
the plist is not the launch path. `from_env` continues to honor `COCKPIT_BACKLOG_SWEEP_SECONDS`,
so the value stays tunable without a code change. One code file + one test file (small arc as scoped).

## Semantic note for lead/Director (fail-loud)
With this mechanism the plist deliberately **no longer carries** the sweep value — the guarantee
moved from the plist env to the code default. The existing hand-injected `=120` in the live plist
is now redundant (harmless; it still wins as an explicit override). If the intent was specifically
that the *plist* remain the visible carrier of the ruling, that is the other option (template
inject) and I'll switch — flag me. I read the brief's "verify plist still carries 120" as "verify
the effective sweep is still 120 after a regenerate", which is what I verified.

## Failing-test-first
`tests/test_cockpit_controller.py::test_backlog_sweep_default_is_the_ratified_120s`
- RED against 600: `assert 600.0 == 120.0` (captured before the fix).
- Asserts constant == 120, dataclass default == 120, and `from_env` with the override **unset**
  resolves 120 (the exact revert path the guard defends).
- Sibling `test_backlog_sweep_env_override_still_tunable` proves env override (300) still wins.

## Verification
- New tests GREEN after the change.
- `tests/test_cockpit_controller.py`: **63 passed, 0 skipped**.
- Broader `test_cockpit_controller + test_cockpit_wake + test_cockpit_history + test_cockpit_notify`:
  **157 passed, 0 skipped**.
- `py_compile` clean on `scripts/cockpit_controller.py`.
- **Dry-run regenerate** (temp dirs, NO live mutation, NO controller restart): installer runs clean,
  renders a plist that `plutil -lint` reports OK, with no sweep-env key — and a controller launched
  from that env resolves `backlog_sweep_seconds == 120.0`. Effective sweep after a regenerate = 120s.
- Existing sweep tests pass `backlog_sweep_seconds` explicitly via `replace(...)`, so the default
  change touches none of them.

## Not done (per brief)
- Did NOT restart the live controller. The live controller (pid 27087) keeps running its current
  env (still 120 via the hand-injected plist key). The persistence guarantee lands whenever the
  plist is next regenerated/reinstalled or the controller is next relaunched. Reinstall is a
  Director/lead operation — flag if you want me to prep it.

## Files
- `scripts/cockpit_controller.py` — constant 600.0 → 120.0 + guard comment.
- `tests/test_cockpit_controller.py` — 2 new tests.
