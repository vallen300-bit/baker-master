---
status: PENDING
brief_id: SCHEDULER_NEON_IDLE_HARDEN_1
dispatch: SCHEDULER_NEON_IDLE_HARDEN_1
to: b2
from: lead
dispatched_by: lead
task_class: production reliability fix (scheduler availability / singleton-lock correctness)
harness_v2: applies
gate_plan: G0 codex PASS (#1875, 7c1a17e) → G1 lead (literal pytest) → G2 /security-review → G3 codex (PR) → merge → POST_DEPLOY_AC_VERDICT v1 (≥40-min live window)
brief_path: briefs/BRIEF_SCHEDULER_NEON_IDLE_HARDEN_1.md
---

# B2 dispatch — SCHEDULER_NEON_IDLE_HARDEN_1

**Full spec: `briefs/BRIEF_SCHEDULER_NEON_IDLE_HARDEN_1.md` (commit 7c1a17e). codex G0 v5 PASS (#1875) after 3 fold rounds. Read the brief — this envelope is the pointer + gate contract.**

## Context Contract
baker-master's Sentinel scheduler enters a ~18-min teardown→rebuild loop. **Root (verified at HEAD, not a guess):** the singleton-lock direct conn (`triggers/scheduler_lease.py:64`) has no TCP keepalives → Neon idle-drops it between 5-min heartbeat probes → the heartbeat probe (`embedded_scheduler.py:1560` `SELECT 1`) fails/hangs → the dashboard watchdog (`outputs/dashboard.py:188`, stale >720s ×2) restarts the whole scheduler. The brief carries every file:line + the connect-param fix.

## Scope (5 fixes — all G0-passed)
1. **Fix 1 — keepalives** in `config/settings.py` `direct_dsn_params` (~:195-211): `keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5`. Shared (reingest/OCR locks benefit too).
2. **Fix 2a — bound the probe:** `connect_timeout=5` (explicit kwarg, NOT in shared params — precedent `embedded_scheduler.py:127`) + per-SESSION `SET statement_timeout='10s'` inside `scheduler_lease.acquire_singleton_lock` only. Keepalives bound TCP-dead, statement_timeout bounds server-stall, connect_timeout bounds initial connect.
3. **Fix 2b — self-heal, 3-state:** new `reacquire_singleton_lock()` (close dead `_held_conn` → reconnect w/ connect_timeout+keepalives+autocommit+statement_timeout → `pg_try_advisory_lock`). TRUE→re-own+continue; FALSE (another holds)→close+`request_standdown()`; connect-fail→WARN+return (transient retry).
4. **Fix 2c — heartbeat control shape (CRITICAL):** `_held_conn is None` while the heartbeat is running (= active scheduler by the `:1699-1707` no-jobs-without-lock invariant) **routes into reacquire, NEVER skips the branch**. Else a transient leaves it firing lock-less with a fresh watermark forever.
5. **Stand-down = non-self-join:** module flag `request_standdown()`/`consume_standdown()`; the request-thread watchdog `_check_scheduler_heartbeat()` consumes it FIRST each tick → `restart_scheduler()`. NEVER call `restart_scheduler()`/`shutdown(wait=True)` from the heartbeat job thread.
6. **Fix 3 — observability:** single greppable `SCHEDULER_RESTART reason=<...>` log line on the restart path.

**Invariants (do NOT break):** watermark written FIRST always; in-memory jobstore unchanged; advisory key 8800100; all DB ops fault-tolerant; no secrets. Do NOT touch the reingest/OCR advisory-lock endpoints (they get keepalives for free).

## Gate contract (Harness V2)
- **Done rubric (literal):** ≥40-min post-deploy window — `scheduler_heartbeat` watermark age never exceeds ~10 min, `/health` shows `running, jobs:64` on ≥5 spot checks with ZERO `stopped/0`, Render logs show ZERO restart/watchdog-restart lines. Paste the watermark-age timeline + 5 health reads.
- **AC0 FIRST (~10 min):** confirm from baker-master logs since 13:35Z the loop is watchdog-driven (periodic restart lines ~18 min apart preceded by stale-heartbeat WARN). If NOT, STOP + bus lead. (Render log access: ask lead if creds needed.)
- **Gates:** G0 PASS (#1875) → G1 lead literal `pytest tests/test_scheduler_liveness*.py tests/test_scheduler_lease*.py -v` (+ the new units in the brief §Verification) → G2 `/security-review` → G3 codex on PR → AH1 merge → you fill `POST_DEPLOY_AC_VERDICT v1`.

## Reply target
Bus-post `lead` (AI Head A) on SHIP with the new sha + PR # once G1 is literal-green. Push to a fresh `scheduler-neon-idle-harden-1` branch. Copy-pasteable snippets + the 3-state table + the full §Verification unit list are in the brief.
