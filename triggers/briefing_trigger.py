"""
Sentinel Trigger — Daily Morning Briefing
Generates Baker's morning briefing at 08:00 CET (06:00 UTC).
Gathers all overnight activity, pending alerts, and queued items.
"""
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.settings import config
from triggers.state import trigger_state

logger = logging.getLogger("sentinel.trigger.briefing")

# Output directory for briefings
_BAKER_MASTER_ROOT = _PROJECT_ROOT.parent
_OUTPUT_DIR = _BAKER_MASTER_ROOT / "04_outputs" / "briefings"


def gather_briefing_context() -> str:
    """
    Gather all context needed for the morning briefing:
    - Queued low-priority items from overnight
    - Pending alerts from PostgreSQL
    - Recent decisions
    - Active deals status
    """
    sections = []

    # 0. Weekly priorities (shapes the entire briefing)
    try:
        from orchestrator.priority_manager import get_current_priorities
        priorities = get_current_priorities()
        if priorities:
            prio_lines = ["DIRECTOR'S PRIORITIES THIS WEEK:"]
            for p in priorities:
                matter = f" [{p['matter_slug']}]" if p.get("matter_slug") else ""
                prio_lines.append(f"  {p['rank']}. {p['priority_text']}{matter}")
            prio_lines.append("Lead the briefing with updates on these priorities.")
            sections.append("\n".join(prio_lines))
    except Exception:
        pass

    # 1. Queued overnight items
    queue = trigger_state.get_briefing_queue()
    if queue:
        email_items = [q for q in queue if q.get("type") == "email"]
        wa_items = [q for q in queue if q.get("type") == "whatsapp"]
        other_items = [q for q in queue if q.get("type") not in ("email", "whatsapp")]

        overnight = []
        if email_items:
            overnight.append(f"  Emails ({len(email_items)}):")
            for item in email_items[:20]:
                subject = item.get("subject", "no subject")
                sender = item.get("contact_name", "unknown")
                overnight.append(f"    - From {sender}: {subject}")

        if wa_items:
            overnight.append(f"  WhatsApp ({len(wa_items)}):")
            for item in wa_items[:20]:
                name = item.get("contact_name", "unknown")
                count = item.get("message_count", "?")
                overnight.append(f"    - {name}: {count} messages")

        if other_items:
            overnight.append(f"  Other ({len(other_items)}):")
            for item in other_items[:10]:
                overnight.append(f"    - [{item.get('type')}] {item.get('content', '')[:80]}")

        if overnight:
            sections.append("OVERNIGHT ITEMS:\n" + "\n".join(overnight))
    else:
        sections.append("OVERNIGHT ITEMS: None — quiet night.")

    # 2. Pending alerts from PostgreSQL
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack()
        alerts = store.get_pending_alerts()
        if alerts:
            alert_lines = []
            for a in alerts:
                tier_label = {1: "URGENT", 2: "IMPORTANT", 3: "INFO"}.get(a["tier"], "?")
                alert_lines.append(f"  [{tier_label}] {a['title']}: {a.get('body', '')[:100]}")
            sections.append(f"PENDING ALERTS ({len(alerts)}):\n" + "\n".join(alert_lines))
        else:
            sections.append("PENDING ALERTS: None — all clear.")
    except Exception as e:
        logger.warning(f"Could not fetch pending alerts: {e}")
        sections.append("PENDING ALERTS: [could not retrieve]")

    # 3. Active deals
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack()
        deals = store.get_active_deals()
        if deals:
            deal_lines = []
            for d in deals:
                meta = d.get("metadata") or {}
                if isinstance(meta, str):
                    import json as _json
                    try:
                        meta = _json.loads(meta)
                    except Exception:
                        meta = {}
                next_action = meta.get("next_action") or d.get("stage") or "no action set"
                value = d.get("deal_value", "")
                currency = d.get("currency", "")
                val_str = f" ({currency} {value})" if value else ""
                deal_lines.append(f"  - {d['name']}{val_str}: {next_action}")
            sections.append(f"ACTIVE DEALS ({len(deals)}):\n" + "\n".join(deal_lines))
    except Exception as e:
        logger.warning(f"Could not fetch active deals: {e}")

    # 4. Owner's Lens — strategic signals (MOHG, network contacts, deal flow)
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if conn:
            try:
                cur = conn.cursor()
                # Find alerts with owner-relevant keywords from last 24h
                cur.execute("""
                    SELECT tier, title, body FROM alerts
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                      AND status = 'pending'
                      AND (
                        title ~* '(Mandarin.Oriental|MOHG|MO.Vienna|MORV|branded.residence|luxury.hotel|sovereign.wealth|family.office|joint.venture|co.invest|strategic.partner|Oskolkov|Aelio|capital.call|Hagenauer)'
                        OR title ~* '(Soulier|Yurkovich|UBM|Wertheimer|Kulibayev|Strothotte|CITIC|Al.Thani|Oskolkov|Buchwalder|Pohanis)'
                        OR body ~* '(Mandarin.Oriental|MOHG|MO.Vienna|MORV|branded.residence|luxury.hotel|sovereign.wealth|family.office|joint.venture|co.invest|strategic.partner|Oskolkov|Aelio|capital.call|Hagenauer)'
                        OR body ~* '(Soulier|Yurkovich|UBM|Wertheimer|Kulibayev|Strothotte|CITIC|Al.Thani|Oskolkov|Buchwalder|Pohanis)'
                      )
                    ORDER BY tier, created_at DESC
                    LIMIT 10
                """)
                owner_alerts = cur.fetchall()
                cur.close()
                if owner_alerts:
                    owner_lines = []
                    for a in owner_alerts:
                        tier_label = {1: "URGENT", 2: "IMPORTANT", 3: "INFO"}.get(a[0], "?")
                        owner_lines.append(f"  [{tier_label}] {a[1]}: {(a[2] or '')[:120]}")
                    sections.insert(0, f"OWNER'S LENS — STRATEGIC SIGNALS ({len(owner_alerts)}):\n" + "\n".join(owner_lines))
                else:
                    sections.insert(0, "OWNER'S LENS — STRATEGIC SIGNALS: No strategic signals in last 24h.")
            except Exception as e:
                logger.warning(f"Could not fetch owner lens alerts: {e}")
                sections.insert(0, "OWNER'S LENS — STRATEGIC SIGNALS: [could not retrieve]")
            finally:
                store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Owner's lens context failed: {e}")

    # 5. AO PM — Investor relationship health check
    ao_ctx = _gather_ao_pm_context()
    if ao_ctx:
        sections.append(f"AO INVESTOR RELATIONSHIP STATUS:\n{ao_ctx}")

    return "\n\n".join(sections)


def _gather_ao_pm_context() -> str:
    """
    Gather AO-specific context for the daily briefing.
    Checks: communication gap, pending discussion items, approaching deadlines.
    This gives Opus the raw material to reason through the AO psychology lens.
    """
    parts = []
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return ""
        try:
            cur = conn.cursor()

            # 1. Last AO-directed communication (email + WhatsApp)
            cur.execute("""
                SELECT 'email' as channel, MAX(created_at) as last_contact
                FROM sent_emails
                WHERE to_address ILIKE '%%oskolkov%%' OR to_address ILIKE '%%aelio%%'
                UNION ALL
                SELECT 'whatsapp', MAX(timestamp)
                FROM whatsapp_messages
                WHERE is_director = true
                  AND (full_text ILIKE '%%oskolkov%%' OR full_text ILIKE '%%andrey%%')
                LIMIT 5
            """)
            contacts = cur.fetchall()
            last_contact = None
            for row in contacts:
                if row[1] and (last_contact is None or row[1] > last_contact):
                    last_contact = row[1]

            if last_contact:
                from datetime import datetime, timezone
                gap_days = (datetime.now(timezone.utc) - last_contact).days
                parts.append(f"AO COMMUNICATION GAP: {gap_days} days since last outbound")
                if gap_days >= 10:
                    parts.append("  ** WARNING: Approaching Rule Zero threshold (14 days) **")
                if gap_days >= 14:
                    parts.append("  ** CRITICAL: Rule Zero violated — silence preceding ask **")
            else:
                parts.append("AO COMMUNICATION GAP: Unknown — no outbound records found")

            # 2. Pending discussion items count
            cur.execute("""
                SELECT jsonb_array_length(state_json->'pending_discussion_with_ao')
                FROM ao_project_state
                WHERE state_key = 'current'
                LIMIT 1
            """)
            row = cur.fetchone()
            pending_count = row[0] if row and row[0] else 0
            if pending_count > 0:
                parts.append(f"AO PENDING ITEMS: {pending_count} items awaiting discussion with AO")

            # 3. AO-related deadlines approaching
            cur.execute("""
                SELECT description, due_date
                FROM deadlines
                WHERE status = 'active'
                  AND due_date <= NOW() + INTERVAL '14 days'
                  AND (description ILIKE '%%oskolkov%%' OR description ILIKE '%%aelio%%'
                       OR description ILIKE '%%aukera%%' OR description ILIKE '%%rg7%%'
                       OR description ILIKE '%%capital call%%')
                ORDER BY due_date
                LIMIT 5
            """)
            deadlines = cur.fetchall()
            if deadlines:
                dl_lines = [f"  - {d[0]}: {d[1].strftime('%Y-%m-%d')}" for d in deadlines]
                parts.append(f"AO DEADLINES (next 14 days):\n" + "\n".join(dl_lines))

            cur.close()
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.warning(f"AO PM briefing context failed: {e}")
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"AO PM briefing context outer error: {e}")

    return "\n".join(parts) if parts else ""


def deliver_briefing(briefing_text: str, date_str: str):
    """
    Deliver the briefing to configured outputs:
    1. Save as markdown file
    2. Post to Slack (if webhook configured)
    """
    # 1. Save to file
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"briefing_{date_str}.md"
    filepath = _OUTPUT_DIR / filename
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(briefing_text)
    logger.info(f"Briefing saved to {filepath}")

    # 2. Post to Slack (Block Kit)
    try:
        from outputs.slack_notifier import SlackNotifier
        notifier = SlackNotifier()
        notifier.post_briefing(briefing_text, date_str)
    except Exception as e:
        logger.warning(f"Could not post briefing to Slack: {e}")


def generate_morning_briefing():
    """
    Main entry point — called by scheduler at 06:00 UTC (08:00 CET).
    1. Gathers all context
    2. Runs pipeline with briefing prompt
    3. Delivers output
    4. Clears briefing queue
    """
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logger.info(f"Generating morning briefing for {date_str}...")

    # Gather context
    briefing_context = gather_briefing_context()
    logger.info(f"Briefing context gathered ({len(briefing_context)} chars)")

    # Build briefing trigger — EMAIL-REFORM-1 structured format
    # The output of this prompt gets embedded directly into the Type 3 daily briefing email.
    # It must produce exactly these two sections (Claude-synthesized, not raw data):
    briefing_content = (
        f"Generate Baker's executive daily briefing for {date_str}.\n\n"
        f"You are Baker, the CEO's AI chief of staff. Write a 2-minute-read executive summary.\n"
        f"Be concise, direct, and prioritize by relevance to the Director.\n\n"
        f"The briefing has TWO parts — Owner's View first, then Operations.\n\n"
        f"Use EXACTLY this format (these sections are embedded into the daily email):\n\n"
        f"\U0001f3e8 OWNER'S VIEW\n"
        f"\u2022 [Strategic signals: MOHG activity, network contacts, luxury hospitality M&A, deal opportunities, co-investment signals]\n"
        f"\u2022 [Item 2]\n"
        f"(If no strategic signals: \"No strategic signals today.\" — always show this section.)\n\n"
        f"\U0001f4cc DECISIONS NEEDED\n"
        f"\u2022 [Item requiring Director action — be specific about what decision is needed]\n"
        f"\u2022 [Item 2]\n"
        f"(If none: \"No pending decisions today.\")\n\n"
        f"\U0001f4ca OPERATIONS (last 24h)\n"
        f"\u2022 [Top development — synthesize, don't just list raw data]\n"
        f"\u2022 [Development 2]\n"
        f"\u2022 [Development 3]\n"
        f"(Max 5 items. Prioritize by relevance to Director.)\n\n"
        f"Rules:\n"
        f"- OWNER'S VIEW comes first — even if empty, show the section header.\n"
        f"- Owner's View covers: Mandarin Oriental news, MOHG activity, luxury hospitality deals/M&A, "
        f"any mention of strategic network contacts (Soulier, Yurkovich, UBM, Wertheimer, Kulibayev, "
        f"Strothotte, CITIC, Al-Thani), co-investment opportunities, DACH region deal flow.\n"
        f"- OPERATIONS covers: project updates, deadline status, team communications, routine alerts.\n"
        f"- Synthesize the information — do NOT just dump raw items.\n"
        f"- Write like a chief of staff briefing a CEO: what matters, what needs action.\n"
        f"- Keep each bullet to 1-2 lines max.\n\n"
        f"---\n"
        f"Here is the overnight context to summarize:\n\n"
        f"{briefing_context}"
    )

    from orchestrator.pipeline import SentinelPipeline, TriggerEvent
    pipeline = SentinelPipeline()
    trigger = TriggerEvent(
        type="scheduled",
        content=briefing_content,
        source_id=f"briefing-{date_str}",
        priority="medium",
    )

    try:
        response = pipeline.run(trigger)
        briefing_text = response.analysis or response.raw_response
        logger.info(f"Briefing generated ({len(briefing_text)} chars)")
    except Exception as e:
        logger.error(f"Morning briefing pipeline failed: {e}")
        # Fallback: use the raw context as a basic briefing
        briefing_text = (
            f"BAKER MORNING BRIEFING — {date_str}\n"
            f"(Auto-generated — pipeline error: {e})\n\n"
            f"{briefing_context}"
        )

    # Deliver
    deliver_briefing(briefing_text, date_str)

    # Email daily summary to Director (EMAIL-SMART-1 Type 3)
    try:
        from outputs.email_alerts import send_daily_summary_email
        send_daily_summary_email(briefing_text)
    except Exception as e:
        logger.warning(f"Daily summary email failed (non-fatal): {e}")

    # Clear the queue
    trigger_state.clear_briefing_queue()

    logger.info("Morning briefing complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    generate_morning_briefing()
