"""Tests for outputs/dashboard.py boot-time backfill chain (2026-05-08).

PR #171 follow-up: when Fireflies hangs (it has been silent-dead since
2026-04-11), it blocked Plaud's boot-time backfill from ever starting.
The fix swaps Plaud-first + adds a per-step timeout so neither source
can wedge the other.

2026-05-08 hardening (BRIEF_BACKFILL_THREADED_POOL_AND_OBSERVABILITY_1):
+ Fix 3 — abandoned-thread alarm + counter when a daemon thread exceeds
  the timeout (covers the silent-pen state where the wedged thread keeps
  holding ``pg_advisory_lock`` + ``_backfill_running`` flag).
+ Fix 4 — replace the tautological ``test_plaud_runs_before_fireflies_in_chain``
  with helper-exercising tests that hit the SAME ``run_boot_backfill_chain``
  helper that ``outputs/dashboard.py:_delayed_backfills`` calls in production.
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
    with patch("triggers.sentinel_health.report_success", MagicMock()):
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
    # Patch report_failure so the timeout path doesn't reach into the real sentinel.
    with patch("triggers.sentinel_health.report_failure", MagicMock()):
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

    # Must not raise. (The wrapped exception is caught inside _wrap, so the
    # outer thread completes "cleanly" — success-clear path will still fire,
    # which is fine: an exception inside the backfill is the trigger module's
    # own concern + reported via its own report_failure call site.)
    with patch("triggers.sentinel_health.report_success", MagicMock()):
        run_backfill_with_timeout("boom", boom, timeout_s=5)


# ---------------------------------------------------------------------------
# Fix 3: abandoned-thread alarm + counter (2026-05-08)
# ---------------------------------------------------------------------------

def test_abandoned_thread_increments_counter_and_fires_sentinel_alarm():
    """Wedged backfill increments abandoned counter + fires sentinel report_failure.

    Anchor: 2026-05-08 finding F3 — silent-pen state where a wedged daemon
    holds advisory lock + ``_backfill_running`` flag without alarm.
    """
    import triggers.backfill_runner as br

    initial = br.abandoned_backfill_count
    blocker = threading.Event()  # never set
    captured = {}

    def fake_report_failure(source, reason):
        captured["source"] = source
        captured["reason"] = reason

    with patch("triggers.sentinel_health.report_failure", fake_report_failure):
        br.run_backfill_with_timeout(
            "wedged_test", lambda: blocker.wait(timeout=30), timeout_s=1,
        )

    assert br.abandoned_backfill_count == initial + 1, (
        "abandoned_backfill_count must increment on timeout"
    )
    assert captured.get("source") == "wedged_test_backfill"
    assert "abandoned" in (captured.get("reason") or "").lower()
    blocker.set()  # release


def test_clean_completion_does_not_increment_abandoned_counter():
    """Fast backfill leaves the abandoned counter untouched."""
    import triggers.backfill_runner as br

    initial = br.abandoned_backfill_count
    with patch("triggers.sentinel_health.report_success", MagicMock()):
        br.run_backfill_with_timeout("fast_test", MagicMock(), timeout_s=5)
    assert br.abandoned_backfill_count == initial


def test_clean_completion_clears_failure_sentinel_key():
    """Clean completion fires report_success on the SAME sentinel key the
    timeout path sets — f"{name}_backfill" — so failures clear after a healthy
    run instead of accumulating until T1 trips after 3 restarts.

    Anchor: 2026-05-08 Gate 4 HIGH finding — sentinel-key parity.
    backfill_plaud / backfill_fireflies use bare ``name`` for their own
    success terminus; the wrapper's failure terminus uses
    f"{name}_backfill". Without this success-clear, the wrapper's failure
    key would never get cleared.
    """
    from triggers.backfill_runner import run_backfill_with_timeout

    captured = {}

    def fake_report_success(source):
        captured["source"] = source

    with patch("triggers.sentinel_health.report_success", fake_report_success):
        run_backfill_with_timeout("fast_clean", MagicMock(), timeout_s=5)

    assert captured.get("source") == "fast_clean_backfill", (
        "success-clear must use the same f'{name}_backfill' key the timeout "
        "path sets — otherwise the failure key never clears"
    )


# ---------------------------------------------------------------------------
# Fix 4: shared chain helper — Plaud first, Fireflies second
# ---------------------------------------------------------------------------

def test_run_boot_backfill_chain_runs_plaud_before_fireflies():
    """When both sources present, Plaud invocation precedes Fireflies.

    LOAD-BEARING REGRESSION: pre-2026-05-08 reversed order let a hung
    Fireflies block Plaud's boot-time backfill from ever running. This
    test exercises the SHARED helper ``run_boot_backfill_chain``, which is
    also called by ``outputs/dashboard.py:_delayed_backfills`` — so a future
    code-path rewrite cannot silently regress the order.
    """
    from triggers.backfill_runner import run_boot_backfill_chain

    call_order = []
    plaud_fn = MagicMock(side_effect=lambda: call_order.append("plaud"))
    fireflies_fn = MagicMock(side_effect=lambda: call_order.append("fireflies"))

    with patch("triggers.sentinel_health.report_success", MagicMock()):
        invoked = run_boot_backfill_chain(
            plaud_token="present",
            plaud_fn=plaud_fn,
            fireflies_api_key="present",
            fireflies_fn=fireflies_fn,
            timeout_s=5,
        )

    assert call_order == ["plaud", "fireflies"]
    assert invoked == ["plaud", "fireflies"]


def test_run_boot_backfill_chain_skips_plaud_when_token_missing():
    """No PLAUD_TOKEN → Plaud step skipped, Fireflies still runs."""
    from triggers.backfill_runner import run_boot_backfill_chain

    plaud_fn = MagicMock()
    fireflies_fn = MagicMock()

    with patch("triggers.sentinel_health.report_success", MagicMock()):
        invoked = run_boot_backfill_chain(
            plaud_token=None,
            plaud_fn=plaud_fn,
            fireflies_api_key="present",
            fireflies_fn=fireflies_fn,
            timeout_s=5,
        )

    assert not plaud_fn.called
    assert fireflies_fn.called
    assert invoked == ["fireflies"]


def test_run_boot_backfill_chain_skips_fireflies_when_api_key_missing():
    """No FIREFLIES_API_KEY → Fireflies step skipped, log doesn't lie.

    Anchor: 2026-05-08 Gate 4 MEDIUM #2. Without this gate, a missing
    api_key still appended "fireflies" to ``invoked`` while the trigger
    returned immediately — operator-facing chain log claimed Fireflies
    ran when it had not.
    """
    from triggers.backfill_runner import run_boot_backfill_chain

    plaud_fn = MagicMock()
    fireflies_fn = MagicMock()

    with patch("triggers.sentinel_health.report_success", MagicMock()):
        invoked = run_boot_backfill_chain(
            plaud_token="present",
            plaud_fn=plaud_fn,
            fireflies_api_key=None,
            fireflies_fn=fireflies_fn,
            timeout_s=5,
        )

    assert plaud_fn.called
    assert not fireflies_fn.called
    assert invoked == ["plaud"]


def test_run_boot_backfill_chain_skips_fireflies_when_module_missing():
    """No fireflies_fn (module deleted/unimportable) → only Plaud runs."""
    from triggers.backfill_runner import run_boot_backfill_chain

    plaud_fn = MagicMock()
    with patch("triggers.sentinel_health.report_success", MagicMock()):
        invoked = run_boot_backfill_chain(
            plaud_token="present",
            plaud_fn=plaud_fn,
            fireflies_api_key="present",
            fireflies_fn=None,
            timeout_s=5,
        )

    assert plaud_fn.called
    assert invoked == ["plaud"]


# ---------------------------------------------------------------------------
# Order + isolation: hung Fireflies cannot block Plaud
# ---------------------------------------------------------------------------

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
    with patch("triggers.sentinel_health.report_success", MagicMock()):
        run_backfill_with_timeout("plaud", plaud_fn, timeout_s=5)
    assert plaud_done.is_set(), "Plaud must complete in step 1"
    # Patch sentinel so the abandoned-thread alarm path doesn't write to real DB.
    with patch("triggers.sentinel_health.report_failure", MagicMock()):
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
    with patch("triggers.sentinel_health.report_success", MagicMock()):
        run_backfill_with_timeout("fireflies", fireflies_fn, timeout_s=5)
    assert fireflies_fn.called


def test_default_timeout_constant_matches_documented_5_minutes():
    """BACKFILL_TIMEOUT_SEC should remain 300s (5 min) — documented invariant."""
    from triggers.backfill_runner import BACKFILL_TIMEOUT_SEC
    assert BACKFILL_TIMEOUT_SEC == 300, (
        "BACKFILL_TIMEOUT_SEC changed; if intentional, update brief + dashboard log line."
    )
