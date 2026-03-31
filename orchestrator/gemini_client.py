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
