"""SCHEDULER_WATCHDOG_WA_KILL_1 — watchdog log-warning throttle.

Pure unit: patches the watermark fetch, ``restart_scheduler``, and the
module logger; asserts two stale-heartbeat checks within the cooldown
window emit exactly ONE throttled WARN log (replaces the prior WA push
disabled 2026-05-15 per Director directive).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


def _stale_hb(seconds_old: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds_old)


def test_watchdog_alert_throttled():
    """Two stale-heartbeat checks back-to-back → only one throttled WARN log."""
    import outputs.dashboard as dash

    # Reset module state so prior tests don't leak.
    dash._watchdog_last_alert_ts = 0

    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(900)  # 15 min stale

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler"), \
         patch.object(dash, "logger") as fake_logger:
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
    """First WARN + ``cooldown+1 s`` later + second stale check → second WARN."""
    import outputs.dashboard as dash

    dash._watchdog_last_alert_ts = 0

    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(900)

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler"), \
         patch.object(dash, "logger") as fake_logger:
        dash._check_scheduler_heartbeat()
        # Simulate cooldown+1 s elapsed.
        dash._watchdog_last_alert_ts -= dash._watchdog_alert_cooldown_s + 1
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
