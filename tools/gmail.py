"""Gmail MCP tool surface — on-demand attachment read.

Wraps the existing extract_gmail attachment pipeline as an MCP-callable tool.
Reuses _get_gmail_service from triggers.email_trigger (no new credential
surface). Uses _extract_text_from_bytes from scripts.extract_gmail for
extraction parity with poll-time path.

Anchor: BRIEF_GMAIL_ATTACHMENT_READ_2 — Director-ratified 2026-05-24.
Amends READ_1 (PR #256). Gmail attachment IDs are OAuth-session-scoped, so
cross-session callers cannot supply them. The tool now matches by filename
and resolves the session-valid attachmentId internally in baker's session.
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
from typing import Any

from mcp.types import Tool  # type: ignore[import-not-found]

logger = logging.getLogger("baker.tools.gmail")


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
]

GMAIL_TOOL_NAMES = frozenset(t.name for t in GMAIL_TOOLS)


def dispatch_gmail(name: str, args: dict) -> str:
    """Route gmail-namespace tool calls. Returns JSON string for MCP transport."""
    if name == "baker_gmail_attachment_read":
        return _attachment_read(args)
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
