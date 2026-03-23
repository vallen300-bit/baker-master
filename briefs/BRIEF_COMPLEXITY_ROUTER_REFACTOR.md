# BRIEF: Complexity Router Refactor

**Author:** AI Head (Claude Code)
**Date:** 2026-03-23
**Status:** Proposed
**Priority:** High — affects every Baker interaction

## Problem

Baker's complexity router asks Haiku to classify tasks as "fast" or "deep" at intent time. This fails consistently because:

1. **Haiku can't predict tool needs.** "Buy me a microphone" looks simple but requires 10+ browser interactions with Opus.
2. **Short ≠ simple.** "What should I do about Cupial?" is 6 words but needs deep analysis.
3. **False-fast is dangerous.** Haiku answers confidently but wrong — no tools, no memory retrieval, hallucinated facts.
4. **The upgrade hack is fragile.** We added regex overrides (browser keywords, purchase patterns) but every new capability needs more regex.

Jensen's GTC point: the router should be dumb and fast, the worker should be smart. We have the router trying to be smart.

## Current Architecture

```
User question → Haiku classifies intent + complexity
  → fast → Haiku agent (5 iter, 30s, limited tools)
  → deep → Opus agent (15 iter, 90s, all tools)
```

Problems:
- Haiku decides complexity based on surface form, not actual requirements
- ~30% of tasks get misrouted (browsing, multi-step, judgment calls)
- We've added 3 separate regex overrides to patch misclassifications
- The auto-upgrade (Haiku→Opus mid-loop) wastes the first iteration on a bad Haiku response

## Proposed Architecture

```
User question → Rule-based router (no LLM, <1ms)
  → FAST whitelist match → Haiku (single-pass, no agent loop)
  → Everything else → Opus agent (20 iter, 300s, all tools)
```

### Fast Whitelist (rule-based, no LLM)

Only these patterns qualify for Haiku fast path:

| Pattern | Example | Why fast |
|---------|---------|----------|
| Single-fact lookup | "What's the deadline for Hagenauer?" | One DB query |
| Status check | "Is the Cupial payment done?" | One DB query |
| Date/amount extraction | "When does the warranty expire?" | One DB query |
| Yes/no with known answer | "Did we send the email to Philip?" | One DB query |
| Simple forwarding | "Send that to myself" | Action, no thinking |

Everything else — analysis, drafting, browsing, purchasing, comparison, "what should I", multi-source, judgment — goes to Opus.

### Implementation

**File:** `orchestrator/complexity_router.py` (new, ~50 lines)

```python
import re

# Narrow whitelist: only these go to Haiku
_FAST_PATTERNS = [
    r"^(what|when|where)\s+(is|was|are)\s+(the\s+)?(deadline|date|status|amount|price|email|phone|address)\b",
    r"^(is|are|was|were|did|has|have)\s+.{5,50}\?$",  # Short yes/no
    r"^(how much|how many)\s+",
    r"^(send|forward|share)\s+(that|this|it|the same)\s+(to|with)\s+",
]
_FAST_RE = re.compile("|".join(_FAST_PATTERNS), re.IGNORECASE)

# Anything matching these is ALWAYS deep (overrides fast match)
_DEEP_FORCE = re.compile(
    r"(https?://|\.com\b|\.ch\b|buy|purchase|order|browse|shop|analyze|review|draft|prepare|"
    r"compare|strategy|recommend|what.should|think.about|plan|research|dossier|brief)",
    re.IGNORECASE,
)

def classify_complexity(question: str) -> str:
    """Rule-based complexity classification. No LLM needed."""
    if _DEEP_FORCE.search(question):
        return "deep"
    if _FAST_RE.search(question) and len(question) < 100:
        return "fast"
    return "deep"  # Default: Opus
```

**Changes to existing files:**

1. `orchestrator/action_handler.py` — Remove `complexity`, `complexity_confidence`, `complexity_reasoning` from Haiku intent prompt. Haiku only classifies intent type (email_action, question, etc.).

2. `outputs/dashboard.py` — Replace `complexity = intent_result.get("complexity", "deep")` with `complexity = classify_complexity(req.question)`. Remove all regex override hacks.

3. `orchestrator/agent.py` — Remove the mid-loop Haiku→Opus upgrade code (no longer needed since Opus is the default).

### Cost Impact

Current: ~60% of questions go to Haiku fast path (~$0.003/query), 40% to Opus (~$0.08/query).

Proposed: ~15% of questions go to Haiku fast path, 85% to Opus.

Estimated daily cost increase: **~$5-8/day** (from ~$15 to ~$20-23). Acceptable given the quality improvement.

### Migration

1. Deploy new router alongside existing (shadow mode: log both, use old)
2. Compare classifications over 2 days
3. Switch to new router
4. Remove old complexity fields from Haiku prompt
5. Remove regex override hacks from dashboard.py and agent.py

## Success Criteria

- Zero browser/purchase tasks routed to Haiku
- Zero "Baker refused to use tools" incidents
- Fast-path queries (dates, amounts, status) still answered in <3s
- No user-visible quality regression on any task type

## Estimated Effort

- Router module: 1 hour
- Integration + cleanup: 2 hours
- Shadow mode testing: 2 days (passive)
- Total: **~3 hours coding + 2 days validation**

## Decision Needed

Approve this refactor? The regex overrides we've been adding are duct tape. This is the clean fix.
