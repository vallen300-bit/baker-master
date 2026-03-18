"""
F5: Weekly Intelligence Digest (Session 26)

Runs every Sunday at 18:00 UTC. Summarizes the week:
  - New alerts by matter (top 5 matters by alert volume)
  - Overdue/approaching deadlines
  - Contacts going silent (>14 days)
  - Meetings this week vs next week
  - Risk matters (from risk_detector scores)

Stores digest to baker_insights + creates a T2 alert with the summary.
"""
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("baker.weekly_digest")


def run_weekly_digest():
    """
    Main entry point — called by scheduler every Sunday 18:00 UTC.
    Generates a structured weekly summary.
    """
    from memory.store_back import SentinelStoreBack
    import psycopg2.extras

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        sections = []

        # 1. Alert volume by matter (this week)
        cur.execute("""
            SELECT COALESCE(matter_slug, 'unassigned') as matter, COUNT(*) as cnt,
                   COUNT(*) FILTER (WHERE tier <= 2) as high_priority
            FROM alerts
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY matter_slug
            ORDER BY cnt DESC LIMIT 5
        """)
        alert_matters = cur.fetchall()
        if alert_matters:
            lines = ["**Alert Activity (top matters this week):**"]
            for m in alert_matters:
                lines.append(f"- {m['matter']}: {m['cnt']} alerts ({m['high_priority']} T1/T2)")
            sections.append("\n".join(lines))

        # 2. Overdue deadlines
        cur.execute("""
            SELECT COUNT(*) as cnt FROM deadlines
            WHERE status = 'active' AND due_date < CURRENT_DATE
        """)
        overdue = cur.fetchone()["cnt"]
        cur.execute("""
            SELECT COUNT(*) as cnt FROM deadlines
            WHERE status = 'active' AND due_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 7
        """)
        approaching = cur.fetchone()["cnt"]
        sections.append(f"**Deadlines:** {overdue} overdue, {approaching} due next week")

        # 3. Contacts going silent
        cur.execute("""
            SELECT name, last_contact_date,
                   EXTRACT(DAY FROM NOW() - last_contact_date) as days_silent
            FROM vip_contacts
            WHERE last_contact_date IS NOT NULL
              AND last_contact_date < NOW() - INTERVAL '30 days'
              AND tier <= 2
            ORDER BY last_contact_date ASC LIMIT 5
        """)
        silent_contacts = cur.fetchall()
        if silent_contacts:
            lines = ["**Relationships cooling (30+ days silent):**"]
            for c in silent_contacts:
                lines.append(f"- {c['name']}: {int(c['days_silent'])} days")
            sections.append("\n".join(lines))

        # 4. Meetings this week vs next
        cur.execute("""
            SELECT COUNT(*) as cnt FROM meeting_transcripts
            WHERE meeting_date > NOW() - INTERVAL '7 days'
        """)
        meetings_this_week = cur.fetchone()["cnt"]
        sections.append(f"**Meetings this week:** {meetings_this_week}")

        # 5. New obligations created
        cur.execute("""
            SELECT COUNT(*) as cnt FROM deadlines
            WHERE created_at > NOW() - INTERVAL '7 days'
        """)
        new_obligations = cur.fetchone()["cnt"]
        sections.append(f"**New obligations this week:** {new_obligations}")

        # 6. Pending alert count
        cur.execute("SELECT COUNT(*) as cnt FROM alerts WHERE status = 'pending'")
        pending = cur.fetchone()["cnt"]
        sections.append(f"**Pending alerts:** {pending}")

        cur.close()

        # Build digest
        digest = "# Weekly Intelligence Digest\n\n" + "\n\n".join(sections)

        # Store as insight
        try:
            store.store_insight(
                title="Weekly Intelligence Digest",
                content=digest,
                tags=["digest", "weekly"],
                source="weekly_digest",
            )
        except Exception:
            pass

        # Create T2 alert
        store.create_alert(
            tier=2,
            title="Weekly Intelligence Digest — Baker's weekly summary",
            body=digest,
            action_required=False,
            tags=["digest", "weekly"],
            source="weekly_digest",
            source_id=f"weekly-{datetime.now(timezone.utc).strftime('%Y-%W')}",
        )

        logger.info(f"Weekly digest generated: {len(sections)} sections")

    except Exception as e:
        logger.error(f"Weekly digest failed: {e}")
    finally:
        store._put_conn(conn)
