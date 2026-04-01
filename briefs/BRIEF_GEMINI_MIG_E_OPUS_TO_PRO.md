# BRIEF: GEMINI_MIG_E_OPUS_TO_PRO — Move 7 Opus sites to Gemini Pro (~€300/month savings)

## Context
All 17 Haiku sites are now on Gemini Flash (Briefs A-D). This brief targets the next cost tier: Opus sites that don't need maximum intelligence. The pipeline alone spends €205/week on Opus — meetings and scheduled triggers can safely use Pro. Email/WA drafts and ClickUp plans are also safe candidates.

**What stays on Opus (not in this brief):**
- T1 email processing (VIP, legal, financial)
- Agent loop (user-facing RAG with tools)
- Capability runner (specialist deep analysis)
- Memory consolidator (lossless compression)
- Chain runner planning (autonomous action chains)

## Estimated time: ~45min
## Complexity: Low-Medium
## Prerequisites: Briefs A-D complete (all Haiku migrated)
## Parallel-safe: Yes — no overlap with triage brief

---

## Part 1: Pipeline routing — Move meetings + scheduled to Pro

### Problem
Pipeline routes `meeting` and `scheduled` trigger types to Opus (€72/week) via the `else` catch-all in `_call_llm()`. These produce meeting summaries and daily briefings — tasks where Gemini Pro's quality is sufficient.

### Current State
File: `orchestrator/pipeline.py`, lines ~463-493:
```python
    _HAIKU_TRIGGER_TYPES = {
        "dropbox_file_new", "dropbox_file_modified",
        "rss_article", "rss_article_new",
        "clickup_task_updated", "clickup_task_overdue", "clickup_task_created",
        "todoist_task_updated", "todoist_task_completed", "todoist_task_overdue",
        "browser_change",
    }

    _SONNET_TRIGGER_TYPES = {
        "email",
        "clickup_handoff_note",
    }

    def generate(self, prompt, max_output_tokens=8192,
                 trigger_type=None, trigger_tier=None):
        if trigger_type in self._HAIKU_TRIGGER_TYPES:
            model = "gemini-2.5-flash"
        elif trigger_type in self._SONNET_TRIGGER_TYPES:
            if trigger_tier == 1:
                model = config.claude.model  # Opus
            else:
                model = "gemini-2.5-pro"
        else:
            model = config.claude.model  # Opus for meetings, scheduled, etc.
```

### Implementation
Add `"meeting"` and `"scheduled"` to `_SONNET_TRIGGER_TYPES` so they follow the same T1=Opus / T2+T3=Pro routing as emails:

```python
    _SONNET_TRIGGER_TYPES = {
        "email",
        "clickup_handoff_note",
        "meeting",
        "scheduled",
    }
```

Also rename the set to reflect it's no longer just Sonnet:

```python
    # PRO_TRIGGER_TYPES: T1 → Opus (critical), T2/T3 → Gemini Pro
    _SONNET_TRIGGER_TYPES = {
        "email",
        "clickup_handoff_note",
        "meeting",
        "scheduled",
    }
```

(Keeping the variable name `_SONNET_TRIGGER_TYPES` to avoid changing all references. Just update the comment.)

### Key Constraints
- T1 meetings and T1 scheduled still get Opus (the `if trigger_tier == 1` check at line 488 handles this automatically)
- The `else` catch-all (line 493) still routes unknown trigger types to Opus — safe default
- The Gemini Pro code path (lines 502-512) already works — used by T2/T3 emails since COST-OPT-WAVE2

### Verification
After deploy, check cost logs for pipeline calls:
```sql
SELECT model, COUNT(*) as calls, ROUND(SUM(cost_eur)::numeric, 2) as cost_eur
FROM api_cost_log
WHERE source = 'pipeline'
  AND logged_at >= NOW() - INTERVAL '1 day'
GROUP BY model
ORDER BY cost_eur DESC;
```
Should see more `gemini-2.5-pro` calls and fewer `claude-opus-4-6` calls than before.

---

## Part 2: Email/WhatsApp drafts → Gemini Pro

### Problem
`generate_email_body()` (line 739) and `_generate_whatsapp_body()` (line 788) use Opus for drafting. Combined: ~11 calls/week, €0.31. Small cost but good to migrate — Pro writes excellent emails and messages.

### Current State (`generate_email_body`, lines 738-751):
```python
    try:
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = claude.messages.create(
            model=config.claude.model,
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": f"Compose this email now: {content_request}"}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(config.claude.model, resp.usage.input_tokens, resp.usage.output_tokens, source="email_draft")
        except Exception:
            pass
        return resp.content[0].text.strip()
```

### Replace (`generate_email_body`):
```python
    try:
        from orchestrator.gemini_client import call_pro
        resp = call_pro(
            messages=[{"role": "user", "content": f"Compose this email now: {content_request}"}],
            max_tokens=1500,
            system=system,
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-pro", resp.usage.input_tokens, resp.usage.output_tokens, source="email_draft")
        except Exception:
            pass
        return resp.text.strip()
```

### Current State (`_generate_whatsapp_body`, lines 787-799):
```python
    try:
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = claude.messages.create(
            model=config.claude.model, max_tokens=500,
            system=system,
            messages=[{"role": "user", "content": f"Write this WhatsApp message now: {content_request}"}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(config.claude.model, resp.usage.input_tokens, resp.usage.output_tokens, source="whatsapp_draft")
        except Exception:
            pass
        return resp.content[0].text.strip()
```

### Replace (`_generate_whatsapp_body`):
```python
    try:
        from orchestrator.gemini_client import call_pro
        resp = call_pro(
            messages=[{"role": "user", "content": f"Write this WhatsApp message now: {content_request}"}],
            max_tokens=500,
            system=system,
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-pro", resp.usage.input_tokens, resp.usage.output_tokens, source="whatsapp_draft")
        except Exception:
            pass
        return resp.text.strip()
```

### Key Constraints
- `system` variable is a local built earlier in each function — pass as `system=system`
- `resp.text` not `resp.content[0].text`
- Remove `claude = anthropic.Anthropic(...)` lines

---

## Part 3: ClickUp plans → Gemini Pro

### Problem
`handle_project_plan()` (line 2268) and `_revise_plan()` (line 2395) use Opus for structured JSON project decomposition. Rarely called, but Pro handles JSON generation well.

### Current State (`handle_project_plan`, lines 2268-2279):
```python
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = claude.messages.create(
            model=config.claude.model, max_tokens=4096,
            system="You are a project planning assistant. Return only JSON.",
            messages=[{"role": "user", "content": plan_prompt}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(config.claude.model, resp.usage.input_tokens, resp.usage.output_tokens, source="clickup_plan")
        except Exception:
            pass
        raw = resp.content[0].text.strip()
```

### Replace:
```python
        from orchestrator.gemini_client import call_pro
        resp = call_pro(
            messages=[{"role": "user", "content": plan_prompt}],
            max_tokens=4096,
            system="You are a project planning assistant. Return only JSON.",
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-pro", resp.usage.input_tokens, resp.usage.output_tokens, source="clickup_plan")
        except Exception:
            pass
        raw = resp.text.strip()
```

Apply the **exact same pattern** to `_revise_plan()` (lines 2395-2406). Same transformation: `call_pro()`, `system=`, `resp.text`, cost log `"gemini-2.5-pro"`, source `"clickup_plan_revise"`.

---

## Part 4: Capability router decomposer → Gemini Pro

### Current State (`capability_router.py`, lines 153-165):
```python
            claude = anthropic.Anthropic(api_key=config.claude.api_key)
            resp = claude.messages.create(
                model=config.claude.model,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": text}],
            )
            try:
                from orchestrator.cost_monitor import log_api_cost
                log_api_cost(config.claude.model, resp.usage.input_tokens, resp.usage.output_tokens, source="decomposer")
            except Exception:
                pass
            raw = resp.content[0].text.strip()
```

### Replace:
```python
            from orchestrator.gemini_client import call_pro
            resp = call_pro(
                messages=[{"role": "user", "content": text}],
                max_tokens=1024,
                system=system,
            )
            try:
                from orchestrator.cost_monitor import log_api_cost
                log_api_cost("gemini-2.5-pro", resp.usage.input_tokens, resp.usage.output_tokens, source="decomposer")
            except Exception:
                pass
            raw = resp.text.strip()
```

Remove `claude = anthropic.Anthropic(...)` line. Remove `import anthropic` from top of file (line 16) — no other Anthropic usage remains.

---

## After All Parts: Clean up `import anthropic`

| File | Action |
|------|--------|
| `action_handler.py` | **KEEP** — `import anthropic` still needed? Check: after Parts 2+3, are there remaining Anthropic sites? **NO** — all 4 Opus sites in this file are migrated. **REMOVE `import anthropic` at line 22.** |
| `capability_router.py` | **REMOVE** `import anthropic` at line 16 |
| `pipeline.py` | **KEEP** — `self.claude` still used for T1 Opus calls in `_call_llm()` |

---

## Files Modified
- `orchestrator/pipeline.py` — Add meeting/scheduled to Pro routing (2 lines)
- `orchestrator/action_handler.py` — 4 sites: email_draft, whatsapp_draft, clickup_plan, clickup_plan_revise
- `orchestrator/capability_router.py` — 1 site: decomposer

## Do NOT Touch
- `orchestrator/agent.py` — Agent loops stay on Opus
- `orchestrator/capability_runner.py` — Specialist queries stay on Opus
- `orchestrator/pipeline.py` `_call_llm()` Anthropic branch — T1 signals stay on Opus
- `orchestrator/memory_consolidator.py` — Tier 2 compression stays on Opus
- `orchestrator/chain_runner.py` — Action planning stays on Opus
- `orchestrator/extraction_engine.py` — Agentic extraction stays on Opus (for now)

## Quality Checkpoints
1. Syntax check all 3 files
2. Dashboard → Ask Baker → "Draft an email to Edita about the Monaco meeting" → should produce a well-written email (test Pro quality)
3. Dashboard → Ask Baker → "Send WhatsApp to Edita about dinner" → message should be warm, conversational
4. Dashboard → Ask Baker → "Create a ClickUp plan for Hagenauer tender" → should return structured JSON
5. Pipeline cost logs after 24h: `gemini-2.5-pro` calls should increase, `claude-opus-4-6` calls should decrease
6. `grep -rn "anthropic" orchestrator/action_handler.py` — should return **zero** results
7. `grep -rn "anthropic" orchestrator/capability_router.py` — should return **zero** results
8. Commit message must include `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`

## Cost Impact
**This is the highest-impact migration brief so far:**
- Pipeline meetings/scheduled: ~37 calls/week × €1.86 avg → moved to Pro (~€0.19/call) = **~€62/week saved**
- Email/WA/ClickUp/decomposer: ~€1/week saved
- **Estimated total: ~€63/week = ~€250/month saved**
- Remaining Opus spend after this brief: ~€236/week (T1 emails, agent loops, specialists)
- Combined with Haiku→Flash (Briefs A-D): **~€265/month total savings**

## Rollback
If quality degrades on Pro drafts or meeting summaries, revert is simple:
- Pipeline: remove `"meeting"` and `"scheduled"` from `_SONNET_TRIGGER_TYPES`
- Drafts/plans: change `call_pro` back to `anthropic.Anthropic` + `config.claude.model`

## Verification SQL
```sql
-- Check model distribution after 24h (compare with pre-deploy baseline)
SELECT model, COUNT(*) as calls, ROUND(SUM(cost_eur)::numeric, 2) as cost_eur
FROM api_cost_log
WHERE source IN ('pipeline', 'email_draft', 'whatsapp_draft', 'clickup_plan', 'decomposer')
  AND logged_at >= NOW() - INTERVAL '1 day'
GROUP BY model
ORDER BY cost_eur DESC;
```
