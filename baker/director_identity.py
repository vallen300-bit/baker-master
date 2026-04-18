"""Director-sender identity — single source of truth.

Layer 0's C2 invariant (Inv 5 — author authority) requires a boolean check
``is_director_sender(signal)`` that covers all three ingestion sources:

    * **Email** — ``From:`` matches one of Director's known addresses
      (business + personal). Comparison is case-insensitive; angle-bracket
      wrappers (``Dimitry Vallen <dvallen@brisengroup.com>``) are stripped.
    * **WhatsApp** — sender phone matches Director's number regardless of
      format. WAHA serializes as ``41799605092@c.us``; CLAUDE.md records
      ``+41 799605092``; other senders may paste ``+41 79 960 50 92``.
      Normalization is digits-only (``re.sub(r"\\D", "", raw)``) before
      comparison — per B2 Step 0 re-review item N4.
    * **Meeting** — transcript payload's ``organizer`` field matches a
      Director email.

Used by:
    * ``kbl.layer0`` — C2 never-drop short-circuit at evaluate() entry
    * future Ayoniso (alert/promote path) — author-authority check
    * future Gold-promote — never-auto-promote if Director is the author

Having one module means rotating a phone or adding an address is a single
edit, not an N-site update.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

# Business + personal addresses Director uses to send. Case-insensitive
# comparison; update here if Director rotates/adds.
DIRECTOR_EMAILS: frozenset[str] = frozenset(
    {
        "dvallen@brisengroup.com",
        "vallen300@gmail.com",
        "office.vienna@brisengroup.com",
    }
)

# Director's WhatsApp number, in digits-only canonical form. Any raw format
# (+41 79 960 50 92 / +41799605092 / 41799605092@c.us / 0041 79 960 50 92)
# normalizes to this string. Update here if Director rotates.
DIRECTOR_PHONES: frozenset[str] = frozenset({"41799605092"})


def _normalize_phone(raw: str) -> str:
    """Return digits-only canonical form for phone comparison.

    Handles all documented formats per B2 N4:
        ``+41 79 960 50 92``        -> ``41799605092``
        ``+41799605092``            -> ``41799605092``
        ``41799605092@c.us``        -> ``41799605092``
        ``0041 79 960 50 92``       -> ``00041799605092`` (distinct!)

    Note the ``0041`` case: some WhatsApp ports preserve an ``00`` trunk
    prefix, giving a 14-digit result that does NOT match the 11-digit
    canonical. This is accurate — Swiss trunk-prefix ``00`` is not the same
    as the empty plus-replacement. If Director adds a format that serializes
    as ``00…`` we add it to DIRECTOR_PHONES explicitly.
    """
    if not raw:
        return ""
    return re.sub(r"\D", "", raw)


def _extract_email(raw: str) -> str:
    """Strip angle-bracket wrapping and lowercase. Returns ''. on malformed."""
    if not raw:
        return ""
    s = raw.strip()
    if "<" in s and ">" in s:
        s = s.split("<", 1)[1].rsplit(">", 1)[0]
    return s.strip().lower()


def _getattr_or_key(obj: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from either an attribute (dataclass) or a mapping."""
    if obj is None:
        return default
    if hasattr(obj, key):
        return getattr(obj, key)
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


def _emails_from_payload(payload: Any) -> Iterable[str]:
    """Candidate email-shaped senders. Yields lowercased addresses.

    Reads both the common ``sender`` / ``from`` fields and a ``organizer``
    field used for meeting signals. Yield in priority order so callers can
    short-circuit on the first match.
    """
    for key in ("sender", "from", "from_address", "organizer"):
        val = _getattr_or_key(payload, key)
        if isinstance(val, str) and val.strip():
            yield _extract_email(val)


def _phones_from_payload(payload: Any) -> Iterable[str]:
    """Candidate phone-shaped senders (WhatsApp). Yields digits-only forms."""
    for key in ("sender", "sender_phone", "from", "chat_id"):
        val = _getattr_or_key(payload, key)
        if isinstance(val, str) and val.strip():
            yield _normalize_phone(val)


def is_director_sender(signal: Any) -> bool:
    """Return True if ``signal`` was authored by Director.

    The signal argument is duck-typed (dataclass, namedtuple, or plain
    dict) — we only read ``source`` and ``payload``. Returns False on
    unrecognized / missing source rather than raising, so an ingestion
    shape we haven't seen yet defaults to "not Director" (conservative:
    C2 protects Director content, so a false negative here just defers
    to the rest of Layer 0, which has its own safeguards).
    """
    source = _getattr_or_key(signal, "source")
    payload = _getattr_or_key(signal, "payload", {})

    if source in ("email", "meeting"):
        for candidate in _emails_from_payload(payload):
            if candidate in DIRECTOR_EMAILS:
                return True
        return False

    if source == "whatsapp":
        for candidate in _phones_from_payload(payload):
            if candidate in DIRECTOR_PHONES:
                return True
        return False

    # Unknown / unsupported source — conservative False.
    return False
