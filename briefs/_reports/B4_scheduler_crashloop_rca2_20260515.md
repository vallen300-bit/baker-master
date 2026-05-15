---
brief: briefs/BRIEF_SCHEDULER_CRASHLOOP_RCA_2.md
phase: B of 2 (scheduler-wa-kill-and-rca dispatch)
status: SHIPPED (RCA only — no code change in this brief)
ship_date: 2026-05-15
author: B4
dispatch_thread: 7649545b-def0-4055-b908-66a94e139057
proposed_followup_brief: BRIEF_SCHEDULER_WATCHDOG_FALSE_POSITIVE_FIX_1 (skeleton inline §6)
director_action_required: ratify proposed-fix scope before any patch dispatch
---

# B4 ship report — SCHEDULER_CRASHLOOP_RCA_2 (Phase B)

## 1. Root cause (single sentence)

**The scheduler is not actually dying.** High-frequency jobs (`kbl_bridge_tick` @ 60s, `kbl_pipeline_tick` @ 120s, `doc_pipeline_drain` @ 120s) fire continuously with sub-second drift; what is dying is the `scheduler_heartbeat` job specifically, which falsely signals "scheduler dead" to the middleware watchdog, triggering a self-reinforcing ~12-min `restart_scheduler()` loop that churns the singleton lock without fixing anything.

**Evidence anchor:** `scheduler_executions` 3h gap distribution — kbl_bridge_tick p90 = 78s (n=168), kbl_pipeline_tick p90 = 135s (n=80), but scheduler_heartbeat p90 = 746s, max = 767s, 8/22 firings >720s (§4).

## 2. Evidence table — 5 hypotheses

| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| 1 | `POSTGRES_HOST_DIRECT` unset → singleton lock disabled | **FALSIFIED** | `pg_locks` shows lock granted (objid=8800100, granted=TRUE, mode=ExclusiveLock, pid=18410); `pg_stat_activity` confirms a real backend session from `neondb_owner` is holding the lock. The "lock disabled" log line at `triggers/scheduler_lease.py:54-60` is NOT being hit. (§3.1) |
| 2 | Held singleton-lock connection dies (Neon auto-suspend / network drop) | **INCONCLUSIVE** | The in-job probe at `triggers/embedded_scheduler.py:1380-1398` IS wired, but its observable side-effect (calling `restart_scheduler` → forcing a new connection) cannot be distinguished from the middleware-watchdog restart path in current telemetry. Backend connections rotate every ~12 min (oldest backend_start = 18:02:34Z, matches most recent heartbeat row), which is consistent with — but not exclusive to — this hypothesis. (§3.2) Requires Render-log inspection to confirm `"scheduler singleton-lock connection dead"` line cadence. |
| 3 | SIGTERM during Render deploy → orphan lock blocks new container | **FALSIFIED for steady-state** | Lock is currently granted to an alive backend session (pg_stat_activity confirms). No Render deploys in the last 6h would explain a recurring 12-min cycle. May apply at actual deploy boundaries but is not driving the steady-state loop. (§3.1) |
| 4 | APScheduler `BackgroundScheduler` thread death on unhandled job exception | **FALSIFIED** | `SELECT job_id, status, COUNT(*) FROM scheduler_executions WHERE fired_at > NOW() - INTERVAL '6 hours' GROUP BY job_id, status` returns ZERO `error` rows across 14 distinct job_ids and 977 total executions. If the scheduler thread were dying, ALL jobs would have gaps — but high-frequency jobs (kbl_bridge_tick n=334) fire continuously. (§3.3, §4) |
| 5 | Memory leak / OOM kill on Render | **FALSIFIED** | `baker_memory_log` 6h: peak RSS = 550 MB / 4 GB allocated (= 13.4%), avg = 470 MB, 0 critical/warning entries. Nowhere near the 3000/3400/3700 MB alert thresholds. (§3.4) |

**Net:** 1 inconclusive (H2), 4 falsified. Loop is driven by something the original 5 hypotheses do not cover — see §5.

## 3. Supporting queries (literal output)

### 3.1 Singleton lock + backend

```sql
SELECT classid, objid, granted, mode, pid, locktype
FROM pg_locks WHERE locktype='advisory' AND objid=8800100;
-- classid:0 objid:8800100 granted:True mode:ExclusiveLock pid:18410

SELECT pid, datname, usename, state, backend_start, query_start
FROM pg_stat_activity WHERE pid=18410;
-- pid:18410 datname:neondb usename:neondb_owner state:idle
-- backend_start: 2026-05-15 18:02:34.200199+00:00
-- query_start:   2026-05-15 18:07:34.340002+00:00   (most recent SELECT 1 probe — exact 5-min cadence)
```

The lock-holding connection's `backend_start` is **18:02:34Z** — identical to the most recent `scheduler_heartbeat` firing in `scheduler_executions`. Confirms the restart-cycle reopens the lock connection each time.

### 3.2 Connection rotation footprint

```sql
SELECT COUNT(DISTINCT pid), COUNT(DISTINCT client_addr), MIN(backend_start), MAX(backend_start)
FROM pg_stat_activity WHERE datname='neondb' AND backend_start > NOW() - INTERVAL '1 hour';
-- n_backends: 4   n_client_addrs: 3   oldest: 18:02:34Z   newest: 18:08:53Z
```

4 backends from 3 distinct client_addr values — consistent with one Render container + pooled connections through Neon's serverless routing layer. **No** evidence of multiple Render instances racing on the lock (would expect more distinct client_addrs over time).

### 3.3 Job error inventory

```sql
SELECT job_id, status, COUNT(*) FROM scheduler_executions
WHERE fired_at > NOW() - INTERVAL '6 hours'
GROUP BY job_id, status ORDER BY job_id;
```

14 distinct jobs, 977 total executions, **0 with status='error'**. All registered jobs (email_poll, kbl_bridge_tick, kbl_pipeline_tick, doc_pipeline_drain, scheduler_heartbeat, memory_watchdog, slack_poll, plaud_scan, fireflies_scan, calendar_prep, expire_browser_actions, tier_b_reservation_sweep, cortex_stuck_cycle_sentinel, evening_push_digest) report only `executed`.

### 3.4 Memory pressure

```sql
SELECT MAX(rss_mb), AVG(rss_mb)::int, COUNT(*) FILTER (WHERE note IS NOT NULL)
FROM baker_memory_log WHERE timestamp > NOW() - INTERVAL '6 hours';
-- peak_rss: 550   avg_rss: 470   critical_n: 0
```

### 3.5 Watchdog WA cross-reference (pre-Phase-A)

```sql
SELECT created_at, payload->>'text_preview' FROM baker_actions
WHERE action_type='whatsapp_send'
  AND payload->>'text_preview' LIKE 'Baker scheduler was dead%'
  AND created_at > NOW() - INTERVAL '6 hours'
ORDER BY created_at DESC;
```

24 WA sends over 6h pre-Phase-A. All but one report "12-15 minutes dead" (matching watchdog 720s + restart-detect drift). One outlier: "1440 minutes" at 15:32:21Z — a single resumption after a longer interruption (likely a deploy / cold start), not part of the steady-state loop. Every WA send aligns with a 720s+ `scheduler_heartbeat` gap. **No** WA sends fire without a corresponding heartbeat gap → cooldown logic is sound (would have falsified the Phase-A removal of the WA push only if the cooldown were misbehaving, which it is not).

## 4. The decisive evidence — gap distribution by job (3h window)

| job_id | interval | n fired | p50 gap | p90 gap | max gap | n over 720s |
|---|---|---|---|---|---|---|
| kbl_bridge_tick | 60s | 168 | 60s | 78s | 150s | **0** |
| doc_pipeline_drain | 120s | 74 | 120s | 168s | 270s | **0** |
| kbl_pipeline_tick | 120s | 80 | 120s | 135s | 270s | **0** |
| email_poll | 300s | 28 | 300s | 468s | 711s | **0** |
| slack_poll | 300s | 28 | 300s | 468s | 711s | **0** |
| scheduler_heartbeat | 300s | 22 | 455s | **746s** | **767s** | **8** |
| memory_watchdog | 300s | 21 | 441s | 770s | 1011s | 6 |
| expire_browser_actions | 300s | 10 | 655s | 1363s | 1521s | 4 |
| tier_b_reservation_sweep | 300s | 15 | 475s | 915s | 2595s | 5 |

**The signal:** every 60s and 120s job runs cleanly with sub-3x interval drift. Two 5-min jobs (`email_poll`, `slack_poll`) run cleanly. Four 5-min jobs — including `scheduler_heartbeat` — exhibit recurring >720s gaps. If the BackgroundScheduler thread were dying, **all** jobs would be affected proportionally. They are not.

## 5. New finding — the false-positive watchdog loop

The four delayed 5-min jobs (`scheduler_heartbeat`, `memory_watchdog`, `expire_browser_actions`, `tier_b_reservation_sweep`) share one trait the clean 5-min jobs do not: their bodies perform **multi-step DB writes** (CREATE TABLE IF NOT EXISTS + INSERT + DELETE on `baker_memory_log`; multi-statement `UPDATE alerts` on `expire_browser_actions`; `_scheduler_heartbeat` runs a SELECT-1 probe against the singleton-lock connection BEFORE writing the watermark — see `triggers/embedded_scheduler.py:1380-1402`). `email_poll` and `slack_poll` execute network calls outside the DB-pool path.

The smoking-gun mechanism in `_scheduler_heartbeat`:

1. Function entry → probe `_lease._held_conn` with `SELECT 1` (line 1386).
2. If the probe blocks (Neon serverless cold-start latency or transient network), the watermark write at line 1401 is **delayed**.
3. The watchdog middleware at `outputs/dashboard.py` reads the watermark via `trigger_state.get_watermark("scheduler_heartbeat")` and computes `age_seconds`. If probe blocks >720s OR if a single heartbeat misses (misfire_grace_time=300, interval=300 → ≤1 fire fits in the grace window) and the next fire is delayed, `age_seconds > 720` → **`restart_scheduler()` fires**.
4. `restart_scheduler()` calls `_scheduler.shutdown(wait=True)` → `release_singleton_lock()` → `start_scheduler()` → new psycopg2.connect → new pid acquires lock. **This is what the `backend_start` rotation shows in §3.1.**
5. Heartbeat fires immediately on the new scheduler (`next_run_time=datetime.now(timezone.utc)` at line 634) → watermark fresh → cycle resets.
6. Within ~12 min, the same conditions recur (the underlying probe-blocks-watermark pathology was not fixed by the restart — the watchdog merely papered over it).

**Secondary footgun:** the same `_scheduler_heartbeat` function ALSO calls `restart_scheduler()` from inside its own body when the probe fails (line 1395). Calling `shutdown(wait=True)` from inside a job thread is reentrancy-hostile — `concurrent.futures.ThreadPoolExecutor.shutdown(wait=True)` joins worker threads, and a thread cannot join itself. This means there are **two restart call sites** (middleware + in-job), and at least one of them is dangerous.

## 6. Proposed fix — BRIEF_SCHEDULER_WATCHDOG_FALSE_POSITIVE_FIX_1 (skeleton)

**Goal:** stop the 12-min false-restart loop. Make the heartbeat watermark a reliable proof-of-life independent of probe latency.

**Scope (~1h, single-file behaviour-narrow):**

1. **`triggers/embedded_scheduler.py:1372-1403`** — refactor `_scheduler_heartbeat`:
   - **Write the watermark FIRST** (before any network IO).
   - **Remove the in-job `restart_scheduler()` call** at line 1395. The middleware watchdog is the sole restarter; one path, one footgun-free implementation.
   - If a lock-connection liveness probe is still wanted, move it to a separate job at a different cadence (e.g., `_scheduler_lock_probe` every 60s, asynchronous to watermark write).

2. **Optional `outputs/dashboard.py:185-209`** — make the watchdog robust against transient watermark blips: require TWO consecutive stale reads (60s apart) before calling `restart_scheduler()`. With the current 60s middleware tick, that's a 720s+60s effective threshold and eliminates single-blip false positives.

3. **`outputs/dashboard.py`** — add an `age_seconds` telemetry write (per heartbeat check) so we can see the distribution of observed staleness and confirm the fix works post-deploy.

**Trigger class:** LOW (single-file behaviour-narrow, no auth, no DB schema, no external surface).

**Ship gate (proposed for the fix brief):**
- pytest `tests/test_watchdog_cooldown.py` green.
- New test: `test_heartbeat_writes_watermark_before_probe` (mock probe to block, assert watermark already written when probe is called).
- New test: `test_in_job_restart_path_removed` (assert `_scheduler_heartbeat` never calls `restart_scheduler` even when probe raises).
- Post-deploy 24h: `scheduler_heartbeat` gap distribution p90 < 500s (vs current 746s); 0 watchdog-WA sends if Phase A's log-warning path keeps the same throttle; the lock-holding backend's `backend_start` stays >1h old (vs current ~12 min rotation).

**Risk:**
- If heartbeat writes watermark before discovering the lock-connection is dead, we lose the early-warning probe. **Mitigation:** the separate `_scheduler_lock_probe` job at 60s cadence runs the same `SELECT 1` against `_lease._held_conn`; on failure it logs `WARN` (no auto-restart — singleton-lock recovery should be handled at next deploy or explicitly).
- Rollback is trivial: revert the single file.

**Verification plan:**
- 24h after deploy, re-run §4 gap-distribution query. Pass = scheduler_heartbeat p90 < 500s AND `n over 720s = 0`.
- 24h pg_stat_activity check: `oldest backend_start` for the lock-holder should exceed 1h (no churn).
- 0 `Baker scheduler was dead%` log-warning lines in Render logs (Phase A's replacement target).

## 7. What is still INCONCLUSIVE / blocked

- **Hypothesis 2 (Neon auto-suspend on the held connection).** The in-job probe path (lines 1380-1398) IS wired and IS firing periodically, but I cannot distinguish "probe-triggered restart" from "middleware-triggered restart" in current telemetry. Both produce the same `backend_start` rotation. **Resolution:** Render-log inspection for `"scheduler singleton-lock connection dead"` log line cadence vs `"SCHEDULER-WATCHDOG-1: Heartbeat stale"` cadence. B4 cannot read Render logs from this picker — needs AH2/AH1 to run `mcp__render__list_logs` (if wired) or pull from the Render dashboard, OR a one-line telemetry add to differentiate the two paths.
- **Step 1 of brief (Render env var check).** No Render MCP tool surfaced in this picker. Hypothesis 1 was falsified via DB evidence (lock is held — implies env var is set), so this step is closed by inference, not by direct env-var read.

## 8. Recommendation

**Proceed with BRIEF_SCHEDULER_WATCHDOG_FALSE_POSITIVE_FIX_1 (§6) immediately.** Why:
- 4 of 5 original hypotheses are falsified; H2 (held-conn dies) is at most a *secondary* contributor — the *primary* loop is the probe-before-watermark + dual restart-call-site design footgun (§5), which the §6 fix addresses directly.
- The fix is single-file, low-risk, reversible.
- Even if H2 is also live, the §6 fix neutralizes its contribution to the false-positive watchdog loop (watermark is fresh regardless of probe outcome).

Director ratification needed on the fix scope before any patch dispatches (per brief §Ship gate). AH2 / AH1 to dispatch BRIEF_SCHEDULER_WATCHDOG_FALSE_POSITIVE_FIX_1 to a B-code after ratification.

## Files modified

- `briefs/_reports/B4_scheduler_crashloop_rca2_20260515.md` (NEW)
- No production code touched (per brief §Trigger class).

## Co-Authored-By

```
Co-authored-by: Code Brisen #4 <b4@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
