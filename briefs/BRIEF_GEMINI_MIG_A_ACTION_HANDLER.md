# BRIEF: GEMINI_MIG_A_ACTION_HANDLER — Migrate 5 Haiku sites in action_handler.py to Gemini Flash

## Context
Gemini migration wave 2 was reverted (19 bugs). This brief redoes the migration for `action_handler.py` only — 5 Haiku call sites that are simple classifiers/extractors. The 5 Opus call sites in the same file (email draft, WhatsApp draft, ClickUp plan) stay on Anthropic.

**Lesson #13**: Never batch-migrate. Three things MUST stay consistent: client type ↔ model name ↔ response access pattern.

## Estimated time: ~30min
## Complexity: Low
## Prerequisites: Revert deployed, dashboard working
## Parallel-safe: Yes — only touches `orchestrator/action_handler.py`

---

## The Migration Pattern

Every site follows the same transformation. **Do NOT deviate.**

### Before (Haiku via Anthropic):
```python
claude = anthropic.Anthropic(api_key=config.claude.api_key)
resp = claude.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=NNN,
    system=SOME_SYSTEM_PROMPT,
    messages=[{"role": "user", "content": user_content}],
)
log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="xxx")
raw = resp.content[0].text.strip()
```

### After (Flash via Gemini):
```python
from orchestrator.gemini_client import call_flash
resp = call_flash(
    messages=[{"role": "user", "content": user_content}],
    max_tokens=NNN,
    system=SOME_SYSTEM_PROMPT,
)
log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="xxx")
raw = resp.text.strip()
```

### Checklist per site (verify ALL before moving to next):
- [ ] `system=` parameter passed to `call_flash()` — CRITICAL
- [ ] `max_tokens=` matches original value exactly
- [ ] Response accessed via `resp.text` (NOT `resp.content[0].text`)
- [ ] Cost logging model string changed to `"gemini-2.5-flash"`
- [ ] The `claude = anthropic.Anthropic(...)` line removed for this site
- [ ] No other code in the same function changed

---

## Site 1: `classify_intent()` — line 630-662

**THE MOST CRITICAL SITE.** If this breaks, all action routing fails.

### Current State (lines 630-647):
```python
    try:
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        # Include conversation history for resolving references like "the same message"
        user_content = question
        if conversation_history:
            user_content = f"Recent conversation:\n{conversation_history}\n\nCurrent message to classify:\n{question}"
        resp = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=_INTENT_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="classify_intent")
        except Exception:
            pass
        raw = resp.content[0].text.strip()
```

### Replace with (lines 630-647):
```python
    try:
        from orchestrator.gemini_client import call_flash
        # Include conversation history for resolving references like "the same message"
        user_content = question
        if conversation_history:
            user_content = f"Recent conversation:\n{conversation_history}\n\nCurrent message to classify:\n{question}"
        resp = call_flash(
            messages=[{"role": "user", "content": user_content}],
            max_tokens=400,
            system=_INTENT_SYSTEM,
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="classify_intent")
        except Exception:
            pass
        raw = resp.text.strip()
```

**Key**: `_INTENT_SYSTEM` is a module-level variable (line 232). Do NOT change it. It MUST be passed as `system=_INTENT_SYSTEM`.

---

## Site 2: `handle_meeting_declaration()` — line 1255-1288

### Current State (lines 1257-1288):
```python
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        today = date.today().isoformat()
        resp = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system="You extract meeting details from messages. Return ONLY valid JSON, no markdown.",
            messages=[{"role": "user", "content": f"""Extract meeting details from this message:
"{question}"

Today's date is {today}.

Return JSON:
...
"""}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="meeting_detect")
        except Exception:
            pass
        raw = resp.content[0].text.strip()
```

### Replace with:
```python
        from orchestrator.gemini_client import call_flash
        today = date.today().isoformat()
        resp = call_flash(
            messages=[{"role": "user", "content": f"""Extract meeting details from this message:
"{question}"

Today's date is {today}.

Return JSON:
{{
  "title": "short meeting title",
  "participants": ["Name1", "Name2"],
  "date": "YYYY-MM-DD or null",
  "time": "HH:MM or descriptive like 'afternoon' or null",
  "location": "place or 'Zoom/Teams' or null",
  "status": "confirmed" | "proposed" | "pending"
}}

Status rules:
- "confirmed": message says "confirmed", "set", "booked", "see you at", or is clearly definite
- "proposed": message says "let's try", "how about", "would X work"
- "pending": needs to be arranged"""}],
            max_tokens=300,
            system="You extract meeting details from messages. Return ONLY valid JSON, no markdown.",
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="meeting_detect")
        except Exception:
            pass
        raw = resp.text.strip()
```

**Key**: The system prompt is inline (`"You extract meeting details..."`). It MUST be passed as `system=` parameter. The user message template with the JSON schema stays in `messages`.

---

## Site 3: `handle_critical_declaration()` — line 1362-1386

### Current State (lines 1363-1386):
```python
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        today = date.today().isoformat()
        resp = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system="Extract the critical task. Return ONLY valid JSON, no markdown.",
            messages=[{"role": "user", "content": f"""Extract the critical item from this message:
"{question}"
...
"""}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="critical_detect")
        except Exception:
            pass
        raw = resp.content[0].text.strip()
```

### Replace with:
```python
        from orchestrator.gemini_client import call_flash
        today = date.today().isoformat()
        resp = call_flash(
            messages=[{"role": "user", "content": f"""Extract the critical item from this message:
"{question}"

Today's date is {today}.

Return JSON:
{{
  "description": "what needs to be done",
  "context": "why it is critical (1 line) or null",
  "due_hint": "today / by 3pm / ASAP / null"
}}"""}],
            max_tokens=200,
            system="Extract the critical task. Return ONLY valid JSON, no markdown.",
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="critical_detect")
        except Exception:
            pass
        raw = resp.text.strip()
```

---

## Site 4: `_extract_fireflies_params()` — line 1587-1608

### Current State (lines 1589-1604):
```python
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=_FIREFLIES_PARAM_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"Today is {today}.\n\nMessage: {message}",
            }],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="fireflies_params")
        except Exception:
            pass
        raw = resp.content[0].text.strip()
```

### Replace with:
```python
        from orchestrator.gemini_client import call_flash
        resp = call_flash(
            messages=[{
                "role": "user",
                "content": f"Today is {today}.\n\nMessage: {message}",
            }],
            max_tokens=300,
            system=_FIREFLIES_PARAM_SYSTEM,
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="fireflies_params")
        except Exception:
            pass
        raw = resp.text.strip()
```

**Key**: `_FIREFLIES_PARAM_SYSTEM` is a module-level variable (line 1575). Pass as `system=`.

---

## Site 5: `_extract_clickup_params()` — line 1956-1968

### Current State (lines 1956-1968):
```python
    claude = anthropic.Anthropic(api_key=config.claude.api_key)
    resp = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=extraction_prompt,
        messages=[{"role": "user", "content": message}],
    )
    try:
        from orchestrator.cost_monitor import log_api_cost
        log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="clickup_params")
    except Exception:
        pass
    raw = resp.content[0].text.strip()
```

### Replace with:
```python
    from orchestrator.gemini_client import call_flash
    resp = call_flash(
        messages=[{"role": "user", "content": message}],
        max_tokens=400,
        system=extraction_prompt,
    )
    try:
        from orchestrator.cost_monitor import log_api_cost
        log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="clickup_params")
    except Exception:
        pass
    raw = resp.text.strip()
```

**Key**: `extraction_prompt` is a local variable built in the same function (line 1940). Pass as `system=`.

---

## After All 5 Sites: Keep `import anthropic`

The file STILL needs `import anthropic` at line 22 because these Opus functions remain on Anthropic:
- `generate_email_body()` (line 740)
- `_generate_whatsapp_body()` (line 789)
- `handle_project_plan()` (line 2273)
- `_revise_plan()` (line 2400)

**DO NOT remove `import anthropic` from this file.**

---

## Files Modified
- `orchestrator/action_handler.py` — 5 Haiku sites → Gemini Flash

## Do NOT Touch
- `orchestrator/action_handler.py` lines 740, 789, 2273, 2400 — Opus sites, stay on Anthropic
- `orchestrator/agent.py` — separate brief (Brief B)
- `orchestrator/capability_runner.py` — separate brief (Brief B)
- `orchestrator/pipeline.py` — separate brief (Brief B)
- All other `orchestrator/*.py` — separate brief (Brief C)
- `outputs/*` — separate brief (triage fixes)

## Quality Checkpoints
1. `python3 -c "import py_compile; py_compile.compile('orchestrator/action_handler.py', doraise=True)"`
2. Dashboard → Ask Baker → "Draft a WhatsApp to Edita about dinner" → should classify as `whatsapp_action` (not crash)
3. Dashboard → Ask Baker → "Add meeting with Edita on Friday at 3pm" → should classify as `meeting_declaration`
4. Dashboard → Ask Baker → "This is critical: call the bank" → should classify as `critical_declaration`
5. Dashboard → Ask Baker → "Find my meeting notes from Tuesday" → should classify as `fireflies_fetch`
6. Dashboard → Ask Baker → "Create a ClickUp task for the brief" → should classify as `clickup_action`
7. Verify no `[Error: ...]` messages in any Ask Baker response
8. Commit message must include `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`

## Cost Impact
- 5 sites × ~100 calls/day × ~1000 tokens avg = ~500K tokens/day
- Haiku: ~$0.125/day → Flash: ~$0.0375/day
- Monthly savings: ~$2.60 (small, but part of larger migration)
- Zero quality impact — these are simple JSON extraction tasks
