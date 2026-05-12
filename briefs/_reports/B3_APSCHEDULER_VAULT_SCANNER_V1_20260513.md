---
type: report
brief: BRIEF_APSCHEDULER_VAULT_SCANNER_V1
builder: b3
shipped_at: 2026-05-13
pr: https://github.com/vallen300-bit/baker-master/pull/197
vault_commit: 97e99ad (baker-vault main)
branch: b3/apscheduler-vault-scanner-1
status: SHIPPED — pending review (mandatory 2nd-pass + /security-review)
---

# B3 — Ship report — APSCHEDULER_VAULT_SCANNER_V1

## What shipped

**baker-master PR #197** — `feat(scheduler): vault scanner + consolidated Slack DM (APSCHEDULER_VAULT_SCANNER_V1)` — commit `d2c7735` on `b3/apscheduler-vault-scanner-1`:

1. `triggers/vault_scanner.py` (NEW, ~520 lines) — daily scan logic.
2. `tests/test_vault_scanner.py` (NEW, ~270 lines) — 10 literal pytest tests.
3. `triggers/embedded_scheduler.py` (MOD) — register `vault_scanner_daily` + startup catch-up + `_vault_scanner_job()` wrapper.

**baker-vault `97e99ad`** — `vault(registry): add vault_scanner_daily entry (APSCHEDULER_VAULT_SCANNER_V1)` — populates `_ops/processes/schedule-registry.yml` per brief §Part 4 (first entry; v1 placeholder retired).

## Ship gate (literal output)

```
$ /opt/homebrew/bin/python3.12 -m pytest tests/test_vault_scanner.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b3
plugins: langsmith-0.7.38, anyio-4.12.1
collecting ... collected 10 items

tests/test_vault_scanner.py::test_1_empty_vault PASSED                   [ 10%]
tests/test_vault_scanner.py::test_2_mohg_task_writes_today_and_sends_dm PASSED [ 20%]
tests/test_vault_scanner.py::test_3_malformed_frontmatter_skipped PASSED [ 30%]
tests/test_vault_scanner.py::test_4_overdue_critical_triggers_urgent_dm PASSED [ 40%]
tests/test_vault_scanner.py::test_5_rate_cap_blocks_second_consolidated_dm PASSED [ 50%]
tests/test_vault_scanner.py::test_6_marker_file_and_prune PASSED         [ 60%]
tests/test_vault_scanner.py::test_7_idempotent_double_call PASSED        [ 70%]
tests/test_vault_scanner.py::test_8_db_unavailable_degrades_gracefully PASSED [ 80%]
tests/test_vault_scanner.py::test_path_traversal_symlinked_desk_rejected PASSED [ 90%]
tests/test_vault_scanner.py::test_path_traversal_dotdot_desk_rejected PASSED [100%]

============================== 10 passed in 0.05s ==============================
```

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

All 8 brief-required tests PASS. 2 extra path-traversal cases added for `/security-review` coverage.

## Brief acceptance criteria → status

| Criterion | Status |
|---|---|
| Cron 06:00 UTC daily | ✅ `CronTrigger(hour=6, minute=0, timezone="UTC")` |
| Idempotent startup catch-up | ✅ `startup_catchup()` + marker file gate |
| Per-desk `today-YYYY-MM-DD.md` | ✅ atomic write via tmp+replace |
| Per-desk stable `today.md` | ✅ copy of dated file |
| Per-desk `upcoming-deadlines.md` | ✅ always regenerated |
| ONE consolidated Slack DM | ✅ `post_to_channel(D0AFY28N030, ...)` |
| Urgent per-desk DM on critical overdue / is_critical | ✅ separate rate cap per desk |
| Rate cap (1 consolidated/day + 1 urgent/desk/day) | ✅ marker files |
| Singleton-replica execution | ✅ inherits `scheduler_lease` lock |
| Path-traversal hardening | ✅ regex + no-symlink + parent-resolve |
| LIMIT 500 on deadline query | ✅ explicit `LIMIT %s` param |
| DB unavailable → degrades, doesn't crash | ✅ test 8 covers |
| Malformed frontmatter → warn + skip | ✅ test 3 covers |
| Marker file + 7d prune | ✅ test 6 covers |
| `VAULT_SCANNER_ENABLED` env gate | ✅ default true |
| `scripts/check_singletons.sh` pass | ✅ |
| Literal pytest output in PR body | ✅ |

## /security-review surface (per brief)

- **External:** Slack DM via existing `outputs.slack_notifier.post_to_channel`. Channel = Director DM `D0AFY28N030`. No new endpoint.
- **Scheduler primitives:** new `vault_scanner_daily` job; new startup catch-up branch; new per-day marker-file rate cap.
- **FS writes:** vault paths `_ops/agents/<desk>/today-*.md`, `today.md`, `upcoming-deadlines.md`, `_ops/agents/_scanner-state/*.marker`. All atomic (tmp + `os.replace`).
- **DB read:** parameterized `SELECT … WHERE assigned_to = %s … LIMIT %s` (no string formatting); `try/except` + `rollback`; failure returns `[]`.
- **Path-traversal:** `desk` name must match `^[a-z0-9-]+$` AND `Path.is_symlink() == False` AND `resolve().parent == agents_dir.resolve()` before any path join. Rejected entries are logged and skipped.

## Coordination notes

- **Brief 1 dependency (b2 / VAULT_TASKS_SCHEMA_V1):** scanner reads `_ops/agents/<desk>/tasks/active/*.md`; if Brief 1 hasn't merged when this PR lands, AH1 should set `VAULT_SCANNER_ENABLED=false` on Render until Brief 1 is in. Default-on at deploy.
- **Brief 3 dependency (b4 / HARD_DEADLINE_AUDIT_V1):** independent. Scanner sees zero deadlines on first run if Brief 3 hasn't landed; degrades cleanly.

## Out of scope (deferred to v2 per brief)

- DataView-rendered today files (plugin-free v1)
- Per-task `recurrence` field handling
- Backfilling closed tasks into separate history
- Cortex Backlog migration from ClickUp
- AID / B-code per-desk DM routing
- WhatsApp fallback (Slack-only v1)
- YAML registry ↔ APScheduler runtime reconciliation

## Bus-post

Per brief §Bus-post on ship + B3 orientation §Communication. Bus key not in local keychain in this session — paste-block for relay:

```
TO: lead
FROM: b3
RE: ship/APSCHEDULER_VAULT_SCANNER_V1

SHIP: APSCHEDULER_VAULT_SCANNER_V1 — PR #197 open + vault commit 97e99ad.
Daily 06:00 UTC scanner. Per-desk today / today-dated / upcoming-deadlines.md mirror files.
ONE consolidated Slack DM to Director + per-desk urgent DM on critical-only.
Ship gate: 10/10 tests PASS (8 brief + 2 path-traversal); singleton guard PASS.
Mandatory 2nd-pass + /security-review pending.
Coordination: gate behind VAULT_SCANNER_ENABLED=false if PR #197 lands before b2's VAULT_TASKS_SCHEMA_V1.
```
