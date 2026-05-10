"""Tier B reservation sweep — clears orphan reservations past TTL.

Runs every 5 min via APScheduler. Pattern B atomicity (see
``orchestrator/tier_b_runtime.py``) writes ``baker_actions`` rows with
``committed_at=NULL`` + ``reserved_at=NOW()`` on PASS. Caller is expected
to call ``confirm_tier_b()`` or ``cancel_tier_b()`` within
``RESERVATION_TTL_MINUTES`` (15 min). If the caller crashed in the
window, this job removes the orphan so the budget returns to the pool
(it already stopped counting against caps once TTL expired — this just
prevents indefinite row bloat).

Idempotent + bounded: query is LIMITed at 1000 rows per run (worst-case
sweep size is tiny — a busy day might have ~1 orphan).
"""
from __future__ import annotations

import logging

from memory.store_back import SentinelStoreBack
from orchestrator.tier_b_runtime import RESERVATION_TTL_MINUTES

logger = logging.getLogger(__name__)


def tier_b_reservation_sweep() -> int:
    """APScheduler entrypoint: delete expired orphan reservations.

    Returns the row count deleted (for logging / ops visibility).
    """
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if conn is None:
        logger.error("tier_b_reservation_sweep: no DB connection — skipping")
        return 0
    try:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM baker_actions
             WHERE id IN (
                 SELECT id FROM baker_actions
                  WHERE tier = 'B'
                    AND committed_at IS NULL
                    AND reserved_at IS NOT NULL
                    AND reserved_at < NOW() AT TIME ZONE 'UTC'
                                    - (%s || ' minutes')::interval
                  LIMIT 1000
             )
            RETURNING id
            """,
            (str(RESERVATION_TTL_MINUTES),),
        )
        deleted = cur.fetchall()
        count = len(deleted)
        conn.commit()
        cur.close()
        if count:
            logger.info(
                "tier_b_reservation_sweep: deleted %d orphan reservations "
                "(>%d min old)",
                count, RESERVATION_TTL_MINUTES,
            )
        return count
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"tier_b_reservation_sweep failed: {e}")
        raise
    finally:
        store._put_conn(conn)
