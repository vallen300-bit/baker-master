"""
Baker 3.0 — Item 2: Context Selector

Sits between classify_intent() and retrieval. Decides WHICH sources
to query and HOW MUCH to inject based on 7 signals:
1. Intent (legal, financial, travel, relationship, operational)
2. Matter (hagenauer, cupial, annaberg, etc.)
3. Contact mentioned
4. Time reference
5. Specialist preferences (hard-coded per specialist)
6. Recency decay
7. Channel of origin (WhatsApp → concise, dashboard → deep)

Returns a context_plan that the retriever uses to filter and budget.
"""
import logging
import re

logger = logging.getLogger("baker.context_selector")

# ─────────────────────────────────────────────────
# Source weights by intent
# ─────────────────────────────────────────────────

# "high" = query with full budget, "medium" = reduced, "low" = minimal, "skip" = don't query
_INTENT_SOURCE_MAP = {
    "legal": {
        "semantic": "high", "emails": "high", "documents": "high",
        "meetings": "medium", "whatsapp": "low", "signal_extractions": "medium",
        "deadlines": "medium", "contacts": "low", "insights": "medium",
        "deals": "skip", "alerts": "low", "decisions": "medium",
        "preferences": "low",
    },
    "financial": {
        "semantic": "high", "emails": "high", "documents": "high",
        "meetings": "medium", "whatsapp": "low", "signal_extractions": "medium",
        "deadlines": "low", "contacts": "low", "insights": "medium",
        "deals": "high", "alerts": "low", "decisions": "medium",
        "preferences": "low",
    },
    "travel": {
        "semantic": "low", "emails": "medium", "documents": "low",
        "meetings": "low", "whatsapp": "medium", "signal_extractions": "low",
        "deadlines": "low", "contacts": "low", "insights": "skip",
        "deals": "skip", "alerts": "skip", "decisions": "skip",
        "preferences": "low",
    },
    "relationship": {
        "semantic": "medium", "emails": "high", "documents": "low",
        "meetings": "high", "whatsapp": "high", "signal_extractions": "medium",
        "deadlines": "low", "contacts": "high", "insights": "low",
        "deals": "low", "alerts": "low", "decisions": "low",
        "preferences": "low",
    },
    "operational": {
        "semantic": "medium", "emails": "high", "documents": "medium",
        "meetings": "medium", "whatsapp": "medium", "signal_extractions": "medium",
        "deadlines": "high", "contacts": "low", "insights": "low",
        "deals": "low", "alerts": "medium", "decisions": "medium",
        "preferences": "low",
    },
    "general": {
        "semantic": "high", "emails": "medium", "documents": "medium",
        "meetings": "medium", "whatsapp": "medium", "signal_extractions": "medium",
        "deadlines": "medium", "contacts": "low", "insights": "low",
        "deals": "low", "alerts": "low", "decisions": "medium",
        "preferences": "low",
    },
}

# ─────────────────────────────────────────────────
# Specialist source preferences
# ─────────────────────────────────────────────────

_SPECIALIST_SOURCE_MAP = {
    "legal": {
        "emails": "high", "documents": "high", "meetings": "high",
        "deadlines": "high", "whatsapp": "medium",
    },
    "finance": {
        "documents": "high", "emails": "high", "deals": "high",
        "signal_extractions": "high", "meetings": "medium",
    },
    "profiling": {
        "contacts": "high", "whatsapp": "high", "meetings": "high",
        "emails": "high", "signal_extractions": "medium",
    },
    "research": {
        "documents": "high", "emails": "high", "whatsapp": "medium",
        "meetings": "medium", "signal_extractions": "medium",
    },
    "sales": {
        "emails": "high", "documents": "high", "deals": "high",
        "contacts": "high", "meetings": "medium",
    },
    "ao_pm": {
        "emails": "high", "whatsapp": "high", "meetings": "high",
        "documents": "high", "contacts": "high", "deadlines": "high",
        "deals": "high", "insights": "high", "decisions": "high",
        "signal_extractions": "high",
    },
    "movie_am": {
        "emails": "high", "whatsapp": "high", "meetings": "high",
        "documents": "high", "contacts": "high", "deadlines": "high",
        "deals": "medium", "insights": "high", "decisions": "high",
        "signal_extractions": "high",
    },
    "asset_management": {
        "documents": "high", "emails": "high", "deadlines": "high",
        "meetings": "medium", "signal_extractions": "medium",
    },
    "communications": {
        "emails": "high", "whatsapp": "high", "meetings": "high",
        "contacts": "high", "signal_extractions": "medium",
    },
    "pr_branding": {
        "emails": "medium", "documents": "medium", "whatsapp": "medium",
        "signal_extractions": "medium", "insights": "high",
    },
    "marketing": {
        "documents": "high", "emails": "medium",
        "signal_extractions": "medium",
    },
    "it": {
        "emails": "high", "documents": "high",
        "meetings": "medium",
    },
    "ai_dev": {
        "documents": "high", "emails": "medium",
    },
}

# ─────────────────────────────────────────────────
# Token budgets by channel of origin
# ─────────────────────────────────────────────────

_CHANNEL_BUDGETS = {
    "whatsapp": 6000,
    "mobile": 8000,
    "dashboard": 12000,
    "specialist": 16000,
    "slack": 8000,
}

# Weight → per-source token budget multiplier
_WEIGHT_BUDGET = {
    "high": 1.0,
    "medium": 0.5,
    "low": 0.25,
    "skip": 0,
}

# Weight → result limit multiplier (for search_all_collections limit_per_collection)
_WEIGHT_LIMITS = {
    "high": 10,
    "medium": 5,
    "low": 2,
    "skip": 0,
}


# ─────────────────────────────────────────────────
# Intent detection
# ─────────────────────────────────────────────────

_INTENT_PATTERNS = {
    "legal": re.compile(
        r"\b(legal|lawyer|court|litigation|dispute|claim|section\s*\d+|"
        r"gewährleistung|vertrag|contract|ofenheimer|blaschka|e\+h|"
        r"insolvency|injunction|damages|liability|mediengesetz)\b",
        re.IGNORECASE,
    ),
    "financial": re.compile(
        r"\b(financ|capital|cashflow|cash\s*flow|budget|loan|interest|"
        r"bank|account|tax|vat|invoice|payment|eur\s*\d|balance|"
        r"funding|equity|dividend|repay|debt)\b",
        re.IGNORECASE,
    ),
    "travel": re.compile(
        r"\b(flight|hotel|travel|trip|airport|booking|check.in|"
        r"luggage|visa|boarding|reservation|transfer|gtc|ihif|mipim)\b",
        re.IGNORECASE,
    ),
    "relationship": re.compile(
        r"\b(relationship|contact|reach\s*out|follow\s*up|"
        r"haven.t\s*(spoken|talked)|cadence|networking|"
        r"introduce|introduction|connect\s*with|meeting\s*with)\b",
        re.IGNORECASE,
    ),
    "operational": re.compile(
        r"\b(clickup|task|todo|status|progress|deadline|overdue|"
        r"scheduled|timeline|milestone|deliverable|sprint|backlog)\b",
        re.IGNORECASE,
    ),
}


def _detect_intent(query: str) -> str:
    """Detect intent from query text using keyword patterns."""
    scores = {}
    for intent, pattern in _INTENT_PATTERNS.items():
        matches = pattern.findall(query)
        scores[intent] = len(matches)

    if scores:
        best = max(scores, key=scores.get)
        if scores[best] > 0:
            return best
    return "general"


def _detect_matter(query: str) -> str:
    """Detect matter reference from query text."""
    _MATTER_PATTERNS = {
        "hagenauer": re.compile(r"\b(hagenauer|hag\b|section\s*14|neubauer|immofokus)", re.IGNORECASE),
        "mandarin-oriental": re.compile(r"\b(mandarin|oriental|mo\s*vienna|morv|residence)", re.IGNORECASE),
        "annaberg": re.compile(r"\b(annaberg|lilienmatt|residenz)", re.IGNORECASE),
        "cupial": re.compile(r"\b(cupial|scorpio|sonderwunsch|sonderwünsch)", re.IGNORECASE),
        "oskolkov": re.compile(r"\b(oskolkov|aelio|lcg)", re.IGNORECASE),
        "kempinski": re.compile(r"\b(kempinski|kitzbühel|kitzbuehel)", re.IGNORECASE),
        "baden-baden": re.compile(r"\b(baden)", re.IGNORECASE),
        "fx-mayr": re.compile(r"\b(fx\s*mayr|mayr)", re.IGNORECASE),
        "brisen-ai": re.compile(r"\b(brisen\s*ai|project\s*claim|baker\s*(system|development))", re.IGNORECASE),
    }
    for matter, pattern in _MATTER_PATTERNS.items():
        if pattern.search(query):
            return matter
    return None


def _detect_contact(query: str) -> str:
    """Detect contact name from query (proper noun extraction)."""
    # Look for capitalized names (2+ chars)
    names = re.findall(r'\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*\b', query)
    # Filter out common non-name words
    _SKIP = {"Baker", "Vienna", "Austria", "Cyprus", "Germany", "Switzerland",
             "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
             "January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December",
             "ClickUp", "Dropbox", "WhatsApp", "Telegram", "Slack",
             "Mandarin", "Oriental", "Kempinski", "Annaberg", "Hagenauer"}
    names = [n for n in names if n not in _SKIP]
    return names[0] if names else None


def _detect_time_window(query: str) -> int:
    """Detect time reference and return window in days. Default 30."""
    q = query.lower()
    if "today" in q or "this morning" in q:
        return 1
    if "yesterday" in q:
        return 2
    if "this week" in q:
        return 7
    if "last week" in q:
        return 14
    if "this month" in q:
        return 30
    if "last month" in q:
        return 60
    if re.search(r"last\s*(\d+)\s*days?", q):
        match = re.search(r"last\s*(\d+)\s*days?", q)
        return int(match.group(1))
    return 30  # default


# ─────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────

def select_context(query: str, intent: str = None, matter: str = None,
                   contact: str = None, specialist: str = None,
                   channel_of_origin: str = "dashboard") -> dict:
    """
    Decide which sources to query and how much to inject.

    Args:
        query: the user's question or trigger content
        intent: pre-classified intent (if available), else auto-detected
        matter: pre-detected matter slug (if available), else auto-detected
        contact: pre-detected contact name (if available), else auto-detected
        specialist: specialist slug (if routing to a specific specialist)
        channel_of_origin: where the question came from (whatsapp, dashboard, etc.)

    Returns:
        context_plan dict with source weights, budgets, and filters.
    """
    # Auto-detect signals if not provided
    if not intent:
        intent = _detect_intent(query)
    if not matter:
        matter = _detect_matter(query)
    if not contact:
        contact = _detect_contact(query)

    time_window = _detect_time_window(query)

    # Start with intent-based source weights
    source_weights = dict(_INTENT_SOURCE_MAP.get(intent, _INTENT_SOURCE_MAP["general"]))

    # Override with specialist preferences if a specialist is assigned
    if specialist and specialist in _SPECIALIST_SOURCE_MAP:
        spec_prefs = _SPECIALIST_SOURCE_MAP[specialist]
        for source, weight in spec_prefs.items():
            # Specialist can only upgrade weights, not downgrade
            if _WEIGHT_BUDGET.get(weight, 0) > _WEIGHT_BUDGET.get(source_weights.get(source, "low"), 0):
                source_weights[source] = weight

    # Contact boost: if a contact is mentioned, boost email/whatsapp/meetings
    if contact:
        for src in ("emails", "whatsapp", "meetings", "contacts"):
            if source_weights.get(src) in ("low", "medium"):
                source_weights[src] = "high"

    # Total budget from channel of origin
    total_budget = _CHANNEL_BUDGETS.get(channel_of_origin, 12000)

    # Build source configs
    sources = {}
    for source, weight in source_weights.items():
        if weight == "skip":
            sources[source] = {"weight": "skip", "budget": 0, "limit": 0}
            continue

        budget = int(total_budget * _WEIGHT_BUDGET[weight] * 0.15)  # each source gets a fraction
        limit = _WEIGHT_LIMITS[weight]

        source_config = {
            "weight": weight,
            "budget": max(budget, 200),  # minimum 200 tokens per source
            "limit": limit,
        }

        # Add filters
        if matter:
            source_config["matter"] = matter
        if contact:
            source_config["contact"] = contact

        sources[source] = source_config

    plan = {
        "intent": intent,
        "matter": matter,
        "contact": contact,
        "specialist": specialist,
        "time_window_days": time_window,
        "total_budget": total_budget,
        "recency_decay": True,
        "channel_of_origin": channel_of_origin,
        "sources": sources,
    }

    logger.info(
        f"Context plan: intent={intent} matter={matter} contact={contact} "
        f"budget={total_budget} sources={sum(1 for s in sources.values() if s.get('weight') != 'skip')} active"
    )

    return plan


def should_skip_source(plan: dict, source_name: str) -> bool:
    """Check if a source should be skipped based on the context plan."""
    if not plan:
        return False  # No plan = query everything (backward compatible)
    sources = plan.get("sources", {})
    config = sources.get(source_name, {})
    return config.get("weight") == "skip"


def get_source_limit(plan: dict, source_name: str, default: int = 10) -> int:
    """Get the result limit for a source based on the context plan."""
    if not plan:
        return default
    sources = plan.get("sources", {})
    config = sources.get(source_name, {})
    return config.get("limit", default)


def get_source_budget(plan: dict, source_name: str, default: int = 2000) -> int:
    """Get the token budget for a source based on the context plan."""
    if not plan:
        return default
    sources = plan.get("sources", {})
    config = sources.get(source_name, {})
    return config.get("budget", default)
