"""DASHBOARD_ALERT_NOISE_FIX_1 — Fix 3: TTL expiry for stale pending alerts.

Nothing in Baker ever aged a stale alert off the board, so pipeline cards from
months ago stayed `pending` forever and the attention feed only grew. This job
applies a flat 30-day TTL across all tiers (Director-LOCKED 2026-06-20).

Hard rules:
  - Acknowledged and snoozed alerts NEVER expire (auto-cleanup must not kill
    Director-curated state).
  - Idempotent — safe to run daily; a second run on the same day touches 0 rows.
  - No LLM calls. Non-fatal: a failure rolls back and logs, never raises.

Registered as a daily APScheduler job in triggers/embedded_scheduler.py.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("baker.alert_expiry")

# Director-LOCKED 2026-06-20: flat 30-day TTL for all tiers.
ALERT_TTL_DAYS = 30


def expire_stale_alerts() -> dict:
    """Expire pending alerts older than the flat TTL. Returns {"expired": N}.

    Excludes acknowledged + actively-snoozed alerts. Non-fatal.
    """
    from memory.store_back import SentinelStoreBack

    store = SentinelStoreBack._get_global_instance()
    result = {"expired": 0}

    conn = store._get_conn()
    if not conn:
        return result
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE alerts
            SET status = 'expired', exit_reason = 'ttl_auto_expire', resolved_at = NOW()
            WHERE status = 'pending'
              AND acknowledged_at IS NULL
              AND (snoozed_until IS NULL OR snoozed_until <= NOW())
              AND created_at < NOW() - (%s || ' days')::interval
            """,
            (str(ALERT_TTL_DAYS),),
        )
        n = cur.rowcount
        conn.commit()
        cur.close()
        result["expired"] = n if n and n > 0 else 0
        logger.info(
            f"expire_stale_alerts: expired {result['expired']} pending alert(s) "
            f"older than {ALERT_TTL_DAYS}d"
        )
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"expire_stale_alerts failed: {e}")
    finally:
        store._put_conn(conn)

    return result
