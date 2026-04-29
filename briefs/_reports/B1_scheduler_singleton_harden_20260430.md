# B1 — Ship report: SCHEDULER_SINGLETON_HARDEN_1

**Builder:** B1 (`~/bm-b1`)
**Brief:** `briefs/BRIEF_SCHEDULER_SINGLETON_HARDEN_1.md`
**Mailbox:** `briefs/_tasks/CODE_1_PENDING.md` (will flip COMPLETE on PR merge)
**Branch:** `b1/scheduler-singleton-harden-1`
**Trigger class:** MEDIUM — touches FastAPI lifespan via `start_scheduler` / `stop_scheduler`. AI Head A or B situational-review pre-merge required.

---

## §0 — Test stdout (literal, Lesson #48)

Run command (Python 3.12 venv with full `requirements.txt` installed):

```
python -m pytest tests/test_watchdog_cooldown.py tests/test_scheduler_singleton.py -v
```

Output (warnings filtered for brevity, raw counts preserved):

```
============================= test session starts ==============================
tests/test_watchdog_cooldown.py::test_watchdog_alert_throttled PASSED    [ 14%]
tests/test_watchdog_cooldown.py::test_watchdog_alert_fires_again_after_cooldown PASSED [ 28%]
tests/test_watchdog_cooldown.py::test_watchdog_no_alert_when_heartbeat_fresh PASSED [ 42%]
tests/test_scheduler_singleton.py::test_first_acquire_succeeds SKIPPED   [ 57%]
tests/test_scheduler_singleton.py::test_second_acquire_from_separate_connection_blocks SKIPPED [ 71%]
tests/test_scheduler_singleton.py::test_release_then_reacquire SKIPPED   [ 85%]
tests/test_scheduler_singleton.py::test_acquire_returns_none_when_host_direct_unset PASSED [100%]
=================== 4 passed, 3 skipped, 5 warnings in 0.73s ===================
```

**Pass count:** 4 unit (3 watchdog + 1 singleton-gating). **Skip count:** 3 — live-PG tests skipped because neither `TEST_DATABASE_URL` nor `NEON_API_KEY+NEON_PROJECT_ID` is set on this workstation (per repo `tests/conftest.py::needs_live_pg` convention). CI auto-provisions an ephemeral Neon branch and runs the 3 skipped tests.

Adjacent-suite smoke (verifying no regression in nearby code):
```
python -m pytest tests/test_audit_sentinel.py tests/test_bridge_alerts_to_signal.py -v
... (output truncated — all PASSED) ...
============================== 44 passed in 0.46s ==============================
```

CI singleton-pattern guard:
```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

---

## §1 — Files changed

| File | Δ | Purpose |
|---|---|---|
| `config/settings.py` | +23 | `host_direct` field + `direct_dsn_params` property on `PostgresConfig` |
| `triggers/scheduler_lease.py` | +118 NEW | Process-singleton advisory lock module on dedicated Neon-direct connection |
| `triggers/embedded_scheduler.py` | +95/-14 | `start_scheduler` integrates lock acquire + retry-thread spawn; `stop_scheduler` + `restart_scheduler` release lock; `restart_scheduler` `wait=True`; `_scheduler_heartbeat` probes held connection |
| `outputs/dashboard.py` | +5/-4 | `_watchdog_cooldown` rate-limit bug fixed (variable was misused as threshold) |
| `tests/test_scheduler_singleton.py` | +119 NEW | 4 tests: 3 live-PG (acquire / two-conn race / release-reacquire) + 1 unit (host_direct gating) |
| `tests/test_watchdog_cooldown.py` | +85 NEW | 3 unit tests: throttle fires once / fires again after cooldown / fresh-heartbeat no-op |

Total: 6 files, +445 / -18 LOC.

---

## §2 — Implementation against brief's 8 Quality Checkpoints

1. **`pytest tests/test_scheduler_singleton.py tests/test_watchdog_cooldown.py -v`** — see §0. 4 pass, 3 live-PG skip (CI executes them).
2. **Verification SQL #1 — `distinct_anchors = 1` per job over 15-min window.** Post-deploy responsibility. Will run via `mcp__baker__baker_raw_query` after Render deploy + 15 min stabilization.
3. **Synthetic deploy stress test (2 deploys in 5 min).** Post-deploy responsibility. Documented in §3 below.
4. **Startup logs during overlap.** Lock-failure path emits `"scheduler singleton lock NOT acquired (key=8800100) — another process holds it"`; retry-thread emits `"scheduler singleton lock acquired on retry — starting jobs"` on success. Both logged at `INFO`.
5. **`pg_locks` shows 1 row for `objid=8800100`.** Post-deploy responsibility. Brief Verification SQL #2.
6. **WA alert ≤1 per 5-min window.** Enforced by `_watchdog_alert_cooldown_s = 300` + last-alert-ts compare. Test `test_watchdog_alert_throttled` proves; `test_watchdog_alert_fires_again_after_cooldown` proves second alert lands after cooldown.
7. **`kbl_bridge_tick` consumer cadence unchanged.** No change to bridge code; bridge advisory lock at `kbl/bridge/alerts_to_signal.py:622` untouched.
8. **`cortex_pipeline.maybe_dispatch` still fires once per signal.** No change to `triggers/cortex_pipeline.py`; cost-gate atomic-claim untouched. Verification SQL #3 (post-deploy).

---

## §3 — Hard-rail compliance

- ✅ **Uses `config.postgres.direct_dsn_params`** for the lock connection (`triggers/scheduler_lease.py:64`).
- ✅ **Held conn kept alive for process lifetime** — module-level `_held_conn`, never returned to a pool, only released by `release_singleton_lock` or process death.
- ✅ **Uses `pg_try_advisory_lock` (session-scoped)** — NOT `pg_try_advisory_xact_lock`. Released only by explicit `pg_advisory_unlock` or session close.
- ✅ **`autocommit = True`** on the lock connection — avoids accidental session-state drift on idle.
- ✅ **NOT in any hot path** — only called from `start_scheduler` at boot and from `restart_scheduler` after watchdog-driven shutdown.
- ✅ **Retry thread is daemon** — process can exit cleanly on SIGTERM regardless of poll state.
- ✅ **Untouched files:** `kbl/bridge/alerts_to_signal.py`, `triggers/cortex_pipeline.py`, `migrations/*.sql`, `start.sh`, `_register_jobs()` job set, `> 720` heartbeat threshold.
- ✅ **No raw Render env-var PUT** — `POSTGRES_HOST_DIRECT` is a Director action via MCP merge mode (see §5).

---

## §4 — Behavior across deploy overlap

```
T₀         OLD container running, holds lock 8800100, runs full job set.
T₁ + 0s    NEW container boots → start_scheduler → acquire_singleton_lock → FAILS
           → logs "lock NOT acquired" → spawns scheduler-lock-retry daemon.
T₁ + 30s   Retry thread polls → still locked → loops.
T₂         OLD container receives SIGTERM → @app.on_event("shutdown") fires →
           stop_scheduler → BackgroundScheduler.shutdown(wait=True) →
           release_singleton_lock → connection.close() → server-side
           lock auto-released. (Belt + suspenders: even if OS-killed before
           graceful path, TCP RST on connection drop releases server-side.)
T₂ + ≤30s  NEW retry thread next poll → acquire_singleton_lock SUCCEEDS →
           start_scheduler runs → BackgroundScheduler created + jobs registered
           + .start() → "scheduler singleton lock acquired on retry — starting jobs".
```

Worst-case scheduler outage during overlap: 30 s (retry-thread cadence). Acceptable given `coalesce=True` on every job + `misfire_grace_time=300`.

---

## §5 — Director action required (not in this PR)

**Render env-var:** set `POSTGRES_HOST_DIRECT` via Render MCP **merge mode** (per `memory/feedback_render_envvar_paginated_put.md` — never raw PUT).

Value: drop `-pooler` from current `POSTGRES_HOST` value. If `POSTGRES_HOST` is `ep-summer-sun-aih7ha4h-pooler.c-4.us-east-1.aws.neon.tech`, set `POSTGRES_HOST_DIRECT` to `ep-summer-sun-aih7ha4h.c-4.us-east-1.aws.neon.tech`.

Verify Neon project has direct compute exposed before setting (Neon dashboard → Project → Connection details → "Direct connection" tab).

**Failure mode if unset:** `acquire_singleton_lock()` logs an ERROR-level message and returns `None`. `start_scheduler` then registers NO jobs and spawns the retry thread. The retry thread will keep failing until `POSTGRES_HOST_DIRECT` is set + a deploy refreshes the env. **No regression vs today's state — duplicate scheduler firing remains possible** (i.e., the singleton fix is dormant). The error log is loud enough that it surfaces in any grep of startup logs.

---

## §6 — Side findings (kept out of this PR)

1. **`tools/ingest/extractors.py:275` uses Python 3.10+ `str | None` syntax** — would fail on Python 3.9. Not a regression from this PR; surfaced during local pytest. Repo declares Python 3.11+ so production is fine, but worth a follow-up Lesson if the team deploys to a 3.9 image anywhere.
2. **`outputs/dashboard.py:2536` SyntaxWarning** for `'\['` in a raw SQL regex string — pre-existing, unrelated to this PR. Surfaced as deprecation noise during pytest.

Neither blocks this PR.

---

## §7 — Verification SQL (for AI Head A/B post-deploy review)

```sql
-- 1. Singleton enforcement — every job has 1 anchor over 15 min window:
SELECT job_id, COUNT(*) AS fires,
       COUNT(DISTINCT (EXTRACT(EPOCH FROM fired_at)::numeric % 60)::text) AS distinct_anchors
FROM scheduler_executions
WHERE fired_at > NOW() - INTERVAL '15 minutes'
GROUP BY job_id
ORDER BY fires DESC
LIMIT 20;
-- Pass: every job has distinct_anchors = 1.

-- 2. Lock visibility:
SELECT locktype, classid, objid, granted, pid
FROM pg_locks
WHERE locktype = 'advisory' AND objid = 8800100;
-- Pass: exactly one row, granted=true.

-- 3. Cortex regression check:
SELECT cycle_id, status, started_at,
       COUNT(*) OVER (PARTITION BY trigger_signal_id) AS dispatches_per_signal
FROM cortex_cycles
WHERE started_at > NOW() - INTERVAL '24 hours'
ORDER BY started_at DESC
LIMIT 20;
-- Pass: dispatches_per_signal = 1 for every row.
```

---

## Co-Authored-By

```
Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
