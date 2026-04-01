# BRIEF: GEMINI_MIGRATION_REDO_W1 — Migrate 15 Haiku call sites to Gemini Flash (properly)

## Context
GEMINI-MIGRATION-1 wave 2 was reverted (19 bugs, dashboard broken). This brief redoes the migration correctly: one function at a time, preserving system prompts, correct response patterns.

**Rule from lessons.md #13:** Never batch-migrate. Three things MUST stay consistent: client type ↔ model name ↔ response access pattern.

## Estimated time: ~2h
## Complexity: Medium (repetitive but each site needs care)
## Prerequisites: Revert deployed and dashboard working

---

## Migration Pattern (COPY THIS FOR EVERY SITE)

### Before (Haiku via Anthropic):
```python
import anthropic
claude = anthropic.Anthropic(api_key=config.claude.api_key)
resp = claude.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=400,
    system=SOME_SYSTEM_PROMPT,
    messages=[{"role": "user", "content": user_input}],
)
result = resp.content[0].text.strip()
```

### After (Flash via Gemini):
```python
from orchestrator.gemini_client import call_flash
resp = call_flash(
    messages=[{"role": "user", "content": user_input}],
    max_tokens=400,
    system=SOME_SYSTEM_PROMPT,  # ← MUST PRESERVE THIS
)
result = resp.text.strip()
```

### Checklist per site:
- [ ] `system=` parameter passed to `call_flash()` — **#1 cause of failure last time**
- [ ] `max_tokens=` matches original (or is explicitly set)
- [ ] Response accessed via `resp.text` (not `resp.content[0].text`)
- [ ] Cost logging updated: `log_api_cost("gemini-2.5-flash", ...)`
- [ ] Remove unused `import anthropic` / `claude = anthropic.Anthropic(...)` lines
- [ ] Syntax check the file

---

## Site 1: `action_handler.py` — `classify_intent()` (line ~636)

**CRITICAL** — This is the intent router. If broken, all actions misroute.

### Current:
```python
claude = anthropic.Anthropic(api_key=config.claude.api_key)
resp = claude.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=400,
    system=_INTENT_SYSTEM,
    messages=[{"role": "user", "content": user_content}],
)
...
log_api_cost("claude-haiku-4-5-20251001", ...)
result = resp.content[0].text.strip()
```

### Replace with:
```python
from orchestrator.gemini_client import call_flash
resp = call_flash(
    messages=[{"role": "user", "content": user_content}],
    max_tokens=400,
    system=_INTENT_SYSTEM,
)
...
log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="classify_intent")
...
raw = resp.text.strip()
```

**Remove:** The `claude = anthropic.Anthropic(...)` line (around line 631).
**Keep:** The `_INTENT_SYSTEM` variable — do NOT touch it.

### Verification:
Go to dashboard → Ask Baker → type "Draft a WhatsApp to Edita about dinner" → should classify as `whatsapp_action`, not crash.

---

## Site 2: `action_handler.py` — `handle_meeting_declaration()` (line ~1259)

### Current:
```python
claude = anthropic.Anthropic(api_key=config.claude.api_key)
resp = claude.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=300,
    system=_MEETING_DETECT_SYSTEM,
    messages=[{"role": "user", "content": question}],
)
raw = resp.content[0].text.strip()
```

### Replace with:
```python
from orchestrator.gemini_client import call_flash
resp = call_flash(
    messages=[{"role": "user", "content": question}],
    max_tokens=300,
    system=_MEETING_DETECT_SYSTEM,
)
raw = resp.text.strip()
```

**Update cost log:** `log_api_cost("gemini-2.5-flash", ...)`

---

## Site 3: `action_handler.py` — `handle_critical_declaration()` (line ~1365)

### Current:
```python
claude = anthropic.Anthropic(api_key=config.claude.api_key)
resp = claude.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=200,
    system=_CRITICAL_DETECT_SYSTEM,
    messages=[{"role": "user", "content": question}],
)
raw = resp.content[0].text.strip()
```

### Replace with:
```python
from orchestrator.gemini_client import call_flash
resp = call_flash(
    messages=[{"role": "user", "content": question}],
    max_tokens=200,
    system=_CRITICAL_DETECT_SYSTEM,
)
raw = resp.text.strip()
```

---

## Site 4: `action_handler.py` — `_extract_fireflies_params()` (line ~1590)

### Current:
```python
claude = anthropic.Anthropic(api_key=config.claude.api_key)
resp = claude.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=300,
    system=_FIREFLIES_PARAM_SYSTEM,
    messages=[...],
)
raw = resp.content[0].text.strip()
```

### Replace with:
```python
from orchestrator.gemini_client import call_flash
resp = call_flash(
    messages=[...],
    max_tokens=300,
    system=_FIREFLIES_PARAM_SYSTEM,
)
raw = resp.text.strip()
```

---

## Site 5: `action_handler.py` — `_extract_clickup_params()` (line ~1957)

### Current:
```python
claude = anthropic.Anthropic(api_key=config.claude.api_key)
resp = claude.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=400,
    system=extraction_prompt,
    messages=[{"role": "user", "content": message}],
)
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
raw = resp.text.strip()
```

---

## Site 6: `agent.py` — `_query_baker_data()` / `ToolExecutor` (line ~1208)

### Current:
```python
client = anthropic.Anthropic(api_key=config.claude.api_key)
resp = client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=500,
    system=(...SQL generation prompt...),
    messages=[{"role": "user", "content": question}],
)
sql = resp.content[0].text.strip()
```

### Replace with:
```python
from orchestrator.gemini_client import call_flash
resp = call_flash(
    messages=[{"role": "user", "content": question}],
    max_tokens=500,
    system=(
        "Generate a PostgreSQL SELECT query to answer the user's question about Baker's data. "
        "ONLY SELECT — no mutations. Available tables:\n"
        ...keep entire system prompt...
        "Return ONLY the SQL query, nothing else. Always include LIMIT (max 20)."
    ),
)
sql = resp.text.strip()
```

**Remove:** `import anthropic` (local) and `client = anthropic.Anthropic(...)`.
**Keep:** The entire SQL system prompt as-is.

---

## Site 7: `capability_runner.py` — `_auto_extract_insights()` (line ~926)

### Current:
```python
_HAIKU = "claude-haiku-4-5-20251001"
resp = self.claude.messages.create(
    model=_HAIKU,
    max_tokens=1000,
    system=_INSIGHT_EXTRACTION_SYSTEM,
    messages=[{"role": "user", "content": text}],
)
raw = resp.content[0].text.strip()
```

### Replace with:
```python
from orchestrator.gemini_client import call_flash
resp = call_flash(
    messages=[{"role": "user", "content": text}],
    max_tokens=1000,
    system=_INSIGHT_EXTRACTION_SYSTEM,
)
raw = resp.text.strip()
```

**Note:** This function is inside the CapabilityRunner class but doesn't need `self.claude` after migration. Don't touch the rest of the class (which uses `self.claude` for Opus agent loops).

---

## Site 8: `decision_engine.py` — `_generate_vip_draft()` (line ~871)

### Current:
```python
claude = anthropic.Anthropic(api_key=config.claude.api_key)
resp = claude.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=1500,
    system=_VIP_DRAFT_SYSTEM,
    messages=[...],
)
raw = resp.content[0].text.strip()
```

### Replace with:
```python
from orchestrator.gemini_client import call_flash
resp = call_flash(
    messages=[...],
    max_tokens=1500,
    system=_VIP_DRAFT_SYSTEM,
)
raw = resp.text.strip()
```

---

## Site 9: `research_trigger.py` — `classify_research_trigger()` (line ~167)

Same pattern. Replace Anthropic Haiku with `call_flash(system=_CLASSIFY_PROMPT + matter_context)`.

---

## Site 10: `convergence_detector.py` — `_extract_entities()` (line ~64)

Same pattern. Replace with `call_flash(system=_ENTITY_SYSTEM, max_tokens=800)`.

---

## Site 11: `convergence_detector.py` — `_analyze_convergence()` (line ~229)

Same pattern. Replace with `call_flash(system=_CONVERGENCE_SYSTEM, max_tokens=1500)`.

---

## Site 12: `obligation_generator.py` — `_generate_proposed_actions()` (line ~418)

Same pattern. Replace with `call_flash(system=_OBLIGATION_PROMPT, max_tokens=3000)`.

**Note:** Original max_tokens was 3000. Pass `max_tokens=3000` explicitly to avoid truncation.

---

## Site 13: `initiative_engine.py` — `_generate_initiatives()` (line ~403)

Same pattern. Replace with `call_flash(system=_INITIATIVE_PROMPT, max_tokens=1500)`.

---

## Site 14: `meeting_pipeline.py` — `generate_meeting_summary()` (line ~177)

Same pattern. Replace with `call_flash(system=_MEETING_SUMMARY_SYSTEM, max_tokens=1000)`.

---

## Site 15: `pipeline.py` — `_get_structured_actions()` (line ~301)

Same pattern. Replace with `call_flash(system=_STRUCTURED_ACTIONS_SYSTEM, max_tokens=2048)`.

**Note:** This function is inside `SentinelPipeline` class. Only migrate this specific method. Do NOT touch `_call_llm()` (line ~514) which uses Opus for main RAG.

---

## After ALL Sites: Clean up `import anthropic`

After migrating all 15 sites, check if any file still needs `import anthropic`. If a file has BOTH Haiku sites (migrated) and Opus sites (staying), keep the import. If ALL sites in a file were migrated, the import can stay (harmless) — don't remove it if other functions in the same file still use Anthropic.

Files that will still need `import anthropic`:
- `agent.py` — agent loops use Opus
- `action_handler.py` — email/WA drafting uses Opus
- `capability_runner.py` — run_single/run_streaming use Opus
- `pipeline.py` — _call_llm uses Opus
- `chain_runner.py` — _generate_plan uses Opus

Files that can drop `import anthropic` after wave 1:
- `decision_engine.py` (check first)
- `research_trigger.py`
- `convergence_detector.py`
- `obligation_generator.py`
- `initiative_engine.py`
- `meeting_pipeline.py`

---

## Files Modified
- `orchestrator/action_handler.py` — 5 sites migrated
- `orchestrator/agent.py` — 1 site migrated (ToolExecutor._query_baker_data)
- `orchestrator/capability_runner.py` — 1 site migrated (_auto_extract_insights)
- `orchestrator/decision_engine.py` — 1 site migrated
- `orchestrator/research_trigger.py` — 1 site migrated
- `orchestrator/convergence_detector.py` — 2 sites migrated
- `orchestrator/obligation_generator.py` — 1 site migrated
- `orchestrator/initiative_engine.py` — 1 site migrated
- `orchestrator/meeting_pipeline.py` — 1 site migrated
- `orchestrator/pipeline.py` — 1 site migrated (_get_structured_actions only)

## Do NOT Touch
- `orchestrator/agent.py` — run_agent_loop, run_agent_loop_streaming, _force_synthesis (Opus)
- `orchestrator/capability_runner.py` — run_single(), run_streaming() (Opus)
- `orchestrator/pipeline.py` — _call_llm() (Opus/tier routing)
- `orchestrator/chain_runner.py` — _generate_plan() (Opus)
- `orchestrator/action_handler.py` — generate_email_body(), _generate_whatsapp_body(), clickup_plan() (Opus)
- `config/settings.py` — don't change haiku_model/fast_model yet

## Quality Checkpoints
1. Syntax check EVERY modified file: `python3 -c "import py_compile; py_compile.compile('file.py', doraise=True)"`
2. After deploying, test Ask Baker: "What meetings do I have this week?" — should work without error
3. Test triage: click "Draft WA" on a card — should classify as whatsapp_action (not crash)
4. Test: "Add meeting with Edita on Friday at 3pm" — should classify as meeting_declaration
5. Verify no `[Error: ...]` messages in Ask Baker responses
6. Bump CSS/JS cache: `style.css?v=57`, `app.js?v=82` (only if frontend changes needed)

## Cost Impact
- 15 Haiku sites → Flash: ~EUR 300-400/mo savings
- Zero Opus calls affected (those stay on Anthropic)
- Net: significant cost reduction with zero quality impact on these classification tasks
