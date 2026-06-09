"""Gmail MCP tool surface — search, read message, on-demand attachment read.

Wraps Gmail's messages.list / messages.get / messages.attachments.get as
MCP-callable tools. Reuses _get_gmail_service from triggers.email_trigger
(no new credential surface). Uses helpers from scripts.extract_gmail for
header extraction, body extraction, and attachment-parts walking.

Three tools:
  baker_gmail_search          — search Gmail with full query syntax (READ_3)
  baker_gmail_read_message    — read message body + headers + attachment meta (READ_3)
  baker_gmail_attachment_read — read a single attachment by filename (READ_2)

Anchors:
  BRIEF_GMAIL_ATTACHMENT_READ_2 — Director-ratified 2026-05-24, PR #257.
  BRIEF_GMAIL_SEARCH_AND_READ_1 — Director-ratified 2026-05-25.
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
from typing import Any

from mcp.types import Tool  # type: ignore[import-not-found]

logger = logging.getLogger("baker.tools.gmail")

# M365_MAIL_BLINDSPOT_DIAGNOSE_FIX_1: baker_gmail_* is Gmail-OAuth-only and is
# STRUCTURALLY BLIND to Director's brisengroup.com mail, which migrated to
# Microsoft 365 / Outlook ~2026-06-03. A silent empty here is the failure mode
# that hid a legal-deadline email. Any brisengroup-scoped query, and ANY
# zero-result, now carries a LOUD pointer to baker_email_search so callers never
# read "no Gmail match" as "no mail".
_M365_MIGRATED_DOMAINS = ("brisengroup.com",)
_M365_POINTER = (
    "Director's brisengroup.com mail migrated to Microsoft 365 / Outlook "
    "~2026-06-03 and is NOT on this Gmail surface. For dvallen@brisengroup.com / "
    "Outlook / M365 mail use baker_email_search (provider=store or all), NOT "
    "baker_gmail_search."
)


def _is_brisengroup_scoped(query: str) -> bool:
    q = (query or "").lower()
    return any(dom in q for dom in _M365_MIGRATED_DOMAINS)


GMAIL_TOOLS: list[Tool] = [
    Tool(
        name="baker_gmail_attachment_read",
        description=(
            "Read a single Gmail attachment on-demand by filename. Returns "
            "extracted text (for PDF/DOCX/XLSX/CSV/TXT/MD/JSON) plus optional "
            "base64-encoded raw bytes. Reuses the existing poll-time extraction "
            "pipeline + Gmail service singleton (no new credential surface). "
            "Use when an agent needs to pull a specific named attachment "
            "mid-session without waiting for the poll cycle to index it."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": (
                        "Gmail message ID (from get_thread or search_threads "
                        "response). NOT the thread_id."
                    ),
                },
                "filename": {
                    "type": "string",
                    "description": (
                        "Attachment filename as it appears in the message "
                        "(case-sensitive, exact match). Gmail preserves the "
                        "original filename."
                    ),
                },
                "attachment_index": {
                    "type": "integer",
                    "description": (
                        "1-based index used as a tiebreaker when multiple "
                        "attachments share the same filename. Default 1 "
                        "(first match). If filename matches >1 attachment "
                        "and index is out of range, returns an error listing "
                        "all matches with their indexes."
                    ),
                    "default": 1,
                    "minimum": 1,
                },
                "include_bytes": {
                    "type": "boolean",
                    "description": (
                        "If true, return base64-encoded raw bytes alongside "
                        "extracted text. Default false (text-only)."
                    ),
                    "default": False,
                },
            },
            "required": ["message_id", "filename"],
        },
    ),
    Tool(
        name="baker_gmail_search",
        description=(
            "Search GMAIL ONLY (vallen300@gmail.com personal account) with full "
            "Gmail query syntax. NOT Outlook/Microsoft 365 — Director's "
            "dvallen@brisengroup.com mail migrated to M365 ~2026-06-03 and is NOT "
            "reachable here; for brisengroup / Outlook / M365 mail use "
            "baker_email_search instead. Returns a list of "
            "matching messages with id, threadId, snippet, From, Subject, and "
            "Date. Reuses baker's existing OAuth session (no new credential "
            "surface). Use to find specific emails by sender/subject/date/"
            "keyword/attachment-presence/label ahead of calling "
            "baker_gmail_read_message or baker_gmail_attachment_read. "
            "Gmail query syntax examples: 'from:counterparty@example.com', "
            "'subject:filing AND has:attachment', 'after:2026/05/01 before:2026/05/15', "
            "'label:Baker', '\"exact phrase\"'. See "
            "https://support.google.com/mail/answer/7190 for full syntax."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Gmail search query using standard Gmail query syntax. "
                        "Empty string is rejected (returns error). Caller must "
                        "supply at least one query term."
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": (
                        "Cap on number of matches returned. Default 20. Hard "
                        "max 50 (server-side enforced; values >50 are clamped "
                        "to 50). Each match costs ~5 Gmail quota units for the "
                        "metadata fetch on top of the list call."
                    ),
                    "default": 20,
                    "minimum": 1,
                    "maximum": 50,
                },
                "page_token": {
                    "type": "string",
                    "description": (
                        "Opaque pagination token from a prior response's "
                        "next_page_token field. Omit on first call."
                    ),
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="baker_gmail_read_message",
        description=(
            "Read a single GMAIL ONLY message body + headers + attachment metadata "
            "by message_id. NOT Outlook/M365 — for brisengroup mail use "
            "baker_email_read. Returns from/to/cc/subject/date/snippet/body_text "
            "plus attachments list ({filename, mime_type, size}). Body extracted "
            "via baker's existing extract_body_text helper (text/plain preferred, "
            "text/html stripped as fallback). Body text capped at 50,000 chars "
            "with truncation marker. Attachment BYTES are NOT included — call "
            "baker_gmail_attachment_read with the filename for bytes/text "
            "extraction. Reuses baker's OAuth session."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": (
                        "Gmail message ID (e.g. from baker_gmail_search results). "
                        "NOT the thread_id."
                    ),
                },
            },
            "required": ["message_id"],
        },
    ),
]

GMAIL_TOOL_NAMES = frozenset(t.name for t in GMAIL_TOOLS)


def dispatch_gmail(name: str, args: dict) -> str:
    """Route gmail-namespace tool calls. Returns JSON string for MCP transport."""
    if name == "baker_gmail_attachment_read":
        return _attachment_read(args)
    if name == "baker_gmail_search":
        return _search(args)
    if name == "baker_gmail_read_message":
        return _read_message(args)
    return json.dumps({"error": f"unknown gmail tool: {name}"})


def _attachment_read(args: dict) -> str:
    message_id = args.get("message_id", "").strip()
    filename = args.get("filename", "").strip()
    attachment_index = args.get("attachment_index", 1)
    include_bytes = bool(args.get("include_bytes", False))

    if not message_id or not filename:
        return json.dumps({
            "error": "message_id and filename are both required",
        })

    if not isinstance(attachment_index, int) or isinstance(attachment_index, bool) or attachment_index < 1:
        return json.dumps({
            "error": f"attachment_index must be a positive integer (got {attachment_index!r})",
        })

    # Reuse poll-time Gmail service singleton — no new credential surface.
    try:
        from triggers.email_trigger import _get_gmail_service
        service = _get_gmail_service()
    except Exception as e:
        logger.error(f"Gmail service init failed: {e}")
        return json.dumps({"error": f"gmail service init failed: {e}"})

    # Fetch the message in baker's own OAuth session so the attachmentId
    # we read from body.attachmentId is valid for the attachments.get() call.
    try:
        message = service.users().messages().get(
            userId="me", id=message_id, format="full",
        ).execute()
    except Exception as e:
        logger.warning(f"gmail message fetch failed (message_id={message_id}): {e}")
        return json.dumps({"error": f"message fetch failed: {e}"})

    from scripts.extract_gmail import (
        _collect_attachment_parts,
        _extract_text_from_bytes,
        _ATTACHMENT_EXTENSIONS,
        _MAX_ATTACHMENT_SIZE,
    )
    payload = message.get("payload", {})
    parts = _collect_attachment_parts(payload)

    # Match by filename (case-sensitive exact). Walk order = depth-first via
    # _collect_attachment_parts so attachment_index is deterministic.
    matches = [p for p in parts if p.get("filename", "") == filename]

    if not matches:
        available = sorted({p.get("filename", "") for p in parts if p.get("filename")})
        return json.dumps({
            "error": f"filename not found in message: {filename}",
            "available_filenames": available,
        })

    if attachment_index > len(matches):
        return json.dumps({
            "error": (
                f"attachment_index {attachment_index} out of range "
                f"({len(matches)} attachment(s) named {filename!r})"
            ),
            "filename": filename,
            "match_count": len(matches),
        })

    target_part = matches[attachment_index - 1]
    body = target_part.get("body", {})
    size = body.get("size", 0)
    session_attachment_id = body.get("attachmentId", "")

    if not session_attachment_id:
        return json.dumps({
            "error": "matched attachment has no attachmentId (inline-data only path not supported)",
            "filename": filename,
        })

    # Size guard — mirror poll-time cap.
    if size > _MAX_ATTACHMENT_SIZE:
        return json.dumps({
            "error": f"attachment too large: {size} bytes (cap {_MAX_ATTACHMENT_SIZE})",
            "filename": filename,
            "size": size,
        })

    # Download attachment bytes using the session-valid attachmentId.
    try:
        att = service.users().messages().attachments().get(
            userId="me", messageId=message_id, id=session_attachment_id,
        ).execute()
        data = att.get("data", "")
        if not data:
            return json.dumps({
                "error": "gmail returned empty attachment data",
                "filename": filename,
            })
        file_bytes = base64.urlsafe_b64decode(data)
    except Exception as e:
        logger.warning(f"attachment download failed ({filename}): {e}")
        return json.dumps({
            "error": f"download failed: {e}",
            "filename": filename,
        })

    # Extract text via existing pipeline.
    from pathlib import Path
    ext = Path(filename).suffix.lower()
    text = ""
    if ext in _ATTACHMENT_EXTENSIONS:
        try:
            extracted = _extract_text_from_bytes(file_bytes, filename, ext)
            text = extracted or ""
        except Exception as e:
            logger.warning(f"extraction failed ({filename}): {e}")

    mime_type, _ = mimetypes.guess_type(filename)
    mime_type = mime_type or "application/octet-stream"

    result: dict[str, Any] = {
        "filename": filename,
        "mime_type": mime_type,
        "size": size,
        "text": text,
        "text_extracted": bool(text),
        "match_count": len(matches),
        "attachment_index": attachment_index,
    }
    if include_bytes:
        result["bytes_base64"] = base64.standard_b64encode(file_bytes).decode("ascii")

    return json.dumps(result)


_SEARCH_MAX_RESULTS_HARD_CAP = 50


def _search(args: dict) -> str:
    query = args.get("query", "").strip()
    max_results = args.get("max_results", 20)
    page_token = args.get("page_token", "").strip()

    if not query:
        return json.dumps({"error": "query is required and cannot be empty"})

    if not isinstance(max_results, int) or isinstance(max_results, bool) or max_results < 1:
        return json.dumps({
            "error": f"max_results must be a positive integer (got {max_results!r})",
        })

    if max_results > _SEARCH_MAX_RESULTS_HARD_CAP:
        max_results = _SEARCH_MAX_RESULTS_HARD_CAP

    try:
        from triggers.email_trigger import _get_gmail_service
        service = _get_gmail_service()
    except Exception as e:
        logger.error(f"Gmail service init failed: {e}")
        return json.dumps({"error": f"gmail service init failed: {e}"})

    try:
        list_kwargs: dict[str, Any] = {
            "userId": "me",
            "q": query,
            "maxResults": max_results,
        }
        if page_token:
            list_kwargs["pageToken"] = page_token
        list_resp = service.users().messages().list(**list_kwargs).execute()
    except Exception as e:
        logger.warning(f"gmail search list failed (query={query!r}): {e}")
        return json.dumps({"error": f"search list failed: {e}"})

    msg_stubs = list_resp.get("messages", []) or []
    next_page_token = list_resp.get("nextPageToken", "")
    result_size_estimate = list_resp.get("resultSizeEstimate", 0)

    # Sequential metadata fetch — cap of 50 keeps cost ≤ ~255 quota units
    # against Gmail's 250/sec per-user limit. Do NOT parallelize; do NOT swap
    # to batchRequest in v1 — keep simple.
    from scripts.extract_gmail import get_header
    matches: list[dict[str, Any]] = []
    for stub in msg_stubs:
        msg_id = stub.get("id", "")
        if not msg_id:
            continue
        try:
            md = service.users().messages().get(
                userId="me",
                id=msg_id,
                format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            ).execute()
        except Exception as e:
            logger.warning(f"gmail metadata fetch failed (msg_id={msg_id}): {e}")
            # NON-FATAL: surface the per-message error, continue with the rest
            matches.append({
                "id": msg_id,
                "thread_id": stub.get("threadId", ""),
                "error": f"metadata fetch failed: {e}",
            })
            continue
        headers = md.get("payload", {}).get("headers", []) or []
        matches.append({
            "id": msg_id,
            "thread_id": md.get("threadId", "") or stub.get("threadId", ""),
            "snippet": md.get("snippet", ""),
            "from": get_header(headers, "From"),
            "to": get_header(headers, "To"),
            "subject": get_header(headers, "Subject"),
            "date": get_header(headers, "Date"),
            "label_ids": md.get("labelIds", []) or [],
        })

    result: dict[str, Any] = {
        "query": query,
        "surface": "gmail_oauth_only",
        "match_count": len(matches),
        "result_size_estimate": result_size_estimate,
        "matches": matches,
    }
    if next_page_token:
        result["next_page_token"] = next_page_token

    # M365_MAIL_BLINDSPOT_DIAGNOSE_FIX_1: never fail silent on brisengroup/M365
    # mail. A brisengroup-scoped query is M365 territory regardless of hit count;
    # and any zero-result here is suspect (this surface can't see M365 mail).
    if _is_brisengroup_scoped(query) or len(matches) == 0:
        result["m365_warning"] = _M365_POINTER

    return json.dumps(result)


_BODY_TEXT_CAP_CHARS = 50_000
_BODY_TRUNCATION_MARKER = "\n\n[... truncated by baker_gmail_read_message at 50,000 chars]"


def _read_message(args: dict) -> str:
    message_id = args.get("message_id", "").strip()

    if not message_id:
        return json.dumps({"error": "message_id is required"})

    try:
        from triggers.email_trigger import _get_gmail_service
        service = _get_gmail_service()
    except Exception as e:
        logger.error(f"Gmail service init failed: {e}")
        return json.dumps({"error": f"gmail service init failed: {e}"})

    try:
        message = service.users().messages().get(
            userId="me", id=message_id, format="full",
        ).execute()
    except Exception as e:
        logger.warning(f"gmail message fetch failed (message_id={message_id}): {e}")
        return json.dumps({"error": f"message fetch failed: {e}"})

    payload = message.get("payload", {})
    headers = payload.get("headers", []) or []

    from scripts.extract_gmail import (
        _collect_attachment_parts,
        extract_body_text,
        get_header,
    )
    body_text = extract_body_text(payload) or ""
    truncated = False
    if len(body_text) > _BODY_TEXT_CAP_CHARS:
        body_text = body_text[:_BODY_TEXT_CAP_CHARS] + _BODY_TRUNCATION_MARKER
        truncated = True

    # Attachment metadata only — BYTES come from baker_gmail_attachment_read.
    attachment_parts = _collect_attachment_parts(payload)
    attachments: list[dict[str, Any]] = []
    for part in attachment_parts:
        filename = part.get("filename", "")
        if not filename:
            continue
        body = part.get("body", {}) or {}
        guessed, _ = mimetypes.guess_type(filename)
        attachments.append({
            "filename": filename,
            "mime_type": guessed or part.get("mimeType", "application/octet-stream"),
            "size": body.get("size", 0),
        })

    result: dict[str, Any] = {
        "message_id": message.get("id", message_id),
        "thread_id": message.get("threadId", ""),
        "snippet": message.get("snippet", ""),
        "from": get_header(headers, "From"),
        "to": get_header(headers, "To"),
        "cc": get_header(headers, "Cc"),
        "subject": get_header(headers, "Subject"),
        "date": get_header(headers, "Date"),
        "label_ids": message.get("labelIds", []) or [],
        "body_text": body_text,
        "body_truncated": truncated,
        "attachments": attachments,
    }
    return json.dumps(result)
