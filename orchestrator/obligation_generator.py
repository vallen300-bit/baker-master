"""
Obligation Generator — Morning Triage Card Deck (Session 30)

Replaces manual Todoist task creation with Baker-proposed actions.
Runs daily at 06:50 UTC (before initiative engine at 07:00).

Flow:
  1. Gather signals (same 8 queries as initiative engine)
  2. Haiku extracts 5-15 SPECIFIC per-item task proposals
  3. Store each as proposed_action (status='proposed')
  4. Send single morning push: "Baker has N actions for today. Tap to review."

Director opens /mobile?tab=actions → swipe right=approve, left=dismiss.

Cost: ~EUR 0.50/day (single Haiku call).
"""
import json
import logging
from datetime import datetime, timezone, timedelta, date

import anthropic

from config.settings import config

logger = logging.getLogger("baker.obligation_generator")


# ─────────────────────────────────────────────────
# Table setup
# ─────────────────────────────────────────────────

def _ensure_proposed_actions_table():
    """Create proposed_actions table if not exists."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS proposed_actions (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    source_type VARCHAR(20),
                    source_ref TEXT,
                    source_snippet TEXT,
                    owner TEXT DEFAULT 'director',
                    due_date DATE,
                    suggested_action TEXT,
                    completion_signals JSONB,
                    priority_rank INTEGER DEFAULT 2,
                    status VARCHAR(20) DEFAULT 'proposed',
                    director_response VARCHAR(20),
                    escalated_to TEXT,
                    todoist_task_id TEXT,
                    run_date DATE DEFAULT CURRENT_DATE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    triaged_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ,
                    completion_evidence TEXT
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_pa_status
                ON proposed_actions(status) WHERE status = 'proposed'
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_pa_date
                ON proposed_actions(run_date)
            """)
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Could not ensure proposed_actions table: {e}")


# ─────────────────────────────────────────────────
# Signal gathering (mirrors initiative_engine._gather_context)
# ─────────────────────────────────────────────────

def _gather_signals() -> dict:
    """Gather all signals for obligation extraction."""
    from memory.store_back import SentinelStoreBack
    import psycopg2.extras

    store = SentinelStoreBack._get_global_instance()
    ctx = {
        "priorities": [],
        "calendar_next_48h": [],
        "approaching_deadlines": [],
        "overdue_deadlines": [],
        "cadence_anomalies": [],
        "unanswered_emails": [],
        "pending_alerts": [],
        "recent_chains": [],
        "yesterday_proposed": [],
    }

    conn = store._get_conn()
    if not conn:
        return ctx

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1. Weekly priorities
        try:
            cur.execute("""
                SELECT priority_text, matter_slug, rank
                FROM weekly_priorities
                WHERE active = TRUE
                ORDER BY rank ASC LIMIT 5
            """)
            ctx["priorities"] = [dict(r) for r in cur.fetchall()]
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

        # 2. Approaching deadlines (next 7 days)
        cur.execute("""
            SELECT description, due_date, priority, matter_slug
            FROM deadlines
            WHERE status = 'active'
              AND due_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 7
            ORDER BY due_date ASC LIMIT 10
        """)
        ctx["approaching_deadlines"] = [
            {**dict(r), "due_date": r["due_date"].isoformat() if r.get("due_date") else None}
            for r in cur.fetchall()
        ]

        # 3. Overdue deadlines
        cur.execute("""
            SELECT description, due_date, priority, matter_slug
            FROM deadlines
            WHERE status = 'active' AND due_date < CURRENT_DATE
            ORDER BY due_date ASC LIMIT 10
        """)
        ctx["overdue_deadlines"] = [
            {**dict(r), "due_date": r["due_date"].isoformat() if r.get("due_date") else None}
            for r in cur.fetchall()
        ]

        # 4. Cadence anomalies
        cur.execute("""
            SELECT name, avg_inbound_gap_days, last_inbound_at, tier,
                   EXTRACT(EPOCH FROM NOW() - last_inbound_at) / 86400.0 as days_silent
            FROM vip_contacts
            WHERE avg_inbound_gap_days IS NOT NULL
              AND avg_inbound_gap_days > 0.5
              AND last_inbound_at IS NOT NULL
              AND EXTRACT(EPOCH FROM NOW() - last_inbound_at) / 86400.0 > avg_inbound_gap_days * 3
              AND EXTRACT(EPOCH FROM NOW() - last_inbound_at) / 86400.0 > 7
            ORDER BY (EXTRACT(EPOCH FROM NOW() - last_inbound_at) / 86400.0 / avg_inbound_gap_days) DESC
            LIMIT 5
        """)
        ctx["cadence_anomalies"] = [
            {
                "name": r["name"],
                "avg_gap_days": round(float(r["avg_inbound_gap_days"]), 1),
                "days_silent": round(float(r["days_silent"]), 0),
                "tier": r.get("tier"),
                "deviation": round(float(r["days_silent"]) / float(r["avg_inbound_gap_days"]), 1)
                    if r.get("avg_inbound_gap_days") else 0,
            }
            for r in cur.fetchall()
        ]

        # 5. Unanswered sent emails (48h+)
        try:
            cur.execute("""
                SELECT recipient, subject, created_at
                FROM sent_emails
                WHERE created_at > NOW() - INTERVAL '14 days'
                  AND created_at < NOW() - INTERVAL '48 hours'
                  AND reply_received = FALSE
                ORDER BY created_at DESC LIMIT 5
            """)
            ctx["unanswered_emails"] = [
                {**dict(r), "created_at": r["created_at"].isoformat() if r.get("created_at") else None}
                for r in cur.fetchall()
            ]
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

        # 6. Pending T1/T2 alerts
        cur.execute("""
            SELECT id, tier, title, matter_slug, created_at
            FROM alerts
            WHERE status = 'pending' AND tier <= 2
            ORDER BY tier ASC, created_at DESC LIMIT 10
        """)
        ctx["pending_alerts"] = [
            {**dict(r), "created_at": r["created_at"].isoformat() if r.get("created_at") else None}
            for r in cur.fetchall()
        ]

        # 7. Recent chains
        try:
            cur.execute("""
                SELECT title, domain, status, created_at
                FROM baker_tasks
                WHERE task_type = 'chain'
                  AND created_at > NOW() - INTERVAL '3 days'
                ORDER BY created_at DESC LIMIT 5
            """)
            ctx["recent_chains"] = [
                {**dict(r), "created_at": r["created_at"].isoformat() if r.get("created_at") else None}
                for r in cur.fetchall()
            ]
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

        # 8. Yesterday's obligation alerts (to avoid re-proposing)
        try:
            cur.execute("""
                SELECT title, status
                FROM alerts
                WHERE source = 'obligation'
                  AND created_at >= CURRENT_DATE - 1
                  AND status != 'dismissed'
                ORDER BY created_at DESC LIMIT 20
            """)
            ctx["yesterday_proposed"] = [dict(r) for r in cur.fetchall()]
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

        cur.close()
    except Exception as e:
        logger.error(f"Obligation signal gathering failed: {e}")
    finally:
        store._put_conn(conn)

    # 9. Calendar next 48h (separate — needs Google API)
    try:
        from triggers.calendar_trigger import poll_upcoming_meetings
        meetings = poll_upcoming_meetings(hours_ahead=48)
        ctx["calendar_next_48h"] = [
            {
                "title": m["title"],
                "start": m["start"],
                "end": m["end"],
                "attendees": len(m.get("attendees", [])),
            }
            for m in meetings
        ]
    except Exception as e:
        logger.debug(f"Calendar fetch for obligations failed (non-fatal): {e}")

    # 10. Baker 3.0: Pre-extracted items from signal_extractions (Item 0b)
    ctx["extracted_items"] = []
    try:
        conn2 = store._get_conn()
        if conn2:
            try:
                cur2 = conn2.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur2.execute("""
                    SELECT source_channel, source_id, extracted_items
                    FROM signal_extractions
                    WHERE processed_at > NOW() - INTERVAL '24 hours'
                    ORDER BY processed_at DESC LIMIT 50
                """)
                for row in cur2.fetchall():
                    items = row.get("extracted_items") or []
                    if isinstance(items, str):
                        items = json.loads(items)
                    for item in items:
                        if item.get("type") in ("commitment", "action_item", "deadline", "follow_up"):
                            item["_source_channel"] = row["source_channel"]
                            item["_source_id"] = row["source_id"]
                            ctx["extracted_items"].append(item)
                cur2.close()
            except Exception:
                try:
                    conn2.rollback()
                except Exception:
                    pass
            finally:
                store._put_conn(conn2)
    except Exception as e:
        logger.debug(f"Signal extractions fetch failed (non-fatal): {e}")

    return ctx


def _format_signals(ctx: dict) -> str:
    """Format signal dict into prompt string for Haiku."""
    parts = []
    today = date.today().isoformat()
    parts.append(f"Date: {today}")

    if ctx["priorities"]:
        parts.append("\n## WEEKLY PRIORITIES")
        for p in ctx["priorities"]:
            matter = f" [{p.get('matter_slug', '')}]" if p.get("matter_slug") else ""
            parts.append(f"  {p.get('rank', '?')}. {p['priority_text']}{matter}")

    if ctx["calendar_next_48h"]:
        parts.append(f"\n## CALENDAR (next 48h) — {len(ctx['calendar_next_48h'])} events")
        for m in ctx["calendar_next_48h"][:8]:
            parts.append(f"  - {m['start'][:16]} {m['title']} ({m['attendees']} attendees)")

    if ctx["approaching_deadlines"]:
        parts.append(f"\n## APPROACHING DEADLINES (next 7 days) — {len(ctx['approaching_deadlines'])}")
        for d in ctx["approaching_deadlines"]:
            parts.append(f"  - [{d.get('priority', 'normal').upper()}] {d['due_date']}: {d['description'][:100]}")

    if ctx["overdue_deadlines"]:
        parts.append(f"\n## OVERDUE DEADLINES — {len(ctx['overdue_deadlines'])}")
        for d in ctx["overdue_deadlines"]:
            parts.append(f"  - [{d.get('priority', 'normal').upper()}] {d['due_date']}: {d['description'][:100]}")

    if ctx["cadence_anomalies"]:
        parts.append(f"\n## CONTACTS GOING QUIET — {len(ctx['cadence_anomalies'])}")
        for c in ctx["cadence_anomalies"]:
            parts.append(
                f"  - {c['name']} (T{c.get('tier', '?')}): {int(c['days_silent'])}d silent "
                f"(normal: every {c['avg_gap_days']}d, {c['deviation']}x deviation)"
            )

    if ctx["unanswered_emails"]:
        parts.append(f"\n## UNANSWERED SENT EMAILS — {len(ctx['unanswered_emails'])}")
        for e in ctx["unanswered_emails"]:
            parts.append(f"  - To: {e.get('recipient', '?')} — {e.get('subject', '?')} (sent {e.get('created_at', '?')[:10]})")

    if ctx["pending_alerts"]:
        t1 = [a for a in ctx["pending_alerts"] if a.get("tier") == 1]
        t2 = [a for a in ctx["pending_alerts"] if a.get("tier") == 2]
        parts.append(f"\n## PENDING ALERTS — {len(t1)} urgent, {len(t2)} important")
        for a in ctx["pending_alerts"][:5]:
            tier_label = "URGENT" if a.get("tier") == 1 else "IMPORTANT"
            parts.append(f"  - [{tier_label}] {a['title'][:80]}")

    if ctx["recent_chains"]:
        parts.append(f"\n## RECENTLY HANDLED BY CHAINS — do NOT re-propose these")
        for c in ctx["recent_chains"]:
            parts.append(f"  - {c['title'][:80]}")

    if ctx["yesterday_proposed"]:
        parts.append(f"\n## YESTERDAY'S PROPOSED ACTIONS (still open — do NOT re-propose)")
        for p in ctx["yesterday_proposed"]:
            parts.append(f"  - [{p.get('status', '?')}] {p['title'][:80]}")

    # Baker 3.0: Pre-extracted items from signal_extractions
    if ctx.get("extracted_items"):
        parts.append(f"\n## PRE-EXTRACTED ACTION ITEMS (from Baker extraction engine, last 24h) — {len(ctx['extracted_items'])}")
        parts.append("These are already structured. Prioritize and format them as proposed actions.")
        for item in ctx["extracted_items"][:20]:
            owner = item.get("who", "?")
            when = f" (by {item['when']})" if item.get("when") else ""
            channel = item.get("_source_channel", "?")
            conf = item.get("confidence", "?")
            parts.append(f"  - [{channel}/{conf}] {owner}: {item.get('text', '')[:120]}{when}")

    return "\n".join(parts)


# ─────────────────────────────────────────────────
# Obligation extraction via Haiku
# ─────────────────────────────────────────────────

_OBLIGATION_PROMPT = """You are Baker, AI Chief of Staff. Extract SPECIFIC, ACTIONABLE tasks from today's signals.

Rules:
- ONE task per detected commitment, follow-up, or deadline — not summaries.
- Each task MUST include: who it involves, what happened (source), what's needed.
- source_type must be one of: email, whatsapp, meeting, calendar, deadline, cadence.
- source_ref MUST be the contact name or deadline description (never empty).
- due_date: ALWAYS inherit from the source deadline when available (YYYY-MM-DD format or null).
- Do NOT include vague tasks ("review inbox", "check priorities").
- Do NOT re-propose tasks that were proposed yesterday and not yet dismissed.
- Max 15 tasks. Quality over quantity.

completion_signals MUST use these exact patterns (Baker auto-detects these):
  - "email_to:person@domain.com" — Baker checks sent emails for this recipient
  - "email_from:person@domain.com" — Baker checks inbox for email from this sender
  - "meeting_with:Contact Name" — Baker checks calendar for meeting with this person
Do NOT use vague signals like "document_created" or "stakeholder_feedback_received".
Every action MUST have at least one email_to: or email_from: signal.

Return ONLY valid JSON:
{
  "actions": [
    {
      "title": "Follow up with Robin on Kempinski timeline",
      "description": "Robin hasn't responded to your March 15 email about the Kempinski acquisition timeline. 18 days silent (normally responds every 5 days).",
      "source_type": "cadence",
      "source_ref": "Robin Schmidt",
      "suggested_action": "Send one-line check-in asking about Kempinski timeline",
      "completion_signals": ["email_to:robin@example.com"],
      "priority_rank": 2,
      "due_date": null
    }
  ]
}"""


def _generate_proposed_actions(context_str: str) -> list:
    """Call Haiku to extract specific task proposals from today's signals."""
    try:
        from orchestrator.gemini_client import call_flash
        resp = call_flash(
                messages=[{"role": "user", "content": context_str}],
        )

        # Log cost
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(
                "gemini-2.5-flash", resp.usage.input_tokens,
                resp.usage.output_tokens, source="obligation_generator",
            )
        except Exception:
            pass

        raw = resp.text.strip()
        # Strip markdown code fences
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        result = json.loads(raw)
        actions = result.get("actions", [])
        logger.info(f"Generated {len(actions)} proposed actions")
        return actions[:15]  # Max 15

    except json.JSONDecodeError as e:
        logger.error(f"Obligation JSON parse failed: {e}")
        return []
    except Exception as e:
        logger.error(f"Obligation generation failed: {e}")
        return []


# ─────────────────────────────────────────────────
# Storage
# ─────────────────────────────────────────────────

def _is_travel_related(title: str) -> bool:
    """TRAVEL-HYGIENE-1: Check if proposed obligation is travel-related."""
    travel_kw = ['flight', 'departure', 'airport', 'check-in', 'travel', 'train', 'boarding']
    t = (title or "").lower()
    return any(kw in t for kw in travel_kw)


def _existing_travel_alert_exists(store) -> bool:
    """TRAVEL-HYGIENE-1: Check if any pending travel alert already exists."""
    conn = store._get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 1 FROM alerts
            WHERE status = 'pending'
              AND (tags ? 'travel' OR title ILIKE '%%flight%%' OR title ILIKE '%%departure%%')
            LIMIT 1
        """)
        exists = cur.fetchone() is not None
        cur.close()
        return exists
    except Exception:
        return False
    finally:
        store._put_conn(conn)


def _store_obligation_alerts(actions: list) -> list:
    """Create alerts for each obligation. Returns list of alert IDs."""
    if not actions:
        return []

    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        ids = []
        for action in actions:
            # TRAVEL-HYGIENE-1: Skip travel obligations if a travel alert already exists
            action_title = action.get("title", "")
            if _is_travel_related(action_title):
                if _existing_travel_alert_exists(store):
                    logger.info(f"TRAVEL-HYGIENE-1: skipped travel obligation — alert already exists: {action_title[:60]}")
                    continue

            due_date = action.get("due_date")
            if due_date:
                try:
                    datetime.strptime(due_date, "%Y-%m-%d")
                except (ValueError, TypeError):
                    due_date = None

            # Map priority_rank → tier: 1→T1, 2→T2, 3+→T3
            prio = action.get("priority_rank", 2)
            tier = min(prio, 3)

            source_type = action.get("source_type", "")
            tags = ["obligation"]
            if source_type:
                tags.append(source_type)

            structured = {
                "suggested_action": action.get("suggested_action", ""),
                "completion_signals": action.get("completion_signals", []),
                "source_ref": action.get("source_ref", ""),
                "due_date": due_date,
                "source_type": source_type,
            }

            alert_id = store.create_alert(
                tier=tier,
                title=action.get("title", "")[:200],
                body=action.get("description", ""),
                action_required=True,
                tags=tags,
                source="obligation",
                source_id=f"obligation-{date.today().isoformat()}-{action.get('title', '')[:50]}",
                structured_actions=structured,
            )
            if alert_id:
                ids.append(alert_id)

        logger.info(f"Stored {len(ids)} obligation alerts: {ids}")
        return ids
    except Exception as e:
        logger.error(f"Obligation alert storage failed: {e}")
        return []


# ─────────────────────────────────────────────────
# Morning push notification
# ─────────────────────────────────────────────────

def _send_morning_push(count: int):
    """Send single morning push notification with proposed action count."""
    if count == 0:
        return

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.debug("pywebpush not installed — skipping morning push")
        return

    vapid_private = config.web_push.vapid_private_key
    vapid_email = config.web_push.vapid_contact_email
    if not vapid_private or not vapid_email:
        logger.debug("VAPID keys not configured — skipping morning push")
        return

    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    subs = store.get_all_push_subscriptions()
    if not subs:
        return

    payload = json.dumps({
        "type": "morning_triage",
        "title": f"Baker has {count} proposed actions for today",
        "tier": 2,
        "url": "/mobile?tab=feed",
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
                logger.info(f"Removed expired push subscription: {sub['endpoint'][:60]}...")
            else:
                logger.warning(f"Morning push failed for {sub['endpoint'][:60]}: {e}")
        except Exception as e:
            logger.warning(f"Morning push error: {e}")

    logger.info(f"Morning push sent to {sent}/{len(subs)} subscriptions ({count} actions)")


# ─────────────────────────────────────────────────
# API helpers
# ─────────────────────────────────────────────────

def get_proposed_actions(status: str = "proposed", days: int = 7) -> list:
    """Get proposed actions for API endpoint."""
    _ensure_proposed_actions_table()
    try:
        from memory.store_back import SentinelStoreBack
        import psycopg2.extras
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if status:
                cur.execute(f"""
                    SELECT id, title, description, source_type, source_ref,
                           source_snippet, owner, due_date, suggested_action,
                           completion_signals, priority_rank, status,
                           director_response, escalated_to, run_date,
                           created_at, triaged_at, completed_at
                    FROM proposed_actions
                    WHERE status = %s
                      AND created_at > NOW() - INTERVAL '{int(days)} days'
                    ORDER BY priority_rank ASC, created_at DESC
                    LIMIT 50
                """, (status,))
            else:
                cur.execute(f"""
                    SELECT id, title, description, source_type, source_ref,
                           source_snippet, owner, due_date, suggested_action,
                           completion_signals, priority_rank, status,
                           director_response, escalated_to, run_date,
                           created_at, triaged_at, completed_at
                    FROM proposed_actions
                    WHERE created_at > NOW() - INTERVAL '{int(days)} days'
                    ORDER BY created_at DESC
                    LIMIT 50
                """)
            results = []
            for r in cur.fetchall():
                row = dict(r)
                # Serialize dates
                for key in ("due_date", "run_date", "created_at", "triaged_at", "completed_at"):
                    if row.get(key) and hasattr(row[key], "isoformat"):
                        row[key] = row[key].isoformat()
                results.append(row)
            cur.close()
            return results
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"get_proposed_actions failed: {e}")
        return []


def get_proposed_actions_count() -> int:
    """Get count of proposed (untriaged) actions."""
    _ensure_proposed_actions_table()
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return 0
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*) FROM proposed_actions
                WHERE status = 'proposed'
                  AND run_date >= CURRENT_DATE - 1
            """)
            count = cur.fetchone()[0]
            cur.close()
            return count
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"get_proposed_actions_count failed: {e}")
        return 0


def respond_to_action(action_id: int, response: str, escalate_to: str = None) -> bool:
    """Record Director's response to a proposed action."""
    valid_responses = ("approved", "dismissed", "done", "escalated")
    if response not in valid_responses:
        logger.warning(f"Invalid response '{response}' for action {action_id}")
        return False

    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            now = datetime.now(timezone.utc)

            if response == "escalated" and escalate_to:
                cur.execute("""
                    UPDATE proposed_actions
                    SET status = 'escalated',
                        director_response = %s,
                        escalated_to = %s,
                        triaged_at = %s
                    WHERE id = %s
                """, (response, escalate_to, now, action_id))
            elif response == "done":
                cur.execute("""
                    UPDATE proposed_actions
                    SET status = 'done',
                        director_response = %s,
                        triaged_at = %s,
                        completed_at = %s
                    WHERE id = %s
                """, (response, now, now, action_id))
            else:
                cur.execute("""
                    UPDATE proposed_actions
                    SET status = %s,
                        director_response = %s,
                        triaged_at = %s
                    WHERE id = %s
                """, (response, response, now, action_id))

            conn.commit()
            cur.close()
            return True
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"respond_to_action failed: {e}")
        return False


# ─────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────

def run_obligation_generator():
    """
    Main entry point — called by scheduler daily at 06:50 UTC.
    1. Advisory lock 900600
    2. Check daily rate limit
    3. Gather signals
    4. Haiku extracts per-item task proposals
    5. Store in proposed_actions
    6. Send single morning push
    """
    from triggers.sentinel_health import report_success, report_failure

    _ensure_proposed_actions_table()

    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return

        try:
            cur = conn.cursor()
            cur.execute("SELECT pg_try_advisory_xact_lock(900600)")
            if not cur.fetchone()[0]:
                logger.info("Obligation generator: another instance running — skipping")
                return

            # Check if already ran today
            cur.execute("""
                SELECT COUNT(*) FROM alerts
                WHERE source = 'obligation'
                  AND created_at >= CURRENT_DATE
            """)
            try:
                count = cur.fetchone()[0]
            except Exception:
                count = 0

            if count > 0:
                logger.info(f"Obligation generator: already generated {count} actions today — skipping")
                return
            cur.close()
        finally:
            store._put_conn(conn)

        # Gather signals
        logger.info("Obligation generator: gathering signals...")
        ctx = _gather_signals()

        # Format for Haiku
        context_str = _format_signals(ctx)
        logger.info(f"Obligation context: {len(context_str)} chars")

        # Check if there's enough signal
        signal_count = (
            len(ctx["approaching_deadlines"])
            + len(ctx["overdue_deadlines"])
            + len(ctx["cadence_anomalies"])
            + len(ctx["unanswered_emails"])
            + len(ctx["pending_alerts"])
        )
        if signal_count == 0 and not ctx["priorities"]:
            logger.info("Obligation generator: no signals and no priorities — skipping")
            return

        # Generate
        actions = _generate_proposed_actions(context_str)
        if not actions:
            logger.info("Obligation generator: no actions generated")
            return

        # Store as alerts
        ids = _store_obligation_alerts(actions)

        # Morning push
        _send_morning_push(len(ids))

        report_success("obligation_generator")
        logger.info(
            f"Obligation generator complete: {len(actions)} actions proposed, IDs: {ids}"
        )

    except Exception as e:
        report_failure("obligation_generator", str(e))
        logger.error(f"Obligation generator failed: {e}")
