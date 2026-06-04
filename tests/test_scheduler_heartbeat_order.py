"""SCHEDULER_WATCHDOG_FALSE_POSITIVE_FIX_1 — heartbeat writes watermark before probe.

Pure unit: patches the watermark fetch, the held singleton-lock connection on
``triggers.scheduler_lease``, and the in-module ``restart_scheduler`` callsite;
asserts (1) watermark is set even when the probe raises, and (2) probe failure
does NOT trigger ``restart_scheduler()`` from inside the heartbeat job thread.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_watermark_written_before_probe():
    """If the lock-conn probe raises, the watermark is STILL written.

    SCHEDULER_NEON_IDLE_HARDEN_1: the probe failure now routes into reacquire
    (mocked here to stay hermetic); the watermark write precedes it.
    """
    import triggers.embedded_scheduler as sched
    import triggers.scheduler_lease as lease

    fake_state = MagicMock()
    fake_conn = MagicMock()
    fake_conn.cursor.return_value.execute.side_effect = ConnectionError("Neon timed out")
    mre = MagicMock(return_value=lease.REACQUIRE_REOWNED)

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.scheduler_lease._held_conn", fake_conn), \
         patch("triggers.scheduler_lease.reacquire_singleton_lock", mre):
        sched._scheduler_heartbeat()

    fake_state.set_watermark.assert_called_once()
    # Confirms the function fully exited via the post-watermark probe branch
    # (rather than short-circuiting before the watermark write).
    assert fake_conn.cursor.return_value.execute.called
    mre.assert_called_once()


def test_probe_failure_does_not_restart():
    """Probe failure self-heals via reacquire but NEVER calls restart from the job thread."""
    import triggers.embedded_scheduler as sched
    import triggers.scheduler_lease as lease

    fake_state = MagicMock()
    fake_conn = MagicMock()
    fake_conn.cursor.return_value.execute.side_effect = ConnectionError("dead")
    fake_restart = MagicMock()
    mre = MagicMock(return_value=lease.REACQUIRE_TRANSIENT)

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.scheduler_lease._held_conn", fake_conn), \
         patch("triggers.scheduler_lease.reacquire_singleton_lock", mre), \
         patch.object(sched, "restart_scheduler", fake_restart):
        sched._scheduler_heartbeat()

    fake_restart.assert_not_called()
    fake_state.set_watermark.assert_called_once()


def test_watermark_written_when_no_held_conn():
    """No held singleton-lock connection → watermark still written.

    SCHEDULER_NEON_IDLE_HARDEN_1 (codex #1872): ``_held_conn is None`` now ROUTES
    INTO reacquire (an active scheduler that lost its conn must recover or stand
    down), it does NOT skip. Watermark is still written FIRST. Reacquire is mocked
    here to keep the unit hermetic (no DB).
    """
    import triggers.embedded_scheduler as sched
    import triggers.scheduler_lease as lease

    fake_state = MagicMock()
    mre = MagicMock(return_value=lease.REACQUIRE_TRANSIENT)

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.scheduler_lease._held_conn", None), \
         patch("triggers.scheduler_lease.reacquire_singleton_lock", mre):
        sched._scheduler_heartbeat()

    fake_state.set_watermark.assert_called_once()
    mre.assert_called_once()  # routed to reacquire, not skipped
