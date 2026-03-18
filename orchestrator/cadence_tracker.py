"""
F3: Communication Cadence Tracker (Session 27)

Runs every 6 hours. For each contact with 3+ inbound interactions:
  - Computes avg gap between interactions (avg_inbound_gap_days)
  - Stores last inbound timestamp (last_inbound_at)
  - Flags contacts whose silence > 3x their normal cadence AND > 7 days

This replaces the fixed 30-day "silent contacts" threshold with personalized
cadence-relative detection. Balazs (avg 0.3d) going 3 days silent is 10x
deviation. Christian Merz (avg 17.5d) going 30 days is barely 2x.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger("baker.cadence_tracker")


def run_cadence_tracker():
    """Main entry point — called by scheduler every 6 hours."""
    from memory.store_back import SentinelStoreBack
    import psycopg2.extras

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Transaction-level advisory lock — auto-releases on commit/rollback
        cur.execute("SELECT pg_try_advisory_xact_lock(900201)")
        if not cur.fetchone()["pg_try_advisory_xact_lock"]:
            logger.info("Cadence tracker: another instance running — skipping")
            return

        # Compute cadence for all contacts with 3+ inbound interactions
        cur.execute("""
            SELECT
                ci.contact_id,
                vc.name,
                COUNT(*) as interaction_count,
                MAX(ci.timestamp) as last_inbound,
                EXTRACT(EPOCH FROM MAX(ci.timestamp) - MIN(ci.timestamp))
                    / NULLIF(COUNT(*) - 1, 0) / 86400.0 as avg_gap_days
            FROM contact_interactions ci
            JOIN vip_contacts vc ON vc.id = ci.contact_id
            WHERE ci.direction = 'inbound'
              AND ci.timestamp IS NOT NULL
            GROUP BY ci.contact_id, vc.name
            HAVING COUNT(*) >= 3
            ORDER BY ci.contact_id
        """)
        rows = cur.fetchall()

        updated = 0
        anomalies = []

        for row in rows:
            contact_id = row["contact_id"]
            avg_gap = float(row["avg_gap_days"]) if row["avg_gap_days"] else None
            last_inbound = row["last_inbound"]
            name = row["name"]

            # Skip contacts with <0.5 day avg gap (burst conversations, not regular contacts)
            if avg_gap is None or avg_gap < 0.5:
                continue

            # Update contact cadence columns
            cur.execute("""
                UPDATE vip_contacts
                SET avg_inbound_gap_days = %s,
                    last_inbound_at = %s
                WHERE id = %s
            """, (round(avg_gap, 1), last_inbound, contact_id))
            updated += 1

            # Check for cadence deviation
            if last_inbound:
                now = datetime.now(timezone.utc)
                days_silent = (now - last_inbound).total_seconds() / 86400.0
                deviation = days_silent / avg_gap if avg_gap > 0 else 0

                # Flag if silence > 3x normal cadence AND > 7 absolute days
                if deviation >= 3.0 and days_silent >= 7:
                    anomalies.append({
                        "contact_id": contact_id,
                        "name": name,
                        "avg_gap_days": round(avg_gap, 1),
                        "days_silent": round(days_silent, 0),
                        "deviation": round(deviation, 1),
                    })

        conn.commit()

        # Create alerts for anomalies (max 3 per run to avoid noise)
        alerts_created = 0
        for anom in sorted(anomalies, key=lambda x: x["deviation"], reverse=True)[:3]:
            from datetime import date
            source_id = f"cadence-{anom['contact_id']}-{date.today().isoformat()}"
            title = (
                f"Cadence break: {anom['name']} — {int(anom['days_silent'])}d silent "
                f"(normal: every {anom['avg_gap_days']}d)"
            )
            body = (
                f"**{anom['name']}** usually communicates every "
                f"**{anom['avg_gap_days']} days** but hasn't been heard from in "
                f"**{int(anom['days_silent'])} days** ({anom['deviation']}x normal).\n\n"
                f"Consider reaching out."
            )
            alert_id = store.create_alert(
                tier=3,
                title=title[:120],
                body=body,
                action_required=False,
                tags=["cadence", "relationship"],
                source="cadence_tracker",
                source_id=source_id,
            )
            if alert_id:
                alerts_created += 1

        logger.info(
            f"Cadence tracker complete: {updated} contacts updated, "
            f"{len(anomalies)} anomalies detected, {alerts_created} alerts created"
        )

    except Exception as e:
        logger.error(f"Cadence tracker failed: {e}")
    finally:
        store._put_conn(conn)
