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

def _format_alert_body(body: str) -> str:
    """Parse alert body into readable Slack mrkdwn with visual structure.

    - First sentence becomes bold summary
    - Lines starting with - or • become bullet points
    - Key patterns (names, amounts, dates) get bolded
    - Paragraphs get spacing
    """
    if not body:
        return ""

    lines = body.strip().split("\n")
    result_lines = []
    first_sentence_done = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            result_lines.append("")
            continue

        # Bold the first meaningful sentence as summary
        if not first_sentence_done and len(stripped) > 10:
            # Find sentence boundary — skip abbreviations (Mr. Dr. EUR. etc.)
            _abbrevs = {"mr", "mrs", "ms", "dr", "prof", "inc", "ltd", "eur", "usd", "chf", "no", "vs", "st", "approx", "e.g", "i.e"}
            dot_pos = -1
            search_start = 0
            while search_start < min(len(stripped), 300):
                pos = stripped.find(". ", search_start)
                if pos < 0:
                    break
                # Check if the word before the dot is an abbreviation
                word_before = stripped[:pos].rsplit(None, 1)[-1].rstrip(".").lower() if pos > 0 else ""
                if word_before not in _abbrevs:
                    dot_pos = pos
                    break
                search_start = pos + 2
            if dot_pos > 20 and dot_pos < 300:
                summary = stripped[:dot_pos + 1]
                remainder = stripped[dot_pos + 2:].strip()
                result_lines.append(f"*{summary}*")
                if remainder:
                    result_lines.append("")
                    result_lines.append(remainder)
            else:
                # No good sentence break — bold the whole first paragraph
                result_lines.append(f"*{stripped[:300]}*")
            first_sentence_done = True
            continue

        # Bullet points — ensure consistent formatting
        if stripped.startswith(("- ", "• ", "* ")):
            result_lines.append(f"  • {stripped[2:]}")
            continue

        # Numbered items
        if len(stripped) > 2 and stripped[0].isdigit() and stripped[1] in (".", ")"):
            result_lines.append(f"  {stripped}")
            continue

        result_lines.append(stripped)

    text = "\n".join(result_lines)

    # Bold key patterns: currency amounts, dates, percentages
    text = re.sub(r'((?:EUR|CHF|USD|€|\$)\s?[\d,.]+[kKmM]?)', r'*\1*', text)
    text = re.sub(r'(\d{1,2}[./]\d{1,2}[./]\d{2,4})', r'*\1*', text)

    return text


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
    body = alert.get("body", "")
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

    # Metadata fields (Contact, Deal) as compact side-by-side fields
    fields = []
    if contact:
        fields.append({"type": "mrkdwn", "text": f"*Contact:* {contact}"})
    if deal:
        fields.append({"type": "mrkdwn", "text": f"*Matter:* {deal}"})
    if action_required:
        fields.append({"type": "mrkdwn", "text": "✅ *Action required*"})
    if fields:
        blocks.append({"type": "section", "fields": fields})

    # Divider between metadata and body
    if fields and body:
        blocks.append({"type": "divider"})

    # Body — formatted for readability
    if body:
        formatted = _format_alert_body(body)
        # Split into chunks if too long (Block Kit 3000 char limit per section)
        chunks = []
        current = []
        current_len = 0
        for line in formatted.split("\n"):
            if current_len + len(line) + 1 > 2800:
                chunks.append("\n".join(current))
                current = [line]
                current_len = len(line)
            else:
                current.append(line)
                current_len += len(line) + 1
        if current:
            chunks.append("\n".join(current))

        for chunk in chunks[:3]:  # Max 3 body sections
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": chunk},
            })

    # Context footer
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"Baker AI • {now}"}],
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
