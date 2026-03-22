# BRIEF: Baker 3.0 — Item 2: Context Selector

**Author:** AI Head
**Date:** 2026-03-22
**Priority:** HIGH — improves every specialist answer + saves 30-40% tokens
**Effort:** 1 session
**Assigned to:** AI Head + Code Brisen
**Depends on:** None (can be built before or after Item 0a)

---

## What We're Building

A new step in Baker's pipeline between `classify_intent()` and retrieval. Instead of querying all sources every time, Baker selects which sources to query and how much to inject based on 7 signals.

---

## New File

### `orchestrator/context_selector.py` (NEW)

```python
def select_context(intent: str, matter: str = None, contact: str = None,
                   time_ref: str = None, specialist: str = None,
                   channel_of_origin: str = "dashboard") -> dict:
    """
    Decide which sources to query and token budget per source.

    Returns:
    {
        "sources": {
            "emails": {"weight": "high", "budget": 4000, "filter": {"matter": "hagenauer", "contacts": ["Ofenheimer"]}},
            "documents": {"weight": "high", "budget": 4000, "filter": {"type": "legal"}},
            "meetings": {"weight": "medium", "budget": 2000, "filter": {"matter": "hagenauer"}},
            "signal_extractions": {"weight": "medium", "budget": 1000},
            "whatsapp": {"weight": "low", "budget": 500},
            "deadlines": {"weight": "low", "budget": 500},
            "clickup": {"weight": "skip"},
            "health": {"weight": "skip"},
            "travel": {"weight": "skip"},
            "rss": {"weight": "skip"},
        },
        "total_budget": 12000,
        "recency_decay": True,
        "recency_window_days": 30
    }
```

### 7 Signals Logic

**1. Intent → source type mapping:**

| Intent | High Weight | Medium Weight | Low/Skip |
|--------|-----------|--------------|----------|
| legal | emails (lawyers), documents (legal) | meetings, signal_extractions | clickup, health, travel, rss |
| financial | documents (financial), emails (banks) | deals, signal_extractions | health, travel, rss |
| travel | calendar, whatsapp, travel docs | emails | clickup, legal docs, deals |
| relationship | whatsapp, emails, meetings, contacts | signal_extractions | documents, clickup, rss |
| operational | clickup, emails, meetings | whatsapp, deadlines | health, travel, rss |
| general | emails, meetings, whatsapp | documents, deadlines | balanced low weight |

**2. Matter → filter all sources to that matter's people, keywords, documents**

**3. Contact → boost emails/WhatsApp from that person**

**4. Time reference → narrow retrieval window** (e.g., "last week" → 7 days, "before IHIF" → before March 23)

**5. Specialist preferences (hard-coded):**

| Specialist | Preferred Sources |
|-----------|------------------|
| legal | emails, documents, meetings, deadlines |
| finance | documents, emails, deals, signal_extractions |
| profiling | contacts, whatsapp, meetings, emails |
| research | documents, emails, rss, whatsapp |
| sales | emails, documents, deals, contacts |
| asset_management | documents, emails, clickup, deadlines |
| communications | emails, whatsapp, meetings, contacts |
| pr_branding | rss, emails, documents, whatsapp |
| marketing | documents, emails, rss |
| it | emails, clickup, documents |
| ai_dev | documents, clickup, emails |

**6. Recency decay** — multiply relevance score by `1 / (1 + days_old * 0.05)`. A 20-day-old result gets 50% weight of a fresh one.

**7. Channel of origin:**

| Origin | Total Budget | Behavior |
|--------|-------------|----------|
| whatsapp | 6,000 tokens | Concise answer expected |
| mobile | 8,000 tokens | Medium depth |
| dashboard (scan) | 12,000 tokens | Full analysis |
| specialist | 16,000 tokens | Deep analysis |

---

## Integration Points

### `memory/retriever.py` — Modify

Current: `retrieve()` queries all Qdrant collections and all PostgreSQL tables.

New: `retrieve()` accepts a `context_plan` parameter from the selector. If provided, only queries sources with weight != "skip", respects per-source budget, applies recency decay.

```python
def retrieve(query, context_plan=None, ...):
    if context_plan:
        sources = context_plan["sources"]
        for source_name, config in sources.items():
            if config.get("weight") == "skip":
                continue
            budget = config.get("budget", 2000)
            # Query this source with budget-aware truncation
            results = self._query_source(source_name, query, budget, config.get("filter"))
    else:
        # Existing behavior — query everything (backward compatible)
```

### `orchestrator/pipeline.py` — Modify

In the Augment step, call context_selector before retrieval:

```python
from orchestrator.context_selector import select_context

# After classify_intent:
context_plan = select_context(
    intent=classified_intent,
    matter=detected_matter,
    contact=detected_contact,
    time_ref=detected_time,
    specialist=assigned_specialist,
    channel_of_origin=trigger_type
)
# Pass to retriever:
context = retriever.retrieve(query, context_plan=context_plan)
```

### `orchestrator/agent.py` — Modify

Agent tool calls should also respect the context selector. When a specialist's agent loop calls `search_emails`, the context selector's filters are passed through.

### `orchestrator/capability_runner.py` — Modify

When running a specialist, pass the specialist slug to `select_context()` to get specialist-specific source preferences.

---

## Backward Compatibility

If `context_plan` is None, retriever behaves exactly as today — queries everything. This means we can deploy the selector and turn it on gradually, not all at once.

---

## Testing

1. **Unit test:** `select_context("legal", matter="hagenauer")` → verify emails and documents are HIGH, health is SKIP
2. **Unit test:** `select_context("travel")` → verify calendar is HIGH, legal docs are SKIP
3. **Integration test:** Ask a legal question on dashboard → verify retriever only queries legal sources
4. **Cost comparison:** Run 10 identical queries with and without selector → measure token count difference
5. **Quality check:** Verify specialist answers are at least as good (not worse) with selective context

---

## Files Modified

| File | Change |
|------|--------|
| `orchestrator/context_selector.py` | NEW — all selector logic |
| `memory/retriever.py` | Accept context_plan parameter, budget-aware retrieval |
| `orchestrator/pipeline.py` | Call selector before retrieval |
| `orchestrator/agent.py` | Pass context filters to tool calls |
| `orchestrator/capability_runner.py` | Pass specialist slug to selector |
