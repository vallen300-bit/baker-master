"""SCHEDULER_WATCHDOG_WA_KILL_1 — watchdog log-warning throttle.

Pure unit: patches the watermark fetch, ``restart_scheduler``, and the
module logger; asserts two stale-heartbeat checks within the cooldown
window emit exactly ONE throttled WARN log (replaces the prior WA push
disabled 2026-05-15 per Director directive).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_watchdog_state():
    """Keep all watchdog module globals hermetic per test.

    SCHEDULER_STALL_CODEFIX_1 added ``_watchdog_restart_failed_streak`` (drives the
    os._exit backstop). Reset it too so a leaked streak from a prior test can never
    push these 2-restart tests over the exit threshold and kill the runner.
    """
    import outputs.dashboard as dash
    dash._watchdog_last_alert_ts = 0
    dash._watchdog_consecutive_stale = 0
    dash._watchdog_restart_failed_streak = 0
    yield


def _stale_hb(seconds_old: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds_old)


def test_watchdog_alert_throttled():
    """Two stale-heartbeat checks back-to-back → only one throttled WARN log.

    FALSE_POSITIVE_FIX_1: the gate now requires TWO stale reads before each
    restart, so to land 2 WARN events we need 4 stale reads (2 restarts), with
    cooldown advanced between them.
    """
    import outputs.dashboard as dash

    # Reset module state so prior tests don't leak.
    dash._watchdog_last_alert_ts = 0
    dash._watchdog_consecutive_stale = 0

    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(900)  # 15 min stale

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler"), \
         patch.object(dash, "logger") as fake_logger:
        # 2 stale reads → first restart fires + first WARN
        dash._check_scheduler_heartbeat()
        dash._check_scheduler_heartbeat()
        # 2 more stale reads inside cooldown window → second restart, WARN throttled
        dash._check_scheduler_heartbeat()
        dash._check_scheduler_heartbeat()

    warn_calls = [
        c for c in fake_logger.warning.call_args_list
        if "WATCHDOG_RESTART" in c.args[0]
    ]
    assert len(warn_calls) == 1, (
        f"expected throttled to 1 WARN, got {len(warn_calls)}"
    )


def test_watchdog_alert_fires_again_after_cooldown():
    """First WARN + ``cooldown+1 s`` later + second stale check → second WARN.

    FALSE_POSITIVE_FIX_1: each restart now needs 2 consecutive stale reads.
    """
    import outputs.dashboard as dash

    dash._watchdog_last_alert_ts = 0
    dash._watchdog_consecutive_stale = 0

    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(900)

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler"), \
         patch.object(dash, "logger") as fake_logger:
        # First restart: 2 stale reads.
        dash._check_scheduler_heartbeat()
        dash._check_scheduler_heartbeat()
        # Simulate cooldown+1 s elapsed.
        dash._watchdog_last_alert_ts -= dash._watchdog_alert_cooldown_s + 1
        # Second restart: 2 more stale reads (counter was reset post-restart).
        dash._check_scheduler_heartbeat()
        dash._check_scheduler_heartbeat()

    warn_calls = [
        c for c in fake_logger.warning.call_args_list
        if "WATCHDOG_RESTART" in c.args[0]
    ]
    assert len(warn_calls) == 2


def test_watchdog_no_alert_when_heartbeat_fresh():
    """Fresh heartbeat → no restart, no WARN."""
    import outputs.dashboard as dash

    dash._watchdog_last_alert_ts = 0
    dash._watchdog_consecutive_stale = 0

    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(60)  # 1 min — fresh
    fake_restart = MagicMock()

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler", fake_restart), \
         patch.object(dash, "logger") as fake_logger:
        dash._check_scheduler_heartbeat()

    warn_calls = [
        c for c in fake_logger.warning.call_args_list
        if "WATCHDOG_RESTART" in c.args[0]
    ]
    assert fake_restart.call_count == 0
    assert len(warn_calls) == 0


# ---------- FALSE_POSITIVE_FIX_1: 2-consecutive-stale gate ----------


def test_single_stale_does_not_restart():
    """One stale read → wait, no restart."""
    import outputs.dashboard as dash

    dash._watchdog_last_alert_ts = 0
    dash._watchdog_consecutive_stale = 0

    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(900)
    fake_restart = MagicMock()

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler", fake_restart):
        dash._check_scheduler_heartbeat()

    fake_restart.assert_not_called()
    assert dash._watchdog_consecutive_stale == 1


def test_two_consecutive_stale_restart():
    """Two stale reads → restart fires + counter resets."""
    import outputs.dashboard as dash

    dash._watchdog_last_alert_ts = 0
    dash._watchdog_consecutive_stale = 0

    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(900)
    fake_restart = MagicMock()

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler", fake_restart):
        dash._check_scheduler_heartbeat()
        dash._check_scheduler_heartbeat()

    fake_restart.assert_called_once()
    assert dash._watchdog_consecutive_stale == 0  # reset post-restart


def test_fresh_read_resets_counter():
    """Stale-then-fresh-read → counter reset, no restart."""
    import outputs.dashboard as dash

    dash._watchdog_last_alert_ts = 0
    dash._watchdog_consecutive_stale = 1

    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(60)  # fresh
    fake_restart = MagicMock()

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler", fake_restart):
        dash._check_scheduler_heartbeat()

    fake_restart.assert_not_called()
    assert dash._watchdog_consecutive_stale == 0
