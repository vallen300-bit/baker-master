"""Gmail MCP tool surface — on-demand attachment read.

Wraps the existing extract_gmail attachment pipeline as an MCP-callable tool.
Reuses _get_gmail_service from triggers.email_trigger (no new credential
surface). Uses _extract_text_from_bytes from scripts.extract_gmail for
extraction parity with poll-time path.

Anchor: BRIEF_GMAIL_ATTACHMENT_READ_1 — Director-ratified 2026-05-24
"start building now, live during sessions." Phase (a) of the (a)-then-(b)
plan (b = label-triggered auto-ingest, separate brief).
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
            "Read a single Gmail attachment on-demand. Returns extracted text "
            "(for PDF/DOCX/XLSX/CSV/TXT/MD/JSON) plus optional base64-encoded "
            "raw bytes. Reuses the existing poll-time extraction pipeline + "
            "Gmail service singleton (no new credential surface). "
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
                "attachment_id": {
                    "type": "string",
                    "description": (
                        "Gmail attachment ID for the specific attachment. "
                        "Required when message has multiple attachments."
                    ),
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
            "required": ["message_id", "attachment_id"],
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
    attachment_id = args.get("attachment_id", "").strip()
    include_bytes = bool(args.get("include_bytes", False))

    if not message_id or not attachment_id:
        return json.dumps({
            "error": "message_id and attachment_id are both required",
        })

    # Reuse poll-time Gmail service singleton — no new credential surface.
    try:
        from triggers.email_trigger import _get_gmail_service
        service = _get_gmail_service()
    except Exception as e:
        logger.error(f"Gmail service init failed: {e}")
        return json.dumps({"error": f"gmail service init failed: {e}"})

    # Fetch the message to get attachment metadata (filename + size).
    try:
        message = service.users().messages().get(
            userId="me", id=message_id, format="full",
        ).execute()
    except Exception as e:
        logger.warning(f"gmail message fetch failed (message_id={message_id}): {e}")
        return json.dumps({"error": f"message fetch failed: {e}"})

    # Locate the attachment part by attachment_id (recursive — handles
    # forwarded emails with nested attachments per EMAIL-ATTACH-FIX-1).
    from scripts.extract_gmail import (
        _collect_attachment_parts,
        _extract_text_from_bytes,
        _ATTACHMENT_EXTENSIONS,
        _MAX_ATTACHMENT_SIZE,
    )
    payload = message.get("payload", {})
    parts = _collect_attachment_parts(payload)
    target_part = None
    for part in parts:
        body = part.get("body", {})
        if body.get("attachmentId") == attachment_id:
            target_part = part
            break
    if target_part is None:
        return json.dumps({"error": f"attachment_id not found in message: {attachment_id}"})

    filename = target_part.get("filename", "")
    body = target_part.get("body", {})
    size = body.get("size", 0)

    # Size guard — mirror poll-time cap. Foot-gun: caller could request a
    # multi-hundred-MB attachment and OOM the worker.
    if size > _MAX_ATTACHMENT_SIZE:
        return json.dumps({
            "error": f"attachment too large: {size} bytes (cap {_MAX_ATTACHMENT_SIZE})",
            "filename": filename,
            "size": size,
        })

    # Download attachment bytes.
    try:
        att = service.users().messages().attachments().get(
            userId="me", messageId=message_id, id=attachment_id,
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

    # Extract text via existing pipeline. Empty text is non-fatal — may be
    # an image attachment (out of v1 scope) or extractor returned empty.
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
    }
    if include_bytes:
        result["bytes_base64"] = base64.standard_b64encode(file_bytes).decode("ascii")

    return json.dumps(result)
