"""Scheduler wrapper for Dispatcher ClickUp-to-bus relay."""
from __future__ import annotations


def run_dispatcher_tick() -> None:
    from orchestrator.dispatcher_relay import run_tick

    run_tick()
