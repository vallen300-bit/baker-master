---
brief_id: BREACH_DETECT_PHASE1_1
attempt: 1
branch: b3/breach-detect-phase1-1
pr: 433
status: DONE — PR #433 merged (squash d34ccef); post-deploy AC v1 all-4 PASS (bus #4545 lead / #4546 deputy). Arc closed; do NOT resume.
dispatched_by: lead
reply_target: lead (bus)
updated: 2026-06-28
---

# CHECKPOINT — BREACH_DETECT_PHASE1_1

## What's done
- Oriented; bus drained; dispatch #4516 acked.
- Cleaned a stale abandoned interactive rebase (m365 replay; already merged via PR #430) — tree clean, main @ 10e1e6e.
- Branch `b3/breach-detect-phase1-1` cut off main.
- Step 0 anti-shadow pre-check: CLEAN (no security_access_log / security_freeze / /api/security / BAKER_SECURITY_FREEZE / access_guard symbols). No `security/` dir.
- Read all reference code: cost_monitor (Slack alarm `_send_*_alert` :611/:639, claim `_claim_tier_alert` :530, bootstrap :96, conn pattern :258), dashboard (auth :188, mcp :1982, client-ip :204, app/cors :487/:546, scheduler middleware :620, startup :1866), migration runner (config/migration_runner.py — schema_migrations tracked, lock check only verifies LISTED files so a NEW migration not in lock is safe), migration format (-- == migrate:up/down ==).

## ADDENDUM (#4518 lead, acked) — retention prune
Add a daily retention prune so security_access_log stays flat:
- daily job: bounded BATCHED DELETE WHERE ts < NOW() - retention (ts indexed).
- window via env BAKER_SECURITY_LOG_RETENTION_DAYS (default 90).
- off the existing scheduler (NOT per-request).
Wiring: prune_access_log() in access_guard + CronTrigger daily job in
triggers/embedded_scheduler.py (id security_access_log_prune, NO register_expected_job
— CronTrigger jobs must not pair, liveness invariant). Add id to _CRON_JOB_IDS in
tests/test_scheduler_liveness_sentinel.py (file convention: new cron jobs need an entry).

## What's left
- TDD FIRST: tests/test_security_access_guard.py (4 vertical + alarm-bypass + prune) — DONE, red expected pre-impl.
- Implement security/access_guard.py (schema, is_frozen fail-closed+env backstop, record_access metadata-only, evaluate_tripwire, security_alarm_send rate-limited, security_guard_middleware coroutine, prune_access_log).
- Wire thin @app.middleware after dashboard.py:620 (outermost) + startup ensure_security_schema call + 3 /api/security/* routes.
- Wire CronTrigger prune job in embedded_scheduler.py + cron-id test entry.
- migrations/20260628_security_access_log.sql (mirror DDL, up/down).
- G2 self-review → G3 codex → G4 /security-review (lead) → merge. Emit POST_DEPLOY_AC_VERDICT v1.

## Key design decisions
- Middleware logic lives in access_guard.security_guard_middleware (testable on a minimal app); dashboard.py keeps only the thin @app.middleware("http") wrapper defined AFTER :620 so it stays outermost. Keeps dashboard lean + unit-testable without importing the 11.7k-line module.
- Metadata-only column set is a module constant ACCESS_LOG_COLUMNS; test asserts no body/secret/raw-key column.
- Alarm rate-limit: in-memory per-(key_fp,flag) window gate as the cheap hot-path primary; DB-claim mirror optional/fail-open. Over-alarming on a breach is acceptable; under-alarming is not.
- Do NOT touch verify_api_key / _mcp_verify_key / CORS / scheduler_watchdog_middleware.

## G3 rework log (#4531, codex #4530) — DONE @ 4bb554c
- F1-MED freeze-time audit gap: record_freeze_block() writes ONE metadata row (status 503, anomaly_flags=blocked_by_freeze) BEFORE the 503. Test asserts row written on frozen path.
- F2-MED Slack false "delivered": parse resp.json(), require ok is True; else fail-loud + return False. New ok=false test.
- tests now 9 passed.

## Exact next command
G3-rework pushed (4bb554c). Re-requested G3 from codex via lead (bus). Await G3 re-verdict → G4 lead /security-review → merge.
On further request_changes → NEW commit (never amend) → push → reply. On merge → emit POST_DEPLOY_AC_VERDICT v1.
