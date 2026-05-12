"""Tests for vault_mirror per-process sync thread.

Regression coverage for VAULT_MIRROR_SYNC_TICK_DIAGNOSE_1 (2026-05-13):
the prior APScheduler ``vault_sync_tick`` job was registered inside the
singleton-locked scheduler in ``triggers.embedded_scheduler``. On Render's
multi-replica deploy only the lock-holding replica ran the job, leaving
every other replica's local FS mirror stale at the startup-clone state.
The fix moves the refresh to a per-process daemon thread spawned in
``vault_mirror.start_sync_thread`` at FastAPI startup — every replica
refreshes its own mirror independently of the scheduler singleton.
"""
from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest

import vault_mirror


@pytest.fixture(autouse=True)
def _reset_sync_thread_state():
    """Stop any running sync thread after each test and reset module globals."""
    yield
    vault_mirror.stop_sync_thread(timeout=2.0)
    vault_mirror._sync_thread = None
    vault_mirror._sync_thread_stop.clear()


def test_start_sync_thread_returns_live_daemon_thread():
    """start_sync_thread spawns a live daemon thread."""
    with patch.object(vault_mirror, "sync_tick"):
        thread = vault_mirror.start_sync_thread(interval_seconds=60)
    assert thread.is_alive()
    assert thread.daemon is True
    assert thread.name == "vault_mirror_sync"


def test_start_sync_thread_idempotent():
    """Second start_sync_thread call returns the SAME live thread (no double-spawn)."""
    with patch.object(vault_mirror, "sync_tick"):
        first = vault_mirror.start_sync_thread(interval_seconds=60)
        second = vault_mirror.start_sync_thread(interval_seconds=60)
    assert first is second
    assert first.is_alive()


def test_sync_thread_invokes_sync_tick_on_interval():
    """The loop must actually call sync_tick on the configured cadence.

    This is the regression: prior APScheduler wiring was registered but
    silent on N-1 replicas. The new thread must fire ``sync_tick`` on
    every replica it runs in.
    """
    with patch.object(vault_mirror, "sync_tick") as mock_tick:
        vault_mirror.start_sync_thread(interval_seconds=0.05)
        # Allow at least 3 ticks (0.05s * 3 = 0.15s + slack).
        time.sleep(0.4)
        vault_mirror.stop_sync_thread(timeout=2.0)
    assert mock_tick.call_count >= 2, (
        f"expected sync_tick to fire at least 2x at 0.05s interval, "
        f"got {mock_tick.call_count}"
    )


def test_stop_sync_thread_joins_and_clears():
    """stop_sync_thread must signal the loop to exit and clear the handle."""
    with patch.object(vault_mirror, "sync_tick"):
        thread = vault_mirror.start_sync_thread(interval_seconds=0.05)
        assert thread.is_alive()
        vault_mirror.stop_sync_thread(timeout=2.0)
    assert not thread.is_alive()
    assert vault_mirror._sync_thread is None


def test_sync_loop_swallows_sync_tick_exceptions():
    """An unexpected raise inside sync_tick must NOT kill the loop.

    ``sync_tick`` already WARN-logs pull failures, but defensive
    swallowing here protects against unanticipated raises (git missing,
    disk full, etc.). If the loop died silently we'd be back in the
    "registered but silent" failure mode.
    """
    call_count = {"n": 0}

    def _raising_tick():
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated unexpected raise")

    with patch.object(vault_mirror, "sync_tick", side_effect=_raising_tick):
        vault_mirror.start_sync_thread(interval_seconds=0.05)
        time.sleep(0.3)
        vault_mirror.stop_sync_thread(timeout=2.0)

    # Loop survived the first-tick exception and kept firing.
    assert call_count["n"] >= 2, (
        f"loop should survive sync_tick raise, got {call_count['n']} calls"
    )


def test_vault_sync_tick_no_longer_registered_in_scheduler():
    """Regression: the singleton scheduler MUST NOT register vault_sync_tick.

    Previously ``_register_jobs`` added a ``vault_sync_tick`` IntervalTrigger
    job; on multi-replica deploys only the lock-holding replica ran it, so
    N-1 replicas served stale baker_vault_read results. The diagnose-fix
    moved the refresh to a per-process daemon thread. Pin the structural
    change so a future refactor doesn't accidentally re-add the singleton-
    scoped job.

    Reads the source file as text rather than importing the module — keeps
    the regression assertion runnable without the APScheduler dependency.
    """
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    source = (repo_root / "triggers" / "embedded_scheduler.py").read_text(
        encoding="utf-8"
    )
    assert 'id="vault_sync_tick"' not in source, (
        "vault_sync_tick must not be re-added to the singleton scheduler — "
        "use vault_mirror.start_sync_thread instead (per-process)."
    )
    assert "_vault_sync_tick_job" not in source, (
        "_vault_sync_tick_job wrapper removed alongside the job registration."
    )


def test_module_exports_lifecycle_api():
    """start_sync_thread + stop_sync_thread must be public on the module."""
    assert callable(vault_mirror.start_sync_thread)
    assert callable(vault_mirror.stop_sync_thread)
