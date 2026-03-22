"""
Baker 3.0 — Push Sender + Digest Gathering

Two daily digests (07:00 + 18:00 UTC) + T1 crisis breakthrough.
Uses Web Push via pywebpush and VAPID keys.
"""
import json
import logging
from datetime import datetime, timezone, timedelta

from config.settings import config

logger = logging.getLogger("baker.push_sender")


# ─────────────────────────────────────────────
# Push sending
# ─────────────────────────────────────────────

def send_push(title: str, body: str, url: str = "/mobile?tab=digest", tag: str = "digest"):
    """Send push notification to all subscribed devices."""
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.debug("pywebpush not installed — skipping push")
        return

    vapid_private = config.web_push.vapid_private_key
    vapid_email = config.web_push.vapid_contact_email
    if not vapid_private or not vapid_email:
        logger.debug("VAPID keys not configured — skipping push")
        return

    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    subs = store.get_all_push_subscriptions()
    if not subs:
        logger.debug("No push subscriptions — skipping")
        return

    payload = json.dumps({
        "title": title,
        "body": body[:200],
        "url": url,
        "tag": tag,
        "type": "digest",
    })

    sent = 0
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=payload,
                vapid_private_key=vapid_private,
                vapid_claims={"sub": f"mailto:{vapid_email}"},
                timeout=5,
            )
            sent += 1
        except WebPushException as e:
            if "410" in str(e) or "404" in str(e):
                store.remove_push_subscription(sub["endpoint"])
                logger.info(f"Removed expired push subscription")
            else:
                logger.warning(f"Web Push failed: {e}")
        except Exception as e:
            logger.warning(f"Web Push error: {e}")

    logger.info(f"Push sent to {sent}/{len(subs)} devices: {title[:60]}")


# ─────────────────────────────────────────────
# Digest gathering
# ─────────────────────────────────────────────

def gather_morning_items() -> list:
    """Gather items for morning digest: alerts, actions, deadlines, unanswered VIP."""
    items = []
    try:
        from memory.store_back import SentinelStoreBack
        import psycopg2.extras
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return items
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # 1. Pending alerts (T1/T2, last 24h)
            cur.execute("""
                SELECT id, title, tier, matter_slug, source, created_at
                FROM alerts
                WHERE status = 'pending' AND tier <= 2
                ORDER BY tier, created_at DESC LIMIT 10
            """)
            for r in cur.fetchall():
                items.append({
                    "type": "alert",
                    "title": r["title"] or "",
                    "description": f"T{r['tier']} alert" + (f" — {r['matter_slug']}" if r.get("matter_slug") else ""),
                    "source": r.get("source", "pipeline"),
                    "id": r["id"],
                    "positive_action": {"label": "View", "tab": "alerts"},
                    "negative_action": {"label": "Dismiss", "endpoint": f"/api/alerts/{r['id']}/dismiss", "method": "POST"},
                })

            # 2. Proposed actions (pending)
            cur.execute("""
                SELECT id, title, source_label, matter_slug
                FROM proposed_actions
                WHERE status = 'pending'
                ORDER BY created_at DESC LIMIT 8
            """)
            for r in cur.fetchall():
                items.append({
                    "type": "action",
                    "title": r["title"] or "",
                    "description": r.get("source_label", ""),
                    "source": "obligation",
                    "id": r["id"],
                    "positive_action": {"label": "Approve", "endpoint": f"/api/actions/{r['id']}/approve", "method": "POST"},
                    "negative_action": {"label": "Dismiss", "endpoint": f"/api/actions/{r['id']}/dismiss", "method": "POST"},
                })

            # 3. Deadlines approaching (next 3 days)
            cur.execute("""
                SELECT id, description, due_date, severity
                FROM deadlines
                WHERE status = 'active'
                  AND due_date <= NOW() + INTERVAL '3 days'
                  AND due_date >= NOW() - INTERVAL '1 day'
                ORDER BY due_date LIMIT 5
            """)
            for r in cur.fetchall():
                due = r["due_date"].strftime("%a %d %b") if r.get("due_date") else ""
                items.append({
                    "type": "deadline",
                    "title": r["description"] or "",
                    "description": f"Due {due}" + (f" ({r['severity']})" if r.get("severity") else ""),
                    "source": "deadline",
                    "id": r["id"],
                    "positive_action": {"label": "View", "tab": "alerts"},
                    "negative_action": None,
                })

            # 4. Unanswered VIP messages (>4h)
            cur.execute("""
                SELECT vc.name, wm.full_text, wm.timestamp
                FROM whatsapp_messages wm
                JOIN vip_contacts vc ON wm.sender = vc.whatsapp_id
                WHERE vc.tier <= 2
                  AND wm.timestamp >= NOW() - INTERVAL '24 hours'
                  AND wm.direction = 'inbound'
                  AND wm.timestamp <= NOW() - INTERVAL '4 hours'
                  AND NOT EXISTS (
                      SELECT 1 FROM whatsapp_messages wm2
                      WHERE wm2.chat_id = wm.chat_id
                        AND wm2.direction = 'outbound'
                        AND wm2.timestamp > wm.timestamp
                  )
                ORDER BY wm.timestamp DESC LIMIT 5
            """)
            for r in cur.fetchall():
                items.append({
                    "type": "unanswered",
                    "title": f"Unanswered: {r['name']}",
                    "description": (r.get("full_text") or "")[:100],
                    "source": "whatsapp",
                    "positive_action": {"label": "Reply", "tab": "baker"},
                    "negative_action": None,
                })

            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"gather_morning_items failed: {e}")

    return items


def gather_evening_items() -> list:
    """Gather items for evening digest: tomorrow's meetings, deferred items, completed actions."""
    items = []
    try:
        from memory.store_back import SentinelStoreBack
        import psycopg2.extras
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return items
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # 1. Tomorrow's deadlines
            cur.execute("""
                SELECT id, description, due_date, severity
                FROM deadlines
                WHERE status = 'active'
                  AND due_date::date = (CURRENT_DATE + 1)
                ORDER BY due_date LIMIT 5
            """)
            for r in cur.fetchall():
                items.append({
                    "type": "deadline",
                    "title": r["description"] or "",
                    "description": f"Due tomorrow ({r.get('severity', '')})",
                    "source": "deadline",
                    "id": r["id"],
                    "positive_action": {"label": "View", "tab": "alerts"},
                    "negative_action": None,
                })

            # 2. Still-pending alerts from today
            cur.execute("""
                SELECT id, title, tier, matter_slug
                FROM alerts
                WHERE status = 'pending'
                  AND created_at >= CURRENT_DATE
                ORDER BY tier, created_at DESC LIMIT 5
            """)
            for r in cur.fetchall():
                items.append({
                    "type": "alert",
                    "title": r["title"] or "",
                    "description": f"Still pending (T{r['tier']})",
                    "source": "pipeline",
                    "id": r["id"],
                    "positive_action": {"label": "View", "tab": "alerts"},
                    "negative_action": {"label": "Dismiss", "endpoint": f"/api/alerts/{r['id']}/dismiss", "method": "POST"},
                })

            # 3. Actions completed today (confirmation)
            cur.execute("""
                SELECT id, title, source_label
                FROM proposed_actions
                WHERE status = 'done'
                  AND updated_at >= CURRENT_DATE
                ORDER BY updated_at DESC LIMIT 5
            """)
            for r in cur.fetchall():
                items.append({
                    "type": "completed",
                    "title": r["title"] or "",
                    "description": "Completed today",
                    "source": "action",
                    "positive_action": None,
                    "negative_action": None,
                })

            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"gather_evening_items failed: {e}")

    return items


def _format_preview(items: list) -> str:
    """Format first few items as push notification body text."""
    lines = []
    for item in items[:3]:
        lines.append(item.get("title", "")[:60])
    return "\n".join(lines)


# ─────────────────────────────────────────────
# Scheduled jobs
# ─────────────────────────────────────────────

def send_morning_digest():
    """Scheduled job (07:00 UTC): gather morning items + send push."""
    from triggers.sentinel_health import report_success, report_failure
    try:
        items = gather_morning_items()
        if not items:
            logger.info("Morning digest: no items to push")
            report_success("morning_digest")
            return

        count = len(items)
        send_push(
            title=f"Good morning. {count} item{'s' if count != 1 else ''} need attention.",
            body=_format_preview(items),
            url="/mobile?tab=digest&type=morning",
            tag="baker-morning-" + datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        )
        report_success("morning_digest")
        logger.info(f"Morning digest sent: {count} items")
    except Exception as e:
        report_failure("morning_digest", str(e))
        logger.error(f"Morning digest failed: {e}")


def send_evening_digest():
    """Scheduled job (18:00 UTC): gather evening items + send push."""
    from triggers.sentinel_health import report_success, report_failure
    try:
        items = gather_evening_items()
        if not items:
            logger.info("Evening digest: no items to push")
            report_success("evening_digest")
            return

        count = len(items)
        send_push(
            title=f"End of day. {count} item{'s' if count != 1 else ''}.",
            body=_format_preview(items),
            url="/mobile?tab=digest&type=evening",
            tag="baker-evening-" + datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        )
        report_success("evening_digest")
        logger.info(f"Evening digest sent: {count} items")
    except Exception as e:
        report_failure("evening_digest", str(e))
        logger.error(f"Evening digest failed: {e}")


def send_crisis_push(title: str, body: str):
    """T1 breakthrough push — only for genuine crises."""
    now = datetime.now(timezone.utc)
    # Quiet hours: 22:00-07:00 UTC
    if now.hour >= 22 or now.hour < 7:
        logger.info(f"Crisis push suppressed during quiet hours: {title[:60]}")
        return
    send_push(
        title=f"URGENT: {title}",
        body=body[:200],
        url="/mobile?tab=alerts",
        tag="baker-crisis",
    )
    logger.info(f"Crisis push sent: {title[:60]}")
