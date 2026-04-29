# BRIEF — CORTEX_ARCHIVE_FAILURE_ALERTING_1

**Author:** AI Head A (sole orchestrator)
**Builder:** AI Head B (aihead2 lane)
**Drafted:** 2026-04-29T~06:00Z
**Director authorization:** "recom is accepted, proceed" (2026-04-29 morning, dispatch ratified to aihead2)
**Promotion gate:** OPEN — Cortex V1 shipped 2026-04-28; first real $4 cycle on AO matter completed 2026-04-29 (`cycle_id=7dc3201b`); cost gate live; Slack interactivity merged (PR #81 `df886be`).
**Trigger class:** MEDIUM (DB sentinel + Slack writes; no auth surface, no Gold writes — A solo /security-review, no B-code review required).

## Anchor

Parked idea: `_ops/ideas/2026-04-28-cortex-archive-failure-alerting.md` (in baker-vault).
Three fold-ins from prior B1 reviews already accumulated in the parked idea — all included in scope below.

## Goal

Stop silent Cortex pipeline failures. Two failure modes today:
1. **Stuck cycles** — `cortex_cycles` row held in transient status (`in_flight`, `awaiting_reason`, `reasoning`, `proposed`, `approving`, `editing`, `refreshing`, `rejecting`) past a staleness threshold with no terminal phase output written.
2. **Self-archive failure** — Phase 6 archive code itself fails (line 189 of `orchestrator/cortex_runner.py` swallows the exception with f-string log; no terminal state is written; row is durably orphaned).

Today both fail silently. After this brief: Slack alert per occurrence + structured logs queryable by `cycle_id` / `phase` / `error_class`.

## Defaults (Director-ratified at dispatch — flag if you disagree)

| Param | Default | Reason |
|---|---|---|
| Sentinel cron | every 5 min | per parked idea §Future scope #3 |
| Stuck-status threshold | 15 min since `started_at` | per parked idea §Future scope #1 |
| Stuck-status enumeration | `in_flight`, `awaiting_reason`, `reasoning`, `proposed`, `approving`, `editing`, `refreshing`, `rejecting` | parked idea §Future scope + 2026-04-28 PR #75 fold-in |
| New status | `archive_failed` | parked idea §Future scope #2 |
| Slack target | Director DM (mirror existing Cortex DM pattern) | ops channel doesn't exist yet — defer dedicated channel until V2 |
| Alert dedup | one alert per cycle_id × failure-mode (idempotent insert into `baker_actions` with `target_task_id=cycle_id`, `action_type='cortex_alert_<mode>'`) | mirrors gate dedup pattern (PR #80) |
| Brief `extra` schema | `{cycle_id, phase, error_class, matter_slug}` | parked idea 2026-04-28T07:55Z fold-in |

## Scope (3 work units)

### 1. Structured logging refactor (parked idea 2026-04-28T07:55Z fold-in)

Convert f-string `logger.error(f"...{cycle_id}...")` to structured `logger.error("...", extra={...})` in:

- `orchestrator/cortex_runner.py:189` — Phase 6 archive-itself-failed log
- `orchestrator/cortex_runner.py` — every `logger.error` call in `_phase6_archive` (line 398+) and Phase 3 cycle-status update paths
- Any other `logger.error(f"...")` you find in the cortex_runner Phase 1/2/3/6 paths during the audit

Schema for `extra`: `{"cycle_id": str, "phase": str, "error_class": str, "matter_slug": str}`. `error_class` = `type(e).__name__`.

### 2. NEW `triggers/cortex_stuck_cycle_sentinel.py`

Pattern after `triggers/audit_sentinel.py` and `triggers/ai_head_audit.py`. Two detectors per run:

**Detector A — stuck transient status:**
```sql
SELECT cycle_id, matter_slug, status, started_at, current_phase
FROM cortex_cycles
WHERE status IN ('in_flight','awaiting_reason','reasoning','proposed',
                 'approving','editing','refreshing','rejecting')
  AND started_at < now() - interval '15 minutes'
  AND cycle_id NOT IN (
      SELECT target_task_id::uuid FROM baker_actions
      WHERE action_type = 'cortex_alert_stuck' AND target_task_id IS NOT NULL
  );
```

**Detector B — archive-failed status:**
```sql
SELECT cycle_id, matter_slug, status, started_at, current_phase
FROM cortex_cycles
WHERE status = 'archive_failed'
  AND cycle_id NOT IN (
      SELECT target_task_id::uuid FROM baker_actions
      WHERE action_type = 'cortex_alert_archive_failed' AND target_task_id IS NOT NULL
  );
```

For each row: post Slack DM to Director with cycle_id + matter_slug + status + last successful phase + age; insert dedup row into `baker_actions` (canonical try/rollback/raise pattern per PR #80 gate precedent).

### 3. Wire `archive_failed` status (cortex_runner.py:189 path)

When `_phase6_archive` itself raises, set `cortex_cycles.status='archive_failed'` and persist before re-swallowing. Today the row keeps stale prior status. After this change, Detector B above can find it.

```python
# orchestrator/cortex_runner.py around line 187
try:
    await _phase6_archive(cycle)
except Exception as e:
    logger.error(
        "Phase 6 archive itself failed",
        extra={"cycle_id": str(cycle.cycle_id), "phase": "archive",
               "error_class": type(e).__name__, "matter_slug": cycle.matter_slug},
    )
    # NEW: persist archive_failed terminal state (best-effort; if THIS write also fails,
    # the stuck-status sentinel is the safety net)
    try:
        await _set_cycle_status(cycle.cycle_id, 'archive_failed')
    except Exception:
        pass  # Detector A catches via stuck-status (if status was transient at entry)
```

### 4. Scheduler registration

Add to `triggers/embedded_scheduler.py`:
```python
scheduler.add_job(
    run_cortex_stuck_cycle_sentinel,
    trigger="interval", minutes=5,
    id="cortex_stuck_cycle_sentinel",
    max_instances=1, coalesce=True,
)
```

## Files modified

- NEW `triggers/cortex_stuck_cycle_sentinel.py` (~150 LOC)
- MOD `orchestrator/cortex_runner.py` (structured-extra logging + `archive_failed` status persist; ~15 line touches)
- MOD `triggers/embedded_scheduler.py` (+8 LOC scheduler.add_job block)
- NEW `tests/test_cortex_stuck_cycle_sentinel.py` (~250 LOC, 6 tests minimum)

## Files NOT touched

- `orchestrator/cortex_phase5_act.py` (handlers stay)
- `triggers/slack_interactivity.py` (just merged, leave alone)
- `triggers/slack_events.py`
- All KBL / Stage 2 / Wiki paths

## Test plan (Lesson #47 — literal stdout required)

1. `pytest tests/test_cortex_stuck_cycle_sentinel.py -v` — all 6+ PASS literal
2. `pytest tests/test_cortex_runner_phase126.py tests/test_cortex_phase5_act.py tests/test_cortex_pre_review_gate.py` — regression PASS literal (these are the cortex paths most likely to be touched indirectly by structured-extra refactor)
3. `python3 -c "import py_compile; py_compile.compile('triggers/cortex_stuck_cycle_sentinel.py', doraise=True)"` — clean
4. `python3 -c "import py_compile; py_compile.compile('orchestrator/cortex_runner.py', doraise=True)"` — clean
5. `python3 -c "import py_compile; py_compile.compile('triggers/embedded_scheduler.py', doraise=True)"` — clean

Test scenarios required:
1. happy path no-stuck — empty result set, no Slack post
2. one stuck cycle in `proposed` past 15min — alert posted, baker_actions dedup row written
3. two stuck cycles — two alerts, two dedup rows
4. already-alerted cycle — NO duplicate alert (dedup honored)
5. one `archive_failed` cycle — alert posted with action_type='cortex_alert_archive_failed'
6. mixed: one stuck + one archive_failed + one already-alerted — exactly 2 alerts

## STOP criteria

- Any test fails or any "by inspection" claim (Lesson #47, #50)
- Sentinel posts duplicate alerts on second run for same cycle
- `archive_failed` status persist itself raises and aborts cycle pipeline
- Files outside the 4-file scope modified
- New status `archive_failed` not added to any enum/CHECK constraint that exists

## Quality checkpoints

| # | Checkpoint | Status (B fills) |
|---|---|---|
| 1 | py_compile clean on all 3 modified files | |
| 2 | 6+ unit tests PASS literally | |
| 3 | Regression cortex_runner + phase5_act + gate PASS literally | |
| 4 | Sentinel scheduled with `max_instances=1, coalesce=True` (matches gold_audit_sentinel pattern) | |
| 5 | Dedup uses canonical try/rollback/raise per PR #80 gate precedent | |
| 6 | Structured `extra` schema consistent across all converted log sites | |
| 7 | No log line includes proposal text / matter context / payload body | |
| 8 | `archive_failed` status-persist is best-effort (won't worsen existing failure) | |

## Post-merge — A executes

1. `/security-review` (Lesson #52 mandatory pre-merge — A solo, MEDIUM trigger class so no B-code review required per RA-24)
2. Squash-merge → Render redeploy
3. Verify `cortex_stuck_cycle_sentinel` registered in scheduler logs (`grep cortex_stuck_cycle_sentinel /var/log/render-stdout.log` or equivalent)
4. Smoke: query `SELECT cycle_id FROM cortex_cycles WHERE status='archive_failed' OR (status IN (...) AND started_at < now() - interval '15 minutes')` — confirm sentinel run picks them up on next 5-min tick
5. If first 24h sees zero alerts on a healthy system → expected. Park follow-up: re-validate at 7 days that the sentinel HAS fired at least once on a synthetic test (manual `UPDATE cortex_cycles SET status='archive_failed' WHERE cycle_id='<test>'`).

## Output

`briefs/_reports/AIHEAD_B_cortex_archive_failure_alerting_20260429.md` — same shape as B-code ship reports:
- §0 literal stdout for all test commands
- §1 what shipped + file list
- §2 ship-gate verification table
- §3 quality checkpoints filled
- §4 deviations from brief (if any)
- §5 PR URL

## Co-Authored-By

```
Co-authored-by: AI Head B <aihead-b@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
