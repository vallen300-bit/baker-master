"""
Phase 3C: Commitment Overdue Checker
Runs every 6 hours. Creates alerts for overdue and due-soon commitments.
Standing Order #5 — Track commitments + follow-through.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger("baker.commitment_checker")


def run_commitment_check():
    """
    Check for overdue commitments. Runs every 6 hours.
    - Overdue (past due_date): update status, create T2 alert
    - Due within 24h: create T3 reminder
    Dedup via trigger_watermarks.
    """
    from memory.store_back import SentinelStoreBack
    from triggers.state import trigger_state
    import psycopg2.extras

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1. Overdue commitments (due_date < today, still open)
        cur.execute("""
            SELECT * FROM commitments
            WHERE status = 'open' AND due_date IS NOT NULL AND due_date < CURRENT_DATE
        """)
        overdue = [dict(r) for r in cur.fetchall()]

        for c in overdue:
            wk = f"commitment_overdue_{c['id']}"
            if trigger_state.watermark_exists(wk):
                continue

            # Update status to overdue
            cur.execute(
                "UPDATE commitments SET status = 'overdue', updated_at = NOW() WHERE id = %s",
                (c['id'],),
            )
            conn.commit()

            alert_id = store.create_alert(
                tier=2,
                title=f"Overdue commitment: {c['description'][:80]}",
                body=(
                    f"**Assigned to:** {c.get('assigned_to', 'Unknown')}\n"
                    f"**Due:** {c['due_date']}\n"
                    f"**Source:** {c.get('source_context', c.get('source_type', ''))}\n\n"
                    f"{c['description']}"
                ),
                action_required=True,
                tags=["commitment", "overdue"],
                source="commitment_check",
            )
            if alert_id:
                trigger_state.set_watermark(wk, datetime.now(timezone.utc))
                logger.info(f"Overdue commitment alert #{alert_id}: {c['description'][:60]}")

        # 2. Due within 24h (reminder)
        cur.execute("""
            SELECT * FROM commitments
            WHERE status = 'open' AND due_date IS NOT NULL
              AND due_date >= CURRENT_DATE AND due_date <= CURRENT_DATE + 1
        """)
        due_soon = [dict(r) for r in cur.fetchall()]

        for c in due_soon:
            wk = f"commitment_due_soon_{c['id']}"
            if trigger_state.watermark_exists(wk):
                continue

            alert_id = store.create_alert(
                tier=3,
                title=f"Commitment due today: {c['description'][:80]}",
                body=(
                    f"**Assigned to:** {c.get('assigned_to', 'Unknown')}\n"
                    f"**Due:** {c['due_date']}\n"
                    f"{c['description']}"
                ),
                action_required=False,
                tags=["commitment"],
                source="commitment_check",
            )
            if alert_id:
                trigger_state.set_watermark(wk, datetime.now(timezone.utc))
                logger.info(f"Due-soon commitment alert #{alert_id}: {c['description'][:60]}")

        cur.close()

        total = len(overdue) + len(due_soon)
        logger.info(f"Commitment check complete: {len(overdue)} overdue, {len(due_soon)} due soon (total open commitments checked)")

    except Exception as e:
        logger.error(f"Commitment check failed: {e}")
    finally:
        store._put_conn(conn)
