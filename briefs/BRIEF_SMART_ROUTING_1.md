# BRIEF: SMART-ROUTING-1 — Haiku-First Intent Classification

**Author:** AI Head (Session 20)
**For:** Code 300 (after RICHER-CONTEXT-1)
**Priority:** HIGH — eliminates regex misfire class of bugs
**Estimated scope:** 1 file, ~40 lines changed
**Cost:** ~$0.001/classification × ~100/day = $0.10/day

---

## Problem

`classify_intent()` in `orchestrator/action_handler.py` runs 8 regex fast-paths before falling back to Haiku. These regex patterns cause misfires:
- "what's up" → WhatsApp (fixed in Session 19, but fragile)
- Broad deadline patterns match questions like "any upcoming events?"
- ClickUp patterns fire on tangential mentions of "task" in questions
- Every new regex added risks a new class of misfires

The Haiku classifier already handles ALL intent types correctly — it just runs as a fallback instead of the primary path.

## Solution

Restructure `classify_intent()` to **Haiku-first for all non-trivial inputs**:

1. **Keep only 2 safe regex fast-paths** (zero misfire risk):
   - `_quick_email_detect()` — requires BOTH email verb AND actual email address (very specific)
   - `_quick_capability_detect()` — requires "agent" or "capability" keyword (very specific)

2. **Remove 6 regex fast-paths** (move to Haiku):
   - `_quick_whatsapp_detect()` — DELETE the call from classify_intent (keep function for reference)
   - `_quick_fireflies_detect()` — DELETE the call
   - `_quick_deadline_detect()` — DELETE the call
   - `_quick_clickup_action_detect()` — DELETE the call
   - `_quick_clickup_plan_detect()` — DELETE the call
   - `_quick_clickup_fetch_detect()` — DELETE the call

3. **The Haiku classifier already handles all these intents** — no changes needed to `_INTENT_SYSTEM` prompt or the Haiku call.

## Change

**File: `orchestrator/action_handler.py`**

**Modify `classify_intent()` (line 577):**

```python
def classify_intent(question: str, conversation_history: str = "") -> dict:
    """
    Classify the Director's input into action types.
    Uses Haiku as the primary classifier for all non-trivial inputs.
    Two safe regex fast-paths remain: email with addresses, explicit capability invocation.
    Falls back to {"type": "question"} on any error.
    """
    _log_action("classify_intent:start", f"question={question[:200]}")

    # Safe regex: explicit capability invocations ("have the finance agent analyze...")
    quick_cap = _quick_capability_detect(question)
    if quick_cap:
        _log_action("classify_intent:regex_match", f"type=capability_task, hint={quick_cap.get('capability_hint')}")
        return quick_cap

    # Safe regex: email commands with actual email addresses present
    quick = _quick_email_detect(question)
    if quick:
        _log_action("classify_intent:regex_match", f"type={quick.get('type')}, recipient={quick.get('recipient')}")
        return quick

    # ALL other intents → Haiku classifier (WhatsApp, fireflies, deadlines, ClickUp, questions)
    try:
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        user_content = question
        if conversation_history:
            user_content = f"Recent conversation:\n{conversation_history}\n\nCurrent message to classify:\n{question}"
        resp = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=_INTENT_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="classify_intent")
        except Exception:
            pass
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        result = json.loads(raw)
        _log_action("classify_intent:haiku_result", f"type={result.get('type')}, raw={raw[:200]}")
        return result
    except Exception as e:
        _log_action("classify_intent:haiku_failed", str(e))
        logger.warning(f"Intent classification failed ({e}) — defaulting to question")
        return {"type": "question"}
```

**That's the entire change.** Remove 6 lines (the 6 regex fast-path calls + their `if` blocks, lines 598-632), keep 2 (capability + email).

**Do NOT delete the `_quick_whatsapp_detect()`, `_quick_fireflies_detect()`, etc. function definitions** — they're unused now but harmless. Removing them is optional cleanup.

## Also Update: _INTENT_SYSTEM prompt (line 232)

One small addition — rename "vip_action" to "contact_action" in the prompt to match Session 20's VIP→Contacts rename:

Line 236, change:
```
"type": "email_action" | "whatsapp_action" | "deadline_action" | "vip_action" | ...
```
to:
```
"type": "email_action" | "whatsapp_action" | "deadline_action" | "contact_action" | ...
```

And line 289-291, update the pattern examples:
```
Contact action patterns:
- "Add [name] to contacts" → type: "contact_action", vip_action_type: "add"
- "Remove [name] from contacts" → type: "contact_action", vip_action_type: "remove"
```

**BUT IMPORTANT:** The rest of the codebase still checks `intent.get("type") == "vip_action"`. So you need to update the handler routing too.

In `outputs/dashboard.py`, search for `vip_action` in the intent routing and add support for both old and new:
```python
elif intent.get("type") in ("vip_action", "contact_action"):
```

And in `triggers/waha_webhook.py`, same pattern:
```python
elif intent_type in ("vip_action", "contact_action"):
```

## What NOT to Change

- Keep the `_quick_*` function definitions (dead code is harmless, removal is optional)
- Don't change the Haiku model — `claude-haiku-4-5-20251001` is correct
- Don't change the WhatsApp webhook's intent handling — it already calls `classify_intent()` which now routes through Haiku
- Don't change `check_pending_draft()` — it handles yes/no/confirm via simple string matching, not this classifier

## Testing

1. `python3 -c "import py_compile; py_compile.compile('orchestrator/action_handler.py', doraise=True)"`
2. `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"`
3. `python3 -c "import py_compile; py_compile.compile('triggers/waha_webhook.py', doraise=True)"`

## Summary

| Before | After |
|--------|-------|
| 8 regex fast-paths → Haiku fallback | 2 safe regex → Haiku for everything else |
| Regex misfires on ambiguous inputs | Haiku understands context + conversation history |
| Free (regex) | ~$0.10/day (negligible) |
| Brittle — each regex is a potential misfire | Robust — Haiku handles edge cases naturally |
