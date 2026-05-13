"""DEADLINE_SIGNAL_HYGIENE_1: pre-classifier noise filter.

Pattern-matches incoming deadline candidates against known-noise signatures
(subscription renewals, webcast/seminar registrations, marketing promos,
hardware delivery, generic billing). Returns True if the candidate is noise
and should be SKIPPED at insert time (no deadline row created).

This runs BEFORE _match_matter_slug() so noise never reaches the classifier.

Patterns are conservative: match only structural signals (verb + object pairs
that are categorical, not matter-specific). Examples that MUST pass through:
- "Cupial settlement chase" — concrete matter action
- "Sign Aukera term sheet by Friday" — deal action
Examples that MUST be filtered:
- "Slack subscription renewal" — SaaS billing
- "Register for AML analysis course" — training event
- "Delivery of [hardware product]" — domestic logistics
- "Subscribe to Bloomberg.com" — marketing
"""
import re
from typing import Optional

# Case-insensitive substring patterns. Each pattern is a structural noise
# signature, not a matter-related one. Anchored to verb+object pairs.
_NOISE_PATTERNS = [
    # SaaS / subscription billing
    r"\bsubscription\s+(renew(al)?|expir|offer|special)",
    r"\bsubscribe\s+to\s+\w+\.(com|io|net)",
    r"\b(special|exclusive)\s+(subscription\s+)?offer\s+(for|on)\b",
    # Marketing / promotional
    r"\b\d{1,2}\s*%\s+(discount|off)\s+(on|for)\b",
    r"\bspring\s+promot",
    # Training / webcast / seminar / course registration
    r"\b(register\s+for|attend|participate\s+in)\s+(the\s+)?[\w\s]+\s+(webcast|seminar|course|event|webinar)\b",
    r"\b'?[\w\s]+'?\s+(webcast|webinar|seminar)\b",
    # Generic billing (credit-card / payment-processor noise ONLY — commercial
    # invoices like Balgerstrasse/Cupial/Heidenauer must pass through, so the
    # bare "invoice payment" pattern is intentionally NOT included).
    r"\bmake\s+payment\s+to\s+(american\s+express|visa|mastercard|paypal)",
    r"\bcredit\s+card\s+(payment|late\s+fee|statement|bill)\b",
    # Consumer-logistics / personal delivery (must NOT match closing
    # documents, title deeds, guarantee letters — those are deal-doc nouns
    # commonly preceded by "delivery of"). Anchor on consumer-courier
    # signatures + parcel/package nouns.
    r"\b(amazon|ups|fedex|dhl|usps|royal\s+mail|deutsche\s+post)\b.*\bdelivery\b",
    r"\bdelivery\s+of\s+(your\s+)?(package|parcel|order|shipment|item)s?\b",
    r"\bpackage\s+(arriv|deliver|out\s+for\s+delivery)",
    r"\bmother's\s+day\s+gifts?",
    # Generic forecast/meeting noise
    r"\bdiscuss\s+\w+/ytd\s+and\s+forecast",
    # Newsletter chrome
    r"\bnews\s+to\s+(read|share)\b",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _NOISE_PATTERNS]


def is_noise(description: Optional[str], source_snippet: Optional[str] = None) -> bool:
    """Return True if the candidate matches a known-noise signature.

    Conservative — only matches structural patterns (verb + categorical object).
    Concrete matter language (named counterparty, slug-able entity, deal action)
    is intentionally NOT pattern-matched here.
    """
    if not description:
        return False
    text = description
    if source_snippet:
        text = text + " " + source_snippet
    for pat in _COMPILED:
        if pat.search(text):
            return True
    return False
