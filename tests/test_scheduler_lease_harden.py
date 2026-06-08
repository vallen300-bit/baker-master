"""SCHEDULER_NEON_IDLE_HARDEN_1 — bound + self-heal the singleton-lock connection.

Pure unit (no live PG). Mocks ``psycopg2.connect`` on ``triggers.scheduler_lease``
and the held connection, so every test runs hermetically regardless of
``POSTGRES_HOST_DIRECT`` in the environment.

Covers the brief §Verification list:
  * ``direct_dsn_params`` carries the 4 keepalive keys.
  * ``acquire_singleton_lock`` issues ``SET statement_timeout`` on the lock session.
  * ``acquire_singleton_lock`` AND ``reacquire_singleton_lock`` pass ``connect_timeout=5``.
  * 3-state reacquire split (REOWNED / LOST / TRANSIENT) + conn lifecycle.
  * heartbeat probe-failure routes to reacquire, watermark still written FIRST.
  * ``_held_conn is None`` routes to reacquire (NOT skip), all 3 outcomes + retry.
  * dashboard watchdog consumes stand-down FIRST → restart; test-and-clear idempotent.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

import triggers.scheduler_lease as lease


@pytest.fixture(autouse=True)
def _reset_lease_state():
    """Reset module globals so tests never leak held-conn / stand-down state."""
    lease._held_conn = None
    lease._held_pid = None  # SCHEDULER_STALL_CODEFIX_1 — tracked holder PID
    lease._standdown_requested = False
    yield
    lease._held_conn = None
    lease._held_pid = None
    lease._standdown_requested = False


def _direct_host(monkeypatch):
    from config.settings import config
    monkeypatch.setattr(config.postgres, "host_direct", "direct.example.neon")


def _mock_lock_conn(lock_granted: bool) -> MagicMock:
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchone.return_value = [lock_granted]
    return conn


class _AutocommitBoomConn:
    """A connection whose post-connect setup (autocommit setter) raises — used to
    prove _open_lock_session closes the half-opened conn instead of leaking it
    (codex G3 #1884). Tracks whether close() was called."""

    def __init__(self):
        self.closed = False

    @property
    def autocommit(self):
        return False

    @autocommit.setter
    def autocommit(self, value):
        raise RuntimeError("post-connect setup failed")

    def close(self):
        self.closed = True


# ---------- Fix 1: keepalives ----------


def test_direct_dsn_params_has_keepalives():
    from config.settings import config
    p = config.postgres.direct_dsn_params
    assert p["keepalives"] == 1
    assert p["keepalives_idle"] == 30
    assert p["keepalives_interval"] == 10
    assert p["keepalives_count"] == 5


# ---------- Fix 2a: acquire bounds (statement_timeout + connect_timeout) ----------


def test_acquire_sets_statement_timeout_and_connect_timeout(monkeypatch):
    """connect_timeout=5 + statement_timeout applied at CONNECT time via libpq options
    (codex G3 #1884: a post-connect SET had an unprotected leak/hang window)."""
    _direct_host(monkeypatch)
    fake_conn = _mock_lock_conn(lock_granted=True)
    with patch.object(lease.psycopg2, "connect", return_value=fake_conn) as mconnect:
        held = lease.acquire_singleton_lock()

    assert held is fake_conn
    assert mconnect.call_args.kwargs.get("connect_timeout") == 5
    assert mconnect.call_args.kwargs.get("options") == "-c statement_timeout=10s"


# ---------- codex G3 #1884: no connection leak on post-connect setup failure ----------


def test_acquire_closes_conn_on_post_connect_failure(monkeypatch):
    """If a post-connect step raises, acquire closes the conn (no leak) + returns None."""
    _direct_host(monkeypatch)
    boom = _AutocommitBoomConn()
    with patch.object(lease.psycopg2, "connect", return_value=boom):
        held = lease.acquire_singleton_lock()

    assert held is None
    assert boom.closed is True
    assert lease._held_conn is None


def test_reacquire_closes_conn_on_post_connect_failure(monkeypatch):
    """Same leak guard on the reacquire path → REACQUIRE_TRANSIENT, conn closed."""
    _direct_host(monkeypatch)
    boom = _AutocommitBoomConn()
    with patch.object(lease.psycopg2, "connect", return_value=boom):
        outcome = lease.reacquire_singleton_lock()

    assert outcome == lease.REACQUIRE_TRANSIENT
    assert boom.closed is True
    assert lease._held_conn is None
    assert lease.consume_standdown() is False  # transient never stands down


def test_acquire_closes_conn_when_advisory_lock_raises(monkeypatch):
    """codex G3 v2 #1888: if the advisory-lock cursor block raises after the conn
    is open, acquire closes it (no leak) + returns None + _held_conn stays None."""
    _direct_host(monkeypatch)
    conn = MagicMock()
    conn.cursor.return_value.execute.side_effect = RuntimeError("SELECT pg_try_advisory_lock failed")
    with patch.object(lease.psycopg2, "connect", return_value=conn):
        held = lease.acquire_singleton_lock()

    assert held is None
    conn.close.assert_called_once()
    assert lease._held_conn is None


def test_reacquire_closes_conn_when_advisory_lock_raises(monkeypatch):
    """Mirror on reacquire: cursor-block raise → conn closed → REACQUIRE_TRANSIENT."""
    _direct_host(monkeypatch)
    conn = MagicMock()
    conn.cursor.return_value.execute.side_effect = RuntimeError("SELECT failed")
    with patch.object(lease.psycopg2, "connect", return_value=conn):
        outcome = lease.reacquire_singleton_lock()

    assert outcome == lease.REACQUIRE_TRANSIENT
    conn.close.assert_called_once()
    assert lease._held_conn is None


# ---------- Fix 2b: reacquire 3-state split ----------


def test_reacquire_reowned_sets_held_no_standdown(monkeypatch):
    """reconnect OK + advisory-lock TRUE → re-own; _held_conn set; NO stand-down."""
    _direct_host(monkeypatch)
    fake_conn = _mock_lock_conn(lock_granted=True)
    with patch.object(lease.psycopg2, "connect", return_value=fake_conn) as mconnect:
        outcome = lease.reacquire_singleton_lock()

    assert outcome == lease.REACQUIRE_REOWNED
    assert lease._held_conn is fake_conn
    assert lease.consume_standdown() is False
    assert mconnect.call_args.kwargs.get("connect_timeout") == 5
    # statement_timeout applied at connect time on the reacquired session too
    assert mconnect.call_args.kwargs.get("options") == "-c statement_timeout=10s"


def test_reacquire_lost_clears_held_closes_conn_requests_standdown(monkeypatch):
    """reconnect OK + advisory-lock FALSE → another holder; close + stand down."""
    _direct_host(monkeypatch)
    fake_conn = _mock_lock_conn(lock_granted=False)
    with patch.object(lease.psycopg2, "connect", return_value=fake_conn):
        outcome = lease.reacquire_singleton_lock()

    assert outcome == lease.REACQUIRE_LOST
    assert lease._held_conn is None
    fake_conn.close.assert_called_once()
    # stand-down was requested (consume returns True exactly once)
    assert lease.consume_standdown() is True


def test_reacquire_transient_on_connect_failure_no_standdown(monkeypatch):
    """reconnect FAILS → indeterminate transient; clear held; NO stand-down; no raise."""
    _direct_host(monkeypatch)
    with patch.object(lease.psycopg2, "connect", side_effect=OSError("network unreachable")):
        outcome = lease.reacquire_singleton_lock()

    assert outcome == lease.REACQUIRE_TRANSIENT
    assert lease._held_conn is None
    assert lease.consume_standdown() is False


def test_reacquire_closes_stale_held_conn_first(monkeypatch):
    """A GENUINELY-dead _held_conn is closed before the reconnect attempt.

    SCHEDULER_STALL_CODEFIX_1: reacquire now probes SELECT 1 first and only
    closes+reconnects when that probe FAILS (a live conn is kept — see
    test_reacquire_false_positive_keeps_live_conn). Here the stale conn's probe
    raises, so the dead-conn close+reconnect path still runs as before.
    """
    _direct_host(monkeypatch)
    stale = MagicMock()
    stale.cursor.return_value.execute.side_effect = RuntimeError("socket dead")  # SELECT 1 fails
    lease._held_conn = stale
    fake_conn = _mock_lock_conn(lock_granted=True)
    with patch.object(lease.psycopg2, "connect", return_value=fake_conn):
        lease.reacquire_singleton_lock()

    stale.close.assert_called_once()
    assert lease._held_conn is fake_conn


def test_reacquire_transient_when_host_direct_unset(monkeypatch):
    """No POSTGRES_HOST_DIRECT → reacquire is a fast transient (no connect attempt)."""
    from config.settings import config
    monkeypatch.setattr(config.postgres, "host_direct", "")
    with patch.object(lease.psycopg2, "connect") as mconnect:
        outcome = lease.reacquire_singleton_lock()

    assert outcome == lease.REACQUIRE_TRANSIENT
    mconnect.assert_not_called()
    assert lease.consume_standdown() is False


# ---------- stand-down flag: test-and-clear idempotency ----------


def test_standdown_request_then_consume_is_idempotent():
    assert lease.consume_standdown() is False  # clean
    lease.request_standdown()
    assert lease.consume_standdown() is True   # consumed once
    assert lease.consume_standdown() is False  # second consume is a no-op


# ---------- Fix 2c: heartbeat lock-health routing ----------


def test_heartbeat_probe_failure_triggers_reacquire_watermark_first():
    """Probe raises → reacquire called; watermark written BEFORE the reacquire."""
    import triggers.embedded_scheduler as sched

    order = []
    fake_state = MagicMock()
    fake_state.set_watermark.side_effect = lambda *a, **k: order.append("watermark")
    fake_conn = MagicMock()
    fake_conn.cursor.return_value.execute.side_effect = ConnectionError("Neon dropped")

    def _reacquire():
        order.append("reacquire")
        return lease.REACQUIRE_REOWNED

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.scheduler_lease._held_conn", fake_conn), \
         patch("triggers.scheduler_lease.reacquire_singleton_lock", side_effect=_reacquire) as mre:
        sched._scheduler_heartbeat()

    mre.assert_called_once()
    fake_state.set_watermark.assert_called_once()
    assert order == ["watermark", "reacquire"], "watermark must be written FIRST"


def test_heartbeat_held_none_reacquires_not_skip():
    """codex #1872: _held_conn is None must route to reacquire, never skip."""
    import triggers.embedded_scheduler as sched

    fake_state = MagicMock()
    mre = MagicMock(return_value=lease.REACQUIRE_REOWNED)
    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.scheduler_lease._held_conn", None), \
         patch("triggers.scheduler_lease.reacquire_singleton_lock", mre):
        sched._scheduler_heartbeat()

    mre.assert_called_once()
    fake_state.set_watermark.assert_called_once()


def test_heartbeat_held_none_lost_requests_standdown():
    """held None + reacquire LOST → heartbeat requests stand-down."""
    import triggers.embedded_scheduler as sched

    fake_state = MagicMock()
    mre = MagicMock(return_value=lease.REACQUIRE_LOST)
    mstand = MagicMock()
    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.scheduler_lease._held_conn", None), \
         patch("triggers.scheduler_lease.reacquire_singleton_lock", mre), \
         patch("triggers.scheduler_lease.request_standdown", mstand):
        sched._scheduler_heartbeat()

    mre.assert_called_once()
    mstand.assert_called_once()


def test_heartbeat_held_none_transient_retries_next_tick():
    """held None + reacquire TRANSIENT → no stand-down; next heartbeat reacquires AGAIN.

    Proves the loop never settles into 'fresh watermark + firing + no lock'.
    """
    import triggers.embedded_scheduler as sched

    fake_state = MagicMock()
    mre = MagicMock(return_value=lease.REACQUIRE_TRANSIENT)
    mstand = MagicMock()
    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.scheduler_lease._held_conn", None), \
         patch("triggers.scheduler_lease.reacquire_singleton_lock", mre), \
         patch("triggers.scheduler_lease.request_standdown", mstand):
        sched._scheduler_heartbeat()
        sched._scheduler_heartbeat()

    assert mre.call_count == 2  # retried, not skipped
    mstand.assert_not_called()  # transient never stands down


# ---------- Fix 2 stand-down consumer in the dashboard watchdog ----------


def test_watchdog_consumes_standdown_first_then_idempotent():
    """Watchdog restarts on a stand-down request, then does NOT re-restart (cleared)."""
    import outputs.dashboard as dash

    dash._watchdog_last_alert_ts = 0
    dash._watchdog_consecutive_stale = 0
    lease._standdown_requested = True

    fake_state = MagicMock()
    fake_state.get_watermark.return_value = datetime.now(timezone.utc)  # fresh
    fake_restart = MagicMock()

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler", fake_restart):
        dash._check_scheduler_heartbeat()  # consumes stand-down → restart
        dash._check_scheduler_heartbeat()  # flag cleared + fresh hb → no restart

    assert fake_restart.call_count == 1
    assert fake_restart.call_args.kwargs.get("reason") == "standdown_lock_lost"
