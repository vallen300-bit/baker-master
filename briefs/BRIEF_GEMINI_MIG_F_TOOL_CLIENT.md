# BRIEF: GEMINI_MIG_F_TOOL_CLIENT — Gemini tool-calling wrapper for agent loop fast-path

## Context
The agent loop's fast-path (simple Ask Baker questions) still uses Haiku via the Anthropic client because the loop needs tool calling (search emails, query data, etc.). Gemini has different tool-calling formats, so a simple model swap doesn't work. This brief adds a compatibility wrapper that translates Anthropic's tool protocol ↔ Gemini's function calling, enabling the fast-path to use Flash.

**The fast-path handles ~30% of Ask Baker queries** (simple factual lookups). After this brief, they use Flash instead of Haiku — better quality AND lower cost.

## Estimated time: ~2h
## Complexity: Medium
## Prerequisites: Briefs A-E complete
## Parallel-safe: Yes — touches gemini_client.py (no other brief touches this), agent.py (Opus sites untouched), settings.py (1 line)

---

## Part 1: Add `GeminiToolClient` to `gemini_client.py`

### Problem
The current `gemini_client.py` only supports simple text generation (`generate()`, `call_flash()`, `call_pro()`). The agent loop needs tool calling: send tool definitions, receive `tool_use` blocks, send `tool_result` blocks back.

### Implementation
Add the following classes and wrapper to the END of `orchestrator/gemini_client.py` (after the existing `call_pro` function):

```python
# ---------------------------------------------------------------------------
# GEMINI-TOOL-CLIENT: Anthropic-compatible tool-calling wrapper
# ---------------------------------------------------------------------------

class _GeminiTextBlock:
    """Mimics anthropic TextBlock."""
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class _GeminiToolUseBlock:
    """Mimics anthropic ToolUseBlock."""
    def __init__(self, id: str, name: str, input: dict):
        self.type = "tool_use"
        self.id = id
        self.name = name
        self.input = input


class _GeminiToolResponse:
    """Mimics anthropic Message for tool-calling flows."""
    def __init__(self, content: list, stop_reason: str, input_tokens: int, output_tokens: int):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = GeminiUsage(input_tokens, output_tokens)


class _GeminiMessages:
    """Implements the .messages.create() interface using Gemini API."""

    def create(self, model, messages, system=None, tools=None,
               max_tokens=4096, **kwargs):
        from google.genai import types

        client = _get_client()

        # 1. Convert Anthropic tool definitions → Gemini function declarations
        gemini_tools = None
        if tools:
            func_decls = []
            for t in tools:
                decl = {
                    "name": t["name"],
                    "description": t.get("description", ""),
                }
                schema = t.get("input_schema")
                if schema:
                    decl["parameters"] = schema
                func_decls.append(decl)
            gemini_tools = [types.Tool(function_declarations=func_decls)]

        # 2. Convert Anthropic messages → Gemini contents
        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            content = msg.get("content", "")

            # Handle list-format content (tool_use / tool_result blocks)
            if isinstance(content, list):
                parts = []
                for block in content:
                    if not isinstance(block, dict):
                        parts.append(types.Part.from_text(text=str(block)))
                        continue
                    btype = block.get("type", "")
                    if btype == "text":
                        parts.append(types.Part.from_text(text=block.get("text", "")))
                    elif btype == "tool_use":
                        # Assistant's tool call → Gemini function_call part
                        parts.append(types.Part.from_function_call(
                            name=block["name"],
                            args=block.get("input", {}),
                            id=block.get("id"),
                        ))
                    elif btype == "tool_result":
                        # User's tool result → Gemini function_response part
                        result_content = block.get("content", "")
                        parts.append(types.Part.from_function_response(
                            name=block.get("name", "unknown"),
                            response={"result": result_content},
                            id=block.get("tool_use_id"),
                        ))
                    else:
                        parts.append(types.Part.from_text(text=str(block)))
                if parts:
                    contents.append(types.Content(role=role, parts=parts))
            elif isinstance(content, str) and content:
                contents.append(types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=content)],
                ))

        # 3. Build config
        gen_config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
        )
        if system:
            gen_config.system_instruction = system
        if gemini_tools:
            gen_config.tools = gemini_tools
            # Disable auto function calling — we handle it in the agent loop
            gen_config.automatic_function_calling = types.AutomaticFunctionCallingConfig(
                disable=True,
            )

        # 4. Call Gemini
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=gen_config,
        )

        # 5. Convert Gemini response → Anthropic-like response
        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0 if usage else 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0 if usage else 0

        result_blocks = []
        has_function_call = False

        if response.candidates:
            for part in response.candidates[0].content.parts:
                if part.function_call:
                    has_function_call = True
                    fc = part.function_call
                    # Generate a stable ID from function name + args hash
                    import hashlib
                    _id_seed = f"{fc.name}:{json.dumps(dict(fc.args) if fc.args else {}, sort_keys=True)}"
                    tool_id = f"toolu_{hashlib.md5(_id_seed.encode()).hexdigest()[:12]}"
                    # Use Gemini's own ID if available
                    if hasattr(fc, 'id') and fc.id:
                        tool_id = fc.id
                    result_blocks.append(_GeminiToolUseBlock(
                        id=tool_id,
                        name=fc.name,
                        input=dict(fc.args) if fc.args else {},
                    ))
                elif part.text:
                    result_blocks.append(_GeminiTextBlock(part.text))

        stop_reason = "tool_use" if has_function_call else "end_turn"

        return _GeminiToolResponse(
            content=result_blocks,
            stop_reason=stop_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


class GeminiToolClient:
    """
    Drop-in replacement for anthropic.Anthropic() that routes to Gemini.
    Supports the same .messages.create() interface including tool calling.
    """
    def __init__(self):
        self.messages = _GeminiMessages()
```

### Key Constraints
- `import json` is already at the top of gemini_client.py — if not, add it
- `GeminiUsage` class already exists in the file (line 35) — reuse it
- `_get_client()` already exists (line 24) — reuse it
- `types.Part.from_function_call` and `types.Part.from_function_response` need the `id` parameter — Gemini SDK supports this
- The `automatic_function_calling` config MUST be set to `disable=True` — otherwise Gemini will try to auto-execute functions
- The `hashlib` import for tool ID generation is a fallback — Gemini should provide its own IDs in newer SDK versions

### Verification
Unit test (run locally):
```python
from orchestrator.gemini_client import GeminiToolClient
client = GeminiToolClient()
# Should not crash on import
print("GeminiToolClient loaded OK")
```

---

## Part 2: Agent loop — pick client based on model

### Problem
Both `run_agent_loop` and `run_agent_loop_streaming` hardcode `claude = anthropic.Anthropic(...)`. Need to branch based on model.

### Implementation

**File: `orchestrator/agent.py`**

#### Change 1: `run_agent_loop` (line ~1698)

Replace:
```python
    claude = anthropic.Anthropic(api_key=config.claude.api_key)
```

With:
```python
    from orchestrator.gemini_client import is_gemini_model, GeminiToolClient
    _effective_model = model_override if model_override else config.claude.model
    if is_gemini_model(_effective_model):
        claude = GeminiToolClient()
    else:
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
```

Note: `run_agent_loop` doesn't currently have a `model_override` parameter. Check the function signature — if it doesn't have one, this is only needed in `run_agent_loop_streaming` (which does have it). Skip this change if `run_agent_loop` has no `model_override`.

#### Change 2: `run_agent_loop_streaming` (line ~1906)

Replace:
```python
    claude = anthropic.Anthropic(api_key=config.claude.api_key)
```

With:
```python
    from orchestrator.gemini_client import is_gemini_model, GeminiToolClient
    _effective_model = model_override if model_override else config.claude.model
    if is_gemini_model(_effective_model):
        claude = GeminiToolClient()
    else:
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
```

#### Change 3: Add `"name"` to tool_result (line ~2083)

The tool_result dict needs the function name for Gemini's `Part.from_function_response`. Add the name field:

Replace:
```python
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result_text,
                })
```

With:
```python
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "name": tu.name,
                    "content": result_text,
                })
```

The Anthropic API ignores extra keys, so this is backward-compatible for Opus calls.

#### Apply the same `"name"` change in `run_agent_loop` (non-streaming)

Find the equivalent `tool_results.append(...)` block in `run_agent_loop` and add `"name": tu.name` there too.

### Key Constraints
- `_force_synthesis()` receives `claude` (the client) as its first arg. If model is Gemini, it will use `GeminiToolClient.messages.create()` WITHOUT tools — this must work. The `_GeminiMessages.create()` handles `tools=None` correctly (no function declarations, plain text generation).
- The `extra_headers` kwarg in some calls (like pipeline) is Anthropic-specific. `_GeminiMessages.create()` accepts `**kwargs` and ignores unknown params.
- Keep `import anthropic` at the top of agent.py — still needed for Opus path.

---

## Part 3: Config — switch fast_model to Flash

### Implementation

**File: `config/settings.py`, line 314**

Replace:
```python
    fast_model: str = "claude-haiku-4-5-20251001"
```

With:
```python
    fast_model: str = "gemini-2.5-flash"
```

### Key Constraints
- `deep_model: str = "claude-opus-4-6"` stays unchanged (line 315)
- The complexity router at `dashboard.py:6812` passes `_cc.fast_model` as `model_override` — this will now be `"gemini-2.5-flash"`, which triggers the `GeminiToolClient` path

---

## Files Modified
- `orchestrator/gemini_client.py` — New `GeminiToolClient` class (~120 lines)
- `orchestrator/agent.py` — Client selection (4 lines × 2 functions) + tool_result name (1 line × 2 functions)
- `config/settings.py` — `fast_model` → `"gemini-2.5-flash"` (1 line)

## Do NOT Touch
- `orchestrator/agent.py` — Opus agent loop logic, tool execution, streaming, synthesis
- `orchestrator/capability_runner.py` — Uses `self.claude` for Opus (separate client)
- `orchestrator/pipeline.py` — Has its own Gemini routing already
- `outputs/*` — Frontend code

## Quality Checkpoints
1. `python3 -c "import py_compile; py_compile.compile('orchestrator/gemini_client.py', doraise=True)"`
2. `python3 -c "import py_compile; py_compile.compile('orchestrator/agent.py', doraise=True)"`
3. `python3 -c "import py_compile; py_compile.compile('config/settings.py', doraise=True)"`
4. **CRITICAL TEST**: Dashboard → Ask Baker → "How many active deadlines do I have?" — this is a fast-path question that uses `query_baker_data` tool. Should return a count, not crash.
5. Dashboard → Ask Baker → "What's Edita's email?" — fast-path with `get_contact` tool. Should return contact info.
6. Dashboard → Ask Baker → "Analyze the Hagenauer situation in depth" — deep-path, should STILL use Opus (not affected by this change).
7. Check cost logs: `SELECT model, source, COUNT(*) FROM api_cost_log WHERE logged_at >= NOW() - INTERVAL '1 hour' AND source = 'agent_loop_streaming' GROUP BY model, source` — should show `gemini-2.5-flash` calls for fast-path questions.
8. Verify `_force_synthesis` works with GeminiToolClient — fast-path timeout should produce a synthesis, not crash.

## Rollback
If Gemini tool calling misbehaves:
1. Change `config/settings.py` back: `fast_model: str = "claude-haiku-4-5-20251001"`
2. Deploy — instant rollback, GeminiToolClient code stays but is never called

The `GeminiToolClient` class is inert when not used — no need to remove it.

## Cost Impact
- Fast-path agent calls: ~30% of Ask Baker queries × ~5 calls/day × Haiku cost (~€0.01/call)
- Savings: ~€0.5-1/month (tiny — but quality improvement matters more than cost here)
- The real value: Flash is a better model than Haiku for tool-calling, so fast-path answers should improve

## Verification SQL
```sql
-- After 24h: confirm fast-path uses Flash
SELECT model, COUNT(*) as calls, ROUND(SUM(cost_eur)::numeric, 4) as cost_eur
FROM api_cost_log
WHERE source = 'agent_loop_streaming'
  AND logged_at >= NOW() - INTERVAL '1 day'
GROUP BY model
ORDER BY calls DESC;
-- Expected: gemini-2.5-flash rows appear alongside claude-opus-4-6
```
