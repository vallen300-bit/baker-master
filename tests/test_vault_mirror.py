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

    Architect+AH2 LOW slack-bump (2026-05-12 PR #193 follow-up): 0.1s
    interval / 1.0s wait / >=3 calls — gives the loop 10 nominal ticks of
    headroom on slow CI hosts, asserting only the lower bound that proves
    the loop is firing on cadence (not just once).
    """
    with patch.object(vault_mirror, "sync_tick") as mock_tick:
        vault_mirror.start_sync_thread(interval_seconds=0.1)
        time.sleep(1.0)
        vault_mirror.stop_sync_thread(timeout=2.0)
    assert mock_tick.call_count >= 3, (
        f"expected sync_tick to fire at least 3x at 0.1s interval over 1.0s, "
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


def test_start_sync_thread_concurrent_idempotent():
    """Concurrent ``start_sync_thread`` racers must spawn exactly one thread.

    Architect LOW L4 (PR #193 follow-up): the idempotency guard reads
    ``_sync_thread is not None and is_alive()`` then writes ``_sync_thread``;
    without the surrounding ``_sync_thread_lock`` two racers landing between
    the check and the assignment would each spawn. ``threading.Barrier`` pins
    them to the same wall-clock instant; 20 iterations gives the scheduler
    enough chances to interleave the racing threads.
    """
    for _ in range(20):
        # Clear any prior thread state so each iteration races from a
        # clean module-global. The fixture's stop+reset only runs at
        # function-end.
        vault_mirror.stop_sync_thread(timeout=2.0)
        vault_mirror._sync_thread = None
        vault_mirror._sync_thread_stop.clear()

        barrier = threading.Barrier(2)
        spawned: list[threading.Thread] = []
        spawn_lock = threading.Lock()

        def _racer():
            barrier.wait()
            with patch.object(vault_mirror, "sync_tick"):
                thread = vault_mirror.start_sync_thread(interval_seconds=60)
            with spawn_lock:
                spawned.append(thread)

        a = threading.Thread(target=_racer)
        b = threading.Thread(target=_racer)
        a.start()
        b.start()
        a.join(timeout=5.0)
        b.join(timeout=5.0)

        assert len(spawned) == 2, "both racers must return a thread handle"
        assert spawned[0] is spawned[1], (
            "concurrent start_sync_thread must return the same Thread "
            "instance — _sync_thread_lock serialized the spawn"
        )
        # Module-global must equal the single spawned thread (no orphan).
        assert vault_mirror._sync_thread is spawned[0]
        assert spawned[0].is_alive()


def test_stop_sync_thread_does_not_block_concurrent_start():
    """Concurrent ``start_sync_thread`` must not wait on stop's join.

    Fix 1 (VAULT_MIRROR_THREAD_LIFECYCLE_HYGIENE_1 / PR #195 follow-up
    L1): ``stop_sync_thread`` detaches ``_sync_thread = None`` inside
    the lock and joins the local handle OUTSIDE the lock. A concurrent
    ``start_sync_thread`` therefore acquires the lock right after the
    detach, observes ``_sync_thread is None``, and spawns a fresh thread
    without waiting for the (potentially up-to-``timeout``-seconds) join.

    Test pins this property by making ``sync_tick`` block until released,
    forcing the stop's join to wait. While the join is in flight, the
    concurrent start must come back fast and with a NEW thread instance
    (not the dying one).
    """
    tick_started = threading.Event()
    tick_release = threading.Event()

    def _slow_tick():
        tick_started.set()
        # Block until released — simulates a slow git pull mid-join.
        tick_release.wait(timeout=5.0)

    try:
        with patch.object(vault_mirror, "sync_tick", side_effect=_slow_tick):
            thread_a = vault_mirror.start_sync_thread(interval_seconds=0.01)
            assert tick_started.wait(timeout=2.0), (
                "thread A never entered sync_tick"
            )

            start_thread_holder: list[threading.Thread] = []
            start_elapsed_ms: list[float] = []
            start_done = threading.Event()

            def _stop_runner():
                vault_mirror.stop_sync_thread(timeout=5.0)

            def _start_runner():
                # Brief sleep to let stop acquire+release lock + detach
                # before this racer tries to spawn.
                time.sleep(0.02)
                t0 = time.monotonic()
                thread_b = vault_mirror.start_sync_thread(interval_seconds=60)
                start_elapsed_ms.append((time.monotonic() - t0) * 1000.0)
                start_thread_holder.append(thread_b)
                start_done.set()

            s_thread = threading.Thread(target=_stop_runner)
            st_thread = threading.Thread(target=_start_runner)
            s_thread.start()
            st_thread.start()

            assert start_done.wait(timeout=2.0), (
                "start_sync_thread never returned — likely blocked on join"
            )

            # CI-safety pad over brief's 50ms target — the property
            # under test is "lock released before join" which translates
            # to <1ms in the ideal case; anything below ~200ms proves we
            # are not waiting on the up-to-5s join. Anything above 1s
            # means the lock was held across join (regression).
            assert start_elapsed_ms[0] < 200.0, (
                "start_sync_thread blocked on stop's join: "
                f"{start_elapsed_ms[0]:.1f}ms (regression: lock held "
                "across join)"
            )
            assert start_thread_holder[0] is not thread_a, (
                "start_sync_thread should return a NEW thread instance, "
                "not the dying handle A"
            )

            # Release the slow sync_tick so thread A can exit and stop's
            # join completes before fixture teardown.
            tick_release.set()
            s_thread.join(timeout=5.0)
            st_thread.join(timeout=5.0)
    finally:
        tick_release.set()


def test_per_thread_stop_event_isolation():
    """Fresh ``threading.Event`` per spawn — no cross-instance leakage.

    Fix 1 (VAULT_MIRROR_THREAD_LIFECYCLE_HYGIENE_1): each
    ``start_sync_thread`` allocates a NEW ``_sync_thread_stop`` Event and
    passes it into ``_sync_loop`` via args. A successor thread therefore
    listens to its own event; setting the predecessor's old event does
    not also stop the successor.

    Pre-fix failure mode: module-level Event was shared. Sequence
    ``start → stop → start → set old event`` would have signalled the
    NEW thread to exit because both shared the same Event instance.
    """
    with patch.object(vault_mirror, "sync_tick"):
        thread_a = vault_mirror.start_sync_thread(interval_seconds=0.05)
        event_a = vault_mirror._sync_thread_stop

        vault_mirror.stop_sync_thread(timeout=2.0)
        # A exited because stop_sync_thread set event_a.
        thread_a.join(timeout=2.0)
        assert not thread_a.is_alive(), "A should have exited after stop"

        thread_b = vault_mirror.start_sync_thread(interval_seconds=0.05)
        event_b = vault_mirror._sync_thread_stop

        assert event_a is not event_b, (
            "successor must have its OWN Event instance — pre-fix would "
            "share one module global"
        )

        # Setting the PRIOR event must not stop B.
        event_a.set()
        time.sleep(0.2)
        assert thread_b.is_alive(), (
            "B was stopped by predecessor's event — cross-instance signal "
            "leakage (regression)"
        )

        # Setting B's own event DOES stop B.
        event_b.set()
        thread_b.join(timeout=2.0)
        assert not thread_b.is_alive()


def test_mirror_status_toctou_safety():
    """``mirror_status`` must not raise under concurrent stop/start churn.

    Fix 2 (VAULT_MIRROR_THREAD_LIFECYCLE_HYGIENE_1 / PR #195 follow-up
    L2): ``mirror_status`` snapshots ``_sync_thread`` to a local before
    calling ``.is_alive()``. Without the snapshot a concurrent
    ``stop_sync_thread`` nulling ``_sync_thread`` between the
    is-not-None check and the is_alive() call raises AttributeError,
    swallowed by /health's outer try/except → one-poll false-negative
    for ``vault_sync_thread_alive``.

    Tight loop pits a poller against a stop+start churner for 500
    iterations. Must surface zero AttributeErrors and always return a
    bool.
    """
    iterations = 500
    with patch.object(vault_mirror, "sync_tick"):
        vault_mirror.start_sync_thread(interval_seconds=60)

        observations: list[object] = []
        errors: list[BaseException] = []
        stop_polling = threading.Event()

        def _poller():
            while not stop_polling.is_set():
                try:
                    status = vault_mirror.mirror_status()
                    observations.append(status["vault_sync_thread_alive"])
                except BaseException as exc:  # noqa: BLE001 — capture for assert
                    errors.append(exc)

        def _churner():
            for _ in range(iterations):
                vault_mirror.stop_sync_thread(timeout=2.0)
                vault_mirror.start_sync_thread(interval_seconds=60)

        poll_thread = threading.Thread(target=_poller)
        churn_thread = threading.Thread(target=_churner)
        poll_thread.start()
        churn_thread.start()

        churn_thread.join(timeout=30.0)
        assert not churn_thread.is_alive(), "churner stalled past 30s"
        stop_polling.set()
        poll_thread.join(timeout=5.0)

    assert not errors, (
        f"mirror_status raised under TOCTOU race: {errors[:3]} "
        f"(regression: lost local-snapshot guard)"
    )
    assert observations, "poller never observed a status"
    assert all(isinstance(v, bool) for v in observations), (
        "vault_sync_thread_alive must always be a bool — got "
        f"non-bool in sample: {[v for v in observations if not isinstance(v, bool)][:3]}"
    )


def test_mirror_status_exposes_thread_liveness():
    """``mirror_status`` must surface ``vault_sync_thread_alive`` for /health.

    Part A of VAULT_MIRROR_NON_LOCK_REPLICA_HOTFIX_1: the diagnostic
    primitive. Production telemetry showed non-lock replica's mirror
    silently stuck at startup-clone state; the new bool lets operators
    distinguish thread-None / thread-not-alive / thread-alive-but-stale.
    """
    # No thread: must be False.
    vault_mirror.stop_sync_thread(timeout=2.0)
    vault_mirror._sync_thread = None
    status = vault_mirror.mirror_status()
    assert "vault_sync_thread_alive" in status, (
        "mirror_status() must surface the new liveness key"
    )
    assert status["vault_sync_thread_alive"] is False

    # Live thread: must be True.
    with patch.object(vault_mirror, "sync_tick"):
        vault_mirror.start_sync_thread(interval_seconds=60)
        status = vault_mirror.mirror_status()
    assert status["vault_sync_thread_alive"] is True
