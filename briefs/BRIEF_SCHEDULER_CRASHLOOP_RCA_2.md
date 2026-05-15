# BRIEF: SCHEDULER_CRASHLOOP_RCA_2 — Root-cause why scheduler keeps dying post-singleton-harden

## Context

`BRIEF_SCHEDULER_SINGLETON_HARDEN_1` shipped (lease module, direct DSN, watchdog cooldown fix, singleton tests — all present in `main`). Yet on 2026-05-15 the scheduler is still crash-looping: ~5-9 watchdog auto-restarts/hour, 426 WA pushes in 3 days. Jobs ARE firing (heartbeat n=48 in 6h, kbl_bridge_tick n=336 in 6h), but heartbeat cadence shows ~24 missed firings vs spec — i.e. scheduler dies every ~12 min, watchdog restarts it, dies again.

Hypotheses to test:
1. `POSTGRES_HOST_DIRECT` not set on Render → singleton lock never acquired → scheduler-lease `_spawn_lock_retry_thread()` runs but `acquire_singleton_lock()` keeps returning None → no jobs registered → watchdog restarts → loops.
2. Lock IS acquired by one container but the held connection dies (Neon auto-suspend, network drop). Fix-4 liveness probe should catch this; verify it does.
3. SIGTERM during Render deploy isn't releasing the lock cleanly → orphan lock blocks new container.
4. APScheduler `BackgroundScheduler` thread dies on an unhandled exception in a job (e.g., `cortex_stuck_cycle_sentinel`, `kbl_pipeline_tick`) — heartbeat job stops with it.
5. Memory leak / OOM kill on Render container → systemd-equivalent restart cycle.

This brief is **RCA-only**, no code fix. B4 produces a ship report with verified root cause + proposed fix. Director ratifies fix scope before any patch dispatches.

## Estimated time: 1-2h
## Complexity: Medium (diagnosis, not implementation)
## Prerequisites: Read `BRIEF_SCHEDULER_SINGLETON_HARDEN_1.md` and `BRIEF_SCHEDULER_DUPLICATE_INSTANCE_RCA_1.md` for context

---

## Investigation steps

### Step 1 — Verify Render env var state

Use Render MCP (read-only) to confirm whether `POSTGRES_HOST_DIRECT` is set on the baker-master service. If unset, that is Hypothesis 1 confirmed: singleton lock perma-disabled → scheduler refuses to register jobs → watchdog restarts forever.

Expected if unset: server logs at startup contain `"POSTGRES_HOST_DIRECT unset — scheduler singleton lock disabled"` (see `triggers/scheduler_lease.py:150-157`).

### Step 2 — Inspect Render logs around watchdog firings

Pull last 2h of Render logs (`mcp__baker__baker_health` won't have this; use Render API or Render dashboard via Chrome MCP). Look for:

- `"scheduler singleton lock NOT acquired"` — Hypothesis 1
- `"scheduler singleton-lock connection dead"` — Hypothesis 2
- Tracebacks from inside `_register_jobs` / `_job_listener` — Hypothesis 4
- OOMKilled / SIGKILL — Hypothesis 5
- SIGTERM cluster around watchdog restarts — Hypothesis 3

### Step 3 — Query advisory lock state

```sql
SELECT classid, objid, granted, mode, pid, locktype
FROM pg_locks
WHERE locktype = 'advisory' AND objid = 8800100;
```

- 0 rows + scheduler claims running anywhere → Hypothesis 1 (no host_direct, lock never taken)
- 1 row + scheduler stopped on monitored container → Hypothesis 3 (orphan lock)
- 1 row + that pid belongs to a dead Render backend → Hypothesis 2 (Neon broke link, server-side already released, but local `_held_conn` stale; the brief's Fix 4 probe should have caught this — verify probe is firing)

### Step 4 — Heartbeat cadence forensics

```sql
SELECT fired_at, LAG(fired_at) OVER (ORDER BY fired_at) AS prev,
       EXTRACT(EPOCH FROM (fired_at - LAG(fired_at) OVER (ORDER BY fired_at))) AS gap_s
FROM scheduler_executions
WHERE job_id = 'scheduler_heartbeat' AND fired_at > NOW() - INTERVAL '6 hours'
ORDER BY fired_at DESC LIMIT 80;
```

Look at the gap distribution. Spec says one firing every 300s. Anything >720s explains a watchdog firing. Gap clusters around 720-900s = clean crash-then-restart pattern. Gap clusters around 1000-1500s = restart itself is slow / failing.

### Step 5 — Cross-reference watchdog WA sends to heartbeat gaps

```sql
SELECT created_at, payload->>'text_preview' AS msg
FROM baker_actions
WHERE action_type='whatsapp_send'
  AND payload->>'text_preview' LIKE 'Baker scheduler was dead%'
  AND created_at > NOW() - INTERVAL '6 hours'
ORDER BY created_at DESC;
```

Confirm each WA send aligns with a heartbeat gap. If WA sends fire without a heartbeat gap → cooldown logic itself is broken (regression from `BRIEF_SCHEDULER_SINGLETON_HARDEN_1` Fix 2). If WA sends consistently align with gaps → real crash loop, hypotheses 1-5 narrow to the matching log evidence.

### Step 6 — Identify the killer

Combine evidence from Steps 1-5 into a single root cause statement. Pin to one hypothesis. If evidence is ambiguous between two, name both and recommend the lower-cost-to-test path first.

---

## Deliverable — ship report

Write a ship report at `briefs/_reports/B4_scheduler_crashloop_rca2_<date>.md` containing:

1. **Root cause** — single sentence, citing the evidence Step (1-5) that confirms it.
2. **Evidence table** — for each of the 5 hypotheses: VERIFIED / FALSIFIED / INCONCLUSIVE with the SQL or log snippet that supports the verdict.
3. **Proposed fix** — concrete code change OR Render env-var update OR Neon config change, scoped tight. Estimate effort. Flag if it requires a follow-up brief (most likely yes — write the follow-up brief skeleton inline so AH2 / AH1 can dispatch immediately after Director ratification).
4. **Risk assessment** — what breaks if the proposed fix is wrong; what's the rollback.
5. **Verification plan** — how do we confirm the fix worked (e.g. "scheduler_heartbeat gap distribution stays <500s for 24h post-deploy; 0 watchdog auto-restarts in baker_actions for 24h").

## Ship gate

No code change in this brief. Ship gate = ship report committed to `briefs/_reports/`, AH2 review-pass marker, surfaced to Director with the proposed-fix scope question for ratification.

## Files Modified

- `briefs/_reports/B4_scheduler_crashloop_rca2_<date>.md` (NEW)
- No production code touched

## Do NOT Touch

- `outputs/dashboard.py` — Phase A (`WA_KILL_1`) handles this
- `triggers/embedded_scheduler.py` / `triggers/scheduler_lease.py` — diagnose only; patch lands in a follow-up brief
- Render env vars — read-only inspection in Step 1

## Trigger class

LOW (RCA, no code mutation). No `/security-review` required for the ship report itself; the follow-up fix brief will trigger normal review chain.

## Co-Authored-By

```
Co-authored-by: Code Brisen #4 <b4@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
