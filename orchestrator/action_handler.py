"""
SCAN-ACTION-1: Baker Action Handler — Email Actions from Natural Language

Handles intent classification, pending draft state, and email action execution
for the Baker Scan endpoint. Bypasses the normal RAG streaming pipeline for
recognised email commands.

Internal flow:
  scan_chat() → classify_intent() → handle_email_action() → send / draft
  scan_chat() → check_pending_draft() → handle_confirmation() / handle_edit()
"""
import json
import logging
import os
from datetime import datetime, timezone

import anthropic
from typing import Optional

from config.settings import config

logger = logging.getLogger("baker.action_handler")

INTERNAL_DOMAIN = "brisengroup.com"
DIRECTOR_EMAIL = "dvallen@brisengroup.com"
BAKER_FOOTER = "\n\n---\nSent via Baker CEO Cockpit on behalf of Dimitry Vallen"

# ---------------------------------------------------------------------------
# In-memory pending draft (single Director use case — no DB needed)
# Draft expires after 5 minutes of inactivity.
# ---------------------------------------------------------------------------
_pending_draft: Optional[dict] = None


def _draft_expired() -> bool:
    if not _pending_draft:
        return False
    age = (datetime.now(timezone.utc) - _pending_draft["created_at"]).total_seconds()
    return age > _pending_draft["expires_after"]


def _clear_draft():
    global _pending_draft
    _pending_draft = None


# ---------------------------------------------------------------------------
# Intent classification (Claude Haiku — fast / cheap)
# ---------------------------------------------------------------------------

_INTENT_SYSTEM = """You are Baker's intent classifier. Given a Director's message, classify it and return a JSON object.

Return exactly this JSON structure (no other text, no markdown):
{
  "type": "email_action" | "question",
  "recipient": "<email address or null>",
  "subject": "<inferred subject line or null>",
  "content_request": "<what Baker should include in the email body, or null>"
}

Email action patterns:
- "Send [something] to [name/email]"
- "Email [name/email] about [topic]"
- "Forward [something] to [name/email]"
- "Share [something] with [name/email]"
- "Write an email to [name/email] about [topic]"

If the message is a question, information request, or anything else → type: "question".
Only return the JSON object."""


def classify_intent(question: str) -> dict:
    """
    Use Claude Haiku to classify the Director's input as email_action or question.
    Returns a dict with type, recipient, subject, content_request.
    Falls back to {"type": "question"} on any error.
    """
    try:
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=_INTENT_SYSTEM,
            messages=[{"role": "user", "content": question}],
        )
        raw = resp.content[0].text.strip()
        # Strip markdown code fences if model adds them
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Intent classification failed ({e}) — defaulting to question")
        return {"type": "question"}


# ---------------------------------------------------------------------------
# Pending draft check — called before RAG pipeline in scan_chat()
# ---------------------------------------------------------------------------

def check_pending_draft(question: str) -> Optional[str]:
    """
    Check whether the question interacts with a pending email draft.

    Returns:
      "confirm"           — Director confirmed ("send it", "yes", "confirm", …)
      "edit:<instruction>"— Director wants edits ("edit: make it shorter")
      "dismiss"           — Any other input; draft cleared, fall through to normal scan
      None                — No pending draft active
    """
    global _pending_draft

    if not _pending_draft:
        return None

    if _draft_expired():
        logger.info("Pending draft expired — cleared")
        _clear_draft()
        return None

    q = question.strip().lower()
    if q in ("send it", "yes", "confirm", "go ahead", "do it", "send"):
        return "confirm"

    if question.strip().lower().startswith("edit:"):
        instruction = question.strip()[5:].strip()
        return f"edit:{instruction}"

    # Any other input clears the draft
    logger.info("Pending draft dismissed by unrelated input")
    _clear_draft()
    return "dismiss"


# ---------------------------------------------------------------------------
# Email body generation via RAG
# ---------------------------------------------------------------------------

def generate_email_body(content_request: str, retriever, project=None, role=None) -> str:
    """
    Retrieve Baker's context for the request and ask Claude to write
    a professional email body. Returns plain text body (no footer).
    """
    try:
        contexts = retriever.search_all_collections(
            query=content_request,
            limit_per_collection=8,
            score_threshold=0.3,
            project=project,
            role=role,
        )
        context_block = "\n\n".join(
            f"[{c.source.upper()}]\n{c.content[:600]}"
            for c in contexts[:10]
        )
    except Exception as e:
        logger.warning(f"RAG retrieval for email body failed: {e}")
        context_block = ""

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    system = (
        "You are Baker, CEO Chief of Staff AI. Write a professional email body based on the "
        "Director's request and the retrieved context below.\n"
        "Rules:\n"
        "- Write only the email body. No salutation ('Dear X'), no subject line, no signature.\n"
        "- Plain text. Professional, concise tone.\n"
        "- Use facts from the retrieved context — do not invent information.\n"
        f"Today's date: {now}\n\n"
        f"RETRIEVED CONTEXT:\n{context_block}"
    )

    try:
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = claude.messages.create(
            model=config.claude.model,
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": f"Write an email body for this request: {content_request}"}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        logger.error(f"Email body generation failed: {e}")
        return f"[Error generating email body: {e}]"


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def handle_email_action(intent: dict, retriever, project=None, role=None) -> str:
    """
    Process a detected email action intent.
    - Internal (@brisengroup.com): auto-send, return confirmation.
    - External: save pending draft, return draft for confirmation.
    Returns the response text to stream back to the Director.
    """
    global _pending_draft

    recipient = (intent.get("recipient") or "").strip()
    subject = (intent.get("subject") or "Email from Dimitry Vallen").strip()
    content_request = (intent.get("content_request") or intent.get("subject") or "general email").strip()

    if not recipient or "@" not in recipient:
        return (
            "I couldn't identify a recipient email address in your request. "
            "Please specify who to send the email to (e.g. \"Send the meeting summary to john@example.com\")."
        )

    body = generate_email_body(content_request, retriever, project, role)
    full_body = body + BAKER_FOOTER

    domain = recipient.split("@")[-1].lower()
    is_internal = domain == INTERNAL_DOMAIN

    if is_internal:
        try:
            from outputs.email_alerts import send_composed_email
            message_id = send_composed_email(recipient, subject, full_body)
            _clear_draft()
            preview = full_body[:200].replace("\n", " ")
            logger.info(f"Action: internal email sent to {recipient} (id={message_id})")
            return (
                f"✅ Email sent to {recipient}\n"
                f"**Subject:** {subject}\n\n"
                f"{preview}…"
            )
        except Exception as e:
            logger.error(f"Internal email send failed: {e}")
            return f"❌ Failed to send email to {recipient}: {e}"
    else:
        _pending_draft = {
            "to": recipient,
            "subject": subject,
            "body": full_body,
            "content_request": content_request,
            "created_at": datetime.now(timezone.utc),
            "expires_after": 300,
        }
        logger.info(f"Action: external draft ready for {recipient}")
        return (
            f'📧 Draft ready — reply **"send it"** to confirm, or **"edit: [instruction]"** to modify.\n\n'
            f"**To:** {recipient}\n"
            f"**Subject:** {subject}\n\n"
            f"---\n\n{full_body}"
        )


def handle_confirmation(retriever=None, project=None, role=None) -> str:
    """Send the pending external draft. Clears state on success."""
    global _pending_draft

    if not _pending_draft or _draft_expired():
        _clear_draft()
        return "No pending draft to send (it may have expired). Please start again with a new email command."

    draft = _pending_draft.copy()
    try:
        from outputs.email_alerts import send_composed_email
        message_id = send_composed_email(draft["to"], draft["subject"], draft["body"])
        _clear_draft()
        preview = draft["body"][:200].replace("\n", " ")
        logger.info(f"Action: confirmed send to {draft['to']} (id={message_id})")
        return (
            f"✅ Email sent to {draft['to']}\n"
            f"**Subject:** {draft['subject']}\n\n"
            f"{preview}…"
        )
    except Exception as e:
        logger.error(f"Confirmation send failed: {e}")
        return f"❌ Failed to send email: {e}"


def handle_edit(edit_instruction: str, retriever, project=None, role=None) -> str:
    """Regenerate the pending draft body with the edit instruction applied."""
    global _pending_draft

    if not _pending_draft or _draft_expired():
        _clear_draft()
        return "No pending draft to edit (it may have expired). Please start again with a new email command."

    enhanced_request = (
        f"{_pending_draft['content_request']}\n\n"
        f"Edit instruction: {edit_instruction}"
    )
    body = generate_email_body(enhanced_request, retriever, project, role)
    full_body = body + BAKER_FOOTER

    _pending_draft["body"] = full_body
    _pending_draft["created_at"] = datetime.now(timezone.utc)  # reset TTL on edit

    logger.info(f"Action: draft updated for {_pending_draft['to']} (edit: {edit_instruction[:60]})")
    return (
        f'📧 Draft updated — reply **"send it"** to confirm, or **"edit: [instruction]"** to modify again.\n\n'
        f"**To:** {_pending_draft['to']}\n"
        f"**Subject:** {_pending_draft['subject']}\n\n"
        f"---\n\n{full_body}"
    )
