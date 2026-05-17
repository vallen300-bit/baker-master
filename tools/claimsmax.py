"""ClaimsMax MCP tools — search, investigate, and render outputs.

Seven MCP tools backed by ``kbl.claimsmax_client`` and ``kbl.report_renderer``:

    Read / search:
      - baker_claimsmax_search
      - baker_claimsmax_investigate
      - baker_claimsmax_check_investigation
      - baker_claimsmax_get_document

    Investigation output flow:
      - baker_claimsmax_save_investigation    (always; cheap default)
      - baker_claimsmax_convert_to_pdf        (Director-gated)
      - baker_claimsmax_convert_to_html       (Director-gated)

The renderer tools follow the Director-ratified 2026-05-17 amendment to
CLAIMSMAX_API_CAPABILITY_1: save raw JSON by default, only convert when the
Director explicitly instructs the matter Desk to convert. No auto-render
heuristic.

Importing this module is cheap — neither the HTTP client nor the renderer
touches the network or filesystem at import time.
"""
from __future__ import annotations

import json
from typing import Any

from mcp.types import Tool

from kbl import claimsmax_client as _client_mod
from kbl import report_renderer as _renderer_mod


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
            client = _client_mod.ClaimsmaxClient()
            payload = client.search(
                query=args["query"],
                filters=args.get("filters"),
                mode=args.get("mode", "natural"),
                per_page=args.get("per_page", 25),
            )
            return _format_search_result(payload)

        if name == "baker_claimsmax_investigate":
            client = _client_mod.ClaimsmaxClient()
            payload = client.investigate_start(
                query=args["query"],
                language=args.get("language", "en"),
                starting_doc_id=args.get("starting_doc_id"),
            )
            return json.dumps(payload, ensure_ascii=False)

        if name == "baker_claimsmax_check_investigation":
            client = _client_mod.ClaimsmaxClient()
            payload = client.investigate_status(args["run_id"])
            return json.dumps(payload, ensure_ascii=False)

        if name == "baker_claimsmax_get_document":
            client = _client_mod.ClaimsmaxClient()
            payload = client.get_document(
                args["doc_id"],
                include_text=args.get("include_text", False),
            )
            return json.dumps(payload, ensure_ascii=False)

        if name == "baker_claimsmax_save_investigation":
            path = _renderer_mod.save_investigation_json(
                run_id=args["run_id"],
                matter_slug=args["matter_slug"],
                topic_slug=args["topic_slug"],
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
