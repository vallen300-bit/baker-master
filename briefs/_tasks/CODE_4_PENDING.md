---
status: PENDING
brief: briefs/BRIEF_SCHEDULER_WATCHDOG_FALSE_POSITIVE_FIX_1.md
trigger_class: LOW (single-file behaviour-narrow, no auth/DB/external surface)
dispatched_at: 2026-05-15T18:35:00Z
dispatched_by: ai-head-2 (AH2)
target: b4
prior_brief_complete: |
  SCHEDULER_WATCHDOG_WA_KILL_1 (Phase A — PR #206 merged 15:57Z, ship report
  3f38d02) + SCHEDULER_CRASHLOOP_RCA_2 (Phase B — RCA ship report b50a424).
  This dispatch implements the §6 proposed fix from the RCA.
director_ratification: |
  Director 2026-05-15 ~18:30Z (in-chat to AH2): "Ratified." — in response to
  AH2's recommendation to dispatch the WhatsApp-filter brief + the scheduler
  false-positive fix brief. Director's anchor framing: "Anything about the
  scheduler watchdog? It's so much noise." — proceeding with both fixes.
priority: P1 (internal reliability; not user-visible after Phase A merged)
phase: 1 of 1
expected_pr_count: 1
expected_branch: b4/scheduler-watchdog-false-positive-fix-1
expected_complexity: low (~1h: reorder _scheduler_heartbeat, remove in-job
                      restart, add 2-consecutive-stale gate to middleware,
                      5 tests across 2 test files)
mandatory_2nd_pass: FALSE (LOW trigger class)
hard_ship_gate: |
  1. `python3 -c "import py_compile; py_compile.compile('triggers/embedded_scheduler.py', doraise=True)"` clean.
  2. `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` clean.
  3. `pytest tests/test_scheduler_heartbeat_order.py tests/test_watchdog_cooldown.py -v` literal green in ship report.
  4. AH2 cross-lane review + /security-review clean.
  5. Post-deploy 24h verification: run brief §"Post-deploy verification" query, paste in ship report addendum.
     Pass criteria: scheduler_heartbeat p90 gap < 500s, n_over_720s = 0,
     pg_stat_activity oldest backend_start for lock-holder > 1h, 0
     WATCHDOG_RESTART log lines in Render logs.
ship_report_to: |
  Bus-post `deputy` on PR open + ship.
---

# CODE_4_PENDING — Scheduler watchdog false-positive fix — 2026-05-15

**Dispatched by:** AH2 (deputy) under Director directive 2026-05-15 ~18:30Z
**Working dir:** `~/bm-b4`
**Branch:** `b4/scheduler-watchdog-false-positive-fix-1` off `main`

Pre-flight:
1. `git pull --ff-only origin main` in `~/bm-b4`.
2. Read `briefs/BRIEF_SCHEDULER_WATCHDOG_FALSE_POSITIVE_FIX_1.md` end-to-end.
3. (You already have full context — this is the implementation of your own §6 RCA proposal.)

---

## Scope

**Fix 1 (mandatory):** `triggers/embedded_scheduler.py:1372-1403` — reorder `_scheduler_heartbeat` so the watermark write happens FIRST, before the singleton-lock probe. Remove the in-job `restart_scheduler()` call on probe failure (reentrancy-hostile + duplicates the middleware path). Probe stays as a diagnostic-only WARN log.

**Fix 2 (recommended, ship in same PR):** `outputs/dashboard.py:165-209` — add a 2-consecutive-stale gate in the middleware watchdog so a single transient watermark blip doesn't trigger an unnecessary restart. Reset counter on fresh-read OR on restart.

Both fixes shipped together as one PR per the brief.

## Background context (read before starting)

- Your own RCA at `briefs/_reports/B4_scheduler_crashloop_rca2_20260515.md` §5 identified the mechanism: watermark write was sequenced AFTER a synchronous probe → probe blocking caused watermark write to be delayed → middleware watchdog read stale → restart fired. Cycle every ~12 min.
- §6 of the RCA proposed exactly this fix. Director ratified the scope tonight.
- H2 (Neon auto-suspend on held conn) is still INCONCLUSIVE — but this fix neutralizes H2's contribution to the false-positive loop regardless. If H2 is still live post-deploy, the probe WARN log will surface it without false restarts.

## Reporting

- Bus-post `deputy` on PR open + ship.
- 24h post-deploy verification query in ship report addendum (per hard ship gate item 5).

## Co-Authored-By

```
Co-authored-by: Code Brisen #4 <b4@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
