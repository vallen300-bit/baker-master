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
    cur.execute("""
        SELECT COUNT(*) FROM sent_emails
        WHERE created_at > NOW() - INTERVAL '14 days'
          AND created_at < NOW() - INTERVAL '48 hours'
          AND replied_at IS NULL
          AND (subject ILIKE %s OR body ILIKE %s)
    """, (f"%{slug}%", f"%{slug}%"))
    unanswered = cur.fetchone()["count"]
    if unanswered > 0:
        signals["unanswered_emails"] = min(unanswered, 2)

    # Calculate total score
    weights = {
        "overdue_deadlines": 2,
        "approaching_deadlines": 1,
        "pending_alerts": 1,
        "unanswered_emails": 2,
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
