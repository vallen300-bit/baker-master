"""Boot-time backfill runner with per-step timeout (2026-05-08).

Lives in `triggers/` (not in `outputs/dashboard.py`) so unit tests can
import it without pulling in FastAPI + the entire dashboard dependency
graph.

Background:
PR #168/PR #171 fixed Plaud's stale-refresh logic, but Plaud's boot-time
backfill never actually fires when Fireflies (legacy, silent-dead since
2026-04-11) hangs ahead of it in the sequential chain. This helper wraps
each backfill in a daemon thread with a hard timeout so neither source
can wedge the other.

2026-05-08 hardening (BRIEF_BACKFILL_THREADED_POOL_AND_OBSERVABILITY_1):
abandoned-thread alarm — if the daemon thread does not return within the
timeout, log a stack-dump and fire a sentinel report_failure so the
silent-pen state surfaces as a T2-down on the cockpit. Plus a shared
``run_boot_backfill_chain`` helper used by both dashboard startup AND
tests, so the canonical Plaud-first order lives in exactly one place.
"""

import logging
import sys
import threading
import traceback
from typing import Callable, List, Optional

logger = logging.getLogger("sentinel.backfill")

# Per-step backfill timeout. 300s = 5 min, generous; typical run is 10-60s.
BACKFILL_TIMEOUT_SEC = 300

# Module-level counter survives the function call but resets on Render restart.
# That's the right scope — abandoned threads can only accumulate within one
# Render instance lifetime, and we want the count cleared on each restart.
abandoned_backfill_count = 0


def run_backfill_with_timeout(name: str, fn, timeout_s: int = BACKFILL_TIMEOUT_SEC) -> None:
    """Run a backfill in a daemon thread; log + alarm + move on if it exceeds timeout.

    Daemon thread keeps running in background after timeout (so any in-flight
    DB writes complete cleanly), but the parent thread continues to the next
    backfill regardless. Failures are caught + logged non-fatally.

    On timeout the wedged-thread state is captured for diagnostics:
    - increment ``abandoned_backfill_count`` (process-local, resets on restart),
    - capture the wedged thread's frame stack via ``sys._current_frames()``
      and emit it on logger.warning,
    - fire ``report_failure("<name>_backfill", ...)`` so the cockpit alarms
      on the silent-pen state (advisory lock + ``_backfill_running`` flag
      remain wedged for the rest of the Render instance lifetime; restart
      is the recovery path — Python has no safe thread-cancellation primitive).
    """
    global abandoned_backfill_count

    def _wrap():
        try:
            fn()
        except Exception as e:
            logger.warning(f"{name} backfill failed (non-fatal): {e}")

    t = threading.Thread(target=_wrap, name=f"backfill-{name}", daemon=True)
    t.start()
    t.join(timeout=timeout_s)
    if t.is_alive():
        abandoned_backfill_count += 1
        # Capture the wedged thread's stack frame for diagnostics.
        frames = sys._current_frames()
        wedged_frame = frames.get(t.ident)
        if wedged_frame is not None:
            stack_dump = "".join(traceback.format_stack(wedged_frame))
        else:
            stack_dump = "(stack frame not accessible)"
        logger.warning(
            f"{name} backfill exceeded {timeout_s}s timeout — moving on "
            f"(daemon thread still running in background; "
            f"abandoned_count={abandoned_backfill_count}). "
            f"Wedged stack:\n{stack_dump}"
        )
        # Fire sentinel alarm so the cockpit surfaces this rather than burying
        # it in Render logs. Wrapped in its own try so a sentinel-write failure
        # never crashes the chain. Local import mirrors the pattern used in
        # backfill_plaud / backfill_fireflies (avoids circular import per
        # BRIEF_SENTINEL_HEALTH_1.md).
        try:
            from triggers.sentinel_health import report_failure
            report_failure(
                f"{name}_backfill",
                f"abandoned thread after {timeout_s}s; advisory lock + "
                f"_backfill_running flag are now wedged for the rest of this "
                f"Render instance lifetime; restart required",
            )
        except Exception as _sh_e:
            logger.warning(f"sentinel report_failure crashed (non-fatal): {_sh_e}")


def run_boot_backfill_chain(
    plaud_token: Optional[str],
    plaud_fn: Optional[Callable[[], None]],
    fireflies_fn: Optional[Callable[[], None]],
    timeout_s: int = BACKFILL_TIMEOUT_SEC,
) -> List[str]:
    """Run boot-time backfill chain in canonical order.

    Returns the list of backfills actually invoked, in the order they ran.
    Used by ``outputs/dashboard.py:_delayed_backfills`` AND by regression
    tests so the canonical order lives in exactly ONE place.

    Order (load-bearing): Plaud first, Fireflies second. Pre-2026-05-08
    reverse order let a hung Fireflies block Plaud's startup (PR #172).

    Each step is gated on its own credential / module presence; missing
    credentials silently skip that step (no exception).
    """
    invoked: List[str] = []

    if plaud_token and plaud_fn is not None:
        invoked.append("plaud")
        run_backfill_with_timeout("plaud", plaud_fn, timeout_s)

    if fireflies_fn is not None:
        invoked.append("fireflies")
        run_backfill_with_timeout("fireflies", fireflies_fn, timeout_s)

    return invoked
