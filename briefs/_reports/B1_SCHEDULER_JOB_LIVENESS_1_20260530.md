---
report: SCHEDULER_JOB_LIVENESS_1
from: b1
to: lead
pr: 273
pr_url: https://github.com/vallen300-bit/baker-master/pull/273
branch: b1/scheduler-job-liveness-1
commit: f966c05
shipped_at: 2026-05-30T15:15:00Z
brief_version: v2 (codex PASS-WITH-NITS bus #1401, all 3 nits folded)
brief_path: /Users/dimitry/bm-aihead1/briefs/BRIEF_SCHEDULER_JOB_LIVENESS_1.md
ship_topic: ship/scheduler-job-liveness-1
---

# B1 ship report — SCHEDULER_JOB_LIVENESS_1

PR: https://github.com/vallen300-bit/baker-master/pull/273

## Scope shipped

- `triggers/scheduler_liveness_sentinel.py` — new module, 200 LOC. Dynamic registry, process-local cold-start anchor + `reset_cold_start_anchor()`, MIN_STALENESS_SECONDS=600 floor, hourly-bucket source_id dedupe, T1/T2 tier mapping.
- `triggers/embedded_scheduler.py` — import `register_expected_job` + `check_scheduler_liveness` at top of `_register_jobs`; `register_expected_job(...)` call after every IntervalTrigger add_job (37 interval jobs total); new `scheduler_job_liveness` job at 10-min cadence inserted after `waha_session_poll`; `reset_cold_start_anchor()` call at top of `start_scheduler()`.
- `tests/test_scheduler_liveness_sentinel.py` — new, 14 base cases + 28 parametrized = 42 tests.

29 cron jobs cleanly skipped (V1 = interval only).

## All 7 codex pre-review findings folded

| # | Finding (round) | Where addressed |
|---|---|---|
| 1 | Wrong literal intervals (FAIL-LIGHT #1395) | Dynamic registry built at startup; embedded_scheduler passes live config/env-clamped values. |
| 2 | Cold-start global MIN bypassed grace (FAIL-LIGHT #1395) | Process-local `_MODULE_LOAD_TIME` at module import; no DB-based grace check. |
| 3 | Registry drift / env-gate skew (FAIL-LIGHT #1395) | Env-gated jobs only call `register_expected_job` inside their if-block, so the registry tracks actual registrations. |
| 4 | Dynamic-interval jobs hardcoded wrong (FAIL-LIGHT #1395) | `_kbl_tick_seconds` / `_bridge_tick_seconds` / `_reflector_minutes` / `_reconciler_minutes` passed live to `register_expected_job`. |
| 5 | Import location (NIT #1 #1401) | Both `check_scheduler_liveness` AND `register_expected_job` imported at top of `_register_jobs` (one-shot, in scope for all 37 add_job blocks). |
| 6 | Side-effect-safe pre-flight (NIT #2 #1401) | AST pairing check uses `ast.parse(pathlib.read_text(...))` — never imports or runs `_register_jobs` (vault_scanner Slack DM + mirror writes preserved). |
| 7 | In-process restart caveat (NIT #3 #1401) | `reset_cold_start_anchor()` exposed and called at top of `start_scheduler()`, restoring grace on `restart_scheduler()` path. |

## Quality checkpoints — literal output

### 1. Pytest (`python3.12 -m pytest tests/test_scheduler_liveness_sentinel.py -v`)

```
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b1
plugins: langsmith-0.7.38, anyio-4.12.1
collected 42 items

tests/test_scheduler_liveness_sentinel.py::test_01_cold_start_suppresses_checks PASSED [  2%]
tests/test_scheduler_liveness_sentinel.py::test_02_post_grace_empty_registry_noops PASSED [  4%]
tests/test_scheduler_liveness_sentinel.py::test_03_clean_path_all_fresh_no_alerts PASSED [  7%]
tests/test_scheduler_liveness_sentinel.py::test_04_single_stale_t1_emits_t1_alert PASSED [  9%]
tests/test_scheduler_liveness_sentinel.py::test_05_single_stale_t2_emits_t2_alert PASSED [ 11%]
tests/test_scheduler_liveness_sentinel.py::test_06_multiple_stale_jobs_emit_multiple_alerts PASSED [ 14%]
tests/test_scheduler_liveness_sentinel.py::test_07_never_fired_t1_emits_alert PASSED [ 16%]
tests/test_scheduler_liveness_sentinel.py::test_08_never_fired_t2_fails_open_no_alert PASSED [ 19%]
tests/test_scheduler_liveness_sentinel.py::test_09_db_unavailable_returns_reason_no_crash PASSED [ 21%]
tests/test_scheduler_liveness_sentinel.py::test_10_create_alert_raises_loop_continues PASSED [ 23%]
tests/test_scheduler_liveness_sentinel.py::test_11_hourly_bucket_source_id_stable PASSED [ 26%]
tests/test_scheduler_liveness_sentinel.py::test_12_no_cron_register_expected_job[clickup_poll] PASSED [ 28%]
... (27 more parametrized cron-invariant cases) ...
tests/test_scheduler_liveness_sentinel.py::test_13_dynamic_interval_env_override PASSED [ 97%]
tests/test_scheduler_liveness_sentinel.py::test_14_below_floor_clamp PASSED [100%]

============================== 42 passed in 0.18s ==============================
```

### 2. Compile-clean

```
$ python3 -c "import py_compile; py_compile.compile('triggers/scheduler_liveness_sentinel.py', doraise=True); py_compile.compile('triggers/embedded_scheduler.py', doraise=True)"
(no output - exit 0)
```

### 3. Singleton guard

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

### 4. AST pre-flight pairing check (side-effect-safe, NIT #2)

```
$ python3 - <<PY  # full script per brief Verification §
OK: 37 interval jobs paired, 29 cron jobs cleanly skipped
```

### 5. Registry-vs-scheduler diff

```
$ diff /tmp/_registered.txt /tmp/_expected.txt
(no output - empty diff)
```

Both files contain the same 37 IntervalTrigger ids. No intentional skips.

## EXPECTED_JOBS coverage (37 interval jobs)

T1 (silent miss = high impact):
- `email_poll`, `scheduler_heartbeat`, `health_watchdog`, `waha_silence_check`, `waha_session_poll`, `memory_watchdog`, `scheduler_job_liveness`

T2 (default, fail-open on never-fired):
- 30 remaining interval ids — `fireflies_scan`, `plaud_scan`, `dropbox_poll`, `dropbox_edita_poll`, `todoist_poll`, `rss_poll`, `slack_poll`, `browser_poll`, `whatsapp_resync`, `deadline_cadence`, `calendar_prep`, `alert_expiry`, `dismiss_past_travel`, `proactive_scan`, `stale_watermark_check`, `risk_detection`, `cadence_tracker`, `financial_detector`, `doc_pipeline_drain`, `action_completion_detector`, `sentiment_backfill`, `expire_browser_actions`, `kbl_pipeline_tick`, `kbl_bridge_tick`, `cortex_stuck_cycle_sentinel`, `phase6_reflector_sweep`, `phase6_reconciler`, `sentinel_quiet_thread`, `sentinel_dismiss_patterns`, `tier_b_reservation_sweep`.

## Post-deploy AC

1. **AC1** — within 12 min of merge: `SELECT MAX(fired_at) FROM scheduler_executions WHERE job_id='scheduler_job_liveness'` returns a row.
2. **AC2** — at merge + 30 min: no false-positive `source='scheduler_job_liveness'` alerts on healthy prod. Cold-start grace covers first 15 min; remainder should be clean.

## Anchor

- Brief: `briefs/BRIEF_SCHEDULER_JOB_LIVENESS_1.md` (final after v1 → FAIL-LIGHT #1395 → v2 → PASS-WITH-NITS #1401).
- Parent codex thread: review #1364 nit #2 on PR #271.
- Concrete failure: `waha_session_poll` silent 92 min on 2026-05-30 between Render deploys.
- Reply target: lead (per mailbox `from: lead` + `reply_to: lead`).
