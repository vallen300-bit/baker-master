"""SCHEDULER_WATCHDOG_FALSE_POSITIVE_FIX_1 — heartbeat writes watermark before probe.

Pure unit: patches the watermark fetch, the held singleton-lock connection on
``triggers.scheduler_lease``, and the in-module ``restart_scheduler`` callsite;
asserts (1) watermark is set even when the probe raises, and (2) probe failure
does NOT trigger ``restart_scheduler()`` from inside the heartbeat job thread.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_watermark_written_before_probe():
    """If the lock-conn probe raises, the watermark is STILL written."""
    import triggers.embedded_scheduler as sched

    fake_state = MagicMock()
    fake_conn = MagicMock()
    fake_conn.cursor.return_value.execute.side_effect = ConnectionError("Neon timed out")

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.scheduler_lease._held_conn", fake_conn):
        sched._scheduler_heartbeat()

    fake_state.set_watermark.assert_called_once()
    # Confirms the function fully exited via the post-watermark probe branch
    # (rather than short-circuiting before the watermark write).
    assert fake_conn.cursor.return_value.execute.called


def test_probe_failure_does_not_restart():
    """Probe failure logs WARN but does NOT call restart_scheduler()."""
    import triggers.embedded_scheduler as sched

    fake_state = MagicMock()
    fake_conn = MagicMock()
    fake_conn.cursor.return_value.execute.side_effect = ConnectionError("dead")
    fake_restart = MagicMock()

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.scheduler_lease._held_conn", fake_conn), \
         patch.object(sched, "restart_scheduler", fake_restart):
        sched._scheduler_heartbeat()

    fake_restart.assert_not_called()
    fake_state.set_watermark.assert_called_once()


def test_watermark_written_when_no_held_conn():
    """No held singleton-lock connection → watermark still written, probe skipped."""
    import triggers.embedded_scheduler as sched

    fake_state = MagicMock()

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.scheduler_lease._held_conn", None):
        sched._scheduler_heartbeat()

    fake_state.set_watermark.assert_called_once()
