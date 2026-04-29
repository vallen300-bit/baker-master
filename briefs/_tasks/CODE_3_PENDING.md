# CODE_3 — DISPATCH (SITUATIONAL_REVIEW_PR84_SCHEDULER_SINGLETON)

**Status:** PENDING — assigned 2026-04-29T~17:50Z
**Type:** Situational review (second-pair-of-eyes; B1 is the builder)
**Builder:** B3
**Trigger class:** MEDIUM (touches FastAPI lifespan; brief-required pre-merge review)
**Dispatched by:** AI Head A (sole orchestrator)
**Director authorization:** scope ratified at brief acceptance ("Brief is unblocked. Hand that to AI Head 1 App." — 2026-04-29 ~17:00Z)

## Target

PR #84 — `b1/scheduler-singleton-harden-1` — commit `133a852`
URL: https://github.com/vallen300-bit/baker-master/pull/84
Brief: `briefs/BRIEF_SCHEDULER_SINGLETON_HARDEN_1.md`

## Why situational review

- B1 is solo author of the implementation. No second pair of eyes yet.
- Process-singleton primitives (PG advisory lock on dedicated Neon direct connection, lifespan timing, deploy-overlap handoff) are hard to test fully in CI — 3 of 4 critical tests live-PG-only.
- Lifespan-touching code; regression here = silent doubled side-effects across the entire scheduler (today's flooded-Slack-DM scenario).

## Scope of review

Read the diff in PR #84. Focus on the 6 modified files:

1. `triggers/scheduler_lease.py` (NEW, ~100 LOC) — held connection pattern, `_lock` thread-safety, `pg_try_advisory_lock` usage, `direct_dsn_params` requirement, error paths return None, autocommit on the held conn.
2. `triggers/embedded_scheduler.py` — `start_scheduler` integration, `_spawn_lock_retry_thread` daemon-ness + idempotency, `stop_scheduler`/`restart_scheduler` release ordering, `_scheduler_heartbeat` liveness probe doesn't fail heartbeat write on probe error.
3. `outputs/dashboard.py` — `_watchdog_last_alert_ts` module-level placement (not function-local), 5-min throttle math, no behavior change on `> 720` heartbeat threshold.
4. `config/settings.py` — `host_direct` field default empty string, `direct_dsn_params` falls back to pooled host (caller MUST detect — verify scheduler_lease detects).
5. `tests/test_scheduler_singleton.py` — live-PG marker, three tests cover acquire / cross-connection block / release-then-reacquire. Cleanup-on-each-test pattern.
6. `tests/test_watchdog_cooldown.py` — mocked-time pattern, asserts second alert within cooldown is suppressed.

## Specific concerns to verify

1. **Held connection MUST NOT enter any pool.** Grep: `_held_conn` should never appear in `_put_conn` / `pool.putconn` / `psycopg2.pool` paths.
2. **Direct DSN MUST be used for the lock.** Grep: `acquire_singleton_lock` uses `config.postgres.direct_dsn_params`, NOT `config.postgres.dsn_params`.
3. **`pg_try_advisory_lock` (session) — not `pg_try_advisory_xact_lock`.** Verify the SQL string is the session variant.
4. **`autocommit = True` on the held conn.** Required because the lock must persist across statement boundaries; Python psycopg2 default opens an implicit transaction that could complicate state.
5. **Lock-poll retry thread:** daemon=True (must), idempotent (no double-spawn), exit condition reachable (when lock acquired OR when scheduler started by another path).
6. **Failure modes log loud + degrade gracefully:** if `POSTGRES_HOST_DIRECT` unset → log error + return None + scheduler continues running without the lock (today's behavior, no regression).
7. **No new schema, no migration, no `slugs.yml` touch.**
8. **Heartbeat probe doesn't raise.** Probe failure → trigger restart, but heartbeat write itself MUST always run regardless.
9. **Lock-key collision check.** `SCHEDULER_LOCK_KEY = 8800100` — grep for any other use of this integer in `pg_try_advisory_*lock` callers (existing locks: 900100/900201/900300/900400/900500/900600/900700, 8004/8005, 867531/867532).
10. **Test cleanup:** every test in `test_scheduler_singleton.py` calls `release_singleton_lock()` first to clean state from prior runs (otherwise tests order-coupled).

## Output

Brief review report at `briefs/_reports/B3_pr84_situational_review_20260429.md`.

Required sections:
- §0 — verdict: APPROVE / REQUEST_CHANGES / NEEDS_DISCUSSION
- §1 — concerns confirmed clean (with line cites)
- §2 — concerns flagged (line cite + severity HIGH/MEDIUM/LOW + recommended fix)
- §3 — note any over-engineering / under-engineering / pattern drift from existing codebase

If §0 = APPROVE: post a GitHub PR review with body matching §0–§3 (use `gh pr review 84 --approve --body "$(cat report)"`).
If §0 = REQUEST_CHANGES: post review with `--request-changes`, AI Head A re-dispatches B1 with the fix list.

## Hard rails

- DO NOT rewrite or modify any code — review-only.
- DO NOT push, do not merge.
- DO NOT touch the PR branch.
- Review on origin's view of the PR; do NOT check out the branch locally (avoid contaminating B3's worktree state).

## Mailbox hygiene

- On report-only: overwrite this file with `COMPLETE` + report path + verdict.

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
