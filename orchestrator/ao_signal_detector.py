"""
AO Signal Detector — flags AO-relevant events across all channels.
Updates ao_project_state.relationship_state so AO PM has real-time awareness.

Three channels (ranked by importance):
1. WhatsApp (DV↔AO direct) — AO actually replies here
2. Fireflies (meeting transcripts) — post-meeting intelligence
3. Email (AO orbit: Buchwalder, Constantinos, Aelio, etc.) — operational signals
"""
import logging
import re

logger = logging.getLogger("baker.ao_signal")

# People in AO's orbit (for email/meeting detection)
_AO_ORBIT_PATTERNS = [
    r'buchwalder|gantey',       # AO's Swiss lawyer
    r'pohanis|constantinos',    # Cyprus coordinator
    r'ofenheimer|alric',        # Hagenauer lawyer (RG7-relevant)
    r'@aelio\.',                # Aelio Holding domain
    r'@mandarin',               # MO hotel operations
    r'aukera',                   # Financing team
]

_AO_KEYWORD_PATTERNS = [
    r'capital.call',
    r'rg7|riemergasse',
    r'aelio|lcg',
    r'oskolkov|andrey',
    r'participation.agreement',
    r'shareholder.loan',
]


def is_ao_relevant_text(sender: str, text: str) -> bool:
    """Check if sender is in AO orbit or text contains AO keywords."""
    sender_lower = (sender or "").lower()
    text_lower = (text or "").lower()
    if any(re.search(p, sender_lower) for p in _AO_ORBIT_PATTERNS):
        return True
    return any(re.search(p, text_lower) for p in _AO_KEYWORD_PATTERNS)


def is_ao_relevant_meeting(title: str, participants: str) -> bool:
    """Check if a meeting involves AO or AO-orbit people."""
    text = f"{title} {participants}".lower()
    # Direct AO involvement
    if re.search(r'oskolkov|andrey|ao\b', text):
        return True
    # AO orbit involvement on AO-related topic
    has_orbit = any(re.search(p, text) for p in _AO_ORBIT_PATTERNS)
    has_keyword = any(re.search(p, text) for p in _AO_KEYWORD_PATTERNS)
    return has_orbit and has_keyword


def is_ao_whatsapp_message(sender_name: str, text: str) -> bool:
    """Check if a WhatsApp message is from AO or mentions AO keywords."""
    name_lower = (sender_name or "").lower()
    text_lower = (text or "").lower()
    # Direct AO message (name match)
    if re.search(r'oskolkov|andrey\s*o', name_lower):
        return True
    # AO keyword in message from non-Director
    return any(re.search(p, text_lower) for p in _AO_KEYWORD_PATTERNS)


def flag_ao_signal(channel: str, source: str, summary: str, timestamp=None):
    """Update ao_project_state with an inbound AO signal."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()

        signal_data = {
            "relationship_state": {
                "last_inbound_channel": channel,
                "last_inbound_from": source[:200],
                "last_inbound_summary": summary[:300],
            }
        }
        if timestamp:
            signal_data["relationship_state"]["last_inbound_at"] = (
                timestamp.isoformat() if hasattr(timestamp, 'isoformat') else str(timestamp)
            )

        store.update_ao_project_state(
            updates=signal_data,
            summary=f"AO signal [{channel}]: {source} — {summary[:100]}",
            mutation_source=f"ao_signal_{channel}",
        )
        logger.info(f"AO signal flagged [{channel}]: {source}")
    except Exception as e:
        logger.warning(f"AO signal flag failed: {e}")
