# Ship Report — BREACH_DETECT_PHASE1_1

- **Worker:** B3
- **Dispatched by:** lead (#4516) + addendum (#4518)
- **Design validation:** codex-arch #4497
- **Branch:** `b3/breach-detect-phase1-1`
- **PR:** #433 → main
- **Commit:** 9c5a55a (+ claim checkpoint c3da0b4)
- **Date:** 2026-06-28
- **Gate chain:** G2 self-review (done) → G3 codex independent → G4 lead `/security-review` (MANDATORY, Lesson #52) → lead merge

## What shipped
A single outermost FastAPI security middleware chokepoint + admin routes + daily prune:

1. **Read-audit log** — every request writes ONE metadata-only row to `security_access_log`.
2. **Anomaly tripwire → Slack alarm** — flags `bulk_read` / `repeated_auth_fail` / `new_ip_for_key` / `large_response`; fires a rate-limited alarm to `#cockpit`, bypassing `BAKER_BLOCK_EMAIL/WA_TO_DIRECTOR` (it's Slack).
3. **Global freeze switch** — `security_freeze` singleton; `POST /api/security/freeze` → instant 503, no redeploy; `BAKER_SECURITY_FREEZE=1` env backstop survives DB outage; `/health` + `/api/security/*` reachable while frozen.
4. **Retention prune** (addendum #4518) — daily `CronTrigger`, bounded batched DELETE, `BAKER_SECURITY_LOG_RETENTION_DAYS` (default 90).

## Files
| File | Change |
|---|---|
| `security/access_guard.py` | NEW — all logic (schema, freeze, record/evaluate, alarm, prune, middleware) |
| `security/__init__.py` | NEW — package marker |
| `outputs/dashboard.py` | thin `@app.middleware` wrapper after `scheduler_watchdog_middleware` (outermost) + 3 `/api/security/*` routes + startup `_ensure_security_tables()` |
| `triggers/embedded_scheduler.py` | daily prune `CronTrigger` job (`security_access_log_prune`) |
| `migrations/20260628_security_access_log.sql` | NEW — mirror DDL (Lesson #50) |
| `tests/test_security_access_guard.py` | NEW — 8 TDD cases (written first) |
| `tests/test_scheduler_liveness_sentinel.py` | add cron id to no-pair list |

## Done rubric (answered)
- **Task class:** security-sensitive hot-path middleware; additive — ships behind no flag, freeze defaults off, rollback = revert the commit.
- **TDD (brief hard gate):** 4 vertical cases written BEFORE implementation, all green:
  1. `BAKER_SECURITY_FREEZE=1` → protected 503; `/health` + `/api/security/*` 200.
  2. successful request → exactly one `security_access_log` row, metadata-only (asserted no body/secret columns + key_fp is a ≤16-char hash).
  3. 401 audited + per-key auth-fail counter increments.
  4. bulk read (N>threshold) → exactly ONE rate-limited Slack alarm.
  + alarm bypasses both Director block flags; + prune is bounded/batched/window-honoring.
- **Constraints:** metadata-only; freeze fails CLOSED (env) / audit fails OPEN; every SQL `LIMIT`-bounded; every except `rollback()`s; `verify_api_key`/`_mcp_verify_key`/CORS/`scheduler_watchdog_middleware` untouched; migration mirrors `ensure_security_schema`; `applied_migrations.lock` not edited.
- **Middleware ordering:** registered AFTER `scheduler_watchdog_middleware` → Starlette runs it outermost (freeze before any handler).
- **Render restart survival:** tables auto-create at startup (bootstrap + migration); freeze persists in DB; env backstop at boot.

## Literal test output
`pytest tests/test_security_access_guard.py tests/test_scheduler_liveness_sentinel.py tests/test_migrations.py -q` → **56 passed, 1 skipped** (live-PG round-trip auto-skips; no `TEST_DATABASE_URL`).
`pytest tests/test_security_access_guard.py -v` → **8 passed**.
Compile-clean: `security/access_guard.py`, `outputs/dashboard.py`, `triggers/embedded_scheduler.py`.

## Pre-existing issues found (NOT from this PR — fail-loud disclosure)
- `test_migration_runner.py::test_migration_file_has_up_marker` FAILS on 13 older migration files lacking up/down markers (all pre-date this work; my new migration HAS the marker, is not in the failing list).
- 5 test collection errors: `ModuleNotFoundError: No module named 'mcp'` — missing optional dep in local clones (`test_email_attachment_read`, `test_mcp_baker_extension_1`, `test_brisen_lab_consumer_mcp`, +2). Pre-existing, unrelated.

## Observation for lead (non-blocking)
Per the brief the middleware audits **every** request including `/health` (freeze-exempt only skips the freeze gate, not the audit) → health-check traffic generates audit rows + one INSERT/request on the hot path. Implemented as-specified. Flagging in case a Phase-1.1 wants to sample/skip health-check audit to cut Neon write amplification.

## Repo-state cleanup (noted)
On session start this clone was in a stale, abandoned interactive rebase (detached HEAD + conflict markers) replaying the already-merged m365 PR #430 commits. Aborted it (non-destructive; orig branch ref preserved), fast-forwarded main to origin @ 10e1e6e, branched clean. No impact on main.

## Post-deploy
Emit `POST_DEPLOY_AC_VERDICT v1` once live: live freeze probe (`POST /api/security/freeze` → protected GET 503, `/health` 200, `POST /api/security/unfreeze` → 200, no redeploy) + simulated leaked-key bulk read → one Slack alarm + `security_access_log` rows with 0 body columns.
