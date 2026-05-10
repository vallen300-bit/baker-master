"""Calendar-month Tier B counter-reset audit job.

Runs 1st of each month at 00:00 UTC (registered in
``triggers/embedded_scheduler.py``). The reset is logical — counter math is
read-driven from ``baker_actions`` filtered by ``DATE_TRUNC('month', NOW())``
— so no UPDATE is needed. The audit row in ``tier_b_counter_resets`` proves
the boundary fired and captures the period's final totals.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from memory.store_back import SentinelStoreBack

logger = logging.getLogger(__name__)


def tier_b_counter_reset() -> None:
    """APScheduler entrypoint: log calendar-month reset event.

    Computes the period that just ended (previous calendar month UTC), sums
    its committed Tier-B actions, and inserts an audit row.
    """
    now_utc = datetime.now(timezone.utc)
    if now_utc.month == 1:
        prev_year, prev_month = now_utc.year - 1, 12
    else:
        prev_year, prev_month = now_utc.year, now_utc.month - 1
    period_label = f"{prev_year:04d}-{prev_month:02d}"

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if conn is None:
        logger.error("tier_b_counter_reset: no DB connection — skipping")
        return
    try:
        cur = conn.cursor()
        # Final month total for the period that just ended (UTC boundaries).
        cur.execute(
            """
            SELECT COALESCE(SUM(cost_eur), 0), COUNT(*)
              FROM baker_actions
             WHERE tier = 'B' AND cost_eur IS NOT NULL
               AND committed_at >= make_timestamptz(%s, %s, 1, 0, 0, 0, 'UTC')
               AND committed_at <  DATE_TRUNC('month', NOW() AT TIME ZONE 'UTC')
             LIMIT 100000
            """,
            (prev_year, prev_month),
        )
        row = cur.fetchone()
        final_month_total = float(row[0])
        actions_count = int(row[1])

        # Day total for the last calendar day of the period (informational).
        cur.execute(
            """
            SELECT COALESCE(SUM(cost_eur), 0)
              FROM baker_actions
             WHERE tier = 'B' AND cost_eur IS NOT NULL
               AND committed_at >= DATE_TRUNC('day', (NOW() AT TIME ZONE 'UTC') - INTERVAL '1 day')
               AND committed_at <  DATE_TRUNC('day',  NOW() AT TIME ZONE 'UTC')
             LIMIT 100000
            """
        )
        final_day_total = float(cur.fetchone()[0])

        cur.execute(
            """
            INSERT INTO tier_b_counter_resets
                (period_label, final_day_total, final_month_total, actions_count)
            VALUES (%s, %s, %s, %s)
            """,
            (period_label, final_day_total, final_month_total, actions_count),
        )
        conn.commit()
        cur.close()
        logger.info(
            "Tier B counter reset logged for period %s: €%.2f across %d actions",
            period_label,
            final_month_total,
            actions_count,
        )
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"tier_b_counter_reset failed: {e}")
        raise
    finally:
        store._put_conn(conn)
