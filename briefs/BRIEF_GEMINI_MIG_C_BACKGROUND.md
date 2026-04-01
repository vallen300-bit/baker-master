# BRIEF: GEMINI_MIG_C_BACKGROUND — Migrate 7 Haiku sites in 6 background orchestrator files

## Context
Part 3 (final) of the Gemini migration redo. Brief A (action_handler, 5 sites) and Brief B (agent/capability_runner/pipeline, 3 sites) are deployed. This brief covers 7 remaining Haiku sites in background processing files. These are lower-traffic than A/B — they run during signal ingestion, not user interactions.

**None of these files have Opus call sites**, so after migration, `import anthropic` can be removed entirely from each file.

## Estimated time: ~45min
## Complexity: Low
## Prerequisites: Briefs A+B deployed
## Parallel-safe: Yes — zero file overlap with A, B, or triage brief

---

## Migration Pattern (same as Briefs A and B)

### Before:
```python
client = anthropic.Anthropic(api_key=config.claude.api_key)
resp = client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=NNN,
    system=SOME_PROMPT,   # may be missing — see notes per site
    messages=[...],
)
log_api_cost("claude-haiku-4-5-20251001", ...)
raw = resp.content[0].text.strip()
```

### After:
```python
from orchestrator.gemini_client import call_flash
resp = call_flash(
    messages=[...],
    max_tokens=NNN,
    system=SOME_PROMPT,   # add if original had it; keep in user msg if not
)
log_api_cost("gemini-2.5-flash", ...)
raw = resp.text.strip()
```

---

## Site 1: `decision_engine.py` — `_generate_vip_draft()` (line ~870)

### Current State (lines 870-882):
```python
        client = anthropic.Anthropic(api_key=_config.claude.api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            system=_VIP_DRAFT_PROMPT,
            messages=[{"role": "user", "content": context}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="vip_auto_draft")
        except Exception:
            pass
        raw = resp.content[0].text.strip()
```

### Replace with:
```python
        from orchestrator.gemini_client import call_flash
        resp = call_flash(
            messages=[{"role": "user", "content": context}],
            max_tokens=1500,
            system=_VIP_DRAFT_PROMPT,
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="vip_auto_draft")
        except Exception:
            pass
        raw = resp.text.strip()
```

**Also**: Remove `import anthropic` at line 854 (local import inside the function). Remove the `client = anthropic.Anthropic(...)` line. Note: `_config` (with underscore) is used here, not `config` — this is fine since we no longer need `_config.claude.api_key`.

---

## Site 2: `research_trigger.py` — `classify_research_trigger()` (line ~166)

### Current State (lines 166-184):
```python
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=_CLASSIFY_PROMPT + matter_context,
            messages=[{"role": "user", "content": f"From: {sender_name}\n\n{message_body[:3000]}"}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(
                "claude-haiku-4-5-20251001", resp.usage.input_tokens,
                resp.usage.output_tokens, source="research_trigger_classify",
            )
        except Exception:
            pass
        raw = resp.content[0].text.strip()
```

### Replace with:
```python
        from orchestrator.gemini_client import call_flash
        resp = call_flash(
            messages=[{"role": "user", "content": f"From: {sender_name}\n\n{message_body[:3000]}"}],
            max_tokens=400,
            system=_CLASSIFY_PROMPT + matter_context,
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(
                "gemini-2.5-flash", resp.usage.input_tokens,
                resp.usage.output_tokens, source="research_trigger_classify",
            )
        except Exception:
            pass
        raw = resp.text.strip()
```

**Key**: `system=_CLASSIFY_PROMPT + matter_context` — the system prompt is dynamically composed. Preserve exactly.

**Cleanup**: Remove `import anthropic` at top of file if it exists, and remove `client = anthropic.Anthropic(...)` line. Check if `config.claude` is still referenced elsewhere in the file — if not, the config import can stay (harmless).

---

## Site 3: `convergence_detector.py` — `_extract_entities()` (line ~63)

### Current State (lines 63-82):
```python
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{
                "role": "user",
                "content": f"{_ENTITY_EXTRACT_PROMPT}\n\nTexts:\n{combined}",
            }],
        )
        ...
        raw = resp.content[0].text.strip()
```

**NOTE**: This site has NO `system=` parameter — the prompt is embedded in the user message. Keep it that way for minimal change.

### Replace with:
```python
        from orchestrator.gemini_client import call_flash
        resp = call_flash(
            messages=[{
                "role": "user",
                "content": f"{_ENTITY_EXTRACT_PROMPT}\n\nTexts:\n{combined}",
            }],
            max_tokens=800,
        )
        ...
        raw = resp.text.strip()
```

Update cost log: `"gemini-2.5-flash"`. Remove `client = anthropic.Anthropic(...)`.

---

## Site 4: `convergence_detector.py` — `_analyze_convergences()` (line ~228)

### Current State (lines 228-247):
```python
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{
                "role": "user",
                "content": f"{_ANALYSIS_PROMPT}\n\nConvergences:\n{conv_text}",
            }],
        )
        ...
        raw = resp.content[0].text.strip()
```

**NOTE**: Same as Site 3 — no `system=` parameter, prompt in user message. Keep it.

### Replace with:
```python
        from orchestrator.gemini_client import call_flash
        resp = call_flash(
            messages=[{
                "role": "user",
                "content": f"{_ANALYSIS_PROMPT}\n\nConvergences:\n{conv_text}",
            }],
            max_tokens=1500,
        )
        ...
        raw = resp.text.strip()
```

Update cost log: `"gemini-2.5-flash"`. Remove `client = anthropic.Anthropic(...)`.

**After both sites**: Remove module-level `import anthropic` at line 23 of convergence_detector.py.

---

## Site 5: `obligation_generator.py` — `_generate_proposed_actions()` (line ~417)

### Current State (lines 417-435):
```python
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=3000,
            system=_OBLIGATION_PROMPT,
            messages=[{"role": "user", "content": context_str}],
        )
        ...
        raw = resp.content[0].text.strip()
```

### Replace with:
```python
        from orchestrator.gemini_client import call_flash
        resp = call_flash(
            messages=[{"role": "user", "content": context_str}],
            max_tokens=3000,
            system=_OBLIGATION_PROMPT,
        )
        ...
        raw = resp.text.strip()
```

**Key**: `max_tokens=3000` — higher than Flash default of 2000. MUST pass explicitly.

---

## Site 6: `initiative_engine.py` — `_generate_initiatives()` (line ~402)

### Current State (lines 402-420):
```python
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            system=_INITIATIVE_PROMPT,
            messages=[{"role": "user", "content": context_str}],
        )
        ...
        raw = resp.content[0].text.strip()
```

### Replace with:
```python
        from orchestrator.gemini_client import call_flash
        resp = call_flash(
            messages=[{"role": "user", "content": context_str}],
            max_tokens=1500,
            system=_INITIATIVE_PROMPT,
        )
        ...
        raw = resp.text.strip()
```

---

## Site 7: `meeting_pipeline.py` — `generate_meeting_summary()` (line ~153)

### Current State (lines 152-183):
```python
        import anthropic
        client = anthropic.Anthropic()

        action_text = "\n".join(...)

        prompt = f"""Draft a brief, professional follow-up email for this meeting.
        ...
        """

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )

        draft_text = response.content[0].text.strip()
```

**NOTE**: No `system=` param, no cost logging. The prompt is entirely in the user message. Also uses `anthropic.Anthropic()` without api_key (relies on env var).

### Replace with:
```python
        from orchestrator.gemini_client import call_flash

        action_text = "\n".join(...)

        prompt = f"""Draft a brief, professional follow-up email for this meeting.
        ...
        """

        response = call_flash(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
        )

        draft_text = response.text.strip()
```

Remove `import anthropic` (line 152) and `client = anthropic.Anthropic()` (line 153). The `prompt` variable and everything after `draft_text` stays unchanged.

**Optional improvement**: Add cost logging (currently missing). Not required for this brief — keep scope minimal.

---

## Cleanup: Remove `import anthropic` where safe

After migrating all sites, remove `import anthropic` from these files (no remaining Anthropic usage):

| File | Line | Type |
|------|------|------|
| `convergence_detector.py` | 23 | Module-level |
| `meeting_pipeline.py` | 152 | Local (inside function) |
| `decision_engine.py` | 854 | Local (inside function) |

For `research_trigger.py`, `obligation_generator.py`, `initiative_engine.py` — check if `import anthropic` exists at module level. If yes and no other Anthropic usage remains, remove it. If unsure, leave it (harmless).

---

## Files Modified
- `orchestrator/decision_engine.py` — 1 site: `_generate_vip_draft()`
- `orchestrator/research_trigger.py` — 1 site: `classify_research_trigger()`
- `orchestrator/convergence_detector.py` — 2 sites: `_extract_entities()`, `_analyze_convergences()`
- `orchestrator/obligation_generator.py` — 1 site: `_generate_proposed_actions()`
- `orchestrator/initiative_engine.py` — 1 site: `_generate_initiatives()`
- `orchestrator/meeting_pipeline.py` — 1 site: `generate_meeting_summary()`

## Do NOT Touch
- `orchestrator/action_handler.py` — already migrated (Brief A)
- `orchestrator/agent.py` — already migrated (Brief B)
- `orchestrator/capability_runner.py` — already migrated (Brief B)
- `orchestrator/pipeline.py` — already migrated (Brief B)
- `outputs/*` — separate brief (triage fixes)

## Quality Checkpoints
1. Syntax check ALL 6 files:
```bash
for f in orchestrator/decision_engine.py orchestrator/research_trigger.py orchestrator/convergence_detector.py orchestrator/obligation_generator.py orchestrator/initiative_engine.py orchestrator/meeting_pipeline.py; do
    python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" && echo "OK: $f"
done
```
2. `grep -rn "claude-haiku" orchestrator/` — should return ZERO results after all 3 briefs complete
3. `grep -rn "anthropic.Anthropic" orchestrator/` — should only show agent.py, capability_runner.py, pipeline.py, action_handler.py (Opus sites)
4. Check Render logs after deploy — no import errors on startup
5. Dashboard loads normally (these are background processes — won't show immediate user-facing changes)
6. Commit message must include `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`

## Cost Impact
- 7 sites migrated, mostly low-frequency background tasks
- Highest volume: obligation_generator (~daily), convergence_detector (~daily)
- Estimated monthly savings: ~$3-5
- Combined with Briefs A+B: total ~$10-15/month saved on Haiku→Flash migration
- The BIG savings come from Opus→Pro migration (future briefs)
