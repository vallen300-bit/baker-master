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
"""

import logging
import threading

logger = logging.getLogger("sentinel.backfill")

# Per-step backfill timeout. 300s = 5 min, generous; typical run is 10-60s.
BACKFILL_TIMEOUT_SEC = 300


def run_backfill_with_timeout(name: str, fn, timeout_s: int = BACKFILL_TIMEOUT_SEC) -> None:
    """Run a backfill in a daemon thread; log + move on if it exceeds timeout.

    Daemon thread keeps running in background after timeout (so any in-flight
    DB writes complete cleanly), but the parent thread continues to the next
    backfill regardless. Failures are caught + logged non-fatally.
    """
    def _wrap():
        try:
            fn()
        except Exception as e:
            logger.warning(f"{name} backfill failed (non-fatal): {e}")

    t = threading.Thread(target=_wrap, name=f"backfill-{name}", daemon=True)
    t.start()
    t.join(timeout=timeout_s)
    if t.is_alive():
        logger.warning(
            f"{name} backfill exceeded {timeout_s}s timeout — moving on "
            f"(daemon thread still running in background)"
        )
