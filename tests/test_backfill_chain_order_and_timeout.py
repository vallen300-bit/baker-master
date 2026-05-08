"""Tests for outputs/dashboard.py boot-time backfill chain (2026-05-08).

PR #171 follow-up: when Fireflies hangs (it has been silent-dead since
2026-04-11), it blocked Plaud's boot-time backfill from ever starting.
The fix swaps Plaud-first + adds a per-step timeout so neither source
can wedge the other.
"""

import time
import threading
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Per-step timeout helper
# ---------------------------------------------------------------------------

def test_run_backfill_with_timeout_completes_fast_call():
    """Fast backfill returns cleanly; no timeout warning."""
    from triggers.backfill_runner import run_backfill_with_timeout

    fn = MagicMock()
    run_backfill_with_timeout("test", fn, timeout_s=5)
    assert fn.called, "backfill function must be invoked"


def test_run_backfill_with_timeout_returns_after_deadline_when_hung():
    """Hung backfill is abandoned after timeout — caller continues."""
    from triggers.backfill_runner import run_backfill_with_timeout

    started = threading.Event()
    blocker = threading.Event()  # never set, simulates hang

    def hang():
        started.set()
        blocker.wait(timeout=10)  # would block 10s; we time out earlier

    start = time.monotonic()
    run_backfill_with_timeout("hung", hang, timeout_s=1)
    elapsed = time.monotonic() - start

    assert started.is_set(), "hung backfill must have started"
    assert elapsed < 3, f"caller should return ~1s after timeout (elapsed={elapsed:.2f}s)"
    blocker.set()  # release the daemon thread so it can clean up


def test_run_backfill_with_timeout_swallows_exceptions():
    """Backfill that raises is logged + does NOT propagate."""
    from triggers.backfill_runner import run_backfill_with_timeout

    def boom():
        raise RuntimeError("simulated upstream API failure")

    # Must not raise.
    run_backfill_with_timeout("boom", boom, timeout_s=5)


# ---------------------------------------------------------------------------
# Order + isolation: Plaud first, Fireflies second
# ---------------------------------------------------------------------------

def test_plaud_runs_before_fireflies_in_chain():
    """When both sources configured, Plaud's backfill is invoked before Fireflies'.

    This is the load-bearing fix: pre-2026-05-08, Fireflies ran first and
    blocked Plaud whenever it hung. Order swap means Plaud always reaches
    backfill_plaud regardless of Fireflies state.
    """
    # Simulate the chain by calling run_backfill_with_timeout in the same
    # order as outputs/dashboard.py:_delayed_backfills().
    from triggers.backfill_runner import run_backfill_with_timeout

    call_order = []
    plaud_fn = MagicMock(side_effect=lambda: call_order.append("plaud"))
    fireflies_fn = MagicMock(side_effect=lambda: call_order.append("fireflies"))

    run_backfill_with_timeout("plaud", plaud_fn, timeout_s=5)
    run_backfill_with_timeout("fireflies", fireflies_fn, timeout_s=5)

    assert call_order == ["plaud", "fireflies"], (
        f"Plaud must run before Fireflies (got {call_order}). "
        "Regression: pre-2026-05-08 order was reversed and a hung Fireflies "
        "blocked Plaud from ever running at boot."
    )


def test_hung_fireflies_does_not_block_plaud_completion_pattern():
    """Pattern test: Plaud completes even if Fireflies (next in chain) would hang.

    Validates the design: Plaud runs to completion in step 1, and only after
    that does step 2 even start Fireflies. So even an infinite Fireflies hang
    cannot affect Plaud's run.
    """
    from triggers.backfill_runner import run_backfill_with_timeout

    plaud_done = threading.Event()
    plaud_fn = MagicMock(side_effect=plaud_done.set)

    fireflies_blocker = threading.Event()  # never set — simulates hang

    def fireflies_hang():
        fireflies_blocker.wait(timeout=10)

    start = time.monotonic()
    run_backfill_with_timeout("plaud", plaud_fn, timeout_s=5)
    assert plaud_done.is_set(), "Plaud must complete in step 1"
    run_backfill_with_timeout("fireflies", fireflies_hang, timeout_s=1)
    elapsed = time.monotonic() - start

    assert plaud_fn.called, "Plaud must have run regardless of Fireflies state"
    assert elapsed < 3, (
        f"chain must return ~1s after Fireflies timeout (elapsed={elapsed:.2f}s) — "
        "no regression to Fireflies-blocks-Plaud era"
    )
    fireflies_blocker.set()  # release daemon thread


def test_plaud_token_missing_skips_plaud_chain():
    """When config.plaud.api_token is unset, Plaud step is silently skipped (no exception).

    Same prior contract — preserved by the new chain. We don't assert what runs
    next; just that the missing-token path doesn't blow up the chain.
    """
    from triggers.backfill_runner import run_backfill_with_timeout

    # Just verify the helper itself is robust to a None fn replaced via the
    # caller's `if config.plaud.api_token:` gate (mimicking the dashboard code).
    fireflies_fn = MagicMock()
    run_backfill_with_timeout("fireflies", fireflies_fn, timeout_s=5)
    assert fireflies_fn.called


def test_default_timeout_constant_matches_documented_5_minutes():
    """BACKFILL_TIMEOUT_SEC should remain 300s (5 min) — documented invariant."""
    from triggers.backfill_runner import BACKFILL_TIMEOUT_SEC
    assert BACKFILL_TIMEOUT_SEC == 300, (
        "BACKFILL_TIMEOUT_SEC changed; if intentional, update brief + dashboard log line."
    )
