# Code Brisen #1 — Pending Task

**From:** AI Head (Team 1 — Meta/Persistence)
**To:** Code Brisen #1
**Task posted:** 2026-04-23
**Status:** OPEN — `AUDIT_SENTINEL_1` (first-fire observability for `ai_head_weekly_audit`)

**Supersedes:** prior `CHANDA_ENFORCEMENT_1` task — shipped as PR #45, merged `3b60b0d` 2026-04-23 05:04 UTC. Mailbox cleared.

---

## Brief-route note (charter §6A)

Full `/write-brief` 6-step protocol. Brief at `briefs/BRIEF_AUDIT_SENTINEL_1.md`.

**Hard ship deadline: Sun 2026-04-26 23:59 UTC** (24h margin before Mon 09:00 UTC first fire of `ai_head_weekly_audit`).

Director + Research Agent ratified Phase 1 scope (Part-G Q1-Q5) in `_ops/ideas/2026-04-23-first-fire-observability.md`. Phase 2 (generalized decorator across 12+ jobs) deferred post-Cortex-3T M0.

---

## Context (TL;DR)

`ai_head_weekly_audit` first-fires Mon 2026-04-27 09:00 UTC. Today APScheduler has no external observability — silent miss = silent loss of AI Head drift detection. This brief adds:

1. `scheduler_executions` PG table + DDL bootstrap in `memory/store_back.py` (template = `_ensure_ai_head_audits_table`)
2. Extend existing `_job_listener` in `triggers/embedded_scheduler.py:23-31` to INSERT execution rows (ADD-ONLY, fault-tolerant)
3. New weekly cron `ai_head_audit_sentinel` Mon 10:00 UTC — SELECTs both `ai_head_audits` + `scheduler_executions`; either missing → Slack DM to `D0AFY28N030`
4. Dedupe via self-write `status='alerted'` row — no double-alerting per 24h window
5. Env gate `AI_HEAD_AUDIT_SENTINEL_ENABLED` (default true)

## Action

Read `briefs/BRIEF_AUDIT_SENTINEL_1.md` end-to-end. Implementation blocks under each Fix/Feature 1-3 are copy-pasteable. All function signatures verified against current code:

- `_ensure_ai_head_audits_table` template at `memory/store_back.py:502-539`
- `__init__` wiring at `memory/store_back.py:148`
- `_job_listener(event)` at `triggers/embedded_scheduler.py:23-31`
- Listener wire at `triggers/embedded_scheduler.py:951`
- `_ai_head_weekly_audit_job` wrapper pattern at `triggers/embedded_scheduler.py:733-751`
- `ai_head_weekly_audit` registration pattern at `triggers/embedded_scheduler.py:632-644`
- `post_to_channel(channel_id: str, text: str) -> bool` at `outputs/slack_notifier.py:111`
- **Singleton rule (PR #46):** `SentinelStoreBack._get_global_instance()`, NOT direct. Pre-push hook `scripts/check_singletons.sh` will enforce.

## Ship gate (literal output required in ship report)

```
python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('triggers/embedded_scheduler.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('triggers/audit_sentinel.py', doraise=True)"
bash scripts/check_singletons.sh
pytest tests/test_audit_sentinel.py -v     # expect 6 passed
pytest tests/ 2>&1 | tail -3               # expect +6 passes, 0 regressions
```

**No "pass by inspection"** (per `feedback_no_ship_by_inspection.md`). Paste literal pytest output.

## Ship shape

- **PR title:** `AUDIT_SENTINEL_1: first-fire observability for ai_head_weekly_audit`
- **Branch:** `audit-sentinel-1`
- **Files:** 2 modified (`memory/store_back.py`, `triggers/embedded_scheduler.py`) + 2 new (`triggers/audit_sentinel.py`, `tests/test_audit_sentinel.py`)
- **Commit style:** one clean squash-ready commit. Example: `audit-sentinel: scheduler_executions table + listener extension + Mon 10:00 UTC sentinel cron`
- **Ship report:** `briefs/_reports/B1_audit_sentinel_1_20260423.md`. Include:
  - All 4 py_compile outputs (empty expected)
  - `check_singletons.sh` output (PASS)
  - Literal `pytest tests/test_audit_sentinel.py -v` (6 passed)
  - Literal `pytest tests/ 2>&1 | tail -3` on main vs branch (delta = +6 passes, 0 regressions)
  - Quote the 1-line `__init__` diff proving `_ensure_scheduler_executions_table()` is wired

**Tier A auto-merge on B3 APPROVE** (standing per charter §3).

## Out of scope (explicit)

- **Do NOT** generalize the listener to wrap every cron job. Phase 2 brief — separate.
- **Do NOT** touch `outputs/slack_notifier.py` — use `post_to_channel` as-is.
- **Do NOT** touch `triggers/ai_head_audit.py` — PR #46 hotfix stays.
- **Do NOT** add a 90-day retention cleanup job — Phase 2 brief.
- **Do NOT** add EVENT_JOB_SUBMITTED listener — Phase 1 uses only EXECUTED+ERROR.

## Timebox

**1.5–2h.** If >3h, stop and report — something's wrong.

**Working dir:** `~/bm-b1`.

---

**Dispatch timestamp:** 2026-04-23 (Team 1, M0-infra parallel track — CORTEX-3T M0 quintet briefs to follow after this lands)
**Team:** Team 1 — Meta/Persistence
**Deadline:** 2026-04-26T23:59:00Z (HARD — first-fire is Mon 2026-04-27 09:00 UTC)
