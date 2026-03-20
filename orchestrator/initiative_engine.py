"""
PROACTIVE-INITIATIVE-1 — Proactive Initiative Engine (Session 29)

Baker proposes 2-3 specific, actionable initiatives daily.

Runs once per day at 07:00 UTC (09:00 CET). Combines:
  - Weekly priorities (what matters)
  - Calendar gaps (when Director has time)
  - Approaching deadlines (what's urgent)
  - Cadence anomalies (who needs attention)
  - Overdue follow-ups (what's slipping)
  - Pending T1/T2 alerts (unresolved issues)

Output: 2-3 initiatives, each with a reason and suggested action.
Delivered via WhatsApp + T2 alert in dashboard.

Cost: ~EUR 0.50/day (single Haiku call).
"""
import json
import logging
from datetime import datetime, timezone, timedelta, date

import anthropic

from config.settings import config

logger = logging.getLogger("baker.initiative_engine")


# ─────────────────────────────────────────────────
# Table setup
# ─────────────────────────────────────────────────

def _ensure_table():
    """Create proactive_initiatives table if not exists."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS proactive_initiatives (
                    id SERIAL PRIMARY KEY,
                    run_date DATE NOT NULL DEFAULT CURRENT_DATE,
                    title TEXT NOT NULL,
                    rationale TEXT,
                    suggested_action JSONB,
                    priority_rank INTEGER DEFAULT 1,
                    status VARCHAR(20) DEFAULT 'proposed',
                    director_response VARCHAR(20),
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_initiatives_date
                ON proactive_initiatives(run_date)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_initiatives_status
                ON proactive_initiatives(status)
                WHERE status = 'proposed'
            """)
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Could not ensure proactive_initiatives table: {e}")


# ─────────────────────────────────────────────────
# Context gathering
# ─────────────────────────────────────────────────

def _gather_context() -> dict:
    """Gather all signals that inform initiative proposals."""
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
    }

    conn = store._get_conn()
    if not conn:
        return ctx

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        now = datetime.now(timezone.utc)

        # 1. Weekly priorities
        try:
            cur.execute("""
                SELECT priority_text, matter_slug, rank
                FROM weekly_priorities
                WHERE active = TRUE
                ORDER BY rank ASC
                LIMIT 5
            """)
            ctx["priorities"] = [dict(r) for r in cur.fetchall()]
        except Exception:
            # Table may not exist — rollback to reset transaction state
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
            ORDER BY due_date ASC
            LIMIT 10
        """)
        ctx["approaching_deadlines"] = [
            {**dict(r), "due_date": r["due_date"].isoformat() if r.get("due_date") else None}
            for r in cur.fetchall()
        ]

        # 3. Overdue deadlines
        cur.execute("""
            SELECT description, due_date, priority, matter_slug
            FROM deadlines
            WHERE status = 'active'
              AND due_date < CURRENT_DATE
            ORDER BY due_date ASC
            LIMIT 10
        """)
        ctx["overdue_deadlines"] = [
            {**dict(r), "due_date": r["due_date"].isoformat() if r.get("due_date") else None}
            for r in cur.fetchall()
        ]

        # 4. Cadence anomalies — contacts with silence > 3x normal AND > 7 days
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

        # 5. Unanswered sent emails (sent by Director, no reply in 48h+)
        try:
            cur.execute("""
                SELECT recipient, subject, created_at
                FROM sent_emails
                WHERE created_at > NOW() - INTERVAL '14 days'
                  AND created_at < NOW() - INTERVAL '48 hours'
                  AND reply_received = FALSE
                ORDER BY created_at DESC
                LIMIT 5
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
            ORDER BY tier ASC, created_at DESC
            LIMIT 10
        """)
        ctx["pending_alerts"] = [
            {**dict(r), "created_at": r["created_at"].isoformat() if r.get("created_at") else None}
            for r in cur.fetchall()
        ]

        # 7. Recent chains (last 3 days — to avoid re-proposing what chains already handled)
        try:
            cur.execute("""
                SELECT title, domain, status, created_at
                FROM baker_tasks
                WHERE task_type = 'chain'
                  AND created_at > NOW() - INTERVAL '3 days'
                ORDER BY created_at DESC
                LIMIT 5
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

        cur.close()
    except Exception as e:
        logger.error(f"Initiative context gathering failed: {e}")
    finally:
        store._put_conn(conn)

    # 8. Calendar next 48h (separate — needs Google API)
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
        logger.debug(f"Calendar fetch for initiatives failed (non-fatal): {e}")

    return ctx


def _format_context(ctx: dict) -> str:
    """Format context dict into a prompt string for Haiku."""
    parts = []
    today = date.today().isoformat()
    parts.append(f"Date: {today}")

    # Priorities
    if ctx["priorities"]:
        parts.append("\n## WEEKLY PRIORITIES")
        for p in ctx["priorities"]:
            matter = f" [{p.get('matter_slug', '')}]" if p.get("matter_slug") else ""
            parts.append(f"  {p.get('rank', '?')}. {p['priority_text']}{matter}")
    else:
        parts.append("\n## WEEKLY PRIORITIES\nNone set.")

    # Calendar
    if ctx["calendar_next_48h"]:
        parts.append(f"\n## CALENDAR (next 48h) — {len(ctx['calendar_next_48h'])} events")
        for m in ctx["calendar_next_48h"][:8]:
            parts.append(f"  - {m['start'][:16]} {m['title']} ({m['attendees']} attendees)")
    else:
        parts.append("\n## CALENDAR (next 48h)\nNo meetings — wide open.")

    # Approaching deadlines
    if ctx["approaching_deadlines"]:
        parts.append(f"\n## APPROACHING DEADLINES (next 7 days) — {len(ctx['approaching_deadlines'])}")
        for d in ctx["approaching_deadlines"]:
            parts.append(f"  - [{d.get('priority', 'normal').upper()}] {d['due_date']}: {d['description'][:100]}")

    # Overdue deadlines
    if ctx["overdue_deadlines"]:
        parts.append(f"\n## OVERDUE DEADLINES — {len(ctx['overdue_deadlines'])}")
        for d in ctx["overdue_deadlines"]:
            parts.append(f"  - [{d.get('priority', 'normal').upper()}] {d['due_date']}: {d['description'][:100]}")

    # Cadence anomalies
    if ctx["cadence_anomalies"]:
        parts.append(f"\n## CONTACTS GOING QUIET — {len(ctx['cadence_anomalies'])}")
        for c in ctx["cadence_anomalies"]:
            parts.append(
                f"  - {c['name']} (T{c.get('tier', '?')}): {int(c['days_silent'])}d silent "
                f"(normal: every {c['avg_gap_days']}d, {c['deviation']}x deviation)"
            )

    # Unanswered emails
    if ctx["unanswered_emails"]:
        parts.append(f"\n## UNANSWERED SENT EMAILS — {len(ctx['unanswered_emails'])}")
        for e in ctx["unanswered_emails"]:
            parts.append(f"  - To: {e.get('recipient', '?')} — {e.get('subject', '?')} (sent {e.get('created_at', '?')[:10]})")

    # Pending alerts
    if ctx["pending_alerts"]:
        t1 = [a for a in ctx["pending_alerts"] if a.get("tier") == 1]
        t2 = [a for a in ctx["pending_alerts"] if a.get("tier") == 2]
        parts.append(f"\n## PENDING ALERTS — {len(t1)} urgent, {len(t2)} important")
        for a in ctx["pending_alerts"][:5]:
            tier_label = "URGENT" if a.get("tier") == 1 else "IMPORTANT"
            parts.append(f"  - [{tier_label}] {a['title'][:80]}")

    # Recent chains (to avoid duplication)
    if ctx["recent_chains"]:
        parts.append(f"\n## RECENTLY HANDLED BY CHAINS — do NOT re-propose these")
        for c in ctx["recent_chains"]:
            parts.append(f"  - {c['title'][:80]}")

    return "\n".join(parts)


# ─────────────────────────────────────────────────
# Initiative generation via Haiku
# ─────────────────────────────────────────────────

_INITIATIVE_PROMPT = """You are Baker, AI Chief of Staff for Dimitry Vallen (Chairman, Brisen Group).

Based on today's signals, propose 2-3 SPECIFIC, ACTIONABLE initiatives the Director should take TODAY or THIS WEEK.

Rules:
- Each initiative must be SPECIFIC — name the person, deadline, project, or action.
- Each initiative must explain WHY NOW — what's the urgency or opportunity.
- Each initiative must include a concrete suggested_action (one of: draft_email, create_deadline, schedule_meeting, review_document, call_contact, block_time).
- Do NOT propose generic advice ("review your priorities", "check your inbox").
- Do NOT re-propose things that chains have recently handled.
- Prioritize by impact: relationship risks > deadline risks > opportunities.
- If the Director has weekly priorities, align initiatives with them.
- If there's nothing urgent, propose relationship maintenance or strategic preparation.
- Max 3 initiatives. Quality over quantity.

Return ONLY valid JSON:
{
  "initiatives": [
    {
      "title": "Short, specific title (e.g., 'Follow up with Hassa — 18 days silent')",
      "rationale": "Why this matters now — 2-3 sentences with specific data.",
      "suggested_action": {
        "type": "draft_email|create_deadline|schedule_meeting|review_document|call_contact|block_time",
        "details": "Specific details (e.g., 'Draft a casual check-in to Hassa asking about Kempinski timeline')"
      },
      "priority_rank": 1
    }
  ]
}"""


def _generate_initiatives(context_str: str) -> list:
    """Call Haiku to generate 2-3 initiatives based on today's signals."""
    try:
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            system=_INITIATIVE_PROMPT,
            messages=[{"role": "user", "content": context_str}],
        )

        # Log cost
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(
                "claude-haiku-4-5-20251001", resp.usage.input_tokens,
                resp.usage.output_tokens, source="initiative_engine",
            )
        except Exception:
            pass

        raw = resp.content[0].text.strip()
        # Strip markdown code fences
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        result = json.loads(raw)
        initiatives = result.get("initiatives", [])
        logger.info(f"Generated {len(initiatives)} initiatives")
        return initiatives[:3]  # Max 3

    except json.JSONDecodeError as e:
        logger.error(f"Initiative JSON parse failed: {e}")
        return []
    except Exception as e:
        logger.error(f"Initiative generation failed: {e}")
        return []


# ─────────────────────────────────────────────────
# Storage
# ─────────────────────────────────────────────────

def _store_initiatives(initiatives: list) -> list:
    """Store initiatives in proactive_initiatives table. Returns list of IDs."""
    _ensure_table()
    if not initiatives:
        return []

    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor()
            ids = []
            for init in initiatives:
                cur.execute("""
                    INSERT INTO proactive_initiatives
                        (title, rationale, suggested_action, priority_rank)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                """, (
                    init.get("title", "")[:200],
                    init.get("rationale", ""),
                    json.dumps(init.get("suggested_action", {})),
                    init.get("priority_rank", 1),
                ))
                ids.append(cur.fetchone()[0])
            conn.commit()
            cur.close()
            logger.info(f"Stored {len(ids)} initiatives: {ids}")
            return ids
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"Initiative storage failed: {e}")
        return []


# ─────────────────────────────────────────────────
# Delivery — WhatsApp + Alert
# ─────────────────────────────────────────────────

def _deliver_initiatives(initiatives: list):
    """Send initiatives to Director via WhatsApp and create dashboard alert."""
    if not initiatives:
        return

    # Build WhatsApp message
    wa_lines = ["Baker's initiatives for today:"]
    for i, init in enumerate(initiatives, 1):
        wa_lines.append(f"\n{i}. {init.get('title', '')}")
        wa_lines.append(f"   → {init.get('rationale', '')[:120]}")
        action = init.get("suggested_action", {})
        if action:
            wa_lines.append(f"   Action: {action.get('details', action.get('type', ''))[:80]}")

    wa_text = "\n".join(wa_lines)

    # Send WhatsApp
    try:
        from outputs.whatsapp_sender import send_whatsapp
        send_whatsapp(f"[Initiatives] {wa_text}"[:1500])
        logger.info("Initiatives sent to Director via WhatsApp")
    except Exception as e:
        logger.warning(f"Initiative WA delivery failed (non-fatal): {e}")

    # Create dashboard alert
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()

        body_parts = []
        for i, init in enumerate(initiatives, 1):
            body_parts.append(f"### {i}. {init.get('title', '')}")
            body_parts.append(init.get("rationale", ""))
            action = init.get("suggested_action", {})
            if action:
                body_parts.append(f"**Suggested:** {action.get('details', action.get('type', ''))}")
            body_parts.append("")

        alert_body = "\n".join(body_parts)

        store.create_alert(
            tier=2,
            title=f"Baker's initiatives — {date.today().strftime('%b %d')}",
            body=alert_body[:4000],
            action_required=True,
            tags=["initiative", "proactive"],
            source="initiative_engine",
            source_id=f"initiative-{date.today().isoformat()}",
        )
        logger.info("Initiative alert created in dashboard")
    except Exception as e:
        logger.warning(f"Initiative alert creation failed: {e}")


# ─────────────────────────────────────────────────
# API helpers
# ─────────────────────────────────────────────────

def get_initiatives(days: int = 7) -> list:
    """Get recent initiatives for API endpoint."""
    _ensure_table()
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
                SELECT id, run_date, title, rationale, suggested_action,
                       priority_rank, status, director_response, created_at
                FROM proactive_initiatives
                WHERE created_at > NOW() - INTERVAL '%s days'
                ORDER BY created_at DESC
                LIMIT 30
            """.replace("%s days", f"{int(days)} days"))
            results = [dict(r) for r in cur.fetchall()]
            cur.close()
            return results
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"get_initiatives failed: {e}")
        return []


def respond_to_initiative(initiative_id: int, response: str) -> bool:
    """Record Director's response to an initiative (approved/dismissed/deferred)."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE proactive_initiatives
                SET director_response = %s,
                    status = CASE WHEN %s = 'approved' THEN 'approved'
                                  WHEN %s = 'dismissed' THEN 'dismissed'
                                  ELSE 'deferred' END
                WHERE id = %s
            """, (response, response, response, initiative_id))
            conn.commit()
            cur.close()
            return True
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"respond_to_initiative failed: {e}")
        return False


# ─────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────

def run_initiative_engine():
    """
    Main entry point — called by scheduler daily at 07:00 UTC.
    1. Check rate — only once per day
    2. Gather all signals
    3. Generate 2-3 initiatives via Haiku
    4. Store in database
    5. Deliver via WhatsApp + dashboard alert
    """
    from triggers.sentinel_health import report_success, report_failure

    # Ensure table exists before any queries
    _ensure_table()

    try:
        # Advisory lock — prevent double-run
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return

        try:
            cur = conn.cursor()
            cur.execute("SELECT pg_try_advisory_xact_lock(900300)")
            if not cur.fetchone()[0]:
                logger.info("Initiative engine: another instance running — skipping")
                return

            # Check if already ran today
            cur.execute("""
                SELECT COUNT(*) FROM proactive_initiatives
                WHERE run_date = CURRENT_DATE
            """)
            try:
                count = cur.fetchone()[0]
            except Exception:
                count = 0

            if count > 0:
                logger.info(f"Initiative engine: already generated {count} initiatives today — skipping")
                return
            cur.close()
        finally:
            store._put_conn(conn)

        # Gather context
        logger.info("Initiative engine: gathering context...")
        ctx = _gather_context()

        # Format for Haiku
        context_str = _format_context(ctx)
        logger.info(f"Initiative context: {len(context_str)} chars")

        # Check if there's enough signal to generate initiatives
        signal_count = (
            len(ctx["approaching_deadlines"])
            + len(ctx["overdue_deadlines"])
            + len(ctx["cadence_anomalies"])
            + len(ctx["unanswered_emails"])
            + len(ctx["pending_alerts"])
        )
        if signal_count == 0 and not ctx["priorities"]:
            logger.info("Initiative engine: no signals and no priorities — skipping")
            return

        # Generate
        initiatives = _generate_initiatives(context_str)
        if not initiatives:
            logger.info("Initiative engine: no initiatives generated")
            return

        # Store
        ids = _store_initiatives(initiatives)

        # Deliver
        _deliver_initiatives(initiatives)

        report_success("initiative_engine")
        logger.info(
            f"Initiative engine complete: {len(initiatives)} initiatives generated, "
            f"IDs: {ids}"
        )

    except Exception as e:
        report_failure("initiative_engine", str(e))
        logger.error(f"Initiative engine failed: {e}")
