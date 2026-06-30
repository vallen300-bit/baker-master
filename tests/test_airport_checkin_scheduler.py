"""BOX5_RECEIPT_TTL_1 — scheduler-gate tests for the check-in sweep job.

No DB. Proves the dark-ship contract: the job's env gate defaults OFF, parses
truthy values, and the interval is bounded. (Live receipt/nudge behaviour lives
in ``tests/test_airport_checkin_reader.py``.)
"""
from __future__ import annotations

import pytest

from triggers.embedded_scheduler import (
    airport_checkin_tick_enabled,
    airport_checkin_tick_interval_seconds,
)


def test_airport_checkin_disabled_by_default(monkeypatch):
    """AC4 dark-ship: unset flag -> disabled (scheduler logs 'skipping')."""
    monkeypatch.delenv("AIRPORT_CHECKIN_SWEEP_ENABLED", raising=False)
    assert airport_checkin_tick_enabled() is False


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1", True), ("true", True), ("TRUE", True), ("yes", True),
        ("on", True), ("On", True),
        ("0", False), ("false", False), ("no", False), ("", False),
        ("maybe", False),
    ],
)
def test_airport_checkin_enabled_values(monkeypatch, value, expected):
    monkeypatch.setenv("AIRPORT_CHECKIN_SWEEP_ENABLED", value)
    assert airport_checkin_tick_enabled() is expected


def test_airport_checkin_interval_bounds(monkeypatch):
    """Default 10 min; clamped to [5, 60] min; non-int falls back to default."""
    monkeypatch.delenv("AIRPORT_CHECKIN_SWEEP_MINUTES", raising=False)
    assert airport_checkin_tick_interval_seconds() == 600  # default 10 min

    monkeypatch.setenv("AIRPORT_CHECKIN_SWEEP_MINUTES", "1")
    assert airport_checkin_tick_interval_seconds() == 300  # clamped up to 5 min

    monkeypatch.setenv("AIRPORT_CHECKIN_SWEEP_MINUTES", "999")
    assert airport_checkin_tick_interval_seconds() == 3600  # clamped down to 60 min

    monkeypatch.setenv("AIRPORT_CHECKIN_SWEEP_MINUTES", "not-an-int")
    assert airport_checkin_tick_interval_seconds() == 600  # fallback
