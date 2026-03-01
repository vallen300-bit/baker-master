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
                expires_at  TIMESTAMPTZ NOT NULL,
                channel     TEXT NOT NULL DEFAULT 'scan'
            )
        """)
        # WHATSAPP-ACTION-1: Add channel column if missing (existing deployments)
        cur.execute("""
            DO $$ BEGIN
                ALTER TABLE pending_drafts ADD COLUMN channel TEXT NOT NULL DEFAULT 'scan';
            EXCEPTION WHEN duplicate_column THEN NULL;
            END $$
        """)
        conn.commit()
        cur.close()
        logger.info("action_handler: pending_drafts table verified (with channel)")
    except Exception as e:
        logger.warning(f"action_handler: could not ensure pending_drafts table: {e}")
    finally:
        _put_conn(conn)


_ensure_draft_table()


# ---------------------------------------------------------------------------
# Draft persistence helpers
# ---------------------------------------------------------------------------

def _save_draft(to: str, subject: str, body: str, content_req: str,
                channel: str = "scan"):
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
            INSERT INTO pending_drafts (id, to_address, subject, body, content_req, created_at, expires_at, channel)
            VALUES ('director', %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                to_address  = EXCLUDED.to_address,
                subject     = EXCLUDED.subject,
                body        = EXCLUDED.body,
                content_req = EXCLUDED.content_req,
                created_at  = EXCLUDED.created_at,
                expires_at  = EXCLUDED.expires_at,
                channel     = EXCLUDED.channel
        """, (to, subject, body, content_req, now, expires_at, channel))
        conn.commit()
        cur.close()
        logger.info(f"action_handler: draft saved for {to} via {channel} (expires {expires_at.strftime('%H:%M:%S')} UTC)")
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
            SELECT to_address, subject, body, content_req, created_at, expires_at, channel
            FROM pending_drafts
            WHERE id = 'director'
        """)
        row = cur.fetchone()
        cur.close()
        if not row:
            return None
        to_address, subject, body, content_req, created_at, expires_at, channel = row
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
            "channel": channel or "scan",
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
  "type": "email_action" | "deadline_action" | "vip_action" | "fireflies_fetch" | "question",
  "recipient": "<email address or null>",
  "subject": "<inferred subject line or null>",
  "content_request": "<what Baker should include in the email body, or null>",
  "deadline_action": "<dismiss | complete | confirm | null>",
  "deadline_search": "<text identifying which deadline, or null>",
  "deadline_date": "<YYYY-MM-DD date for confirm action, or null>",
  "vip_action_type": "<add | remove | null>",
  "vip_name": "<name of VIP contact, or null>",
  "vip_email": "<email of VIP contact, or null>"
}

Email action patterns:
- "Send [something] to [name/email]"
- "Email [name/email] about [topic]"
- "Forward [something] to [name/email]"
- "Share [something] with [name/email]"
- "Write an email to [name/email] about [topic]"

Deadline action patterns:
- "Dismiss the [X] deadline" → type: "deadline_action", deadline_action: "dismiss"
- "Cancel the [date] deadline" → type: "deadline_action", deadline_action: "dismiss"
- "This deadline is done" / "I completed [X]" → type: "deadline_action", deadline_action: "complete"
- "Confirm the [X] deadline for [date]" → type: "deadline_action", deadline_action: "confirm"
- "Confirm [X] for March 15" → type: "deadline_action", deadline_action: "confirm", deadline_date: "2026-03-15"
- "Disregard the [X] deadline" → type: "deadline_action", deadline_action: "dismiss"

VIP action patterns:
- "Add [name] to the VIP list" → type: "vip_action", vip_action_type: "add"
- "Remove [name] from the VIP list" → type: "vip_action", vip_action_type: "remove"

Fireflies fetch patterns:
- "Pull the Fireflies recording with [name]" → type: "fireflies_fetch"
- "Get the Fireflies transcript from [date]" → type: "fireflies_fetch"
- "Fetch the meeting with [name] from Tuesday" → type: "fireflies_fetch"
- "Check Fireflies for the [name] call" → type: "fireflies_fetch"
- "Find the recording of the [topic] meeting" → type: "fireflies_fetch"
- "Pull the Fireflies recording with John and draft a follow-up email" → type: "fireflies_fetch" (the email action will be chained after fetch)

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
# REPLY-TRACK-1: Sent email logging helper
# ---------------------------------------------------------------------------

def _log_sent_email(to: str, subject: str, body: str, message_id: str,
                    thread_id: str, channel: str = "scan"):
    """Log a sent email for reply tracking. Non-fatal on error."""
    try:
        from models.sent_emails import log_sent_email
        log_sent_email(
            to_address=to,
            subject=subject,
            body_preview=body[:200] if body else "",
            gmail_message_id=message_id,
            gmail_thread_id=thread_id,
            channel=channel,
        )
    except Exception as e:
        logger.warning(f"Failed to log sent email for reply tracking: {e}")


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def handle_email_action(intent: dict, retriever, project=None, role=None,
                        channel: str = "scan") -> str:
    """
    Process a detected email action intent.
    - Internal (@brisengroup.com): auto-send, return confirmation.
    - External: save pending draft to PostgreSQL, return draft for confirmation.
    Returns the response text to stream back to the Director.
    channel: "scan" or "whatsapp" — determines where confirmations/replies go.
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
            result = send_composed_email(recipient, subject, full_body)
            if not result:
                return f"\u274c Failed to send email to {recipient}: no response from Gmail"
            message_id = result.get("message_id")
            thread_id = result.get("thread_id")
            _delete_draft()
            # REPLY-TRACK-1: Log sent email for reply tracking
            _log_sent_email(recipient, subject, full_body, message_id, thread_id, channel)
            preview = full_body[:200].replace("\n", " ")
            logger.info(f"Action: internal email sent to {recipient} via {channel} (id={message_id})")
            return (
                f"\u2705 Email sent to {recipient}\n"
                f"Subject: {subject}\n\n"
                f"{preview}\u2026"
            )
        except Exception as e:
            logger.error(f"Internal email send failed: {e}")
            return f"\u274c Failed to send email to {recipient}: {e}"
    else:
        _save_draft(recipient, subject, full_body, content_request, channel=channel)
        logger.info(f"Action: external draft saved for {recipient} via {channel}")
        return (
            f'\U0001f4e7 Draft ready \u2014 reply "send" to confirm, or "edit: [changes]" to modify.\n\n'
            f"To: {recipient}\n"
            f"Subject: {subject}\n\n"
            f"---\n\n{full_body}"
        )


def handle_confirmation(retriever=None, project=None, role=None) -> str:
    """Send the pending external draft. Clears state on success."""
    draft = _load_draft()
    if draft is None:
        return "No pending draft to send (it may have expired). Please start again with a new email command."

    try:
        from outputs.email_alerts import send_composed_email
        result = send_composed_email(draft["to"], draft["subject"], draft["body"])
        if not result:
            return "\u274c Failed to send email: no response from Gmail"
        message_id = result.get("message_id")
        thread_id = result.get("thread_id")
        draft_channel = draft.get("channel", "scan")
        _delete_draft()
        # REPLY-TRACK-1: Log sent email for reply tracking (use original channel)
        _log_sent_email(draft["to"], draft["subject"], draft["body"], message_id, thread_id, draft_channel)
        preview = draft["body"][:200].replace("\n", " ")
        logger.info(f"Action: confirmed send to {draft['to']} via {draft_channel} (id={message_id})")
        return (
            f"\u2705 Email sent to {draft['to']}\n"
            f"Subject: {draft['subject']}\n\n"
            f"{preview}\u2026"
        )
    except Exception as e:
        logger.error(f"Confirmation send failed: {e}")
        return f"\u274c Failed to send email: {e}"


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


# ---------------------------------------------------------------------------
# DEADLINE-SYSTEM-1: Deadline and VIP action handlers
# ---------------------------------------------------------------------------

def handle_deadline_action(intent: dict) -> str:
    """
    Process a detected deadline action intent.
    Returns the response text to stream back to the Director.
    """
    action = (intent.get("deadline_action") or "").lower()
    search = intent.get("deadline_search") or intent.get("content_request") or ""

    if not search:
        return "I couldn't identify which deadline you're referring to. Please be more specific."

    try:
        from orchestrator.deadline_manager import (
            dismiss_deadline, complete_deadline, confirm_deadline,
        )

        if action == "dismiss":
            return dismiss_deadline(search)
        elif action == "complete":
            return complete_deadline(search)
        elif action == "confirm":
            date_str = intent.get("deadline_date") or ""
            return confirm_deadline(search, date_str)
        else:
            return f"I didn't understand the deadline action \"{action}\". Try: dismiss, complete, or confirm."
    except Exception as e:
        logger.error(f"Deadline action failed: {e}")
        return f"Failed to process deadline action: {e}"


def handle_vip_action(intent: dict) -> str:
    """
    Process a detected VIP contact management action.
    Returns the response text to stream back to the Director.
    """
    action = (intent.get("vip_action_type") or "").lower()
    name = intent.get("vip_name") or ""

    if not name:
        return "I couldn't identify the contact name. Please specify who to add or remove."

    try:
        from orchestrator.deadline_manager import add_vip, remove_vip

        if action == "add":
            email = intent.get("vip_email")
            return add_vip(name=name, email=email)
        elif action == "remove":
            return remove_vip(name=name)
        else:
            return f"I didn't understand the VIP action \"{action}\". Try: add or remove."
    except Exception as e:
        logger.error(f"VIP action failed: {e}")
        return f"Failed to process VIP action: {e}"


# ---------------------------------------------------------------------------
# FIREFLIES-FETCH-1: On-demand Fireflies fetch
# ---------------------------------------------------------------------------

_FIREFLIES_PARAM_SYSTEM = """Extract Fireflies search parameters from this message.
Return JSON (no other text):
{
    "keyword": "person name or topic keyword, or null",
    "date_hint": "relative or absolute date like 'Tuesday', 'last week', 'March 2', or null",
    "action_after": "the follow-up action requested (e.g. 'draft a follow-up email to John'), or null"
}
"""


def _extract_fireflies_params(message: str) -> dict:
    """Use Claude Haiku to extract search parameters from the Director's message."""
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d (%A)")
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=_FIREFLIES_PARAM_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"Today is {today}.\n\nMessage: {message}",
            }],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Fireflies param extraction failed: {e}")
        return {}


def _resolve_date_hint(date_hint: str) -> tuple:
    """
    Resolve a natural language date hint to (from_date, to_date) ISO strings.
    Returns (None, None) if unresolvable.
    """
    if not date_hint:
        return None, None

    now = datetime.now(timezone.utc)
    hint = date_hint.lower().strip()

    # Relative hints
    if hint in ("today",):
        d = now.strftime("%Y-%m-%d")
        return d, d
    if hint in ("yesterday",):
        d = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        return d, d
    if "last week" in hint:
        start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        return start, now.strftime("%Y-%m-%d")
    if "this week" in hint:
        # Monday of this week
        monday = now - timedelta(days=now.weekday())
        return monday.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")

    # Day names (most recent occurrence)
    day_names = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    for day_name, day_num in day_names.items():
        if day_name in hint:
            days_ago = (now.weekday() - day_num) % 7
            if days_ago == 0:
                days_ago = 7  # "Tuesday" means last Tuesday if today is Tuesday
            target = now - timedelta(days=days_ago)
            d = target.strftime("%Y-%m-%d")
            return d, d

    # Try direct date parse
    for fmt in ("%Y-%m-%d", "%B %d", "%b %d", "%d %B", "%d %b"):
        try:
            parsed = datetime.strptime(hint, fmt)
            if parsed.year == 1900:
                parsed = parsed.replace(year=now.year)
            d = parsed.strftime("%Y-%m-%d")
            return d, d
        except ValueError:
            continue

    return None, None


def handle_fireflies_fetch(message: str, retriever=None, project=None,
                           role=None, channel: str = "scan") -> str:
    """
    FIREFLIES-FETCH-1: On-demand Fireflies transcript fetch.
    1. Extract search params via Haiku
    2. Search Fireflies API
    3. Ingest new transcripts through pipeline
    4. Chain follow-up action if requested
    5. Return summary
    """
    # 1. Extract params
    params = _extract_fireflies_params(message)
    keyword = params.get("keyword")
    date_hint = params.get("date_hint")
    action_after = params.get("action_after")

    from_date, to_date = _resolve_date_hint(date_hint)

    logger.info(
        f"Fireflies fetch: keyword={keyword}, date_hint={date_hint}, "
        f"resolved=({from_date}, {to_date}), action_after={action_after}"
    )

    # 2. Search Fireflies API
    api_key = config.fireflies.api_key
    if not api_key:
        return "Fireflies API key is not configured. Cannot fetch recordings."

    try:
        from scripts.extract_fireflies import search_transcripts, format_transcript
        results = search_transcripts(
            api_key=api_key,
            keyword=keyword,
            from_date=from_date,
            to_date=to_date,
            limit=10,
        )
    except Exception as e:
        logger.error(f"Fireflies search failed: {e}")
        return f"Failed to search Fireflies: {e}"

    if not results:
        parts = ["No Fireflies recordings found"]
        if keyword:
            parts.append(f'matching "{keyword}"')
        if date_hint:
            parts.append(f"from {date_hint}")
        return " ".join(parts) + "."

    # 3. Filter out already-processed (dedup)
    from triggers.state import trigger_state
    new_results = []
    for t in results:
        source_id = t.get("id", "")
        if source_id and not trigger_state.is_processed("meeting", source_id):
            new_results.append(t)

    # 4. Ingest each through pipeline
    from orchestrator.pipeline import SentinelPipeline, TriggerEvent
    pipeline = SentinelPipeline()
    ingested = 0
    titles = []

    for t in new_results:
        formatted = format_transcript(t)
        source_id = t.get("id", "")
        metadata = formatted.get("metadata", {})
        titles.append(f"{metadata.get('meeting_title', '?')} ({metadata.get('date', '?')})")

        trigger = TriggerEvent(
            type="meeting",
            content=formatted["text"],
            source_id=source_id,
            contact_name=metadata.get("organizer"),
            priority="medium",
        )

        try:
            pipeline.run(trigger)
            ingested += 1
        except Exception as e:
            logger.error(f"Fireflies fetch: pipeline failed for {source_id}: {e}")

        # Deadline extraction
        try:
            from orchestrator.deadline_manager import extract_deadlines
            extract_deadlines(
                content=formatted["text"],
                source_type="fireflies",
                source_id=source_id,
                sender_name=metadata.get("organizer", ""),
            )
        except Exception:
            pass

    # 5. Build reply
    already_had = len(results) - len(new_results)
    reply_parts = [f"\U0001f4cb Fetched {ingested} recording(s) from Fireflies"]
    if titles:
        for t in titles:
            reply_parts.append(f"\u2022 {t}")
    if already_had > 0:
        reply_parts.append(f"({already_had} already in Baker's memory)")
    if ingested > 0:
        reply_parts.append("\nNow in Baker's memory \u2014 you can ask questions about it.")

    # 6. Chain follow-up action if requested
    if action_after and ingested > 0 and retriever:
        reply_parts.append("\nProcessing your follow-up request...")
        # Re-classify the action part
        action_intent = classify_intent(action_after)
        if action_intent.get("type") == "email_action":
            email_result = handle_email_action(
                action_intent, retriever, project, role, channel=channel,
            )
            reply_parts.append(email_result)

    return "\n".join(reply_parts)
