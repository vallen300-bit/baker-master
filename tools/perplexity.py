"""Perplexity MCP tool — cited web-grounded ask.

One MCP tool backed by ``kbl.perplexity_client``:

    - baker_perplexity_ask — a single Perplexity Sonar call that returns a cited
      answer (text + structured citations)

``baker_perplexity_ask`` is a metered LLM call (POST /chat/completions on
api.perplexity.ai), so it MUST route through this governed dispatcher — never a
direct client construction — to inherit the SAME cost circuit-breaker +
usage-logging + timeout validation as every other metered caller (the G0 #2391
lesson: an ALLOW-class tool that bypasses the cost governor is a blocking finding).

The HTTP client is built lazily on first dispatch and cached at module level so
its httpx connection pool is reused across MCP dispatches.

Key rotation
------------
``PerplexityClient.__init__`` reads ``PERPLEXITY_API_KEY`` once at construction.
After rotating the key on Render, call :func:`reset_client_cache` to drop the
cached client so the next dispatch re-reads the fresh env var (mirrors
``tools.grok.reset_client_cache``)::

    python3 -c "from tools.perplexity import reset_client_cache; reset_client_cache()"
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Optional

from mcp.types import Tool

from kbl import perplexity_client as _client_mod


logger = logging.getLogger("baker.tools.perplexity")


# ─────────────────────────── module-level client cache ───────────────────────────


_CLIENT: Optional[_client_mod.PerplexityClient] = None
_CLIENT_LOCK = threading.Lock()


def _get_client() -> _client_mod.PerplexityClient:
    """Lazy module-level PerplexityClient cache.

    Thread-safe via double-checked locking; ``PERPLEXITY_API_KEY`` is still read
    at first call so missing-env failures surface at dispatch (visible to the
    caller) rather than at module import.
    """
    global _CLIENT
    if _CLIENT is None:
        with _CLIENT_LOCK:
            if _CLIENT is None:
                _CLIENT = _client_mod.PerplexityClient()
    return _CLIENT


def reset_client_cache() -> None:
    """Drop the cached PerplexityClient. Call after rotating ``PERPLEXITY_API_KEY``
    on Render so the next dispatch rebuilds the client and reads the fresh env var.

    Safe to call from any thread; no-op if no client is cached. Closing the httpx
    pool of the prior client is best-effort — a close failure does not prevent the
    cache from being cleared.
    """
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is not None:
            try:
                _CLIENT.close()
            except Exception:
                pass
        _CLIENT = None


# Backwards-compat alias for any external callers (identity-preserving so
# monkeypatches survive).
_reset_client_for_tests = reset_client_cache


# ─────────────────────────── tool catalog ───────────────────────────


PERPLEXITY_TOOLS: list[Tool] = [
    Tool(
        name="baker_perplexity_ask",
        description=(
            "Ask Perplexity Sonar a question and get a web-grounded answer with "
            "inline citations. Returns Perplexity's answer text plus a structured "
            "list of cited sources (url, title, date, snippet). Parallel to "
            "baker_grok_web_search — both stay live; prefer Perplexity for a single "
            "synthesized cited answer, Grok when the query needs combined X + web "
            "signal or tweet metadata. Default model 'sonar'; pass model='sonar-pro' "
            "for the deeper variant or 'sonar-reasoning' for chain-of-thought."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The question / prompt to ask Perplexity.",
                },
                "model": {
                    "type": "string",
                    "description": "Override model id (default sonar; sonar-pro / sonar-reasoning available).",
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Max output tokens (default 4000).",
                    "default": 4000,
                },
                "search_domain_filter": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Restrict cited sources to these domains (prefix a domain "
                        "with '-' to block it). Optional."
                    ),
                },
                "instructions": {
                    "type": "string",
                    "description": "Optional system-prompt-style instructions.",
                },
                "matter_slug": {
                    "type": "string",
                    "description": "Matter slug for cost attribution (optional).",
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": (
                        "Per-attempt HTTP timeout in seconds (default 60, max 300). "
                        "Bounds each individual attempt — does NOT bound 429 retry "
                        "wall-clock. Wrap in your own deadline for a hard upper bound."
                    ),
                    "minimum": 1,
                    "maximum": 300,
                },
            },
            "required": ["prompt"],
        },
    ),
]


PERPLEXITY_TOOL_NAMES: frozenset[str] = frozenset(t.name for t in PERPLEXITY_TOOLS)


# ─────────────────────────── dispatch ───────────────────────────


def dispatch_perplexity(name: str, args: dict[str, Any]) -> str:
    """Dispatch a Perplexity MCP tool call. Returns a JSON string for downstream use.

    Errors are caught here and surfaced as ``Error: <message>`` text so callers
    don't need Perplexity-specific exception handling. Per repo hard rule: fault-
    tolerant or it doesn't ship.

    Cost-governor wiring (mirrors dispatch_grok): pre-invocation
    ``check_circuit_breaker`` blocks the call if the daily hard-stop has tripped;
    post-invocation ``log_api_cost`` attributes usage to the matter_slug (when
    supplied) for daily aggregation. Both wrapped so an instrumentation outage
    never blocks a real Perplexity call.
    """
    # Pre-invocation cost gate. Failure to import / DB unavailable → allow the
    # call (fail-open on instrumentation; fail-closed on hard-stop).
    try:
        from orchestrator.cost_monitor import check_circuit_breaker
        allowed, daily_cost_eur = check_circuit_breaker()
        if not allowed:
            return f"Error: cost circuit breaker tripped (daily €{daily_cost_eur:.2f})"
    except Exception:
        logger.exception("dispatch_perplexity: cost_monitor.check_circuit_breaker failed (allowing call)")

    matter_slug = args.get("matter_slug")

    timeout, timeout_err = _validate_timeout_seconds(args.get("timeout_seconds"))
    if timeout_err is not None:
        return timeout_err

    try:
        if name == "baker_perplexity_ask":
            payload = _get_client().ask(
                prompt=args["prompt"],
                model=args.get("model") or "sonar",
                max_tokens=int(args.get("max_tokens", 4000)),
                search_domain_filter=args.get("search_domain_filter"),
                instructions=args.get("instructions"),
                timeout=timeout,
            )
            _log_perplexity_cost(payload, matter_slug)
            return json.dumps(payload, ensure_ascii=False)

        return f"Error: unknown Perplexity tool: {name}"

    except KeyError as e:
        return f"Error: missing required arg: {e.args[0]}"
    except _client_mod.PerplexityError as e:
        return f"Error: Perplexity: {e}"
    except Exception as e:
        # Generic catch per repo's fault-tolerant rule. Log full traceback so
        # programming errors (AttributeError, TypeError) don't go invisible.
        logger.exception("dispatch_perplexity: unhandled error in %s", name)
        return f"Error: {type(e).__name__}: {e}"


_TIMEOUT_ERR = "Error: timeout_seconds must be a positive number ≤ 300"


def _validate_timeout_seconds(value: Any) -> tuple[Optional[float], Optional[str]]:
    """Validate the MCP-facing ``timeout_seconds`` arg.

    Returns ``(timeout, None)`` on success (``timeout`` may be ``None`` when the
    caller omitted the arg) or ``(None, error_string)`` on rejection. Booleans are
    rejected on purpose — ``True`` would otherwise coerce to 1.0 and silently mask
    a caller bug.
    """
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, _TIMEOUT_ERR
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None, _TIMEOUT_ERR
    if v <= 0 or v > 300:
        return None, _TIMEOUT_ERR
    return v, None


def _log_perplexity_cost(payload: dict, matter_slug: Optional[str]) -> None:
    """Attribute the Perplexity call's token usage via cost_monitor.

    Wrapped so a logging failure never blocks the caller from seeing the payload.
    ``payload`` is the dict returned by PerplexityClient.ask — ``model`` keys the
    cost_monitor MODEL_COSTS table (sonar / sonar-pro / sonar-reasoning added in
    PR 2d-2; unknown models fall back to the default rate there).
    """
    try:
        from orchestrator.cost_monitor import log_api_cost
        log_api_cost(
            model=payload.get("model") or "sonar",
            input_tokens=int(payload.get("tokens_in") or 0),
            output_tokens=int(payload.get("tokens_out") or 0),
            source="perplexity_realtime",
            matter_slug=matter_slug,
        )
    except Exception:
        logger.exception("dispatch_perplexity: cost_monitor.log_api_cost failed (non-fatal)")
