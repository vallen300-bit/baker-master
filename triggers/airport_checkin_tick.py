"""Scheduler wrapper for the Airport check-in reader + TTL nudge sweep."""
from __future__ import annotations


def run_airport_checkin_tick() -> None:
    from orchestrator.airport_checkin_reader import run_checkin_sweep

    run_checkin_sweep()
