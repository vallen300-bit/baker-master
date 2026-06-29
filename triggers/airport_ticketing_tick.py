"""Scheduler wrapper for Airport Ticketing Bridge."""
from __future__ import annotations


def run_airport_ticketing_tick() -> None:
    from orchestrator.airport_ticketing_bridge import run_tick

    run_tick()
