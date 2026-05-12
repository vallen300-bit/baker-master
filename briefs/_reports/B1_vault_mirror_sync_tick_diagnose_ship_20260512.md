---
brief: VAULT_MIRROR_SYNC_TICK_DIAGNOSE_1
mailbox: briefs/_tasks/CODE_1_PENDING.md (dispatch commit b4e5c2a)
agent: b1
state: SHIPPED_PENDING_REVIEW
shipped_at: 2026-05-12T20:45Z
pr: https://github.com/vallen300-bit/baker-master/pull/193
branch: b1/vault-mirror-sync-tick-diagnose-1
head_sha: 82b5a06
bus_post: msg #166 ship/vault-mirror-sync-tick-diagnose-1
ratify_source: lead bus msg #156 (Director 2026-05-12 20:30Z "go" — Option A)
gates_required:
  - AH2 /security-review
  - picker-architect
live_verify: pending (Render auto-deploy after merge)
---

# B1 — VAULT_MIRROR_SYNC_TICK_DIAGNOSE_1 — ship report

## Root cause

`vault_sync_tick` was an APScheduler job registered inside `triggers.embedded_scheduler._register_jobs()` — the **singleton-locked** `BackgroundScheduler`. On Render's multi-replica deploy of `baker-master`, only the lock-holding replica runs the scheduler; every other replica spawns a lock-retry thread and registers **zero** jobs. Each replica owns a per-process local FS mirror at `/opt/render/project/src/baker-vault-mirror` plus per-process `_last_pull_at`, so non-lock replicas froze at `ensure_mirror()`'s startup-clone state. `baker_vault_read` MCP requests load-balanced across replicas → ~50%+ hit a stale-mirror replica.

Variant of brief hypothesis #5 ("Render-side process reload kills the job") — actual mechanism is **singleton-scoping mismatch**: `vault_mirror`'s state is per-process but the refresh job was shared-scoped.

## Evidence

8 rapid `/health` polls (~1s apart, 2026-05-12 ~20:20-20:22Z) returned exactly two alternating replica states:
- `sched=running,jobs=62,vault_last=20:20:11` (lock-holder) — 5/8
- `sched=stopped,jobs=0,vault_last=19:40:10` (non-lock, 40-min stale @ startup-clone time) — 3/8

Same `vault_mirror_commit_sha` on both states only because the lock-holder hadn't pulled new content yet; any baker-vault commit immediately diverges N-1 replicas.

## Fix (Option A — Director-ratified via lead msg #156)

- `vault_mirror.start_sync_thread(interval_seconds=None)` — idempotent per-process daemon thread spawner. Loops `sync_tick()` on configured interval (300s default, 60s floor from `sync_interval_seconds()`).
- `vault_mirror.stop_sync_thread(timeout=5.0)` — clean stop for tests + shutdown. Uses `threading.Event.wait` so stop cuts a pending sleep promptly.
- `outputs/dashboard.py::_ensure_vault_mirror()` calls `start_sync_thread()` right after `ensure_mirror()`. Runs on EVERY replica at FastAPI startup, independent of the singleton lock.
- `triggers/embedded_scheduler.py` — removed `scheduler.add_job(_vault_sync_tick_job, IntervalTrigger(...), id="vault_sync_tick", ...)` block AND the `_vault_sync_tick_job` wrapper. Replaced with anchor comment.

Not a workaround: re-scopes the job to its correct lifecycle owner. The brief's "do not ship a workaround" caveat targeted band-aids (manual `/pull` endpoint, separate cron-trigger sentinel) — this re-scopes the existing job rather than adding parallel mechanisms.

## Tests

`tests/test_vault_mirror.py` — 7 cases under Python 3.12:

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
collected 7 items

tests/test_vault_mirror.py::test_start_sync_thread_returns_live_daemon_thread PASSED [ 14%]
tests/test_vault_mirror.py::test_start_sync_thread_idempotent PASSED     [ 28%]
tests/test_vault_mirror.py::test_sync_thread_invokes_sync_tick_on_interval PASSED [ 42%]
tests/test_vault_mirror.py::test_stop_sync_thread_joins_and_clears PASSED [ 57%]
tests/test_vault_mirror.py::test_sync_loop_swallows_sync_tick_exceptions PASSED [ 71%]
tests/test_vault_mirror.py::test_vault_sync_tick_no_longer_registered_in_scheduler PASSED [ 85%]
tests/test_vault_mirror.py::test_module_exports_lifecycle_api PASSED     [100%]

============================== 7 passed in 0.74s ===============================
```

## Live verification (pending merge + Render auto-deploy)

Per ratify msg #156 sharpened ship gate: poll `/health` 8x rapid after Render deploys the merged PR. ALL replicas should show `vault_mirror_last_pull` advancing within ≤5min of a forced baker-vault commit. Will append before/after timestamps to PR #193 body before final ship-mark.

## Bus posts

- `claimed/vault-mirror-sync-tick-diagnose-1` — msg #153
- `blocker/vault-mirror-sync-tick-diagnose-1` (scope escalation) — msg #154
- `ship/vault-mirror-sync-tick-diagnose-1` — msg #166
