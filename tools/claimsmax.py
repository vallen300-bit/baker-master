"""ClaimsMax MCP tools — search, investigate, ask, and render outputs.

Eight MCP tools backed by ``kbl.claimsmax_client`` and ``kbl.report_renderer``:

    Read / search:
      - baker_claimsmax_search
      - baker_claimsmax_investigate
      - baker_claimsmax_check_investigation
      - baker_claimsmax_get_document

    Ask synthesis:
      - baker_claimsmax_ask                   (RAG-grounded answer + citations)

    Investigation output flow:
      - baker_claimsmax_save_investigation    (always; cheap default)
      - baker_claimsmax_convert_to_pdf        (Director-gated)
      - baker_claimsmax_convert_to_html       (Director-gated)

The renderer tools follow the Director-ratified 2026-05-17 amendment to
CLAIMSMAX_API_CAPABILITY_1: save raw JSON by default, only convert when the
Director explicitly instructs the matter Desk to convert. No auto-render
heuristic.

Importing this module is cheap — neither the HTTP client nor the renderer
touches the network or filesystem at import time. The HTTP client is built
lazily on first dispatch and cached at module level so its connection pool
is reused across MCP calls (matters during /investigate polling).
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Optional

from mcp.types import Tool

from kbl import claimsmax_client as _client_mod
from kbl import report_renderer as _renderer_mod


logger = logging.getLogger("baker.tools.claimsmax")


# ─────────────────────────── module-level client cache ───────────────────────────


_CLIENT: Optional[_client_mod.ClaimsmaxClient] = None
_CLIENT_LOCK = threading.Lock()


def _get_client() -> _client_mod.ClaimsmaxClient:
    """Lazy module-level ClaimsmaxClient cache.

    A fresh client was previously instantiated for every MCP dispatch — for
    /investigate runs that triggered dozens of redundant TLS handshakes
    against ClaimsMax. One cached instance reuses the pooled httpx
    connection across all dispatches in the process.

    Thread-safe via double-checked locking; ``CLAIMSMAX_API_KEY`` is still
    read at first call so missing-env failures surface at dispatch (visible
    to the caller) rather than at module import.
    """
    global _CLIENT
    if _CLIENT is None:
        with _CLIENT_LOCK:
            if _CLIENT is None:
                _CLIENT = _client_mod.ClaimsmaxClient()
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


CLAIMSMAX_TOOLS: list[Tool] = [
    Tool(
        name="baker_claimsmax_search",
        description=(
            "Search the ClaimsMax document archive (187K docs / 173K emails / "
            "1.4M chunks; Hagenauer/RG7 / MO Vie / Brisen Development / Cupial "
            "corpora). Hybrid full-text + semantic; supports natural / boolean / "
            "proximity modes plus filter dict (l1/l2/l3_tags/date_from/date_to/...)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query text."},
                "filters": {
                    "type": "object",
                    "description": "Optional filter dict — keys per ClaimsMax /search spec (l1, l2, l3_tags, date_from, date_to, extensions, persons, organisations, ...).",
                },
                "mode": {
                    "type": "string",
                    "description": "Search mode: natural | boolean | proximity.",
                    "default": "natural",
                },
                "per_page": {
                    "type": "integer",
                    "description": "Results per page (default 25).",
                    "default": 25,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="baker_claimsmax_investigate",
        description=(
            "Start a multi-step ClaimsMax investigation (fire-and-forget). "
            "Returns {run_id, status}; poll status with baker_claimsmax_check_investigation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Investigation prompt."},
                "language": {
                    "type": "string",
                    "description": "Final-report language: en | de.",
                    "default": "en",
                },
                "starting_doc_id": {
                    "type": "string",
                    "description": "Optional anchor doc id.",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="baker_claimsmax_check_investigation",
        description=(
            "Poll the status of a ClaimsMax investigation run. Returns "
            "{status, step_count, title, report, error}. status flips to 'complete' "
            "when the report markdown is ready."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "string",
                    "description": "Run id returned by baker_claimsmax_investigate.",
                },
            },
            "required": ["run_id"],
        },
    ),
    Tool(
        name="baker_claimsmax_get_document",
        description=(
            "Fetch full ClaimsMax document metadata; optionally include the "
            "extracted text body."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "doc_id": {"type": "string", "description": "Document UUID or sha256."},
                "include_text": {
                    "type": "boolean",
                    "description": "Include extracted_text in the response (default false).",
                    "default": False,
                },
            },
            "required": ["doc_id"],
        },
    ),
    Tool(
        name="baker_claimsmax_ask",
        description=(
            "RAG-grounded synthesis against the ClaimsMax corpus. Returns "
            "{answer, citations, used_chunks, confidence, retrieval, ...}. "
            "Answer markdown carries inline [D1]-style refs into the citations "
            "list. Use for single-shot Q&A; investigations remain the right tool "
            "for multi-step research. Optional claim_id narrows the corpus."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Natural-language question."},
                "claim_id": {
                    "type": "string",
                    "description": "Optional ClaimsMax claim id to scope retrieval.",
                },
                "language": {
                    "type": "string",
                    "description": "Answer language: en | de.",
                    "enum": ["en", "de"],
                    "default": "en",
                },
            },
            "required": ["question"],
        },
    ),
    Tool(
        name="baker_claimsmax_save_investigation",
        description=(
            "Persist a completed ClaimsMax investigation's final state as JSON in "
            "the matter's Dropbox research folder. Cheap default; run after every "
            "investigation completes. Returns the absolute file path."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Investigation run id."},
                "matter_slug": {
                    "type": "string",
                    "description": "Matter folder under 1_ACTIVE_PROJECTS/ (e.g. 'mo-vie', 'hagenauer-rg7').",
                },
                "topic_slug": {
                    "type": "string",
                    "description": "Short kebab-case topic name embedded in the filename.",
                },
            },
            "required": ["run_id", "matter_slug", "topic_slug"],
        },
    ),
    Tool(
        name="baker_claimsmax_convert_to_pdf",
        description=(
            "Convert an investigation JSON into a PDF sibling. Run ONLY when "
            "Director instructs the matter Desk to convert. Requires pandoc on the "
            "host runtime."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "json_path": {
                    "type": "string",
                    "description": "Absolute path to the investigation JSON (output of baker_claimsmax_save_investigation).",
                },
            },
            "required": ["json_path"],
        },
    ),
    Tool(
        name="baker_claimsmax_convert_to_html",
        description=(
            "Convert an investigation JSON into a standalone HTML under "
            "docs-site/<matter>/. Run ONLY when Director instructs. Caller commits "
            "+ pushes docs-site so Render publishes the page. Requires pandoc."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "json_path": {
                    "type": "string",
                    "description": "Absolute path to the investigation JSON.",
                },
            },
            "required": ["json_path"],
        },
    ),
]


CLAIMSMAX_TOOL_NAMES: frozenset[str] = frozenset(t.name for t in CLAIMSMAX_TOOLS)


# ─────────────────────────── dispatch ───────────────────────────


def dispatch_claimsmax(name: str, args: dict[str, Any]) -> str:
    """Dispatch a ClaimsMax MCP tool call. Returns a JSON string for downstream
    use (uniformly machine-readable; matches the rest of the Baker MCP surface
    via str output of structured payloads).

    Errors are caught here and surfaced as ``Error: <message>`` text so callers
    don't need ClaimsMax-specific exception handling. Per repo hard rule:
    fault-tolerant or it doesn't ship.
    """
    try:
        if name == "baker_claimsmax_search":
            payload = _get_client().search(
                query=args["query"],
                filters=args.get("filters"),
                mode=args.get("mode", "natural"),
                per_page=args.get("per_page", 25),
            )
            return _format_search_result(payload)

        if name == "baker_claimsmax_investigate":
            payload = _get_client().investigate_start(
                query=args["query"],
                language=args.get("language", "en"),
                starting_doc_id=args.get("starting_doc_id"),
            )
            return json.dumps(payload, ensure_ascii=False)

        if name == "baker_claimsmax_check_investigation":
            payload = _get_client().investigate_status(args["run_id"])
            return json.dumps(payload, ensure_ascii=False)

        if name == "baker_claimsmax_get_document":
            payload = _get_client().get_document(
                args["doc_id"],
                include_text=args.get("include_text", False),
            )
            return json.dumps(payload, ensure_ascii=False)

        if name == "baker_claimsmax_ask":
            payload = _get_client().ask(
                question=args["question"],
                claim_id=args.get("claim_id"),
                language=args.get("language", "en"),
            )
            return json.dumps(payload, ensure_ascii=False)

        if name == "baker_claimsmax_save_investigation":
            path = _renderer_mod.save_investigation_json(
                run_id=args["run_id"],
                matter_slug=args["matter_slug"],
                topic_slug=args["topic_slug"],
                client=_get_client(),
            )
            return json.dumps({"json_path": path}, ensure_ascii=False)

        if name == "baker_claimsmax_convert_to_pdf":
            path = _renderer_mod.convert_to_pdf(args["json_path"])
            return json.dumps({"pdf_path": path}, ensure_ascii=False)

        if name == "baker_claimsmax_convert_to_html":
            path = _renderer_mod.convert_to_html(args["json_path"])
            return json.dumps({"html_path": path}, ensure_ascii=False)

        return f"Error: unknown ClaimsMax tool: {name}"

    except KeyError as e:
        return f"Error: missing required arg: {e.args[0]}"
    except _client_mod.ClaimsmaxError as e:
        return f"Error: ClaimsMax: {e}"
    except _renderer_mod.RendererError as e:
        return f"Error: renderer: {e}"
    except Exception as e:
        # Generic catch is the last line of defence per repo's fault-tolerant
        # rule; programming errors (AttributeError, TypeError) get swallowed
        # here too, so log the full traceback before stringifying so prod
        # bugs aren't invisible.
        logger.exception("dispatch_claimsmax: unhandled error in %s", name)
        return f"Error: {type(e).__name__}: {e}"


# ─────────────────────────── formatting ───────────────────────────


def _format_search_result(payload: dict[str, Any]) -> str:
    """Trim the /search response to a slim, MCP-friendly JSON projection."""
    results = payload.get("results") or []
    slim_results = [
        {
            "doc_id": r.get("doc_id"),
            "filename": r.get("filename"),
            "doc_date": r.get("doc_date"),
            "l1": r.get("l1"),
            "l2": r.get("l2"),
            # l3 mirrors the l3_tags_required filter — agents that pass the
            # filter want to see which l3 tags the hit actually carries so
            # they can rank or follow-up. Dropping it silently in the slim
            # projection forced a second get_document round-trip per hit.
            "l3": r.get("l3"),
            "snippet": r.get("snippet"),
            "score": r.get("score"),
        }
        for r in results
    ]
    out = {
        "total": payload.get("total"),
        "page": payload.get("page"),
        "per_page": payload.get("per_page"),
        "query_ms": payload.get("query_ms"),
        "results": slim_results,
    }
    return json.dumps(out, ensure_ascii=False)
