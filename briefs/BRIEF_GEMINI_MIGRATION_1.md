# BRIEF: GEMINI-MIGRATION-1 — Replace Haiku/Sonnet with Gemini Flash/Pro

## Context
Director decision (Session 44, 1 Apr 2026): Substitute Claude Haiku with Gemini 2.5 Flash and Claude Sonnet with Gemini 2.5 Pro across Baker. Additionally, move T2 extraction and non-T1 pipeline generation from Opus to Gemini Pro. Opus stays for T1 signals, agentic RAG, and extended thinking.

**Cost impact:** ~50-60% reduction on workhorse + mid-tier API spend.

## Estimated time: ~4h
## Complexity: Medium-High
## Prerequisites: `GEMINI_API_KEY` env var on Render

---

## Fix 1: Add Google GenAI SDK + Config

### Problem
Baker currently only has the `anthropic` SDK. Need `google-genai` for Gemini API calls.

### Current State
- `requirements.txt` line 5: `anthropic>=0.40.0`
- `config/settings.py` has `ClaudeConfig` but no Gemini config

### Implementation

**File: `requirements.txt`** — add:
```
google-genai>=1.0.0          # Gemini API client
```

**File: `config/settings.py`** — add after `ClaudeConfig` (after line 57):
```python
@dataclass
class GeminiConfig:
    api_key: str = os.getenv("GEMINI_API_KEY", "")
    flash_model: str = "gemini-2.5-flash"
    pro_model: str = "gemini-2.5-pro"
    # Cost per million tokens (USD)
    flash_cost_input: float = 0.30
    flash_cost_output: float = 2.50
    pro_cost_input: float = 1.25
    pro_cost_output: float = 10.00
```

**File: `config/settings.py`** — add to `SentinelConfig` (line ~316):
```python
    gemini: GeminiConfig = field(default_factory=GeminiConfig)
```

**File: `config/settings.py`** — update `DecisionEngineConfig` (line 288):
```python
    haiku_model: str = "gemini-2.5-flash"  # was claude-haiku-4-5-20251001
```

**File: `config/settings.py`** — update `ComplexityConfig` (line 305):
```python
    fast_model: str = "gemini-2.5-flash"  # was claude-haiku-4-5-20251001
```

### Key Constraints
- `GEMINI_API_KEY` must be set on Render before deploy
- Do NOT touch `ClaudeConfig` — Opus stays on Anthropic

---

## Fix 2: Create Gemini Client Wrapper

### Problem
All existing code uses `anthropic.Anthropic().messages.create()`. Gemini has a different SDK interface. We need a thin wrapper that matches our calling pattern.

### Current State
Every call site does:
```python
client = anthropic.Anthropic(api_key=config.claude.api_key)
resp = client.messages.create(model=..., max_tokens=..., messages=[...], system=...)
resp.content[0].text  # response text
resp.usage.input_tokens  # token counts
```

### Implementation

**File: `orchestrator/gemini_client.py`** — NEW FILE:
```python
"""
Gemini client wrapper — provides Claude-compatible interface for Gemini models.
GEMINI-MIGRATION-1: Drop-in replacement for Haiku/Sonnet call sites.
"""
import json
import logging
import os

from google import genai

from config.settings import config

logger = logging.getLogger("baker.gemini_client")

# Lazy singleton
_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = config.gemini.api_key or os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set")
        _client = genai.Client(api_key=api_key)
    return _client


class GeminiUsage:
    """Mimics anthropic response.usage for cost logging compatibility."""
    def __init__(self, input_tokens: int, output_tokens: int):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class GeminiResponse:
    """Mimics anthropic response shape for drop-in compatibility."""
    def __init__(self, text: str, input_tokens: int, output_tokens: int):
        self.text = text
        self.usage = GeminiUsage(input_tokens, output_tokens)


def generate(
    model: str,
    messages: list,
    max_tokens: int = 2000,
    system: str = None,
) -> GeminiResponse:
    """
    Call Gemini API with Claude-style message format.

    Args:
        model: "gemini-2.5-flash" or "gemini-2.5-pro"
        messages: [{"role": "user", "content": "..."}] — Claude format
        max_tokens: max output tokens
        system: system prompt (optional)
    """
    client = _get_client()

    # Build Gemini contents from Claude-style messages
    contents = []
    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"
        content = msg["content"]
        # Handle list-format content (vision messages)
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(part["text"])
                elif isinstance(part, dict) and part.get("type") == "image":
                    # Base64 image — convert to Gemini Part
                    src = part.get("source", {})
                    import base64 as b64
                    from google.genai import types
                    parts.append(types.Part.from_bytes(
                        data=b64.b64decode(src["data"]),
                        mime_type=src.get("media_type", "image/jpeg"),
                    ))
                else:
                    parts.append(str(part))
            contents.append({"role": role, "parts": parts})
        else:
            contents.append({"role": role, "parts": [str(content)]})

    # Build config
    gen_config = {"max_output_tokens": max_tokens}
    if system:
        gen_config["system_instruction"] = system

    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=gen_config,
        )

        text = response.text or ""
        input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0

        return GeminiResponse(text, input_tokens, output_tokens)

    except Exception as e:
        logger.error(f"Gemini API error ({model}): {e}")
        raise


def is_gemini_model(model: str) -> bool:
    """Check if a model string is a Gemini model."""
    return model.startswith("gemini-")
```

### Key Constraints
- This wrapper must handle both text-only and vision (image) messages
- Error handling must match Baker's fault-tolerant pattern (log + raise)
- No tool use support needed for Flash/Pro — only Opus does agentic tool loops

---

## Fix 3: Update Cost Monitor for Gemini Models

### Problem
`cost_monitor.py` only knows Anthropic model pricing. Gemini calls will log with wrong costs or fail to match.

### Current State
`orchestrator/cost_monitor.py` lines 24-28:
```python
MODEL_COSTS = {
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
}
```

### Implementation

**File: `orchestrator/cost_monitor.py`** — update `MODEL_COSTS` (line 24):
```python
MODEL_COSTS = {
    # Anthropic
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    # Gemini
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
}
```

### Verification
```sql
SELECT model, COUNT(*), ROUND(SUM(cost_eur)::numeric, 4) as total_eur
FROM api_cost_log WHERE logged_at > NOW() - INTERVAL '1 day'
GROUP BY model ORDER BY total_eur DESC LIMIT 10;
```

---

## Fix 4: Replace All Haiku Call Sites with Gemini Flash

### Problem
~40 hardcoded `"claude-haiku-4-5-20251001"` strings across 15+ files. Each needs to switch to Gemini Flash using the new wrapper.

### Current State
All Haiku call sites follow this pattern:
```python
import anthropic
client = anthropic.Anthropic(api_key=config.claude.api_key)
resp = client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=N,
    messages=[{"role": "user", "content": prompt}],
)
text = resp.content[0].text.strip()
# cost logging: log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, ...)
```

### Implementation

Create a helper function in `orchestrator/gemini_client.py` (append to existing file):
```python
def call_flash(messages: list, max_tokens: int = 2000, system: str = None) -> GeminiResponse:
    """Convenience: call Gemini Flash (workhorse tier)."""
    return generate(config.gemini.flash_model, messages, max_tokens, system)


def call_pro(messages: list, max_tokens: int = 2000, system: str = None) -> GeminiResponse:
    """Convenience: call Gemini Pro (mid tier)."""
    return generate(config.gemini.pro_model, messages, max_tokens, system)
```

**For EACH Haiku call site, apply this transformation pattern:**

Before:
```python
import anthropic
client = anthropic.Anthropic(api_key=config.claude.api_key)
resp = client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=N,
    messages=[{"role": "user", "content": prompt}],
)
text = resp.content[0].text.strip()
log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="xxx")
```

After:
```python
from orchestrator.gemini_client import call_flash
resp = call_flash(
    messages=[{"role": "user", "content": prompt}],
    max_tokens=N,
)
text = resp.text.strip()
log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="xxx")
```

**Files to update (Haiku → Flash):**

| File | Lines | Call Site |
|------|-------|-----------|
| `orchestrator/extraction_engine.py` | 159-163 | `_extract_haiku()` — T3 extraction |
| `orchestrator/extraction_engine.py` | 366-367 | Vision/image analysis |
| `orchestrator/sentiment_scorer.py` | 59-66 | Sentiment scoring |
| `orchestrator/decision_engine.py` | 220-224 | Domain classification |
| `orchestrator/deadline_manager.py` | 74-82 | Deadline extraction |
| `orchestrator/insight_to_task.py` | ~63 | Insight-to-task conversion |
| `orchestrator/capability_runner.py` | 65-66 | Correction extraction |
| `orchestrator/pipeline.py` | 485 | Pipeline Haiku routing |
| `triggers/rss_trigger.py` | 516 | RSS relevance scoring |
| `triggers/email_trigger.py` | 106, 169, 481, 573 | Meeting detect, commitment detect, commitments, intelligence |
| `triggers/waha_webhook.py` | 62, 120 | WA meeting detect, commitment detect |
| `triggers/fireflies_trigger.py` | 99, 173 | Commitment extract, meeting detect |
| `triggers/calendar_trigger.py` | 539 | Meeting prep |
| `tools/document_pipeline.py` | 31 | `_HAIKU_MODEL` constant |
| `outputs/dashboard.py` | 641, 2752, 2783, 3224, 3286, 4605 | Trip filters, morning narrative, morning proposals |

**IMPORTANT:** For call sites that use `system=` parameter, pass it as the `system` kwarg to `call_flash()`.

**IMPORTANT:** For the vision/image call site (extraction_engine.py:366), the `call_flash()` wrapper already handles list-format content with image parts.

### Key Constraints
- Do NOT remove `import anthropic` from files that also have Opus calls
- Keep the `anthropic.Anthropic()` client for any remaining Claude calls in the same file
- Each file change: run `python3 -c "import py_compile; py_compile.compile('file.py', doraise=True)"`

---

## Fix 5: Replace Sonnet Call Sites with Gemini Pro

### Problem
3 hardcoded Sonnet references need to switch to Gemini Pro.

### Current State
```
orchestrator/pipeline.py:491         → model = "claude-sonnet-4-20250514"
triggers/email_trigger.py:386        → model = "claude-sonnet-4-20250514"
orchestrator/memory_consolidator.py:51 → TIER3_MODEL = "claude-sonnet-4-20250514"
```

### Implementation

**File: `orchestrator/pipeline.py`** line 491 — change:
```python
# Before:
                model = "claude-sonnet-4-20250514"
# After:
                model = "gemini-2.5-pro"
```

BUT — the pipeline `generate()` method uses `self.claude.messages.create()` which is the Anthropic client. For Gemini models, it needs to route through the Gemini wrapper.

**Rewrite `pipeline.py` `generate()` method (lines 476-520):**
```python
    def generate(self, prompt: dict, max_output_tokens: int = 8192,
                 trigger_type: str = None, trigger_tier: int = None) -> str:
        """Send assembled prompt to LLM and get response.
        GEMINI-MIGRATION-1: Multi-provider routing:
        - Gemini Flash: document ingestion, RSS, task status changes
        - Gemini Pro: emails, handoff notes, T2 extraction, non-T1 pipeline
        - Opus: meetings, briefings, T1 critical signals
        """
        if trigger_type in self._HAIKU_TRIGGER_TYPES:
            model = "gemini-2.5-flash"
        elif trigger_type in self._SONNET_TRIGGER_TYPES:
            if trigger_tier == 1:
                model = config.claude.model  # Opus for T1
            else:
                model = "gemini-2.5-pro"
        else:
            model = config.claude.model  # Opus for meetings, scheduled, etc.

        logger.info(
            f"Calling LLM: model={model}, "
            f"~{prompt['metadata']['tokens_estimated']} input tokens"
        )

        from orchestrator.gemini_client import is_gemini_model

        if is_gemini_model(model):
            from orchestrator.gemini_client import generate as gemini_generate
            resp = gemini_generate(
                model=model,
                messages=prompt["messages"],
                max_tokens=max_output_tokens,
                system=prompt["system"],
            )
            raw_text = resp.text
            input_tokens = resp.usage.input_tokens
            output_tokens = resp.usage.output_tokens
        else:
            response = self.claude.messages.create(
                model=model,
                max_tokens=max_output_tokens,
                system=prompt["system"],
                messages=prompt["messages"],
                extra_headers={"anthropic-beta": config.claude.beta_header},
            )
            raw_text = response.content[0].text
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens

        logger.info(f"LLM responded: {input_tokens} in, {output_tokens} out")

        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(model, input_tokens, output_tokens, source="pipeline")
        except Exception:
            pass
        return raw_text
```

**File: `triggers/email_trigger.py`** line 386 — same transformation as Haiku sites:
```python
# Before:
                model="claude-sonnet-4-20250514",
# After — use call_pro:
from orchestrator.gemini_client import call_pro
resp = call_pro(messages=[...], max_tokens=N)
```

**File: `orchestrator/memory_consolidator.py`** line 51:
```python
# Before:
TIER3_MODEL = "claude-sonnet-4-20250514"
# After:
TIER3_MODEL = "gemini-2.5-pro"
```
Also update the client call in memory_consolidator to use Gemini wrapper when model is Gemini.

---

## Fix 6: Move T2 Extraction to Gemini Pro

### Problem
T2 extraction currently uses Opus (`extraction_engine.py:268`). Director approved moving T2 to Gemini Pro. T1 stays on Opus.

### Current State
`orchestrator/extraction_engine.py` line 266-268:
```python
        for iteration in range(4):
            response = client.messages.create(
                model="claude-opus-4-6",
```
This is the agentic RAG extraction loop. It uses tool calls — **Gemini Pro does NOT support this tool pattern.**

### Implementation
**Split the agentic extraction by tier:**

In `extract_items()` (the main dispatch function), add tier-based routing:
```python
# T1: Opus agentic extraction (tool calls, full reasoning)
# T2: Gemini Pro single-pass extraction (no tool calls, structured output)
# T3: Gemini Flash literal extraction (cheapest)

if tier == 1:
    items, elapsed_ms, cost = _extract_agentic(content, source_channel, source_id)
elif tier == 2:
    items, elapsed_ms, cost = _extract_pro(content, source_channel, source_id)
else:
    items, elapsed_ms, cost = _extract_flash(content, source_channel, source_id)
```

**Add new `_extract_pro()` function** (single-pass, no tool calls):
```python
def _extract_pro(content, source_channel, source_id):
    """T2: Gemini Pro single-pass extraction — structured output, no tool calls."""
    start = time.time()
    try:
        from orchestrator.gemini_client import call_pro

        text = content[:12000] if len(content) > 12000 else content

        prompt = _HAIKU_EXTRACTION_PROMPT.format(
            source_channel=source_channel,
            content=text,
        )

        resp = call_pro(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
        )

        result_text = resp.text.strip()
        items = _parse_json_array(result_text)

        elapsed_ms = int((time.time() - start) * 1000)
        cost_usd = (resp.usage.input_tokens / 1_000_000) * 1.25 + (resp.usage.output_tokens / 1_000_000) * 10.00

        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-pro", resp.usage.input_tokens, resp.usage.output_tokens, source="t2_extraction")
        except Exception:
            pass

        logger.info(
            f"Pro extraction: {len(items)} items from {source_channel}:{source_id} "
            f"({elapsed_ms}ms)"
        )
        return items, elapsed_ms, cost_usd

    except Exception as e:
        logger.error(f"Pro extraction failed for {source_channel}:{source_id}: {e}")
        elapsed_ms = int((time.time() - start) * 1000)
        return [], elapsed_ms, 0.0
```

**Rename `_extract_haiku()` to `_extract_flash()`** and update it to use Gemini Flash.

### Key Constraints
- T1 agentic extraction STAYS on Opus — it uses tool calls that Gemini doesn't support in our pattern
- T2 uses the same extraction prompt as T3 but with higher token limits (12K input, 3K output)
- If Gemini Pro fails, do NOT fall back to Opus — log error and return empty (fault-tolerant)

---

## Fix 7: Env Var on Render

### Problem
Need `GEMINI_API_KEY` available at runtime.

### Implementation
Use Render MCP (merge mode) to add:
```
GEMINI_API_KEY=<value from Director>
```

**IMPORTANT:** Director must provide the API key. Get it from https://aistudio.google.com/apikey

### Key Constraints
- Use MCP merge mode, NEVER raw PUT (known Baker pattern)
- Do NOT commit the key to code

---

## Files Modified
- `requirements.txt` — add `google-genai`
- `config/settings.py` — add `GeminiConfig`, update `DecisionEngineConfig.haiku_model`, update `ComplexityConfig.fast_model`
- `orchestrator/gemini_client.py` — NEW: Gemini wrapper with `generate()`, `call_flash()`, `call_pro()`
- `orchestrator/cost_monitor.py` — add Gemini models to `MODEL_COSTS`
- `orchestrator/pipeline.py` — rewrite `generate()` for multi-provider routing
- `orchestrator/extraction_engine.py` — add `_extract_pro()`, rename `_extract_haiku()` → `_extract_flash()`
- `orchestrator/sentiment_scorer.py` — Haiku → Flash
- `orchestrator/decision_engine.py` — Haiku → Flash
- `orchestrator/deadline_manager.py` — Haiku → Flash
- `orchestrator/insight_to_task.py` — Haiku → Flash
- `orchestrator/capability_runner.py` — Haiku → Flash
- `orchestrator/memory_consolidator.py` — Sonnet → Pro
- `triggers/rss_trigger.py` — Haiku → Flash
- `triggers/email_trigger.py` — Haiku → Flash, Sonnet → Pro
- `triggers/waha_webhook.py` — Haiku → Flash
- `triggers/fireflies_trigger.py` — Haiku → Flash
- `triggers/calendar_trigger.py` — Haiku → Flash
- `tools/document_pipeline.py` — Haiku → Flash
- `outputs/dashboard.py` — Haiku → Flash (6 call sites)

## Do NOT Touch
- `orchestrator/agent.py` — Opus agentic loop, must stay Anthropic
- `baker_rag.py` — Opus RAG, must stay Anthropic
- `memory/retriever.py` — Voyage embeddings, different provider
- `orchestrator/capability_runner.py` lines 256-258 — extended thinking, Opus only
- `orchestrator/extraction_engine.py` lines 266-268 — T1 agentic extraction stays Opus

## Quality Checkpoints
1. `python3 -c "import py_compile; py_compile.compile('orchestrator/gemini_client.py', doraise=True)"`
2. `python3 -c "import py_compile; py_compile.compile('orchestrator/pipeline.py', doraise=True)"`
3. Repeat for every modified file
4. After deploy: check `/api/cost-dashboard` — Gemini models should appear in breakdown
5. Trigger a test email → verify it routes through Gemini Flash (check logs for `model=gemini-2.5-flash`)
6. Trigger a T2 signal → verify Pro extraction works
7. Trigger a T1 signal → verify Opus still handles it

## Verification SQL
```sql
-- After deploy: confirm Gemini models appear in cost log
SELECT model, COUNT(*) as calls, ROUND(SUM(cost_eur)::numeric, 4) as total_eur
FROM api_cost_log
WHERE logged_at > NOW() - INTERVAL '1 hour'
GROUP BY model ORDER BY calls DESC LIMIT 10;

-- Compare costs: before vs after (run after 24h)
SELECT model,
       COUNT(*) as calls,
       ROUND(SUM(cost_eur)::numeric, 2) as total_eur,
       ROUND(AVG(cost_eur)::numeric, 4) as avg_eur
FROM api_cost_log
WHERE logged_at > NOW() - INTERVAL '1 day'
GROUP BY model ORDER BY total_eur DESC LIMIT 10;
```

## Rollback Plan
If Gemini quality is unacceptable:
1. Set env var `BAKER_USE_GEMINI=false`
2. In `gemini_client.py`, add check: if not enabled, raise so callers fall back
3. OR: revert the commit (all changes are in one branch)

Better: add a feature flag from the start:
```python
GEMINI_ENABLED = os.getenv("BAKER_USE_GEMINI", "true").lower() == "true"
```
If `false`, all `call_flash()`/`call_pro()` calls fall back to Anthropic Haiku/Sonnet. This gives a zero-downtime rollback path.
