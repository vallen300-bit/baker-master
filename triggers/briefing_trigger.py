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

    return "\n\n".join(sections)


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

    # Build briefing trigger
    briefing_content = (
        f"Generate the Baker Morning Briefing for {date_str}.\n\n"
        f"Use this format:\n"
        f"BAKER MORNING BRIEFING — {date_str}\n\n"
        f"IMMEDIATE (Tier 1)\n"
        f"- [urgent alert summaries]\n\n"
        f"TODAY (Tier 2)\n"
        f"- [items needing attention within 24h]\n\n"
        f"RADAR\n"
        f"- [deal updates, project status, people waiting]\n\n"
        f"OVERNIGHT\n"
        f"- [summary of emails/messages received since last briefing]\n\n"
        f"DECISIONS PENDING\n"
        f"- [any draft messages awaiting CEO approval]\n\n"
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
