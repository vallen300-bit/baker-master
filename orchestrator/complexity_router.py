"""
Rule-based complexity router — replaces Haiku LLM classification.

Jensen principle: router is dumb and fast, worker is smart.
Only a narrow whitelist of single-fact patterns goes to Haiku.
Everything else → Opus.

No LLM call, <1ms, zero misroutes on browser/analysis/judgment tasks.
"""
import re

# ─── Narrow fast whitelist ───────────────────────────────
# Only these patterns qualify for Haiku fast path.
# Must be short, single-fact, no judgment required.

_FAST_PATTERNS = re.compile(
    r"(?:"
    # Single-fact lookups: "what is the deadline for X"
    r"^(?:what|when|where)\s+(?:is|was|are|were)\s+(?:the\s+)?(?:deadline|date|status|amount|price|email|phone|address|number)\b"
    r"|"
    # Short yes/no: "is X done?" "did we send Y?"
    r"^(?:is|are|was|were|did|has|have|do|does)\s+.{5,60}\?$"
    r"|"
    # How much/many: "how much did we pay for X"
    r"^(?:how much|how many)\s+"
    r"|"
    # Simple forward/relay: "send that to myself"
    r"^(?:send|forward|share)\s+(?:that|this|it|the same)\s+(?:to|with)\s+"
    r"|"
    # Quick status: "status of X", "update on Y"
    r"^(?:status|update)\s+(?:of|on)\s+"
    r")",
    re.IGNORECASE,
)

# ─── Deep force patterns ─────────────────────────────────
# Anything matching these is ALWAYS deep, even if it looks short.

_DEEP_FORCE = re.compile(
    r"(?:"
    # URLs and websites
    r"https?://"
    r"|\.com\b|\.ch\b|\.de\b|\.at\b|\.org\b|\.net\b|\.io\b"
    r"|"
    # Browser/purchase intent
    r"\b(?:buy|purchase|order|shop|browse|checkout|add.to.cart|go.to)\b"
    r"|"
    # Analysis and judgment
    r"\b(?:analyze|analyse|review|draft|prepare|compare|strategy|recommend)\b"
    r"|"
    # Thinking tasks
    r"\b(?:what.should|think.about|plan|research|dossier|brief|pros.and.cons)\b"
    r"|"
    # Multi-step
    r"\b(?:summarize|summary|timeline|history|overview|assessment|evaluation)\b"
    r"|"
    # Product/website names (common shopping)
    r"\b(?:amazon|rode|microphone|product|website)\b"
    r")",
    re.IGNORECASE,
)


def classify_complexity(question: str) -> str:
    """Rule-based complexity classification. No LLM needed, <1ms.

    Returns:
        'fast' — Haiku single-pass (narrow whitelist only)
        'deep' — Opus agent loop (everything else)
    """
    # Deep-force patterns always win
    if _DEEP_FORCE.search(question):
        return "deep"

    # Fast whitelist: must match pattern AND be short
    if _FAST_RE_match(question):
        return "fast"

    # Default: Opus. False-deep is expensive but safe.
    # False-fast is dangerous (wrong answers, no tools).
    return "deep"


def _FAST_RE_match(question: str) -> bool:
    """Check if question matches fast whitelist AND is short enough."""
    return bool(_FAST_PATTERNS.search(question)) and len(question) < 120
