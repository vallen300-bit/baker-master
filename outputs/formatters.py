"""
Baker AI — Output Formatters
Multi-format rendering: Slack Block Kit, plain text, markdown.
"""
import re
from datetime import datetime, timezone


# ============================================================
# Tier helpers
# ============================================================

def tier_emoji(tier: int) -> str:
    """Return emoji for alert tier."""
    return {1: "🔴", 2: "🟡", 3: "🟢"}.get(tier, "⚪")


def tier_label(tier: int) -> str:
    """Return label for alert tier."""
    return {1: "URGENT", 2: "IMPORTANT", 3: "INFO"}.get(tier, "UNKNOWN")


# ============================================================
# Text truncation
# ============================================================

def _truncate(text: str, max_len: int = 3000) -> str:
    """Truncate text for Block Kit limits (3000 chars per text block)."""
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


# ============================================================
# Alert formatters
# ============================================================

def format_alert_slack(alert: dict) -> dict:
    """
    Format a single alert as Slack Block Kit payload.
    alert keys: tier (int), title (str), body (str),
                action_required (bool), contact_name (str), deal_name (str)
    """
    tier = alert.get("tier", 3)
    emoji = tier_emoji(tier)
    label = tier_label(tier)
    title = alert.get("title", "Untitled")
    body = _truncate(alert.get("body", ""), 2800)
    contact = alert.get("contact_name")
    deal = alert.get("deal_name")
    action_required = alert.get("action_required", False)

    # Header block
    header_text = f"{emoji} {label}: {title}"
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_text[:150], "emoji": True},
        }
    ]

    # Body section — build mrkdwn with optional fields
    body_parts = []
    if contact:
        body_parts.append(f"*Contact:* {contact}")
    if deal:
        body_parts.append(f"*Deal:* {deal}")
    if body:
        if body_parts:
            body_parts.append("")  # blank line
        body_parts.append(body)

    if body_parts:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": _truncate("\n".join(body_parts))},
        })

    # Context line
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ctx_parts = [f"Baker AI • {now}"]
    if action_required:
        ctx_parts.append("Action required ✅")
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": " • ".join(ctx_parts)}],
    })

    return {"blocks": blocks}


def format_alert_text(alert: dict) -> str:
    """Format an alert as plain text (for file/log output)."""
    tier = alert.get("tier", 3)
    label = tier_label(tier)
    title = alert.get("title", "Untitled")
    body = alert.get("body", "")
    action = " [ACTION REQUIRED]" if alert.get("action_required") else ""
    return f"[{label}]{action} {title}\n{body}"


# ============================================================
# Briefing formatters
# ============================================================

_BRIEFING_HEADERS = [
    "IMMEDIATE",
    "TODAY",
    "RADAR",
    "OVERNIGHT",
    "DECISIONS PENDING",
]


def parse_briefing_sections(briefing_text: str) -> list:
    """
    Split briefing text on section headers.
    Returns list of {"title": ..., "content": ...} dicts.
    """
    if not briefing_text:
        return []

    # Build regex that matches known section headers
    pattern = r"(?:^|\n)\s*(?:#+\s*)?(" + "|".join(
        re.escape(h) for h in _BRIEFING_HEADERS
    ) + r")(?:\s*\(.*?\))?\s*\n"

    parts = re.split(pattern, briefing_text, flags=re.IGNORECASE)

    sections = []
    # First chunk before any header → intro
    intro = parts[0].strip()
    if intro:
        # Check if the intro contains the briefing title line
        lines = intro.split("\n")
        non_title_lines = [l for l in lines if "MORNING BRIEFING" not in l.upper() and l.strip() not in ("---", "")]
        if non_title_lines:
            sections.append({"title": "Overview", "content": "\n".join(non_title_lines).strip()})

    # Remaining pairs: [header, content, header, content, ...]
    i = 1
    while i < len(parts) - 1:
        title = parts[i].strip()
        content = parts[i + 1].strip()
        if content:
            sections.append({"title": title, "content": content})
        else:
            sections.append({"title": title, "content": "Nothing to report."})
        i += 2

    return sections


def format_briefing_slack(briefing_text: str, date_str: str) -> dict:
    """
    Parse briefing markdown into Slack Block Kit sections.
    Returns payload dict with blocks list.
    """
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"☀️ BAKER MORNING BRIEFING — {date_str}", "emoji": True},
        },
        {"type": "divider"},
    ]

    sections = parse_briefing_sections(briefing_text)

    if not sections:
        # Fallback: post entire text as one section
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": _truncate(briefing_text)},
        })
    else:
        for section in sections:
            title = section["title"].upper()
            content = _truncate(section["content"], 2800)

            # Use tier emojis for known sections
            if "IMMEDIATE" in title:
                title = f"🔴 {title}"
            elif "TODAY" in title:
                title = f"🟡 {title}"
            elif "RADAR" in title:
                title = f"📡 {title}"
            elif "OVERNIGHT" in title:
                title = f"🌙 {title}"
            elif "DECISION" in title:
                title = f"⚖️ {title}"

            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{title}*\n{content}"},
            })
            blocks.append({"type": "divider"})

    # Footer context
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"Generated by Baker AI • {now} • Pipeline v1"}],
    })

    return {"blocks": blocks}


def format_briefing_text(briefing_text: str, date_str: str) -> str:
    """Clean text version of the briefing (passthrough with header)."""
    return f"BAKER MORNING BRIEFING — {date_str}\n{'='*40}\n\n{briefing_text}"


# ============================================================
# Pipeline result formatter
# ============================================================

_TYPE_ICONS = {
    "email": "📧",
    "whatsapp": "💬",
    "meeting": "🎙️",
    "calendar": "📅",
    "scheduled": "⏰",
    "manual": "🔍",
}


def format_pipeline_result_slack(analysis: str, trigger_type: str,
                                  contact_name: str = None) -> dict:
    """Compact Slack summary of a pipeline result."""
    icon = _TYPE_ICONS.get(trigger_type, "📌")
    contact_line = f" — {contact_name}" if contact_name else ""

    # First meaningful line of the analysis as excerpt
    excerpt = ""
    for line in (analysis or "").split("\n"):
        stripped = line.strip().strip("-•#* ")
        if len(stripped) > 20:
            excerpt = _truncate(stripped, 200)
            break
    if not excerpt:
        excerpt = _truncate(analysis or "(no analysis)", 200)

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{icon} *{trigger_type.title()}{contact_line}*\n{excerpt}",
            },
        },
    ]
    return {"blocks": blocks}
