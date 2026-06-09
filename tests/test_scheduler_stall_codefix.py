"""SCHEDULER_STALL_CODEFIX_1 — permanent fix for the #2508 orphaned-lock stall.

Hermetic unit coverage (no live PG; psycopg2.connect + the held conn are mocked).
Covers the three fix parts ratified by lead in bus #2517:

  Fix 1 (triggers/scheduler_lease.py):
    * acquire records the holder PID (pg_backend_pid).
    * reacquire false-positive guard: a STILL-ALIVE lock conn is kept, not dropped.
    * reacquire terminates the orphaned prior holder BEFORE re-probing the lock.
    * release evicts the orphan by tracked PID when _held_conn was already lost
      (the exact no-op that turned a transient blip into a permanent stall).
    * _terminate_lock_holder is PID-reuse-safe (join-guarded on pg_locks).
  Fix 2 (outputs/dashboard.py):
    * watchdog os._exit(1) after _WATCHDOG_EXIT_THRESHOLD consecutive restarts that
      still leave job_count==0; resets the streak on a fresh heartbeat.
  Fix 3 (triggers/state.py):
    * set_watermark rolls back the poisoned pooled conn on failure + counts it.

The live-PG path (real pg_terminate_backend of a real orphaned advisory-lock
holder) is exercised by the post-merge AC on PROD, not here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

import triggers.scheduler_lease as lease


@pytest.fixture(autouse=True)
def _reset_lease_state():
    lease._held_conn = None
    lease._held_pid = None
    lease._standdown_requested = False
    yield
    lease._held_conn = None
    lease._held_pid = None
    lease._standdown_requested = False


def _direct_host(monkeypatch):
    # Patch the EXACT config object scheduler_lease holds (`lease.config`), not a
    # re-imported one. Pre-existing full-suite contamination can leave the global
    # config singleton's host_direct unset; patching via lease.config is robust to
    # that (the lease module reads `config.postgres.host_direct` off this object).
    monkeypatch.setattr(lease.config.postgres, "host_direct", "direct.example.neon")


# ============================================================
# Fix 1 — PID tracking + orphan eviction
# ============================================================


def test_acquire_records_held_pid(monkeypatch):
    """acquire success → _held_pid set from pg_backend_pid()."""
    _direct_host(monkeypatch)
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    # 1st fetchone = advisory-lock TRUE; 2nd = pg_backend_pid() → 343
    cur.fetchone.side_effect = [[True], [343]]
    with patch.object(lease.psycopg2, "connect", return_value=conn):
        held = lease.acquire_singleton_lock()

    assert held is conn
    assert lease.held_pid() == 343


def test_reacquire_false_positive_keeps_live_conn(monkeypatch):
    """AC2 — a STILL-ALIVE _held_conn (SELECT 1 ok) is kept; NO reconnect, REOWNED.

    This is the regression guard for the #2508 trigger: the old code dropped the
    live lock conn on a transient blip, orphaning the server session.
    """
    _direct_host(monkeypatch)
    live = MagicMock()
    live.cursor.return_value.fetchone.return_value = [1]  # SELECT 1 answers
    lease._held_conn = live
    lease._held_pid = 343

    with patch.object(lease.psycopg2, "connect") as mconnect:
        outcome = lease.reacquire_singleton_lock()

    assert outcome == lease.REACQUIRE_REOWNED
    assert lease._held_conn is live          # kept the same conn
    assert lease._held_pid == 343            # pid unchanged
    mconnect.assert_not_called()             # never reconnected


def test_reacquire_terminates_orphan_before_reprobe(monkeypatch):
    """AC1 (hermetic) — a DEAD _held_conn with a known pid → terminate that pid on a
    fresh session BEFORE pg_try_advisory_lock, then re-own."""
    _direct_host(monkeypatch)
    # Old conn is dead: SELECT 1 raises → genuine-drop path.
    dead = MagicMock()
    dead.cursor.return_value.execute.side_effect = RuntimeError("socket dead")
    lease._held_conn = dead
    lease._held_pid = 343

    fresh = MagicMock()
    fcur = MagicMock()
    fresh.cursor.return_value = fcur
    # fetchone order on fresh conn:
    #   1) _terminate_lock_holder → [True] (343 still held the lock, killed)
    #   2) pg_try_advisory_lock   → [True]
    #   3) pg_backend_pid()       → [999]
    fcur.fetchone.side_effect = [[True], [True], [999]]

    with patch.object(lease.psycopg2, "connect", return_value=fresh):
        outcome = lease.reacquire_singleton_lock()

    assert outcome == lease.REACQUIRE_REOWNED
    assert lease._held_conn is fresh
    assert lease.held_pid() == 999
    # Prove the terminate ran against the orphaned pid 343.
    sqls = " ".join(str(c.args[0]) for c in fcur.execute.call_args_list)
    assert "pg_terminate_backend" in sqls
    terminate_call = next(c for c in fcur.execute.call_args_list
                          if "pg_terminate_backend" in str(c.args[0]))
    assert 343 in terminate_call.args[1]


def test_terminate_lock_holder_is_pid_reuse_safe(monkeypatch):
    """The terminate is join-guarded: it only kills a pid that STILL holds key 8800100.
    If the pid no longer holds the lock (reused backend), fetchone is empty → no kill."""
    cur = MagicMock()
    cur.fetchone.return_value = None  # join matched nothing → pid not a holder
    killed = lease._terminate_lock_holder(cur, 343)
    assert killed is False
    # codex G3 #2533 — the guard MUST pin the single-bigint lock identity, not just
    # objid (a two-int lock with the same objid would otherwise falsely match). Assert
    # the SQL shape carries objsubid=1 + the reconstructed 64-bit key. (No trailing
    # 'or True' — the prior version was vacuous and never checked the SQL.)
    sql = " ".join(str(cur.execute.call_args.args[0]).split())
    assert "pg_locks" in sql
    assert "objsubid = 1" in sql      # single-key form only (excludes two-int objsubid=2)
    assert "classid = 0" in sql       # high 32 bits zero — pins our small bigint key
    assert "objid = %s" in sql
    assert cur.execute.call_args.args[1] == (lease.SCHEDULER_LOCK_KEY, 343)


def test_release_evicts_orphan_when_conn_already_lost(monkeypatch):
    """The core #2508 fix — release with _held_conn already None but a tracked pid
    opens a fresh session and terminates the orphan (old release was a pure no-op)."""
    _direct_host(monkeypatch)
    lease._held_conn = None
    lease._held_pid = 343

    fresh = MagicMock()
    fcur = MagicMock()
    fresh.cursor.return_value = fcur
    fcur.fetchone.return_value = [True]  # terminate hit a live holder

    with patch.object(lease.psycopg2, "connect", return_value=fresh):
        lease.release_singleton_lock()

    sqls = " ".join(str(c.args[0]) for c in fcur.execute.call_args_list)
    assert "pg_terminate_backend" in sqls
    assert lease._held_pid is None  # cleared after eviction
    fresh.close.assert_called()


def test_release_normal_clears_pid(monkeypatch):
    """Graceful release with a live _held_conn unlocks, closes, and clears the pid."""
    live = MagicMock()
    lease._held_conn = live
    lease._held_pid = 343

    lease.release_singleton_lock()

    assert lease._held_conn is None
    assert lease._held_pid is None
    live.close.assert_called()


# ============================================================
# Fix 2 — watchdog os._exit backstop
# ============================================================


def _stale_hb(seconds_old: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds_old)


def test_watchdog_osexit_after_threshold():
    """3 consecutive watchdog restarts that leave job_count==0 → os._exit(1)."""
    import outputs.dashboard as dash
    dash._watchdog_last_alert_ts = 0
    dash._watchdog_consecutive_stale = 0
    dash._watchdog_restart_failed_streak = 0

    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(900)  # 15 min stale
    # SCHEDULER_WATCHDOG_HARDEN_1: a truly dead scheduler writes NO executions, so
    # the recency probe is stale (>180s window) → the restart is NOT suppressed and
    # the os._exit backstop path stays exercised.
    fake_state.seconds_since_last_scheduler_execution.return_value = 900.0

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler"), \
         patch("triggers.embedded_scheduler.get_scheduler_status",
               return_value={"running": False, "job_count": 0}), \
         patch.object(dash.os, "_exit") as mexit, \
         patch.object(dash, "logger"):
        # Each restart needs 2 stale reads → 3 restarts = 6 reads.
        for _ in range(6):
            dash._check_scheduler_heartbeat()

    mexit.assert_called_once_with(1)
    assert dash._watchdog_restart_failed_streak >= dash._WATCHDOG_EXIT_THRESHOLD


def test_watchdog_no_exit_when_jobs_register():
    """If a restart brings job_count>0, the streak resets and os._exit never fires."""
    import outputs.dashboard as dash
    dash._watchdog_last_alert_ts = 0
    dash._watchdog_consecutive_stale = 0
    dash._watchdog_restart_failed_streak = 0

    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(900)
    # SCHEDULER_WATCHDOG_HARDEN_1: stale executions too → restart is not suppressed,
    # so this still exercises the job_count>0 streak-reset path on each restart.
    fake_state.seconds_since_last_scheduler_execution.return_value = 900.0

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler"), \
         patch("triggers.embedded_scheduler.get_scheduler_status",
               return_value={"running": True, "job_count": 66}), \
         patch.object(dash.os, "_exit") as mexit, \
         patch.object(dash, "logger"):
        for _ in range(8):  # 4 restarts, all healthy
            dash._check_scheduler_heartbeat()

    mexit.assert_not_called()
    assert dash._watchdog_restart_failed_streak == 0


def test_watchdog_fresh_heartbeat_resets_failed_streak():
    """A fresh heartbeat clears a partially-accumulated failed-restart streak."""
    import outputs.dashboard as dash
    dash._watchdog_consecutive_stale = 0
    dash._watchdog_restart_failed_streak = 2  # pretend 2 prior failed restarts

    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(60)  # fresh

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler"), \
         patch.object(dash, "logger"):
        dash._check_scheduler_heartbeat()

    assert dash._watchdog_restart_failed_streak == 0


# ============================================================
# Fix 3 — set_watermark rollback + failure counter
# ============================================================


def test_set_watermark_rolls_back_and_counts_on_failure():
    """A failed INSERT rolls back the pooled conn (so it isn't returned poisoned)
    and increments the surfaced failure counter."""
    import triggers.state as state_mod

    conn = MagicMock()
    conn.cursor.return_value.execute.side_effect = RuntimeError("write failed")
    store = MagicMock()
    store._get_conn.return_value = conn

    ts = state_mod.TriggerState.__new__(state_mod.TriggerState)  # skip __init__/_ensure_tables
    before = state_mod.get_watermark_failure_count()

    with patch.object(ts, "_get_store", return_value=store):
        ts.set_watermark("scheduler_heartbeat", datetime.now(timezone.utc))

    conn.rollback.assert_called_once()          # poisoned conn rolled back
    store._put_conn.assert_called_once_with(conn)  # still returned to the pool
    assert state_mod.get_watermark_failure_count() == before + 1


def test_set_watermark_success_no_rollback_no_count():
    """Happy path: commit, no rollback, counter unchanged."""
    import triggers.state as state_mod

    conn = MagicMock()
    store = MagicMock()
    store._get_conn.return_value = conn

    ts = state_mod.TriggerState.__new__(state_mod.TriggerState)
    before = state_mod.get_watermark_failure_count()

    with patch.object(ts, "_get_store", return_value=store):
        ts.set_watermark("scheduler_heartbeat", datetime.now(timezone.utc))

    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()
    store._put_conn.assert_called_once_with(conn)
    assert state_mod.get_watermark_failure_count() == before


# ============================================================
# Fix 1 (live-PG) — codex G3 #2533: the terminate guard must match ONLY the
# single-bigint scheduler lock, never a two-int lock sharing the same objid.
# Auto-skips without TEST_DATABASE_URL / ephemeral Neon.
# ============================================================


def _pg_backend_pid(conn) -> int:
    c = conn.cursor()
    c.execute("SELECT pg_backend_pid()")
    pid = c.fetchone()[0]
    c.close()
    return pid


def test_terminate_guard_ignores_two_int_lock_with_same_objid(needs_live_pg):
    """A two-int advisory lock pg_advisory_lock(X, 8800100) has objsubid=2 and the
    SAME objid as our single-key lock — it MUST NOT be matched/terminated (the codex
    G3 #2533 S2 innocent-backend-kill regression)."""
    import psycopg2
    dsn = needs_live_pg
    victim = psycopg2.connect(dsn); victim.autocommit = True
    checker = psycopg2.connect(dsn); checker.autocommit = True
    try:
        vcur = victim.cursor()
        # two-int form → classid=12345, objid=SCHEDULER_LOCK_KEY, objsubid=2
        vcur.execute("SELECT pg_advisory_lock(%s, %s)", (12345, lease.SCHEDULER_LOCK_KEY))
        vcur.fetchone()
        victim_pid = _pg_backend_pid(victim)

        ccur = checker.cursor()
        killed = lease._terminate_lock_holder(ccur, victim_pid)
        ccur.close()

        assert killed is False, "two-int lock must NOT match the single-bigint guard"
        vcur.execute("SELECT 1")          # victim still alive (not terminated)
        assert vcur.fetchone()[0] == 1
    finally:
        for c in (victim, checker):
            try:
                c.close()
            except Exception:
                pass


def test_terminate_guard_matches_single_bigint_lock(needs_live_pg):
    """Positive: a real single-bigint pg_try_advisory_lock(8800100) holder IS matched
    + terminated — proves the objsubid/reconstructed-key guard isn't over-tightened."""
    import psycopg2
    dsn = needs_live_pg
    victim = psycopg2.connect(dsn); victim.autocommit = True
    checker = psycopg2.connect(dsn); checker.autocommit = True
    try:
        vcur = victim.cursor()
        vcur.execute("SELECT pg_try_advisory_lock(%s)", (lease.SCHEDULER_LOCK_KEY,))
        assert vcur.fetchone()[0] is True
        victim_pid = _pg_backend_pid(victim)

        ccur = checker.cursor()
        killed = lease._terminate_lock_holder(ccur, victim_pid)
        ccur.close()

        assert killed is True, "single-bigint lock holder should be matched + terminated"
    finally:
        for c in (victim, checker):
            try:
                c.close()
            except Exception:
                pass
