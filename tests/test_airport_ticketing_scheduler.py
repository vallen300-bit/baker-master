from __future__ import annotations

from triggers import embedded_scheduler as sched


def test_airport_ticketing_tick_default_off(monkeypatch):
    monkeypatch.delenv("AIRPORT_TICKETING_BRIDGE_ENABLED", raising=False)
    assert sched.airport_ticketing_tick_enabled() is False


def test_airport_ticketing_tick_enabled_values(monkeypatch):
    monkeypatch.setenv("AIRPORT_TICKETING_BRIDGE_ENABLED", "true")
    assert sched.airport_ticketing_tick_enabled() is True
    monkeypatch.setenv("AIRPORT_TICKETING_BRIDGE_ENABLED", "yes")
    assert sched.airport_ticketing_tick_enabled() is True
    monkeypatch.setenv("AIRPORT_TICKETING_BRIDGE_ENABLED", "false")
    assert sched.airport_ticketing_tick_enabled() is False


def test_airport_ticketing_tick_interval_bounds(monkeypatch):
    monkeypatch.delenv("AIRPORT_TICKETING_TICK_MINUTES", raising=False)
    assert sched.airport_ticketing_tick_interval_seconds() == 10 * 60
    monkeypatch.setenv("AIRPORT_TICKETING_TICK_MINUTES", "1")
    assert sched.airport_ticketing_tick_interval_seconds() == 5 * 60
    monkeypatch.setenv("AIRPORT_TICKETING_TICK_MINUTES", "90")
    assert sched.airport_ticketing_tick_interval_seconds() == 60 * 60
    monkeypatch.setenv("AIRPORT_TICKETING_TICK_MINUTES", "bad")
    assert sched.airport_ticketing_tick_interval_seconds() == 10 * 60
