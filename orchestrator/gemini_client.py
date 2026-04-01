"""
Gemini client wrapper — GEMINI-MIGRATION-1
Provides Claude-compatible interface for Gemini Flash/Pro models.
Drop-in replacement for Haiku/Sonnet call sites.

Usage:
    from orchestrator.gemini_client import call_flash, call_pro, is_gemini_model

    resp = call_flash(messages=[{"role": "user", "content": "..."}], max_tokens=2000)
    text = resp.text
    tokens_in = resp.usage.input_tokens
"""
import logging
import os

from config.settings import config

logger = logging.getLogger("baker.gemini_client")

# Lazy singleton
_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai
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
    from google.genai import types

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
                    import base64 as b64
                    src = part.get("source", {})
                    parts.append(types.Part.from_bytes(
                        data=b64.b64decode(src["data"]),
                        mime_type=src.get("media_type", "image/jpeg"),
                    ))
                else:
                    parts.append(str(part))
            contents.append(types.Content(role=role, parts=[
                types.Part.from_text(text=p) if isinstance(p, str) else p
                for p in parts
            ]))
        else:
            contents.append(types.Content(
                role=role,
                parts=[types.Part.from_text(text=str(content))],
            ))

    # Build config
    gen_config = types.GenerateContentConfig(
        max_output_tokens=max_tokens,
    )
    if system:
        gen_config.system_instruction = system

    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=gen_config,
        )

        text = response.text or ""
        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0 if usage else 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0 if usage else 0

        return GeminiResponse(text, input_tokens, output_tokens)

    except Exception as e:
        logger.error(f"Gemini API error ({model}): {e}")
        raise


def call_flash(messages: list, max_tokens: int = 2000, system: str = None) -> GeminiResponse:
    """Convenience: call Gemini Flash (workhorse tier)."""
    return generate(config.gemini.flash_model, messages, max_tokens, system)


def call_pro(messages: list, max_tokens: int = 2000, system: str = None) -> GeminiResponse:
    """Convenience: call Gemini Pro (mid tier)."""
    return generate(config.gemini.pro_model, messages, max_tokens, system)


def is_gemini_model(model: str) -> bool:
    """Check if a model string is a Gemini model."""
    return model.startswith("gemini-")


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
        import json
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
