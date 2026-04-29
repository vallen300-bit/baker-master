# CODE_1 — DISPATCH (SCHEDULER_SINGLETON_HARDEN_1)

**Status:** PENDING — assigned 2026-04-29T~17:30Z
**Brief:** `briefs/BRIEF_SCHEDULER_SINGLETON_HARDEN_1.md`
**Builder:** B1
**Trigger class:** MEDIUM (touches FastAPI lifespan; B1 situational-review pre-merge required)
**Dispatched by:** AI Head A (sole orchestrator)
**Director authorization:** "Brief is unblocked. Hand that to AI Head 1 App." (2026-04-29 ~17:00Z)

## Scope reminder (read brief for full detail)

- Singleton-lock the BackgroundScheduler across processes via `pg_try_advisory_lock` on a DEDICATED non-pooled (Neon direct) connection held for process lifetime.
- Required because Render Pro zero-downtime deploys = 2-3 min OLD+NEW overlap. Bridge advisory lock saved `kbl_bridge_tick`; other 2x-firing jobs (email_poll, clickup_poll, gold_audit_sentinel, ai_head_weekly_audit, daily_briefing, cortex_stuck_cycle_sentinel) silently doubled for 6+ days.
- 4 fixes:
  1. Singleton lock module + start_scheduler integration + 30s lock-poll retry thread
  2. `_watchdog_cooldown` rate-limit bug fix (variable misused as threshold)
  3. Live-PG singleton-enforcement tests + watchdog cooldown unit test
  4. Held-connection liveness probe via `_scheduler_heartbeat` (Neon auto-suspend safeguard)

## Hard rails

- MUST use `config.postgres.direct_dsn_params` for the lock connection — pgbouncer pooler is unsafe for session-level locks (today's pool-poisoning RCA at `memory/feedback_mcp_pgbouncer_pool_poisoning.md`).
- MUST keep `held_conn` alive for process lifetime; do NOT pass back to any pool.
- MUST NOT call `pg_try_advisory_xact_lock` (transaction-scoped — wrong primitive).
- MUST NOT touch: `kbl/bridge/alerts_to_signal.py`, `triggers/cortex_pipeline.py`, `migrations/*.sql`, `start.sh`, `_register_jobs()` job set, the `> 720` heartbeat threshold.
- Render env var `POSTGRES_HOST_DIRECT` set via MCP merge mode ONLY (today's 80-var wipe at `memory/feedback_render_envvar_paginated_put.md`). NEVER raw PUT.

## Output

Standard PR + ship report at `briefs/_reports/B1_scheduler_singleton_harden_20260430.md` with §0 literal `pytest` stdout per Lesson #48 (NOT "by inspection").

## Test plan (Lesson #48 literal stdout required)

- `pytest tests/test_scheduler_singleton.py -v` — full output in §0
- `pytest tests/test_watchdog_cooldown.py -v` — full output in §0
- Post-deploy verification: SQL #1 from brief Verification SQL section — every job `distinct_anchors = 1` over a 15-min window

## Pass criteria

- All 8 Quality Checkpoints from brief satisfied
- Verification SQL #1: every job `distinct_anchors = 1` over 15-min window post-deploy
- Verification SQL #2: `pg_locks` shows exactly 1 row for `objid=8800100`
- No regression: `kbl_bridge_tick` consumer cadence unchanged, `cortex_pipeline.maybe_dispatch` still fires once per signal

## Mailbox hygiene (RATIFIED 2026-04-24 §3)

- On PR merge: overwrite this file with `COMPLETE` + PR URL + post-deploy verification

## Co-Authored-By

```
Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
