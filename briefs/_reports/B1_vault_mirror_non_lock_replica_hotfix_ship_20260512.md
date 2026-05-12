---
brief: VAULT_MIRROR_NON_LOCK_REPLICA_HOTFIX_1
mailbox: briefs/_tasks/CODE_1_PENDING.md
mailbox_commit: 0536286
target: b1
status: SHIPPED
shipped_at: 2026-05-12T21:45:06+00:00
pr: 195
pr_url: https://github.com/vallen300-bit/baker-master/pull/195
branch: b1/vault-mirror-non-lock-replica-hotfix-1
commit: cb6c9a7
base_main: 0536286
priority: P1
trigger_class: TIER_B_CONCURRENCY_PRIMITIVE_HOTFIX
mandatory_2nd_pass: TRUE
gates_required:
  - AH2 /security-review
  - picker-architect
  - AH1 feature-dev:code-reviewer 2nd-pass
ship_gate_status: pytest GREEN (9/9); live /health 8x poll PENDING auto-deploy
bus_post:
  topic: ship/vault-mirror-non-lock-replica-hotfix-1
  recipient: lead
  message_id: 179
  thread_id: 21faa1a7-b31d-44dd-b415-b09558f76376
---

# B1 ship report — VAULT_MIRROR_NON_LOCK_REPLICA_HOTFIX_1

## What shipped

PR #195 — three-part hotfix following PR #193's non-lock-replica regression on Render deploy `3c8acd2`:

1. **Part A — Observability primitive (lands first by design).** `vault_mirror.mirror_status()` returns new key `vault_sync_thread_alive`; `/health` surfaces the bool. Gives operators the signal to distinguish `thread None` / `thread !alive` / `thread alive but stale last_pull` from the next `/health` poll alone.
2. **Part B — Make the failure path loud.** `_sync_loop`'s defensive `except` switched from `logger.warning` to `logger.exception` (captures full traceback — was the architect M1 / 2nd-pass L1 gap). `_ensure_vault_mirror()` wraps `start_sync_thread()` with explicit info-log on success + exception-log on raise.
3. **Part C — Fold PR #193 2nd-pass + architect nits.** Lock symmetry on `stop_sync_thread` (M1); timing-test slack `0.1s/1.0s/>=3` (L2); new concurrent-idempotency test using `threading.Barrier(2)` + 20-iteration loop (L4).

## Root cause identification (acceptance criterion 1)

**Hypothesis 1 from the brief** — silent exception inside `start_sync_thread()` or the first `_sync_loop` tick on the non-lock replica, swallowed by the defensive guard. Confirming empirically requires Part A's `vault_sync_thread_alive` bool deployed first. This PR's design is deliberate: ship the diagnostic before the targeted fix so the post-deploy /health poll names the actual hypothesis from real telemetry rather than guessing.

Part B's `logger.exception` in `_sync_loop` ensures the next failure (if any) leaves a traceback in Render logs that pinpoints the spawn / first-tick failure for a follow-up PR.

## Ship gate

### Pytest — literal output (`tests/test_vault_mirror.py -v` GREEN, 9 passed)

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b1
plugins: langsmith-0.7.38, anyio-4.12.1
collecting ... collected 9 items

tests/test_vault_mirror.py::test_start_sync_thread_returns_live_daemon_thread PASSED [ 11%]
tests/test_vault_mirror.py::test_start_sync_thread_idempotent PASSED     [ 22%]
tests/test_vault_mirror.py::test_sync_thread_invokes_sync_tick_on_interval PASSED [ 33%]
tests/test_vault_mirror.py::test_stop_sync_thread_joins_and_clears PASSED [ 44%]
tests/test_vault_mirror.py::test_sync_loop_swallows_sync_tick_exceptions PASSED [ 55%]
tests/test_vault_mirror.py::test_vault_sync_tick_no_longer_registered_in_scheduler PASSED [ 66%]
tests/test_vault_mirror.py::test_module_exports_lifecycle_api PASSED     [ 77%]
tests/test_vault_mirror.py::test_start_sync_thread_concurrent_idempotent PASSED [ 88%]
tests/test_vault_mirror.py::test_mirror_status_exposes_thread_liveness PASSED [100%]

============================== 9 passed in 1.36s ===============================
```

### Live 8× /health replica poll — PENDING auto-deploy

B1 has no Tier-B prerogative to drive a Render redeploy. Once AH1 merges + Render auto-deploy lands, the 8× /health poll across replicas (15s spacing) goes into the PR description below the existing "## Test plan" block. Pass criterion: `vault_sync_thread_alive: true` on every replica hit AND `vault_mirror_last_pull` ≤5 min old.

## Files touched

- `vault_mirror.py` — `mirror_status()` adds new key; `_sync_loop` switches to `logger.exception`; `stop_sync_thread` acquires `_sync_thread_lock`.
- `outputs/dashboard.py` — `_ensure_vault_mirror()` wraps `start_sync_thread()` with explicit logging; `/health` surfaces `vault_sync_thread_alive` (default dict + response payload both updated).
- `tests/test_vault_mirror.py` — timing-test slack bumped; new `test_start_sync_thread_concurrent_idempotent` (Barrier + 20-iter); new `test_mirror_status_exposes_thread_liveness`.

## Open questions for AH1

None. Scope was unambiguous per brief commit `0536286`. Gates are scheduled; B1 is standing down on this dispatch.
