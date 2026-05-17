"""Grok MCP tools — X-search, web-search, ask.

Three MCP tools backed by ``kbl.grok_client``:

    - baker_grok_x_search   — X/Twitter Live Search
    - baker_grok_web_search — open-web Live Search (web + news sources)
    - baker_grok_ask        — plain Grok Responses-API call (no Live Search)

All three resolve to ``POST /v1/responses`` on the xAI API. The X / web split
exists at the MCP-tool surface for matter-Desk clarity; the underlying client
parameterizes ``search_parameters.sources`` per call (one endpoint, three
intents).

The HTTP client is built lazily on first dispatch and cached at module level
so its httpx connection pool is reused across MCP dispatches.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Optional

from mcp.types import Tool

from kbl import grok_client as _client_mod


logger = logging.getLogger("baker.tools.grok")


# ─────────────────────────── module-level client cache ───────────────────────────


_CLIENT: Optional[_client_mod.GrokClient] = None
_CLIENT_LOCK = threading.Lock()


def _get_client() -> _client_mod.GrokClient:
    """Lazy module-level GrokClient cache.

    Thread-safe via double-checked locking; ``XAI_API_KEY`` is still read at
    first call so missing-env failures surface at dispatch (visible to the
    caller) rather than at module import.
    """
    global _CLIENT
    if _CLIENT is None:
        with _CLIENT_LOCK:
            if _CLIENT is None:
                _CLIENT = _client_mod.GrokClient()
    return _CLIENT


def _reset_client_for_tests() -> None:
    """Drop the cached client (test hook only)."""
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is not None:
            try:
                _CLIENT.close()
            except Exception:
                pass
        _CLIENT = None


# ─────────────────────────── tool catalog ───────────────────────────


GROK_TOOLS: list[Tool] = [
    Tool(
        name="baker_grok_x_search",
        description=(
            "Search X/Twitter via xAI Grok Live Search. Returns Grok's "
            "summary of the result set plus a structured list of tweet "
            "citations (url, author, date, text, engagement). Replaces the "
            "fragile Chrome-MCP port-9222 X path and the Director-manual-Grok "
            "workaround. Use for: tweet lookups, X-trend monitoring, "
            "counterparty social-signal sweeps."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "X search query (natural language).",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max tweet citations to surface (default 10).",
                    "default": 10,
                },
                "from_date": {
                    "type": "string",
                    "description": "ISO-8601 lower bound YYYY-MM-DD (optional).",
                },
                "to_date": {
                    "type": "string",
                    "description": "ISO-8601 upper bound YYYY-MM-DD (optional).",
                },
                "matter_slug": {
                    "type": "string",
                    "description": "Matter slug for cost attribution (optional).",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="baker_grok_web_search",
        description=(
            "Search the open web via xAI Grok Live Search (web + news sources). "
            "Returns Grok's summary plus structured citations (url, title, "
            "date, snippet). Parallel to baker_perplexity_ask — both stay live; "
            "Grok is preferred when the query needs combined X + web signal or "
            "when caller wants tweet metadata alongside web hits."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Web search query.",
                },
                "freshness_days": {
                    "type": "integer",
                    "description": (
                        "Restrict results to the last N days (default 7). Set "
                        "to 0 or omit to skip the freshness window."
                    ),
                    "default": 7,
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max citations to surface (default 10).",
                    "default": 10,
                },
                "include_news": {
                    "type": "boolean",
                    "description": "Include the news source in addition to web (default true).",
                    "default": True,
                },
                "matter_slug": {
                    "type": "string",
                    "description": "Matter slug for cost attribution (optional).",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="baker_grok_ask",
        description=(
            "Plain Grok Responses-API call (no Live Search). Returns Grok's "
            "text answer plus token + cost metadata. Use for general reasoning "
            "on the matter Desk side when the prompt does NOT need real-time "
            "X / web data. Default model grok-4.3; pass model='grok-4.20-0309-reasoning' "
            "for the heavy reasoning variant."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Grok input prompt.",
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Max output tokens (default 4000).",
                    "default": 4000,
                },
                "model": {
                    "type": "string",
                    "description": "Override model id (default grok-4.3).",
                },
                "instructions": {
                    "type": "string",
                    "description": "Optional system-prompt-style instructions.",
                },
                "matter_slug": {
                    "type": "string",
                    "description": "Matter slug for cost attribution (optional).",
                },
            },
            "required": ["prompt"],
        },
    ),
]


GROK_TOOL_NAMES: frozenset[str] = frozenset(t.name for t in GROK_TOOLS)


# ─────────────────────────── dispatch ───────────────────────────


def dispatch_grok(name: str, args: dict[str, Any]) -> str:
    """Dispatch a Grok MCP tool call. Returns a JSON string for downstream use.

    Errors are caught here and surfaced as ``Error: <message>`` text so callers
    don't need Grok-specific exception handling. Per repo hard rule: fault-
    tolerant or it doesn't ship.

    Cost-governor wiring: pre-invocation ``check_circuit_breaker`` blocks the
    call if the daily hard-stop has tripped; post-invocation ``log_api_cost``
    attributes usage to the matter_slug (when supplied) for daily aggregation.
    Both wrapped so an instrumentation outage never blocks a real Grok call.
    """
    # Pre-invocation cost gate. Failure to import / DB unavailable → allow
    # the call (fail-open on instrumentation; fail-closed on hard-stop).
    try:
        from orchestrator.cost_monitor import check_circuit_breaker
        allowed, daily_cost_eur = check_circuit_breaker()
        if not allowed:
            return f"Error: cost circuit breaker tripped (daily €{daily_cost_eur:.2f})"
    except Exception:
        logger.exception("dispatch_grok: cost_monitor.check_circuit_breaker failed (allowing call)")

    matter_slug = args.get("matter_slug")
    payload: Optional[dict] = None
    try:
        if name == "baker_grok_x_search":
            payload = _get_client().x_search(
                query=args["query"],
                max_results=int(args.get("max_results", 10)),
                from_date=args.get("from_date"),
                to_date=args.get("to_date"),
            )
            _log_grok_cost(payload, matter_slug)
            return json.dumps(payload, ensure_ascii=False)

        if name == "baker_grok_web_search":
            freshness = args.get("freshness_days", 7)
            if isinstance(freshness, str):
                try:
                    freshness = int(freshness)
                except ValueError:
                    freshness = 7
            if freshness == 0:
                freshness = None
            payload = _get_client().web_search(
                query=args["query"],
                freshness_days=freshness,
                max_results=int(args.get("max_results", 10)),
                include_news=bool(args.get("include_news", True)),
            )
            _log_grok_cost(payload, matter_slug)
            return json.dumps(payload, ensure_ascii=False)

        if name == "baker_grok_ask":
            payload = _get_client().ask(
                prompt=args["prompt"],
                max_output_tokens=int(args.get("max_tokens", 4000)),
                model=args.get("model") or "grok-4.3",
                instructions=args.get("instructions"),
            )
            _log_grok_cost(payload, matter_slug)
            return json.dumps(payload, ensure_ascii=False)

        return f"Error: unknown Grok tool: {name}"

    except KeyError as e:
        return f"Error: missing required arg: {e.args[0]}"
    except _client_mod.GrokError as e:
        return f"Error: Grok: {e}"
    except Exception as e:
        # Generic catch per repo's fault-tolerant rule. Log full traceback so
        # programming errors (AttributeError, TypeError) don't go invisible.
        logger.exception("dispatch_grok: unhandled error in %s", name)
        return f"Error: {type(e).__name__}: {e}"


def _log_grok_cost(payload: dict, matter_slug: Optional[str]) -> None:
    """Attribute the Grok call's token usage via cost_monitor.

    Wrapped so a logging failure never blocks the caller from seeing the
    Grok payload. ``payload`` is the dict returned by GrokClient.{ask,
    x_search, web_search} — token fields are normalized in _shape_*.
    """
    try:
        from orchestrator.cost_monitor import log_api_cost
        log_api_cost(
            model=payload.get("model") or "grok-4.3",
            input_tokens=int(payload.get("tokens_in") or 0),
            output_tokens=int(payload.get("tokens_out") or 0),
            source="grok_realtime",
            matter_slug=matter_slug,
        )
    except Exception:
        logger.exception("dispatch_grok: cost_monitor.log_api_cost failed (non-fatal)")
