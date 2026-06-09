"""SCHEDULER_WATCHDOG_HARDEN_1 — the request-time watchdog must NOT restart a
scheduler that is provably executing.

Anchor (lead #2566, 2026-06-09): live diagnosis found the scheduler_heartbeat
WATERMARK frozen 08:22→08:36 (the heartbeat job's set_watermark write silently
stopped advancing it) while 13 other jobs kept firing every cycle. The old
watchdog keyed SOLELY on heartbeat-watermark age > 720s, so it restarted a
healthy scheduler at the 12-min mark — confirmed by the interval-trigger
re-anchor fingerprint in scheduler_executions. The fix: gate the restart on a
truer liveness signal — a fresh scheduler_executions row (ANY job) within
_WATCHDOG_EXEC_FRESH_WINDOW_S means the scheduler thread is alive, so the stale
watermark is a gauge failure, not a stall → suppress the restart.

Real-stall recovery (#2508) is preserved: a dead scheduler writes NO executions,
so exec_age is stale (or None) → the restart still fires.

Hermetic — no live PG. trigger_state + embedded_scheduler entry points mocked.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


def _stale_hb(seconds_old: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds_old)


def _reset_watchdog_globals(dash):
    dash._watchdog_last_alert_ts = 0
    dash._watchdog_consecutive_stale = 0
    dash._watchdog_restart_failed_streak = 0


# ============================================================
# Watchdog restart-suppression gate
# ============================================================


def test_suppresses_restart_when_executions_fresh():
    """Stale heartbeat watermark BUT a job executed inside the fresh window ⇒
    NO restart, NO os._exit, and both escalation counters cleared."""
    import outputs.dashboard as dash
    _reset_watchdog_globals(dash)

    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(900)  # 15 min stale gauge
    # A job fired 20s ago — well inside the 180s fresh window → scheduler is live.
    fake_state.seconds_since_last_scheduler_execution.return_value = 20.0

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler") as mrestart, \
         patch("triggers.embedded_scheduler.get_scheduler_status",
               return_value={"running": True, "job_count": 66}), \
         patch.object(dash.os, "_exit") as mexit, \
         patch.object(dash, "logger"):
        # Two stale reads would normally trigger the restart on the 2nd.
        dash._check_scheduler_heartbeat()
        dash._check_scheduler_heartbeat()

    mrestart.assert_not_called()
    mexit.assert_not_called()
    assert dash._watchdog_consecutive_stale == 0
    assert dash._watchdog_restart_failed_streak == 0


def test_restarts_when_executions_stale():
    """Stale heartbeat AND last execution older than the fresh window ⇒ a real
    stall → restart fires (recovery path preserved)."""
    import outputs.dashboard as dash
    _reset_watchdog_globals(dash)

    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(900)
    fake_state.seconds_since_last_scheduler_execution.return_value = 400.0  # > 180s

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler") as mrestart, \
         patch("triggers.embedded_scheduler.get_scheduler_status",
               return_value={"running": True, "job_count": 66}), \
         patch.object(dash.os, "_exit"), \
         patch.object(dash, "logger"):
        dash._check_scheduler_heartbeat()  # read #1 — waits
        dash._check_scheduler_heartbeat()  # read #2 — restarts

    mrestart.assert_called_once()
    assert "heartbeat_stale" in mrestart.call_args.kwargs.get("reason", "")


def test_restarts_when_no_executions_recorded():
    """None from the recency probe (empty table / DB error) is FAIL-SAFE → the
    watchdog falls through to the existing stale-watermark restart."""
    import outputs.dashboard as dash
    _reset_watchdog_globals(dash)

    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(900)
    fake_state.seconds_since_last_scheduler_execution.return_value = None

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler") as mrestart, \
         patch("triggers.embedded_scheduler.get_scheduler_status",
               return_value={"running": True, "job_count": 66}), \
         patch.object(dash.os, "_exit"), \
         patch.object(dash, "logger"):
        dash._check_scheduler_heartbeat()
        dash._check_scheduler_heartbeat()

    mrestart.assert_called_once()


def test_suppression_clears_partial_failed_streak():
    """A provably-live scheduler clears a partially-accumulated os._exit streak so
    the backstop can never fire against a healthy scheduler."""
    import outputs.dashboard as dash
    _reset_watchdog_globals(dash)
    dash._watchdog_consecutive_stale = 1  # one prior stale read already banked
    dash._watchdog_restart_failed_streak = 2  # pretend 2 prior failed restarts

    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(900)
    fake_state.seconds_since_last_scheduler_execution.return_value = 5.0

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler") as mrestart, \
         patch("triggers.embedded_scheduler.get_scheduler_status",
               return_value={"running": True, "job_count": 66}), \
         patch.object(dash.os, "_exit") as mexit, \
         patch.object(dash, "logger"):
        # consecutive_stale starts at 1 → this single read reaches 2 → gate runs.
        dash._check_scheduler_heartbeat()

    mrestart.assert_not_called()
    mexit.assert_not_called()
    assert dash._watchdog_restart_failed_streak == 0


def test_fresh_heartbeat_skips_recency_probe():
    """A non-stale heartbeat short-circuits before any executions probe (cheap path
    stays cheap — the recency query only runs when about to restart)."""
    import outputs.dashboard as dash
    _reset_watchdog_globals(dash)

    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(60)  # fresh, < 720s

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler") as mrestart, \
         patch.object(dash, "logger"):
        dash._check_scheduler_heartbeat()

    mrestart.assert_not_called()
    fake_state.seconds_since_last_scheduler_execution.assert_not_called()


# ============================================================
# state.seconds_since_last_scheduler_execution — DB-derived liveness helper
# ============================================================


def test_recency_helper_returns_age_float():
    """Returns the EXTRACT(EPOCH ...) age as a float when a row exists."""
    import triggers.state as state_mod

    conn = MagicMock()
    conn.cursor.return_value.fetchone.return_value = [42.5]
    store = MagicMock()
    store._get_conn.return_value = conn

    ts = state_mod.TriggerState.__new__(state_mod.TriggerState)
    with patch.object(ts, "_get_store", return_value=store):
        age = ts.seconds_since_last_scheduler_execution()

    assert age == 42.5
    store._put_conn.assert_called_once_with(conn)


def test_recency_helper_none_on_empty_table():
    """MAX over an empty table is NULL → helper returns None (fail-safe)."""
    import triggers.state as state_mod

    conn = MagicMock()
    conn.cursor.return_value.fetchone.return_value = [None]
    store = MagicMock()
    store._get_conn.return_value = conn

    ts = state_mod.TriggerState.__new__(state_mod.TriggerState)
    with patch.object(ts, "_get_store", return_value=store):
        age = ts.seconds_since_last_scheduler_execution()

    assert age is None


def test_recency_helper_none_on_db_error():
    """Any DB error → None, never an exception (a read failure must not disable
    the watchdog by raising into it)."""
    import triggers.state as state_mod

    conn = MagicMock()
    conn.cursor.return_value.execute.side_effect = RuntimeError("conn dropped")
    store = MagicMock()
    store._get_conn.return_value = conn

    ts = state_mod.TriggerState.__new__(state_mod.TriggerState)
    with patch.object(ts, "_get_store", return_value=store):
        age = ts.seconds_since_last_scheduler_execution()

    assert age is None
    store._put_conn.assert_called_once_with(conn)
