# Brief: SPECIALIST-THINKING-1 — Extended Thinking + Citations for Specialists

**Author:** Code 300 (Session 16)
**For:** Code Brisen
**Priority:** HIGH — Director-requested, high ROI for legal/financial specialists

---

## Context

Baker's specialists already have tools (web_search, read_document, spreadsheet generation, email drafting). The two missing capabilities that would significantly upgrade specialist quality are:

1. **Extended Thinking** — Claude reasons internally before answering (chain of thought, self-correction, weighing alternatives)
2. **Citations** — Specialist responses reference specific sources with clickable links back to the original document/email/transcript

## What to Build

### 1. Extended Thinking

**Backend change in `orchestrator/capability_runner.py`:**

Currently, specialist calls use `client.messages.create()` with standard parameters. Add extended thinking by including the `thinking` parameter for specialists that benefit from deep reasoning.

**Which specialists get thinking:**

| Specialist | Thinking | Why |
|-----------|----------|-----|
| `legal` | YES | Contract analysis, deadline calculations, multi-jurisdiction reasoning |
| `finance` | YES | IRR calculations, cashflow modeling, tax implications |
| `profiling` | YES | Counterparty dossiers, negotiation tactics, game theory |
| `sales` | YES | Deal structuring, pricing strategy, investor pipeline analysis |
| `asset_management` | YES | Portfolio KPIs, capex decisions, insurance analysis |
| `research` | YES | Market analysis, competitor intel, OSINT synthesis |
| `communications` | NO | Email drafts don't need chain-of-thought |
| `pr_branding` | NO | Brand strategy is more creative than analytical |
| `marketing` | NO | Campaign work is more creative than analytical |
| `it` | NO | IT ops queries are straightforward |
| `ai_dev` | NO | Dev queries are straightforward |
| `decomposer` | NO | Meta-agent, fast routing |
| `synthesizer` | NO | Meta-agent, fast assembly |

**Implementation:**

1. Add a `use_thinking` boolean field to the `capability_sets` table:
```sql
ALTER TABLE capability_sets ADD COLUMN IF NOT EXISTS use_thinking BOOLEAN DEFAULT FALSE;
```

2. Update seed data — set `use_thinking = TRUE` for: legal, finance, profiling, sales, asset_management, research.

3. In `capability_runner.py`, where the Claude API call is made (search for `client.messages.create`), check the capability's `use_thinking` flag:

```python
# Build API params
api_params = {
    "model": model,
    "max_tokens": max_tokens,
    "system": system_prompt,
    "messages": messages,
}

# Add extended thinking for analytical specialists
if capability.get("use_thinking"):
    api_params["thinking"] = {
        "type": "enabled",
        "budget_tokens": 10000,  # 10K tokens for reasoning
    }
    # Extended thinking requires max_tokens to include thinking budget
    api_params["max_tokens"] = max(max_tokens, 16000)

resp = client.messages.create(**api_params)
```

4. **Streaming:** Extended thinking works with streaming. The thinking blocks appear as `content_block` events with `type: "thinking"`. The existing SSE handler in `capability_runner.py` streams `text` blocks — add handling to skip `thinking` blocks (they're internal reasoning, not shown to the user) OR show them collapsed:

```python
for event in stream:
    if event.type == "content_block_start":
        if event.content_block.type == "thinking":
            # Option A: Skip (don't show internal reasoning)
            continue
            # Option B: Show collapsed (Director can expand to see reasoning)
            yield f"data: {json.dumps({'thinking_start': True})}\n\n"
    elif event.type == "content_block_delta":
        if hasattr(event.delta, 'thinking'):
            # Skip or stream thinking tokens
            continue
        elif hasattr(event.delta, 'text'):
            yield f"data: {json.dumps({'token': event.delta.text})}\n\n"
```

**Recommendation:** Start with Option A (skip thinking output). The quality improvement comes from Claude reasoning internally — the Director doesn't need to see the chain of thought. Can add Option B later if the Director wants to see "how Baker thinks."

5. **Cost note:** Extended thinking uses additional tokens (up to 10K per query). At Haiku rates (~$0.001/1K tokens), this adds ~$0.01 per specialist query. Negligible. Log the thinking tokens in `log_api_cost()`.

### 2. Citations

**Concept:** When Baker retrieves context from Qdrant (emails, meetings, WhatsApp, documents) and passes it to the specialist, the specialist should cite specific sources in its response.

**Implementation approach — source markers in context:**

1. **In the RAG retrieval step** (`memory/retriever.py` or `orchestrator/agent.py`), when assembling retrieved context for the specialist prompt, tag each chunk with a source marker:

```python
# Before (current):
context_text = chunk["text"]

# After (with citation markers):
source_label = _build_source_label(chunk["metadata"])
context_text = f"[SOURCE:{source_id}|{source_label}]\n{chunk['text']}\n[/SOURCE]"
```

Where `_build_source_label` produces human-readable labels like:
- `Email from JCB re Wertheimer, 2 Mar 2026`
- `Meeting: Hagenauer strategy review, 26 Feb 2026`
- `WhatsApp from Oskolkov, 5 Mar 2026`
- `Document: TU Agreement §4.2`

2. **In the specialist system prompt**, add an instruction:

```
When referencing information from the provided sources, cite them using [Source: label] format.
Example: "The payment deadline is March 11 [Source: Email from Ofenheimer, 6 Mar 2026]."
```

3. **In the frontend** (`app.js`, in the `md()` function), render citation markers as styled badges:

```javascript
// In md() function, after other replacements:
h = h.replace(/\[Source: ([^\]]+)\]/g,
    '<span class="citation" style="font-size:10px;background:var(--badge-bg);color:var(--badge-text);padding:1px 6px;border-radius:3px;cursor:help;" title="$1">📎 $1</span>');
```

This renders citations as small grey badges inline with the text. Hovering shows the full source label.

4. **Optional enhancement — clickable citations:** If the source_id maps to a known alert, email, or meeting, the citation badge could link to the source. This requires passing source IDs through the response, which is more complex. Defer to Phase 2.

**Source label builder (`_build_source_label`):**

```python
def _build_source_label(metadata: dict) -> str:
    """Build human-readable source label from Qdrant chunk metadata."""
    content_type = metadata.get("content_type", "")

    if content_type == "email_thread":
        sender = metadata.get("sender", "Unknown")
        subject = metadata.get("subject", "")
        date = metadata.get("date", "")[:10]
        return f"Email from {sender}: {subject[:40]}, {date}"

    elif content_type == "meeting_transcript":
        title = metadata.get("title", metadata.get("label", "Meeting"))
        date = metadata.get("date", "")[:10]
        return f"Meeting: {title[:40]}, {date}"

    elif content_type == "whatsapp":
        sender = metadata.get("sender", metadata.get("author", "Unknown"))
        date = metadata.get("date", "")[:10]
        return f"WhatsApp from {sender}, {date}"

    elif content_type == "clickup_task":
        name = metadata.get("name", metadata.get("label", "Task"))
        return f"ClickUp: {name[:40]}"

    elif content_type == "document":
        label = metadata.get("label", metadata.get("filename", "Document"))
        return f"Document: {label[:40]}"

    else:
        label = metadata.get("label", content_type or "Source")
        date = metadata.get("date", "")[:10]
        return f"{label[:40]}" + (f", {date}" if date else "")
```

## Files to Modify

| File | Change |
|------|--------|
| `orchestrator/capability_runner.py` | Add `thinking` parameter to API call for analytical specialists |
| `orchestrator/capability_registry.py` | Load `use_thinking` from capability_sets table |
| `memory/store_back.py` | Add `use_thinking` column migration |
| `memory/retriever.py` | Add source markers to retrieved chunks |
| `orchestrator/agent.py` | Add source markers when building tool results |
| `orchestrator/scan_prompt.py` | Add citation instruction to specialist system prompts |
| `outputs/static/app.js` | Render citation badges in `md()` function |
| `orchestrator/cost_monitor.py` | Log thinking tokens separately |

## Seed Data Update

After migration, run:
```sql
UPDATE capability_sets SET use_thinking = TRUE
WHERE slug IN ('legal', 'finance', 'profiling', 'sales', 'asset_management', 'research');
```

## Verification

1. Ask the **Legal** specialist: "Analyze the Hagenauer insolvency timeline and our options"
   - Response should be noticeably more structured and thorough (thinking enabled)
   - Citations like `[Source: Email from Ofenheimer, 6 Mar 2026]` should appear as badges

2. Ask the **Communications** specialist: "Draft a follow-up email to JCB"
   - Response should be normal speed (no thinking overhead)
   - Citations still work for referenced emails

3. Check `/api/cost/today` — thinking tokens should appear in the cost log

## What NOT to Build

- Clickable citations linking to original source (Phase 2)
- Thinking output visible to Director (defer — start with hidden)
- Per-specialist thinking budget configuration (use 10K for all, adjust later)
