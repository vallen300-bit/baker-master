"""
F1: Compounding Risk Detector (Session 26)

Runs every 2 hours. For each active matter, counts:
  - Overdue deadlines
  - Unanswered messages (emails/WA sent by Director, no reply in 48h+)
  - Pending alerts (T1/T2)
  - Approaching deadlines (within 7 days)

Computes a risk score. If score > threshold → T1 alert:
"Matter X is deteriorating — 3 overdue deadlines, 2 unanswered messages"

This is the cross-source pattern detection Baker was missing.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger("baker.risk_detector")


def run_risk_detection():
    """
    Main entry point — called by scheduler every 2 hours.
    Scans all active matters and computes compounding risk scores.
    """
    from memory.store_back import SentinelStoreBack
    import psycopg2.extras

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Transaction-level advisory lock — auto-releases on commit/rollback
        cur.execute("SELECT pg_try_advisory_xact_lock(900100)")
        if not cur.fetchone()["pg_try_advisory_xact_lock"]:
            logger.info("Risk detection: another instance running — skipping")
            return

        # Get all active matters (exclude internal/development matters)
        _INTERNAL_MATTERS = {'Baker', 'Brisen-AI', "Owner's Lens"}
        cur.execute("SELECT matter_name, keywords, people FROM matter_registry WHERE status = 'active'")
        matters = [dict(r) for r in cur.fetchall() if r['matter_name'] not in _INTERNAL_MATTERS]

        if not matters:
            logger.info("Risk detection: no active matters found")
            return

        alerts_created = 0
        now = datetime.now(timezone.utc)

        for matter in matters:
            slug = matter["matter_name"]
            score, signals = _score_matter(cur, slug, now)

            if score >= 5:  # Threshold: 5+ signals = compounding risk
                title = f"Compounding risk: {slug} — {_summarize_signals(signals)}"
                body = _build_risk_body(slug, score, signals)

                alert_id = store.create_alert(
                    tier=1 if score >= 8 else 2,
                    title=title[:120],
                    body=body,
                    action_required=True,
                    matter_slug=slug,
                    tags=["risk", "compounding"],
                    source="risk_detector",
                    source_id=f"risk-{slug}-{now.strftime('%Y-%m-%d')}",
                )
                if alert_id:
                    alerts_created += 1
                    logger.info(f"Risk alert #{alert_id}: {slug} (score={score})")

        logger.info(f"Risk detection complete: {len(matters)} matters scanned, {alerts_created} alerts created")

    except Exception as e:
        logger.error(f"Risk detection failed: {e}")
    finally:
        store._put_conn(conn)


def _score_matter(cur, slug: str, now: datetime) -> tuple:
    """
    Compute risk score for a matter. Returns (score, signals_dict).
    Each signal type contributes 0-3 points based on severity.
    """
    signals = {}

    # 1. Overdue deadlines (weight: 2 per deadline, max 6)
    cur.execute("""
        SELECT COUNT(*) FROM deadlines
        WHERE status = 'active'
          AND due_date < CURRENT_DATE
          AND (description ILIKE %s OR source_snippet ILIKE %s)
    """, (f"%{slug}%", f"%{slug}%"))
    overdue_deadlines = cur.fetchone()["count"]
    if overdue_deadlines > 0:
        signals["overdue_deadlines"] = min(overdue_deadlines, 3)

    # 2. Approaching deadlines within 7 days (weight: 1 per deadline, max 3)
    cur.execute("""
        SELECT COUNT(*) FROM deadlines
        WHERE status = 'active'
          AND due_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 7
          AND (description ILIKE %s OR source_snippet ILIKE %s)
    """, (f"%{slug}%", f"%{slug}%"))
    approaching = cur.fetchone()["count"]
    if approaching > 0:
        signals["approaching_deadlines"] = min(approaching, 3)

    # 3. Pending T1/T2 alerts (weight: 1 per alert, max 3)
    cur.execute("""
        SELECT COUNT(*) FROM alerts
        WHERE status = 'pending' AND tier <= 2
          AND (matter_slug = %s OR title ILIKE %s)
    """, (slug, f"%{slug}%"))
    pending_alerts = cur.fetchone()["count"]
    if pending_alerts > 0:
        signals["pending_alerts"] = min(pending_alerts, 3)

    # 4. Unanswered sent emails (sent by Director, no reply in 48h+) (weight: 2 per email, max 4)
    try:
        cur.execute("""
            SELECT COUNT(*) FROM sent_emails
            WHERE created_at > NOW() - INTERVAL '14 days'
              AND created_at < NOW() - INTERVAL '48 hours'
              AND reply_received = FALSE
              AND (subject ILIKE %s OR body_preview ILIKE %s)
        """, (f"%{slug}%", f"%{slug}%"))
        unanswered = cur.fetchone()["count"]
        if unanswered > 0:
            signals["unanswered_emails"] = min(unanswered, 2)
    except Exception:
        pass  # sent_emails may not have matching columns

    # 5. Overdue ClickUp tasks (weight: 1 per task, max 3)
    try:
        cur.execute("""
            SELECT COUNT(*) FROM clickup_tasks
            WHERE status NOT IN ('complete', 'closed', 'done')
              AND due_date IS NOT NULL AND due_date < NOW()
              AND (name ILIKE %s OR description ILIKE %s)
        """, (f"%{slug}%", f"%{slug}%"))
        overdue_tasks = cur.fetchone()["count"]
        if overdue_tasks > 0:
            signals["overdue_clickup_tasks"] = min(overdue_tasks, 3)
    except Exception:
        pass  # clickup_tasks schema may vary

    # 6. Days since last interaction with matter contacts (weight: 1 if >14d, 2 if >30d)
    try:
        cur.execute("""
            SELECT MIN(EXTRACT(DAY FROM NOW() - last_contact_date)) as min_days
            FROM vip_contacts
            WHERE last_contact_date IS NOT NULL
              AND name ILIKE ANY(
                SELECT unnest(people) FROM matter_registry WHERE matter_name = %s
              )
        """, (slug,))
        row = cur.fetchone()
        if row and row.get("min_days") and row["min_days"] > 14:
            signals["contact_silence"] = 2 if row["min_days"] > 30 else 1
    except Exception:
        pass  # matter_registry people array may not match

    # Calculate total score
    weights = {
        "overdue_deadlines": 2,
        "approaching_deadlines": 1,
        "pending_alerts": 1,
        "unanswered_emails": 2,
        "overdue_clickup_tasks": 1,
        "contact_silence": 1,
    }
    score = sum(signals.get(k, 0) * weights[k] for k in weights)

    return score, signals


def _summarize_signals(signals: dict) -> str:
    """One-line summary of active signals."""
    parts = []
    if signals.get("overdue_deadlines"):
        parts.append(f"{signals['overdue_deadlines']} overdue deadline(s)")
    if signals.get("unanswered_emails"):
        parts.append(f"{signals['unanswered_emails']} unanswered email(s)")
    if signals.get("approaching_deadlines"):
        parts.append(f"{signals['approaching_deadlines']} deadline(s) within 7d")
    if signals.get("pending_alerts"):
        parts.append(f"{signals['pending_alerts']} unresolved alert(s)")
    if signals.get("overdue_clickup_tasks"):
        parts.append(f"{signals['overdue_clickup_tasks']} overdue task(s)")
    if signals.get("contact_silence"):
        parts.append("contact(s) going silent")
    return ", ".join(parts) if parts else "multiple signals"


def _build_risk_body(slug: str, score: int, signals: dict) -> str:
    """Build detailed alert body."""
    lines = [f"**Matter:** {slug}", f"**Risk Score:** {score}/16", ""]
    lines.append("**Active Signals:**")
    for key, count in signals.items():
        label = key.replace("_", " ").title()
        lines.append(f"- {label}: {count}")
    lines.append("")
    lines.append("This matter has multiple compounding risk factors. Review and take action.")
    return "\n".join(lines)
