# B3 — Situational review: PR #84 SCHEDULER_SINGLETON_HARDEN_1

**Reviewer:** Code Brisen #3 (B3)
**Date:** 2026-04-29
**Target:** PR #84 — `b1/scheduler-singleton-harden-1` — head `133a852`
**Brief:** `briefs/BRIEF_SCHEDULER_SINGLETON_HARDEN_1.md`
**Builder:** B1 (solo author)
**Trigger class:** MEDIUM (touches FastAPI lifespan)
**Method:** Read-only review of `origin/b1/scheduler-singleton-harden-1` at head; no checkout, no edits.

---

## §0 — Verdict

**APPROVE**

All 10 specific concerns from the dispatch are clean against the implementation
as shipped. The four-fix design (lock module, lifespan wiring, watchdog throttle
fix, liveness probe) maps 1:1 to the brief and the diff is surgical (625
insertions, 10 deletions, 6 source files + 1 ship report). One operational
**deployment-ordering risk** must be honored at merge time — flagged in §2 as
MEDIUM but does not block approval since it's an env-var sequencing call that
the Director already owns per the brief's §"Render env var (Director action)".

Tests as shipped:
- 4 singleton tests (3 live-PG + 1 unit guard for HOST_DIRECT-unset)
- 3 watchdog-throttle tests (throttle on / cooldown-elapsed re-fire / fresh-HB no-op)

---

## §1 — Concerns confirmed clean

### Concern 1 — Held connection never enters any pool. ✓
- `_held_conn` is created via direct `psycopg2.connect(**direct_dsn_params)` at
  `triggers/scheduler_lease.py:64` and stored at module scope `:31`.
- Grep across the diff for `_held_conn` shows only:
  - `scheduler_lease.py` (declares + holds + releases — no pool involvement).
  - `embedded_scheduler.py:1167` (`_lease._held_conn` read-only for the heartbeat
    liveness probe; no `_put_conn` / pool path).
- No `pool.putconn(_held_conn)` or `_put_conn(_held_conn)` anywhere. Clean.

### Concern 2 — Direct DSN used for the lock. ✓
- `scheduler_lease.py:64` calls `psycopg2.connect(**config.postgres.direct_dsn_params)`.
- The pre-connect gate at `scheduler_lease.py:51-60` refuses to proceed if
  `host_direct` is empty, so the `direct_dsn_params` fallback-to-pooled-host
  branch (`config/settings.py:181 host = self.host_direct or self.host`) is
  unreachable from the lock path. Caller-detect requirement honored.

### Concern 3 — Session lock primitive (not xact). ✓
- `scheduler_lease.py:69` `cur.execute("SELECT pg_try_advisory_lock(%s)", ...)`.
- `scheduler_lease.py:99` release uses `pg_advisory_unlock(%s)` (matching session
  variant). No `pg_try_advisory_xact_lock` in the new module.

### Concern 4 — `autocommit = True` on the held conn. ✓
- `scheduler_lease.py:67` sets `conn.autocommit = True` immediately after
  `psycopg2.connect`. Prevents implicit-transaction state drift from interfering
  with the session lock.

### Concern 5 — Lock-poll retry thread. ✓
- `embedded_scheduler.py:1360` constructs with `daemon=True` — process can exit
  on SIGTERM regardless of poll state.
- Idempotency at `embedded_scheduler.py:1338-1340`: `if _lock_retry_thread is not
  None and _lock_retry_thread.is_alive(): return`. Module-level
  `_lock_retry_thread = None` declared at `:21`.
- Two reachable exit conditions inside `_poll`:
  - `embedded_scheduler.py:1346` — scheduler started via another path → return.
  - `embedded_scheduler.py:1357` — lock acquired on retry → calls
    `start_scheduler()` then return.
- Re-entry into `start_scheduler()` from the retry thread is safe: the second
  `acquire_singleton_lock()` call (now under the same module's `_lock`) sees
  `_held_conn is not None` at `scheduler_lease.py:48` and returns the same
  connection — no duplicate connect, no duplicate `_register_jobs`.

### Concern 7 — No new schema, migration, or `slugs.yml` touch. ✓
- PR file list (per `gh pr view 84`): only `triggers/scheduler_lease.py` (new),
  `triggers/embedded_scheduler.py`, `outputs/dashboard.py`, `config/settings.py`,
  `tests/test_scheduler_singleton.py` (new), `tests/test_watchdog_cooldown.py`
  (new), `briefs/_reports/B1_scheduler_singleton_harden_20260430.md`.
- No `migrations/` files, no `baker-vault/slugs.yml`, no DDL in the diff.

### Concern 8 — Heartbeat probe doesn't raise out of `_scheduler_heartbeat`. ✓
- Outer try/except (`embedded_scheduler.py:1165-1183`) wraps the probe and
  catches all `Exception` (`pass` on `:1183`). A raise inside the cursor /
  fetch / close path cannot escape.
- Inner probe catches the dead-connection error explicitly
  (`embedded_scheduler.py:1175-1181`), logs at error level, calls
  `restart_scheduler()`, and `return`s. The early-return matches the brief's
  Step 4 verbatim ("# restart will re-write heartbeat next cycle"). Note that
  on the dead-conn path the current invocation skips the heartbeat-write — see
  §3 note 2 below; matches brief.
- Heartbeat-write itself (`embedded_scheduler.py:1184-1188`) is in its own
  try/except — a raise from the watermark write cannot propagate.

### Concern 9 — Lock-key collision check. ✓
- `SCHEDULER_LOCK_KEY = 8800100` at `scheduler_lease.py:30`.
- Repo grep for known advisory-lock callers finds:
  900100 (`risk_detector`), 900201 (`cadence_tracker`), 900300 (`financial_detector`,
  `initiative_engine` — pre-existing non-PR collision unrelated to this review),
  900400 (`sentiment_scorer`), 900500 (`convergence_detector`), 900600
  (`obligation_generator`, `bridge`), 900700 (`action_completion_detector`),
  8004 (`memory_consolidator`), 8005 (`trend_detector`), 867531 (fireflies),
  867532 (plaud), 0x42BA4E00001 (migration runner).
- `8800100` is distinct from every value above. No collision.

### Concern 10 — Test cleanup. ✓
- All three live-PG tests in `tests/test_scheduler_singleton.py` call
  `release_singleton_lock()` at the top before any assertion (lines 47, 67, 92).
- All three additionally wrap the body in `try/finally` with
  `release_singleton_lock()` in `finally` — safer than the brief sketch since
  failures partway through don't leak held state into the next test.
- The bonus `test_acquire_returns_none_when_host_direct_unset` (pure unit) also
  resets `_lease._held_conn = None` defensively.

---

## §2 — Concerns flagged

### Concern 6 — Failure-mode degradation. **MEDIUM — operational**

`scheduler_lease.py:51-60`: when `POSTGRES_HOST_DIRECT` is unset,
`acquire_singleton_lock` logs at error level and returns `None`.
`start_scheduler` then logs a warning, spawns the retry thread, and **returns
without registering any jobs** (`embedded_scheduler.py:1308-1315`).

The retry thread polls every 30 s and re-calls `acquire_singleton_lock`, which
will keep returning `None` forever as long as `host_direct` stays empty (the
gate fires before any connect attempt). Net effect: **with `POSTGRES_HOST_DIRECT`
unset, the scheduler never starts at all** — strictly worse than today's "running
but doubled" state.

This **matches the brief's Step 1C verbatim** ("if held_conn is None …
registering NO jobs"), so the code is correct against the brief's primary spec.
But it contradicts:
- Dispatch concern 6 ("scheduler continues running without the lock — today's
  behavior, no regression").
- Brief §"Render env var (Director action)" final paragraph: "duplicate scheduler
  firing remains possible, no regression vs today's state."
- B1's commit message body: "Failure-mode is log-loud and degrades to today's
  state (duplicate firing possible), no new regression."

The implementation followed the dominant spec (Step 1C) and did the *safer* thing
— refusing pooler fallback rather than silently running unprotected. **No code
change requested.** But the deployment-ordering must be honored:

- **Severity:** MEDIUM (operational — not a code defect).
- **Recommended fix (process, not code):** Director sets `POSTGRES_HOST_DIRECT`
  on Render via MCP merge mode **before** this PR merges. Verify post-set with
  `bash scripts/check_envvars.sh` or `MCP render get-env`. If the merge happens
  first, the scheduler is dead until the env var lands and the next deploy.
- **Alternative if Director prefers belt-and-suspenders:** add a one-line
  fallback in `start_scheduler()` that, after `_spawn_lock_retry_thread()`,
  *also* registers jobs without the lock when `host_direct` is unset (mirroring
  today's behavior so duplicate-fire is possible but scheduler runs). Out of
  scope for this PR; would require a follow-up brief if Director wants it.

This is the only flag in the review.

---

## §3 — Notes on engineering / pattern fit

1. **Heartbeat probe reaches into module internals.**
   `embedded_scheduler.py:1166-1167` imports `triggers.scheduler_lease as _lease`
   and reads `_lease._held_conn` directly. The brief explicitly authorizes this
   ("Module-level import of `_held_conn` is intentional; the singleton is by
   design"), so it matches spec. Style nit only: a public
   `scheduler_lease.probe_held_conn()` helper would be cleaner long-term and
   would let `_held_conn` keep its single-underscore "private" intent. **LOW —
   no fix requested.**

2. **Heartbeat-write skipped on dead-conn detection.**
   `embedded_scheduler.py:1180-1181` returns before writing the watermark when
   the probe fires. Matches brief Step 4 line-for-line. The dispatch concern 8
   wording ("heartbeat write itself MUST always run regardless") suggests strict
   always-write, but the brief's authoritative code block returns early. The
   implementation is correct against the brief; the dispatch wording is slightly
   misleading but not actionable. The new BackgroundScheduler instance from
   `restart_scheduler()` re-registers `_scheduler_heartbeat` and the next
   5-min tick writes — well inside the 12-min stale threshold. **LOW — no fix
   requested.**

3. **`start_scheduler()` re-entry from retry thread.**
   When the retry thread calls `start_scheduler()` after acquiring the lock, the
   call is on the retry thread (not the main thread). `BackgroundScheduler.start()`
   is documented as thread-safe and APScheduler spawns its own executor threads
   regardless, so this is fine. Worth noting only because the retry thread is
   `daemon=True` — if SIGTERM hits during the narrow window between
   `_lock_retry_thread.start()` and the next 30s poll, the daemon dies cleanly.
   No concern.

4. **Test-isolation risk with the live-PG tests.**
   The three live-PG tests share `SCHEDULER_LOCK_KEY = 8800100` per process; if
   pytest runs them in parallel (`-n auto`), they will collide. Today's repo
   uses serial pytest (no `pytest-xdist` in requirements); assuming serial, the
   tests are safe. If the project ever adopts `-n auto`, these need a per-test
   key. **LOW — no fix requested today.**

5. **Lock-poll cadence.**
   30 s poll interval matches the brief and bounds worst-case post-deploy gap to
   ~30 s. APScheduler `misfire_grace_time=300` (5 min) absorbs this for
   cron-style jobs (Mon 09:00 UTC weekly audit). Clean.

6. **Pre-existing `pg_try_advisory_xact_lock(900300)` collision** between
   `orchestrator/financial_detector.py:76` and `orchestrator/initiative_engine.py:630`
   surfaced incidentally during the §1 concern-9 grep. **Out of scope for this
   PR** — flagging only as future-cleanup signal for AI Head A.

---

## §4 — Action

§0 = **APPROVE**. Posting GitHub PR review with this body via
`gh pr review 84 --approve`.

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
