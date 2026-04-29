"""SCHEDULER_SINGLETON_HARDEN_1 — watchdog WhatsApp-alert throttle.

Pure unit: patches ``send_whatsapp``, the watermark fetch, and
``restart_scheduler``; asserts two stale-heartbeat checks within the
cooldown window send exactly ONE WA alert.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


def _stale_hb(seconds_old: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds_old)


def test_watchdog_alert_throttled():
    """Two stale-heartbeat checks back-to-back → only one WA alert."""
    import outputs.dashboard as dash

    # Reset module state so prior tests don't leak.
    dash._watchdog_last_alert_ts = 0

    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(900)  # 15 min stale

    fake_wa = MagicMock()

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler"), \
         patch("outputs.whatsapp_sender.send_whatsapp", fake_wa):
        dash._check_scheduler_heartbeat()
        dash._check_scheduler_heartbeat()

    assert fake_wa.call_count == 1, (
        f"expected throttled to 1 alert, got {fake_wa.call_count}"
    )


def test_watchdog_alert_fires_again_after_cooldown():
    """First alert + ``cooldown+1 s`` later + second stale check → second alert."""
    import outputs.dashboard as dash

    dash._watchdog_last_alert_ts = 0

    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(900)
    fake_wa = MagicMock()

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler"), \
         patch("outputs.whatsapp_sender.send_whatsapp", fake_wa):
        dash._check_scheduler_heartbeat()
        # Simulate cooldown+1 s elapsed.
        dash._watchdog_last_alert_ts -= dash._watchdog_alert_cooldown_s + 1
        dash._check_scheduler_heartbeat()

    assert fake_wa.call_count == 2


def test_watchdog_no_alert_when_heartbeat_fresh():
    """Fresh heartbeat → no restart, no alert."""
    import outputs.dashboard as dash

    dash._watchdog_last_alert_ts = 0

    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(60)  # 1 min — fresh
    fake_wa = MagicMock()
    fake_restart = MagicMock()

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler", fake_restart), \
         patch("outputs.whatsapp_sender.send_whatsapp", fake_wa):
        dash._check_scheduler_heartbeat()

    assert fake_restart.call_count == 0
    assert fake_wa.call_count == 0
