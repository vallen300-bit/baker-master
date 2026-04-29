# CODE_1 — PR-OPEN (SCHEDULER_SINGLETON_HARDEN_1)

**Status:** PR-OPEN awaiting AI Head A/B situational-review (MEDIUM trigger class)
**PR:** https://github.com/vallen300-bit/baker-master/pull/84
**Branch:** `b1/scheduler-singleton-harden-1`
**Commit:** `133a852`
**Ship report:** `briefs/_reports/B1_scheduler_singleton_harden_20260430.md`
**Drafted:** 2026-04-29

## What shipped

1. `triggers/scheduler_lease.py` (NEW) — process-singleton lock via `pg_try_advisory_lock(8800100)` on Neon-direct connection
2. `start_scheduler` / `stop_scheduler` / `restart_scheduler` integrate lock acquire/release; `restart_scheduler` now `wait=True`
3. `_watchdog_cooldown` rate-limit bug fixed in `outputs/dashboard.py`
4. `_scheduler_heartbeat` probes held connection for Neon-auto-suspend liveness

## Tests

- 4 pass, 3 live-PG skip (no `TEST_DATABASE_URL` locally; CI auto-provisions Neon ephemeral)
- 44 adjacent tests pass — no regression
- `scripts/check_singletons.sh` clean

## Director action required (post-merge, NOT in PR)

Set Render env-var `POSTGRES_HOST_DIRECT` via MCP merge mode (drop `-pooler` from current `POSTGRES_HOST`). Failure-mode degrades to today's state with loud ERROR log — no new regression.

## Post-deploy verification (AI Head)

- Verification SQL #1 from report §7: every job `distinct_anchors = 1` over 15-min window
- Verification SQL #2: `pg_locks` shows 1 row for `objid=8800100`
- Verification SQL #3: `cortex_pipeline.maybe_dispatch` still 1× per signal

## Mailbox hygiene

On merge: overwrite this file with `COMPLETE` + post-deploy verification status.
