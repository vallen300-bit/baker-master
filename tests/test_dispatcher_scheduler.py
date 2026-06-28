from __future__ import annotations

from triggers import embedded_scheduler as sched


def test_dispatcher_tick_default_off(monkeypatch):
    monkeypatch.delenv("DISPATCHER_ENABLED", raising=False)
    assert sched.dispatcher_tick_enabled() is False


def test_dispatcher_tick_enabled_values(monkeypatch):
    monkeypatch.setenv("DISPATCHER_ENABLED", "true")
    assert sched.dispatcher_tick_enabled() is True
    monkeypatch.setenv("DISPATCHER_ENABLED", "yes")
    assert sched.dispatcher_tick_enabled() is True
    monkeypatch.setenv("DISPATCHER_ENABLED", "false")
    assert sched.dispatcher_tick_enabled() is False


def test_dispatcher_tick_interval_bounds(monkeypatch):
    monkeypatch.delenv("DISPATCHER_TICK_MINUTES", raising=False)
    assert sched.dispatcher_tick_interval_seconds() == 15 * 60
    monkeypatch.setenv("DISPATCHER_TICK_MINUTES", "1")
    assert sched.dispatcher_tick_interval_seconds() == 5 * 60
    monkeypatch.setenv("DISPATCHER_TICK_MINUTES", "90")
    assert sched.dispatcher_tick_interval_seconds() == 60 * 60
    monkeypatch.setenv("DISPATCHER_TICK_MINUTES", "bad")
    assert sched.dispatcher_tick_interval_seconds() == 15 * 60
