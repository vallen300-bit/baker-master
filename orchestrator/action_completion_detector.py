"""
Action Completion Detector — Auto-mark approved actions as done (Session 30)

Runs every 6 hours. For each 'approved' proposed_action:
1. Parse completion_signals (e.g., ["email_to:sandy@bellboyrobotics.com"])
2. Check for matching event in DB (sent_emails, email_messages)
3. If found, mark action as 'auto_completed' with evidence
4. Create T3 alert so Director sees what was auto-completed

Cost: EUR 0 (all DB queries, no LLM).
"""
import logging
import re
from datetime import datetime, timezone, timedelta

from config.settings import config

logger = logging.getLogger("baker.action_completion_detector")


def _get_approved_actions() -> list:
    """Get all approved actions that haven't been completed yet."""
    try:
        from memory.store_back import SentinelStoreBack
        import psycopg2.extras
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT id, title, completion_signals, source_ref, triaged_at
                FROM proposed_actions
                WHERE status = 'approved'
                  AND completed_at IS NULL
                  AND triaged_at > NOW() - INTERVAL '14 days'
                ORDER BY triaged_at ASC
                LIMIT 50
            """)
            results = [dict(r) for r in cur.fetchall()]
            cur.close()
            return results
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"_get_approved_actions failed: {e}")
        return []


def _check_email_to(address: str, since: datetime) -> str:
    """Check if an email was sent TO this address since the action was approved."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            # Check sent_emails table (emails Director sent via Baker)
            cur.execute("""
                SELECT id, to_address, subject, created_at
                FROM sent_emails
                WHERE LOWER(to_address) LIKE %s
                  AND created_at > %s
                ORDER BY created_at DESC
                LIMIT 1
            """, (f"%{address.lower()}%", since))
            row = cur.fetchone()
            cur.close()
            if row:
                return f"Email sent to {row[1]} on {row[3].isoformat()[:10]} — \"{row[2][:60]}\" (sent_emails.id={row[0]})"
            return None
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.debug(f"_check_email_to failed: {e}")
        return None


def _check_email_from(address: str, since: datetime) -> str:
    """Check if an email was received FROM this address since the action was approved."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT message_id, sender_email, subject, received_date
                FROM email_messages
                WHERE LOWER(sender_email) LIKE %s
                  AND received_date > %s
                ORDER BY received_date DESC
                LIMIT 1
            """, (f"%{address.lower()}%", since))
            row = cur.fetchone()
            cur.close()
            if row:
                return f"Email received from {row[1]} on {row[3].isoformat()[:10]} — \"{row[2][:60]}\" (message_id={row[0][:20]})"
            return None
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.debug(f"_check_email_from failed: {e}")
        return None


def _check_completion_signals(action: dict) -> str:
    """Parse completion_signals and check each against DB. Returns evidence or None."""
    signals = action.get("completion_signals")
    if not signals:
        return None

    # Parse JSONB — could be list of strings or already parsed
    if isinstance(signals, str):
        try:
            import json
            signals = json.loads(signals)
        except Exception:
            return None

    if not isinstance(signals, list):
        return None

    since = action.get("triaged_at")
    if not since:
        return None
    # If triaged_at is a string, parse it
    if isinstance(since, str):
        try:
            since = datetime.fromisoformat(since)
        except Exception:
            since = datetime.now(timezone.utc) - timedelta(days=7)

    for signal in signals:
        if not isinstance(signal, str):
            continue

        # email_to:ADDRESS
        match = re.match(r'^email_to:(.+)$', signal, re.IGNORECASE)
        if match:
            address = match.group(1).strip()
            evidence = _check_email_to(address, since)
            if evidence:
                return evidence

        # email_from:ADDRESS
        match = re.match(r'^email_from:(.+)$', signal, re.IGNORECASE)
        if match:
            address = match.group(1).strip()
            evidence = _check_email_from(address, since)
            if evidence:
                return evidence

        # response_received (generic — check email_from with source_ref as name)
        if signal.lower() in ("response_received", "response_received_within_7d"):
            source_ref = action.get("source_ref", "")
            if source_ref:
                # Try matching by name in sender_name or sender_email
                evidence = _check_email_from(source_ref, since)
                if evidence:
                    return evidence

    return None


def _mark_auto_completed(action_id: int, evidence: str):
    """Mark action as auto_completed with evidence."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            now = datetime.now(timezone.utc)
            cur.execute("""
                UPDATE proposed_actions
                SET status = 'auto_completed',
                    completed_at = %s,
                    completion_evidence = %s
                WHERE id = %s AND completed_at IS NULL
            """, (now, evidence, action_id))
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"_mark_auto_completed failed for {action_id}: {e}")


def _notify_completion(action: dict, evidence: str):
    """Create a T3 alert for auto-completed action."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        store.create_alert(
            tier=3,
            title=f"Auto-completed: {action.get('title', '')[:80]}",
            body=f"Baker detected completion.\n\n**Evidence:** {evidence}",
            action_required=False,
            tags=["auto_completed", "action"],
            source="action_completion_detector",
            source_id=f"auto-complete-{action['id']}",
        )
    except Exception as e:
        logger.debug(f"_notify_completion failed: {e}")


def run_action_completion_detector():
    """
    Main entry point — called by scheduler every 6 hours.
    Scans approved actions, checks completion signals, auto-marks done.
    """
    from triggers.sentinel_health import report_success, report_failure

    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return

        try:
            cur = conn.cursor()
            cur.execute("SELECT pg_try_advisory_xact_lock(900700)")
            if not cur.fetchone()[0]:
                logger.info("Action completion detector: another instance running — skipping")
                return
            cur.close()
        finally:
            store._put_conn(conn)

        actions = _get_approved_actions()
        if not actions:
            logger.info("Action completion detector: no approved actions to check")
            report_success("action_completion_detector")
            return

        completed = 0
        for action in actions:
            evidence = _check_completion_signals(action)
            if evidence:
                _mark_auto_completed(action["id"], evidence)
                _notify_completion(action, evidence)
                completed += 1
                logger.info(f"Auto-completed action {action['id']}: {action.get('title', '')[:60]}")

        report_success("action_completion_detector")
        logger.info(f"Action completion detector: checked {len(actions)} actions, auto-completed {completed}")

    except Exception as e:
        report_failure("action_completion_detector", str(e))
        logger.error(f"Action completion detector failed: {e}")
