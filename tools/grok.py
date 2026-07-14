"""Grok MCP tools — X-search, web-search, ask.

Three MCP tools backed by ``kbl.grok_client``:

    - baker_grok_x_search   — X/Twitter search via xAI Agent Tools API
    - baker_grok_web_search — open-web search via xAI Agent Tools API
    - baker_grok_ask        — plain Grok Responses-API call (no tool use)

All three resolve to ``POST /v1/responses`` on the xAI API. The X / web split
exists at the MCP-tool surface for matter-Desk clarity; the underlying client
selects ``tools=[{type:'x_search', ...}]`` vs ``[{type:'web_search', ...}]``
per call (one endpoint, three intents). The earlier Live Search /
``search_parameters`` dict form was server-side deprecated 2026-05.

The HTTP client is built lazily on first dispatch and cached at module level
so its httpx connection pool is reused across MCP dispatches.

Key rotation
------------
``GrokClient.__init__`` reads ``XAI_API_KEY`` once at construction and stores it
on the instance. After rotating the key on Render (e.g. ``op item edit`` →
Render env-var PUT via ``tools.render_env_guard.safe_env_put``), call
:func:`reset_client_cache` to drop the cached client so the next dispatch
re-reads the fresh env var. Worker restart is the heavier alternative; the
reset hook avoids the restart and survives concurrent dispatches via the
``_CLIENT_LOCK`` double-checked guard. Callable from any admin entrypoint or
one-shot Render shell::

    python3 -c "from tools.grok import reset_client_cache; reset_client_cache()"
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


def reset_client_cache() -> None:
    """Drop the cached GrokClient. Call after rotating ``XAI_API_KEY`` on Render
    so the next dispatch rebuilds the client and reads the fresh env var.

    Safe to call from any thread; no-op if no client is cached. Closing the
    httpx pool of the prior client is best-effort — a close failure does not
    prevent the cache from being cleared.
    """
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is not None:
            try:
                _CLIENT.close()
            except Exception:
                pass
        _CLIENT = None


# Backwards-compat alias for any external callers that imported the underscore
# name. Identity-preserving (``is`` check passes) so monkeypatches survive.
_reset_client_for_tests = reset_client_cache


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
                "from_date": {
                    "type": "string",
                    "description": "ISO-8601 lower bound YYYY-MM-DD (optional).",
                },
                "to_date": {
                    "type": "string",
                    "description": "ISO-8601 upper bound YYYY-MM-DD (optional).",
                },
                "allowed_x_handles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Restrict to specific X handles (max 10, mutex with excluded_x_handles).",
                },
                "excluded_x_handles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Block specific X handles (max 10, mutex with allowed_x_handles).",
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
                        "wall-clock: total wall-clock ≈ timeout × max_retries + "
                        "Retry-After × max_retries (up to ~120s with defaults). "
                        "Wrap in your own deadline if you need a hard upper bound."
                    ),
                    "minimum": 1,
                    "maximum": 300,
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
                "allowed_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Restrict search to specific domains (max 5).",
                },
                "excluded_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Block specific domains from search (max 5).",
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
                        "wall-clock: total wall-clock ≈ timeout × max_retries + "
                        "Retry-After × max_retries (up to ~120s with defaults). "
                        "Wrap in your own deadline if you need a hard upper bound."
                    ),
                    "minimum": 1,
                    "maximum": 300,
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
            "X / web data. Default model grok-4.3. Pass a trial `route` "
            "(GROK_4_5_WEEK_TRIAL) to run the governed grok-4.5 path with weekly "
            "reservation ledger + per-call audit; grok-4.5 is trial-only and "
            "reachable ONLY through an enabled route."
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
                "route": {
                    "type": "string",
                    "description": (
                        "Trial route key (GROK_4_5_WEEK_TRIAL). When listed in "
                        "GROK45_ENABLED_ROUTES the call runs grok-4.5 under the "
                        "weekly reservation ledger. Known: b4_runtime, "
                        "researcher_channel, researcher_shadow_synth. Omit for a "
                        "normal grok-4.3 call."
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
                        "wall-clock: total wall-clock ≈ timeout × max_retries + "
                        "Retry-After × max_retries (up to ~120s with defaults). "
                        "Wrap in your own deadline if you need a hard upper bound."
                    ),
                    "minimum": 1,
                    "maximum": 300,
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

    # Per-call HTTP timeout override (M3). Capped at 300s here — the client
    # is reusable in non-MCP contexts where higher timeouts may be legitimate,
    # so the cap lives at the dispatcher, not in GrokClient. None = inherit
    # the client's per-instance default (60s).
    timeout, timeout_err = _validate_timeout_seconds(args.get("timeout_seconds"))
    if timeout_err is not None:
        return timeout_err

    payload: Optional[dict] = None
    try:
        if name == "baker_grok_x_search":
            payload = _get_client().x_search(
                query=args["query"],
                from_date=args.get("from_date"),
                to_date=args.get("to_date"),
                allowed_x_handles=args.get("allowed_x_handles"),
                excluded_x_handles=args.get("excluded_x_handles"),
                timeout=timeout,
            )
            _log_grok_cost(payload, matter_slug)
            return json.dumps(payload, ensure_ascii=False)

        if name == "baker_grok_web_search":
            payload = _get_client().web_search(
                query=args["query"],
                allowed_domains=args.get("allowed_domains"),
                excluded_domains=args.get("excluded_domains"),
                timeout=timeout,
            )
            _log_grok_cost(payload, matter_slug)
            return json.dumps(payload, ensure_ascii=False)

        if name == "baker_grok_ask":
            route = (args.get("route") or "").strip() or None
            requested_model = args.get("model")
            from orchestrator import xai_trial_route as _trial

            # Enter the trial governor for a route that is ENABLED or UNKNOWN.
            # run_grok_ask is the SINGLE rejection point (codex #11381): it writes
            # exactly one xai_call_audit row per attempt — including the
            # blocked_route_unknown row for an unknown route — then raises
            # GrokTrialError, which we surface loud with NO fallback. Routing the
            # unknown case through here (rather than an early dispatcher return)
            # keeps requirement #4 intact: no attempt goes un-audited, and no path
            # writes a double row. A route that is KNOWN but simply not enabled is
            # the designed grok-4.3 fallthrough below (not a trial attempt → no
            # audit row). No route param → normal path untouched. The trial governor
            # logs cost + audit itself, so we do NOT double-log via _log_grok_cost.
            if route is not None and (
                _trial.is_route_enabled(route) or not _trial.is_route_known(route)
            ):
                try:
                    payload = _trial.run_grok_ask(
                        client=_get_client(),
                        prompt=args["prompt"],
                        route=route,
                        max_output_tokens=int(args.get("max_tokens", 4000)),
                        instructions=args.get("instructions"),
                        model=requested_model,
                        matter_slug=matter_slug,
                        timeout=timeout,
                    )
                    return json.dumps(payload, ensure_ascii=False)
                except _trial.GrokTrialError as e:
                    # Fail loud with route + cause + spend; NO fallback model.
                    return "Error: grok trial blocked: " + json.dumps(e.info, ensure_ascii=False)

            # grok-4.5 is trial-only — never reachable off a governed route.
            if requested_model == _trial.TRIAL_MODEL:
                return (
                    "Error: grok-4.5 is trial-only (GROK_4_5_WEEK_TRIAL); invoke via an "
                    "enabled route in GROK45_ENABLED_ROUTES, not a raw model override"
                )

            payload = _get_client().ask(
                prompt=args["prompt"],
                max_output_tokens=int(args.get("max_tokens", 4000)),
                model=requested_model or "grok-4.3",
                instructions=args.get("instructions"),
                timeout=timeout,
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


_TIMEOUT_ERR = "Error: timeout_seconds must be a positive number ≤ 300"


def _validate_timeout_seconds(value: Any) -> tuple[Optional[float], Optional[str]]:
    """Validate the MCP-facing ``timeout_seconds`` arg.

    Returns ``(timeout, None)`` on success (``timeout`` may be ``None`` when
    the caller omitted the arg) or ``(None, error_string)`` on rejection.
    Booleans are rejected on purpose — ``True`` would otherwise coerce to 1.0
    and silently mask a caller bug.
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
