"""WhatsApp message attribution utilities — shared between webhook + backfill.

Anchor: BRIEF_WAHA_OUTBOUND_CAPTURE_1.
"""
from __future__ import annotations

# Director's WhatsApp identifiers. WAHA uses two JID formats interchangeably:
#   @c.us             — canonical "contact" form, what the webhook delivers
#   @s.whatsapp.net   — legacy "session" form, what backfill /chats returns
DIRECTOR_WHATSAPP_CUS = "41799605092@c.us"
DIRECTOR_WHATSAPP_JID = "41799605092@s.whatsapp.net"
DIRECTOR_WHATSAPP_IDS = (DIRECTOR_WHATSAPP_CUS, DIRECTOR_WHATSAPP_JID)

# Baker's WhatsApp "self-chat" — the chat_id used when Director messages
# himself (i.e. the Director-to-Baker channel). Director's own number in both
# JID formats: dominant historic chat_id by row count is
# `41799605092@s.whatsapp.net` (644 rows; 5x next-highest at HEAD 7e5657c per
# Fix-4 derivation SQL). @c.us form is what new webhook writes will produce
# after Fix 3 chat_id normalization; @s.whatsapp.net form is what backfill
# wrote historically. A new fromMe webhook event for the self-chat may also
# arrive as @c.us via payload["to"], so both are first-class.
BAKER_SELF_CHAT_CUS = "41799605092@c.us"
BAKER_SELF_CHAT_JID = "41799605092@s.whatsapp.net"
BAKER_SELF_CHAT_IDS = frozenset({BAKER_SELF_CHAT_CUS, BAKER_SELF_CHAT_JID})


def attribute_sender(
    raw_sender: str,
    raw_sender_name: str,
    from_me: bool,
) -> tuple[str, str, bool]:
    """Return (sender, sender_name, is_director) given raw webhook/backfill fields.

    When fromMe=True, the upstream WAHA payload's `from` field is the REMOTE
    party (counterparty), not Director. Re-attribute to Director's canonical
    @c.us JID and label sender_name = "Director".

    When fromMe=False, pass through unchanged but still set is_director if the
    raw sender happens to be one of Director's known JIDs (defensive — should
    not occur in webhook flow but does occur in backfill of historic data).
    """
    if from_me:
        return DIRECTOR_WHATSAPP_CUS, "Director", True

    is_director = raw_sender in DIRECTOR_WHATSAPP_IDS
    return raw_sender, raw_sender_name, is_director


def is_baker_self_chat(chat_id: str | None) -> bool:
    """True iff chat_id corresponds to Director's self-chat (Director-to-Baker).

    Handles both @c.us and @s.whatsapp.net forms; case-insensitive on suffix
    by relying on the literal set (WAHA never returns mixed case).
    """
    if not chat_id:
        return False
    return chat_id in BAKER_SELF_CHAT_IDS
