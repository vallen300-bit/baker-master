# B1 — RCA: SCHEDULER_DUPLICATE_INSTANCE_RCA_1

**Builder:** B1 (`~/bm-b1`)
**Brief:** `briefs/BRIEF_SCHEDULER_DUPLICATE_INSTANCE_RCA_1.md`
**Drafted:** 2026-04-29T~12:15Z
**Ship:** RCA-only — fix surfaces as follow-up brief per STOP criteria (touches scheduler lifecycle / Render config — out-of-scope for this brief).

---

## §0 — Literal commands run + key outputs

### Code grep (canonical sources of `kbl_bridge_tick`)
```
grep -n "kbl_bridge_tick\|run_bridge_tick\|_kbl_bridge_tick_job" --include="*.py" -r
```
Hits in production code: TWO. Both in `triggers/embedded_scheduler.py`:
- Line **679** — single `scheduler.add_job(..., id="kbl_bridge_tick", replace_existing=True, ...)`
- Line **914** — `_kbl_bridge_tick_job` definition (the wrapper)

`outputs/dashboard.py` has zero references. No HTTP route invokes the bridge. No retry/self-recursion in `kbl/bridge/alerts_to_signal.py:run_bridge_tick`. **The brief's "second registration somewhere we didn't grep" hypothesis is RULED OUT.**

### `scheduler_executions` aggregate (last 8 min, all jobs)
```sql
SELECT job_id, COUNT(*) AS n,
       ARRAY_AGG(DISTINCT (EXTRACT(EPOCH FROM fired_at)::numeric % 60)::text)
FROM scheduler_executions
WHERE fired_at > NOW() - INTERVAL '8 minutes'
GROUP BY job_id;
```

| job_id | fires/8min | sub-second anchors |
|---|---|---|
| kbl_bridge_tick | 16 | `:09.375246`, `:11.044640` |
| doc_pipeline_drain | 8 | `:09.345554`, `:11.039290` |
| kbl_pipeline_tick | 7 | `:09.375056`, `:11.044482` |
| scheduler_heartbeat | 4 | `:09.374644`, `:11.044180` |
| memory_watchdog | 4 | `:09.374853`, `:11.044326` |
| expire_browser_actions | 4 | `:09.374484`, `:11.044009` |
| slack_poll | 4 | `:09.279887`, `:11.026642` |
| vault_sync_tick | 4 | `:09.380836`, `:11.047006` |
| cortex_stuck_cycle_sentinel | 4 | `:09.380116`, `:11.046216` |
| email_poll | 4 | `:09.245529`, `:11.020079` |
| clickup_poll | 2 | `:39.257631`, `:41.022053` |

**Every job has TWO anchors, ~1.67s apart, mirrored across the entire job set.**

### History — when did duplication start?
```sql
WITH per_min AS (SELECT DATE_TRUNC('minute', fired_at) AS m, COUNT(*) AS n
                 FROM scheduler_executions WHERE job_id='kbl_bridge_tick' GROUP BY 1)
SELECT MIN(m) FROM per_min WHERE n >= 2;
-- 2026-04-23 06:42:00+00:00
```
Duplicate firing has existed since the **first row** of `scheduler_executions` (table created with PR #48, 2026-04-23). 6+ days. Not a new regression — pre-existing condition that nobody had instrumentation for until the audit table landed.

### Hourly counts last 6 hours (sanity)
| hour UTC | bridge (60s) | pipeline (120s) | heartbeat (300s) |
|---|---|---|---|
| 06 | 96 | 48 | 17 |
| 07 | 121 | 59 | 32 |
| 08 | 121 | 60 | 25 |
| 09 | 93 | 49 | 24 |
| 10 | 126 | 58 | 30 |
| 11 | 123 | 60 | 29 |

Expected (1 scheduler): bridge 60/h, pipeline 30/h, heartbeat 12/h.
Observed (~2 schedulers): bridge ~120/h ✓, pipeline ~60/h ✓, heartbeat ~24/h ✓ (clickup/email also ~2× expected).

---

## §1 — Hypotheses RULED OUT

| # | Hypothesis (brief §"What's been ruled out" + new) | Verdict | Evidence |
|---|---|---|---|
| H1 | Multiple Render `numInstances` | Per brief: confirmed via Render API | (Brief author already verified) |
| H2 | Multiple uvicorn `--workers` | Per brief: `start.sh` has no flag | `start.sh` line 4 — single uvicorn, no workers arg |
| H3 | Direct double-`add_job` | RULED OUT | grep — only one `add_job(..., id="kbl_bridge_tick")` at `triggers/embedded_scheduler.py:679` |
| H4 | `BlockingScheduler` from `triggers/scheduler.py` parallel | RULED OUT | That class doesn't even register `kbl_bridge_tick` (its `_register_jobs` only adds email/fireflies/clickup/dropbox/todoist/daily_briefing). Module-level `__main__` only |
| H5 | HTTP route fires bridge | RULED OUT | grep `outputs/` — zero callers of `run_bridge_tick`/`_kbl_bridge_tick_job` |
| H6 | Sentinel-internal sub-call | RULED OUT | `cortex_pipeline.py` is a *consumer* of bridge (post-commit dispatch hook), not a caller of `run_bridge_tick` |
| H7 | `_kbl_bridge_tick_job` self-retry on error | RULED OUT | Wrapper at `triggers/embedded_scheduler.py:914-927` catches+raises; no manual retry. APScheduler's `misfire_grace_time=30` only matters for missed fires, not duplicates |
| H8 | Listener registered twice → double DB write | RULED OUT | If a single fire wrote two rows, both rows would have *identical* `event.scheduled_run_time`. Observed rows have *different* `fired_at` (1.67s apart) — these are two real, separate scheduler firings |
| H9 | `replace_existing=True` not deduping inside one scheduler | RULED OUT | Two job entries with same `id="kbl_bridge_tick"` cannot coexist in the same `BackgroundScheduler` (APScheduler enforces unique id) |
| H10 | Brief's "ONLY kbl_bridge_tick is duplicated" framing | **RULED OUT** | The brief was misled by counting fires-per-minute and comparing to interval. Bridge (60s interval × 2 schedulers = 2/min — visibly suspicious) flagged it; pipeline (120s × 2 = 1/min) and heartbeat (300s × 2 = 0.4/min) hit *expected* rates if you assume one scheduler. Aggregating by *anchor microseconds* shows every job has two anchors — see §0 table |

---

## §2 — Confirmed root cause

**Two `BackgroundScheduler` instances are running concurrently in the same Render deployment, each registering the full `_register_jobs()` set.**

Evidence (necessary + sufficient):

1. **Every job — without exception — has exactly two distinct sub-second `fired_at` anchors** in `scheduler_executions`, persistently, for 6+ days. (§0 table.)
2. **The two anchors are offset by a stable ~1.67s** across all 11 currently-active jobs. A constant offset across the entire job set is the signature of two `_register_jobs(scheduler)` calls executed ~1.67s apart, *not* of duplicate registrations within a single scheduler.
3. **Anchors re-set on every observable restart event** (e.g., 11:30Z `:24/:25` → 11:39Z `:50/:52` → 12:00Z `:09/:11`). After each restart the offset stays ~1.34–1.67s. Two starts always happen, in lockstep, ~1.67s apart.
4. **Duplication is not from PR #48 / `_job_listener` instrumentation**: row data shows two genuinely-different `event.scheduled_run_time` values per minute (not identical timestamps written twice).
5. **Single-process leak hypothesis is implausible**: a thread leaked from `restart_scheduler()` (`shutdown(wait=False)` then `_scheduler = None`) would yield arbitrary offsets, not a stable ~1.67s gap, and the leak would compound after each watchdog event (3+ schedulers after 2 events). Observed: always exactly 2 anchors, never 3+.

**Most-likely upstream cause (not in scope to confirm without Render dashboard access):**

> **Two Render container instances are serving traffic** — either a Pro-plan zero-downtime "preboot" replica that didn't get torn down, an autoscale floor of 2, or a manually-set replica count that doesn't surface in the brief author's `GET /v1/services/{id}` `numInstances` field. The 1.67s offset matches the time between two parallel uvicorn boots reaching `_start_scheduler()` — both go through `_init_store → _run_migrations → _ensure_vault_mirror → _start_scheduler`, with `_ensure_vault_mirror`'s git pull being the natural source of inter-process variance.

Both replicas connect to the same Neon DB and the same Qdrant. Both run the full scheduler. Both write to `scheduler_executions`. The bridge's `pg_try_advisory_xact_lock` (`kbl/bridge/alerts_to_signal.py:622`) protects against double-INSERT into `signal_queue` — that's why active flooding has stopped — but every job that is *not* lock-guarded (heartbeat, watchdog, `email_poll`, `clickup_poll`, `vault_sync_tick`, `gold_audit_sentinel`, `ai_head_weekly_audit`, etc.) is firing 2×.

**Why "ONLY kbl_bridge_tick" looked broken:** the brief computed expected fires from each job's interval and a single-scheduler assumption. Bridge at 60s is the only job whose 2× rate exceeds 1/min, making it visually obvious. All other jobs ARE doubled — but at intervals (120s, 300s) where 2× still equals or under-runs "1/min" intuition. **Other observability is required to see the doubling on slower jobs.** The audit-sentinel `EVENT_JOB_EXECUTED` rows surface it cleanly when grouped by anchor.

**Cross-matter side-effects worth flagging (not the reported flooding, but real):**
- `email_poll` runs 2× → 2 Gmail API calls / cycle, doubled rate-limit pressure
- `clickup_poll` runs 2× → 2 ClickUp API calls / cycle (every 5 min)
- `gold_audit_sentinel` (Mon 09:30 UTC) will fire 2× — AI Head B's planned watch may see racing inserts
- `ai_head_weekly_audit` (Mon 09:00 UTC) will fire 2× — duplicate audit row writes
- `daily_briefing` would fire 2×
- `cortex_stuck_cycle_sentinel` 2× — likely ok (idempotent), but doubled DB load
- All Cortex auto-trigger pathways (Phase 3a meta-reasoning) execute on TWO containers in parallel — the bridge advisory lock prevents sibling double-INSERT into `signal_queue`, but `cortex_pipeline.maybe_dispatch` does NOT have an equivalent lock

---

## §3 — Proposed fix (LOC count, scope)

### Two-step remediation, neither shippable inside this brief's authority:

**Step A — Confirm instance count (Director, ~5 min):**
1. Open Render dashboard for service `15_Baker_Master`.
2. Service settings → Instance count + autoscale settings + zero-downtime / preboot config.
3. If the dashboard shows ≥2 instances (or autoscale floor ≥2 or `preboot=true`): **scale to 1 / disable preboot**. Restart deploy. Re-query `scheduler_executions` — anchors should collapse to 1.
4. Also worth: `GET /v1/services/{id}/instances` (if the API exposes it — `numInstances` in the *service config* shows desired, but the *active replica list* might be a separate endpoint).

**Step B — Defense-in-depth, follow-up brief (out of scope here):**
1. **Process-level singleton lock at `start_scheduler()`** — write a PG advisory lock keyed by `service_id` + `process_role='scheduler'`, held for the lifetime of the process. Second instance sees the lock and skips `_register_jobs`/start, runs as web-only. ~30 LOC.
2. **Fix `restart_scheduler()` thread leak** (`triggers/embedded_scheduler.py:1237-1248`) — change `shutdown(wait=False)` to `wait=True` with a 5s soft cap, or guard against null-ref + restart by checking `_scheduler.running` before nulling. ~5 LOC. Defensive — not the current root cause but worth fixing because once Step A lands, any future watchdog event would re-create the doubling.
3. **Add per-fire `pid` + `id(scheduler)` columns to `scheduler_executions`** — makes future incidents a 1-query diagnosis. ~10 LOC migration + 3 LOC listener change. Out of scope for current brief but should land before Cortex Stage 2 V1's first AO-matter cycle (which will fire 2× until Step A clears).

**LOC if Step B were to ship together: ~50.** That is well over the brief's "20 LOC" hard scope cap. STOP triggered.

---

## §4 — Fix shipped? **NO.**

Per brief's STOP criteria:
> "The investigation surfaces ANY code path that requires changes to scheduler lifecycle, watchdog, or FastAPI lifespan handling — STOP, surface RCA report alone, A drafts follow-up brief."

The remediation requires (a) a Render-config change Director must make from the dashboard, OR (b) scheduler-lifecycle code (singleton lock + `wait=False` fix). Both are out-of-scope. Surfacing this report alone.

No commit on this branch. No PR opened.

---

## §5 — Recommended next-brief scope

**Title suggestion:** `SCHEDULER_SINGLETON_HARDEN_1`

**Pre-work (Director, before brief is written):**
- Confirm Render service replica count + preboot/autoscale config.
- If 2 instances: scale to 1, redeploy, observe `scheduler_executions` for 30 min — duplicate should disappear.
- If still 2 anchors after scale-to-1: it's a single-process leak (most likely `restart_scheduler` ↔ stale-watermark race at boot). Then we are in scenario "B" not "A".

**Brief contents (whichever scenario applies after pre-work):**

*Scenario A — Render had ≥2 active replicas:*
- Single-instance is the steady-state config. Add a Render deploy guard in `start.sh` that asserts replica count = 1 (e.g., echo `RENDER_INSTANCE_ID` and crash on mismatch via env-var pattern), so a future autoscale event surfaces loudly.
- Backfill `scheduler_executions` audit query into `gold_audit_sentinel` weekly Mon 09:30 watch — flag if any job's anchor count > 1 in past 24h.

*Scenario B — single process, leaked thread:*
- Add PG advisory lock to `start_scheduler()` and exit second-call early.
- Fix `restart_scheduler()` to use `wait=True` + 5s timeout, then `_scheduler = None`.
- Fix `_check_scheduler_heartbeat()` to skip first-N-seconds-after-startup (current logic reads the *prior container's* watermark and may trigger a useless restart).
- Add a startup log line: `BackgroundScheduler started: pid=<X>, id=<Y>, jobs=<N>` so log-grep gives instant 1-vs-2 visibility.

*Both scenarios:*
- Add pid + scheduler object id columns to `scheduler_executions` (migration + 3-line listener change).

**Tests:**
- New `tests/test_scheduler_singleton.py` — boot two `start_scheduler()` calls in one process under PG-lock fixture, assert second returns early. (Live-PG marker so CI auto-skips when `TEST_DATABASE_URL` not set.)

**Pass criteria for the follow-up brief:**
- `SELECT job_id, COUNT(DISTINCT (fired_at::numeric % 60)) FROM scheduler_executions WHERE fired_at > NOW() - INTERVAL '15 minutes' GROUP BY 1` returns exactly **1** distinct anchor per job.
- No regression in `kbl_bridge_tick` consumer cadence (signal_queue keeps draining at the expected rate).

---

## §6 — Notes for AI Head A

1. **This is a stale bug, not today's regression.** Earliest evidence in `scheduler_executions` is 2026-04-23 06:42 — i.e., the table was created with the bug already present. The `gold_audit_sentinel` watch you scheduled for Mon 09:30 needs awareness: one of its two fires is a wasted run, and depending on internal dedupe may write two audit rows.
2. **The bridge advisory lock saved us today.** Without `pg_try_advisory_xact_lock` at `kbl/bridge/alerts_to_signal.py:622`, today's flood would have been 2× worse. Worth crediting in the next handover.
3. **Cortex Stage 2 V1 first AO-matter cycle.** Until this is fixed, Cortex auto-trigger via `cortex_pipeline.maybe_dispatch` runs on both replicas. Verify whether `cortex_pipeline.py` has equivalent lock-guarding before Director kicks the first live cycle.
4. **`_check_scheduler_heartbeat` cooldown bug** (separate small finding): `_watchdog_cooldown` is initialized to `300` (line 161) but the code at line 189 compares `age_seconds > _watchdog_cooldown` to gate the WhatsApp alert. Comparison reads "alert if dead longer than 5 min" — the variable name implies "don't re-alert within 5 min of a restart." Variable mis-used as threshold rather than rate-limit timestamp. Out of scope here; mention if you draft the follow-up.

---

## Co-Authored-By

```
Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
