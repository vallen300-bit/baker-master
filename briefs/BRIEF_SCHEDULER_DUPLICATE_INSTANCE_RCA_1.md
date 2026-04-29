# BRIEF — SCHEDULER_DUPLICATE_INSTANCE_RCA_1

**Author:** AI Head A (sole orchestrator)
**Builder:** B1 (read-only RCA + small surgical fix expected)
**Drafted:** 2026-04-29T~11:35Z
**Director authorization:** "Park for tomorrow brief" (2026-04-29 ~11:30Z, post-flood diagnosis)
**Trigger class:** LOW (read-only investigation; any code fix surfaces back as a separate brief if material)

## Problem

`kbl_bridge_tick` is firing 2× per minute consistently:

| Window | Expected fires | Actual fires |
|---|---|---|
| 30 min | 30 | 59 |
| 3 min (post clear-cache deploy 11:11Z) | 3 | 6 |

The two fires are at a **stable 1.34s offset** every minute, e.g.:
- 11:17:24.329508 + 11:17:25.669745
- 11:18:24.329508 + 11:18:25.669745
- 11:19:24.329508 + 11:19:25.669745

Stable repeating pattern → two independent scheduler instances each running the same job on their own clocks, NOT a single scheduler with `max_instances=2`.

## Today's incident chain (context)

This bug surfaced from Director's "I'm flooded by Baker messages" report at 11:08Z. Investigation showed:
- Director's Baker DM has 108 unread mentions, every message back to Apr 22 duplicated 3-5×
- Real-time check at 11:30Z: 0 new signal_queue / cortex_cycles / baker_actions in last 10 min — the active flooding has stopped, but the bug remains
- The pre-V1 deploy chain today triggered repeated worker spawns; orphan workers may have been the historical 3-5× duplicate source
- Clear-cache redeploy `dep-d7ouelhn839s738joutg` at 11:11Z did NOT fix the post-deploy 2× firing — confirms it's not just stale workers

## What's been ruled out

| Hypothesis | Verdict | Evidence |
|---|---|---|
| Multiple Render instances (`numInstances`) | RULED OUT | Render API returns `numInstances=1`, `plan=pro` |
| Multiple uvicorn workers | RULED OUT | `start.sh` is `exec uvicorn outputs.dashboard:app --host 0.0.0.0 --port $PORT` — no `--workers` flag, default 1 |
| Watchdog auto-restart loop creating zombie scheduler | UNLIKELY | scheduler_heartbeat watermark at 4.5min age — well within 12min stale threshold; no `SCHEDULER-WATCHDOG-1` log lines in last 25 min |
| `restart_scheduler()` with `shutdown(wait=False)` leaking threads | POSSIBLE | If watchdog fired at startup against a stale watermark from prior deploy, restart_scheduler would `_scheduler.shutdown(wait=False)` then null + start. Old scheduler's APScheduler thread MAY continue firing pending jobs. But scheduler_heartbeat is fresh now → unclear if this happened earlier |
| Direct double-registration in `_register_jobs()` | RULED OUT | grep confirms only ONE `add_job` for `kbl_bridge_tick` in `triggers/embedded_scheduler.py:679` |
| `BlockingScheduler` from `triggers/scheduler.py` running in parallel | RULED OUT | `SentinelScheduler` only imported by itself; no other module instantiates it |
| `replace_existing=True` not preventing duplicate | RULED OUT | The kwarg works at single-scheduler-instance level; doesn't prevent two scheduler INSTANCES |
| FastAPI lifespan-vs-startup double-call | UNTESTED | Worth grepping for both `@app.on_event("startup")` and lifespan context manager — if both registered, startup runs twice |
| Render Pro plan hidden HA replica | UNTESTED | Render Pro tier MAY run a passive HA replica that doesn't show in `numInstances` API field. Worth confirming via Render support / docs |
| External cron / GitHub Actions / sidecar firing the bridge directly | UNTESTED | grep for any HTTP endpoint that triggers bridge_tick + check Render dashboard for any scheduled jobs / cron services |

## Why ONLY kbl_bridge_tick

If two full scheduler instances were running, ALL jobs would 2×. But fire counts in 30 min:
- kbl_bridge_tick: 59 (2×)
- kbl_pipeline_tick: 30 (1×)
- doc_pipeline_drain: 29 (~1×)
- vault_sync_tick: 12 (matches 2.5min interval, 1×)

So the 2× is bridge-specific. This **disproves the "two complete schedulers" hypothesis** and points at:
1. A second registration of `kbl_bridge_tick` specifically (somewhere we didn't grep)
2. The bridge tick function being called from BOTH the scheduler AND another path (e.g., a route handler, a sentinel that internally triggers bridge_tick, etc.)
3. A retry-on-error pattern in `_kbl_bridge_tick_job` itself that re-fires once

## Investigation goals

1. **Find the second source.** Walk every code path that can invoke `_kbl_bridge_tick_job` or `run_kbl_bridge` or anything that writes to `signal_queue` from alerts. Specifically check:
   - All HTTP routes in `outputs/dashboard.py` that accept "trigger bridge" calls
   - Any sentinel / poller that internally calls bridge as a subroutine
   - Any post-init / startup hook that fires bridge once on boot AND ALSO registers it on scheduler
   - Test fixtures or `if __name__ == "__main__"` paths that could leak
   - The bridge's own retry/exception-handling logic (does it re-call itself on error?)
2. **Confirm scheduler topology.** Add a debug endpoint or log line that dumps `_scheduler.get_jobs()` with their next-fire timestamps and the underlying `id(_scheduler)` Python object id. If two object ids appear, we have two `BackgroundScheduler` instances live in the same process.
3. **If two scheduler instances confirmed:** trace the second instance's creation site. Stack-trace logging at `BackgroundScheduler.__init__` would identify the offending caller.

## Hard scope (NO production code changes in THIS brief)

- B1's deliverable is an RCA REPORT identifying the root cause + a proposed fix.
- IF the fix is a one-liner (e.g. duplicate `add_job` in some forgotten module), B1 may include it as a small commit on the same branch.
- IF the fix requires more than 20 LOC OR touches scheduler lifecycle / lifespan / watchdog: STOP, surface the RCA report alone, and AI Head A drafts a follow-up brief.

## Files allowed to read (no quota)

- All of `triggers/`, `outputs/dashboard.py`, `kbl/`, `memory/store_back.py`
- `start.sh`, `requirements.txt`, anything in repo root
- Render API: `GET /v1/services/{id}/env-vars?limit=100`, `GET /v1/services/{id}` for service config
- Render logs API: search for "BackgroundScheduler started", "Sentinel scheduler started", "Registered: kbl_bridge_tick", "SCHEDULER-WATCHDOG-1", "scheduler.add_job" — count occurrences in any 30-min window

## Files allowed to modify (only if RCA finds a one-liner)

- `triggers/embedded_scheduler.py` (max 5 LOC delta)
- `outputs/dashboard.py` (max 5 LOC delta in scheduler-related setup only)

## Files NOT to touch

- All Cortex code (`orchestrator/cortex_*`, `triggers/slack_interactivity.py`, `triggers/cortex_stuck_cycle_sentinel.py`, all phase handlers)
- Any KBL pipeline code
- Any migration files

## Test plan (Lesson #47 literal stdout)

- IF B1's fix is code: re-run `pytest tests/test_embedded_scheduler*.py -v` (or whatever exists) — must PASS literally
- IF B1's fix is config-only (env var): no code-test needed; smoke via Render scheduler_executions table query showing 1× firing in 5-min window post-deploy

## Pass criteria

**For RCA-only (no fix):**
- Report identifies the second source with file:line evidence
- Report explains why ONLY kbl_bridge_tick is affected
- Report includes proposed fix with LOC estimate

**For RCA + small fix:**
- All above + the fix lands in the same branch
- Post-deploy verification: `kbl_bridge_tick` fires 1× per minute for 5 consecutive min in `scheduler_executions`
- No regression in other scheduler jobs

## STOP criteria

- The investigation surfaces ANY code path that requires changes to scheduler lifecycle, watchdog, or FastAPI lifespan handling — STOP, surface RCA report alone, A drafts follow-up brief.
- The investigation surfaces an issue that touches Cortex / Slack interactivity / Phase 5 handlers — STOP, surface alone, A handles separately.
- The fix is non-obvious or requires architectural change — STOP, RCA-only.

## Output

`briefs/_reports/B1_scheduler_duplicate_instance_rca_20260430.md` — same shape as PR review reports:
- §0: literal commands run + key outputs
- §1: ruled-out hypotheses (with evidence)
- §2: confirmed root cause (with file:line citations)
- §3: proposed fix (LOC count, scope)
- §4: IF fix shipped — PR URL + post-deploy verification
- §5: IF fix NOT shipped — recommended next-brief scope

## Why this is a brief, not a hot-fix

- Active flooding has stopped (zero Slack-bound activity in last 5+ min as of 11:30Z)
- Bridge writes go to signal_queue, not Slack — no immediate Director impact
- Real signal-queue inflow is rare (2 signals in 30 min) → duplicate fires on EMPTY input is harmless
- Worth understanding before patching — lessons today (env-var wipe, pool poisoning) prove that "fix fast without diagnosis" is more expensive than "diagnose first"

## Co-Authored-By

```
Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
