"""
SCAN-ACTION-1: Baker Action Handler — Email Actions from Natural Language

Handles intent classification, pending draft state, and email action execution
for the Baker Scan endpoint. Bypasses the normal RAG streaming pipeline for
recognised email commands.

Draft state is persisted to PostgreSQL (pending_drafts table, single row keyed
'director') so it survives process restarts and multi-worker deployments.
TTL is enforced passively on every read — no background sweep required.

Internal flow:
  scan_chat() → classify_intent() → handle_email_action() → send / draft
  scan_chat() → check_pending_draft() → handle_confirmation() / handle_edit()
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import anthropic
import psycopg2
import psycopg2.pool

from config.settings import config

logger = logging.getLogger("baker.action_handler")

INTERNAL_DOMAIN = "brisengroup.com"
DIRECTOR_EMAIL = "dvallen@brisengroup.com"
BAKER_FOOTER = "\n\n---\nSent via Baker CEO Cockpit on behalf of Dimitry Vallen"
DRAFT_TTL_SECONDS = 300

# ---------------------------------------------------------------------------
# Lightweight PostgreSQL pool — draft table only (min=1, max=2)
# ---------------------------------------------------------------------------

_pool: Optional[psycopg2.pool.SimpleConnectionPool] = None


def _get_pool() -> Optional[psycopg2.pool.SimpleConnectionPool]:
    global _pool
    if _pool is None:
        try:
            _pool = psycopg2.pool.SimpleConnectionPool(
                minconn=1,
                maxconn=2,
                **config.postgres.dsn_params,
            )
            logger.info("action_handler: PostgreSQL pool initialised")
        except Exception as e:
            logger.warning(f"action_handler: PostgreSQL pool init failed: {e}")
    return _pool


def _get_conn():
    pool = _get_pool()
    if pool is None:
        return None
    try:
        return pool.getconn()
    except Exception as e:
        logger.warning(f"action_handler: could not get connection: {e}")
        return None


def _put_conn(conn):
    pool = _get_pool()
    if pool and conn:
        try:
            pool.putconn(conn)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Table bootstrap — called once at import time
# ---------------------------------------------------------------------------

def _ensure_draft_table():
    conn = _get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pending_drafts (
                id          TEXT PRIMARY KEY,
                to_address  TEXT NOT NULL,
                subject     TEXT NOT NULL,
                body        TEXT NOT NULL,
                content_req TEXT NOT NULL,
                created_at  TIMESTAMPTZ NOT NULL,
                expires_at  TIMESTAMPTZ NOT NULL
            )
        """)
        conn.commit()
        cur.close()
        logger.info("action_handler: pending_drafts table verified")
    except Exception as e:
        logger.warning(f"action_handler: could not ensure pending_drafts table: {e}")
    finally:
        _put_conn(conn)


_ensure_draft_table()


# ---------------------------------------------------------------------------
# Draft persistence helpers
# ---------------------------------------------------------------------------

def _save_draft(to: str, subject: str, body: str, content_req: str):
    """Upsert a single pending draft for the Director."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=DRAFT_TTL_SECONDS)
    conn = _get_conn()
    if not conn:
        logger.error("action_handler: no DB connection — draft not saved")
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO pending_drafts (id, to_address, subject, body, content_req, created_at, expires_at)
            VALUES ('director', %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                to_address  = EXCLUDED.to_address,
                subject     = EXCLUDED.subject,
                body        = EXCLUDED.body,
                content_req = EXCLUDED.content_req,
                created_at  = EXCLUDED.created_at,
                expires_at  = EXCLUDED.expires_at
        """, (to, subject, body, content_req, now, expires_at))
        conn.commit()
        cur.close()
        logger.info(f"action_handler: draft saved for {to} (expires {expires_at.strftime('%H:%M:%S')} UTC)")
    except Exception as e:
        logger.error(f"action_handler: draft save failed: {e}")
    finally:
        _put_conn(conn)


def _load_draft() -> Optional[dict]:
    """
    Load the pending draft. Returns None if no draft exists or TTL has expired.
    Expired drafts are auto-deleted on load.
    """
    conn = _get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT to_address, subject, body, content_req, created_at, expires_at
            FROM pending_drafts
            WHERE id = 'director'
        """)
        row = cur.fetchone()
        cur.close()
        if not row:
            return None
        to_address, subject, body, content_req, created_at, expires_at = row
        if datetime.now(timezone.utc) > expires_at:
            logger.info("action_handler: draft expired — auto-deleting")
            _delete_draft()
            return None
        return {
            "to": to_address,
            "subject": subject,
            "body": body,
            "content_request": content_req,
            "created_at": created_at,
            "expires_at": expires_at,
        }
    except Exception as e:
        logger.warning(f"action_handler: draft load failed: {e}")
        return None
    finally:
        _put_conn(conn)


def _delete_draft():
    """Remove the pending draft."""
    conn = _get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM pending_drafts WHERE id = 'director'")
        conn.commit()
        cur.close()
    except Exception as e:
        logger.warning(f"action_handler: draft delete failed: {e}")
    finally:
        _put_conn(conn)


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
    draft = _load_draft()
    if draft is None:
        return None

    q = question.strip().lower()
    if q in ("send it", "yes", "confirm", "go ahead", "do it", "send"):
        return "confirm"

    if question.strip().lower().startswith("edit:"):
        instruction = question.strip()[5:].strip()
        return f"edit:{instruction}"

    # Any other input clears the draft and falls through to normal scan
    logger.info("action_handler: pending draft dismissed by unrelated input")
    _delete_draft()
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
    - External: save pending draft to PostgreSQL, return draft for confirmation.
    Returns the response text to stream back to the Director.
    """
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
            _delete_draft()
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
        _save_draft(recipient, subject, full_body, content_request)
        logger.info(f"Action: external draft saved for {recipient}")
        return (
            f'📧 Draft ready — reply **"send it"** to confirm, or **"edit: [instruction]"** to modify.\n\n'
            f"**To:** {recipient}\n"
            f"**Subject:** {subject}\n\n"
            f"---\n\n{full_body}"
        )


def handle_confirmation(retriever=None, project=None, role=None) -> str:
    """Send the pending external draft. Clears state on success."""
    draft = _load_draft()
    if draft is None:
        return "No pending draft to send (it may have expired). Please start again with a new email command."

    try:
        from outputs.email_alerts import send_composed_email
        message_id = send_composed_email(draft["to"], draft["subject"], draft["body"])
        _delete_draft()
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
    draft = _load_draft()
    if draft is None:
        return "No pending draft to edit (it may have expired). Please start again with a new email command."

    enhanced_request = (
        f"{draft['content_request']}\n\n"
        f"Edit instruction: {edit_instruction}"
    )
    body = generate_email_body(enhanced_request, retriever, project, role)
    full_body = body + BAKER_FOOTER

    # Re-save with updated body and reset TTL
    _save_draft(draft["to"], draft["subject"], full_body, draft["content_request"])

    logger.info(f"Action: draft updated for {draft['to']} (edit: {edit_instruction[:60]})")
    return (
        f'📧 Draft updated — reply **"send it"** to confirm, or **"edit: [instruction]"** to modify again.\n\n'
        f"**To:** {draft['to']}\n"
        f"**Subject:** {draft['subject']}\n\n"
        f"---\n\n{full_body}"
    )
