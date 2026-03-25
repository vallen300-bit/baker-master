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
import re
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
DRAFT_TTL_SECONDS = 1800  # 30 minutes — multi-turn revision conversations need time

# EMAIL-DELIVERY-1 DEBUG: In-memory action log for remote diagnosis
_action_log: list = []
_ACTION_LOG_MAX = 50


def _log_action(event: str, detail: str = ""):
    """Append to in-memory action log for /api/debug/action-log endpoint."""
    from datetime import datetime, timezone
    entry = {
        "time": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "detail": detail[:500],
    }
    _action_log.append(entry)
    if len(_action_log) > _ACTION_LOG_MAX:
        _action_log.pop(0)
    logger.info(f"ACTION_LOG: {event} | {detail[:200]}")

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
  "type": "email_action" | "whatsapp_action" | "deadline_action" | "contact_action" | "fireflies_fetch" | "clickup_action" | "clickup_fetch" | "clickup_plan" | "meeting_declaration" | "critical_declaration" | "question",
  "recipient": "<email address OR name of recipient(s). For multiple recipients, return comma-separated (e.g. 'Edita Vallen, Philip Vallen, dvallen@brisengroup.com'). 'myself' or 'me' means dvallen@brisengroup.com. Return null only if no recipient at all.>",
  "subject": "<inferred subject line or null>",
  "content_request": "<what Baker should include in the email body, or null>",
  "whatsapp_recipient": "<name of WhatsApp recipient, or null>",
  "whatsapp_message": "<message content to send via WhatsApp, or null>",
  "deadline_action": "<dismiss | complete | confirm | null>",
  "deadline_search": "<text identifying which deadline, or null>",
  "deadline_date": "<YYYY-MM-DD date for confirm action, or null>",
  "vip_action_type": "<add | remove | null>",
  "vip_name": "<name of VIP contact, or null>",
  "vip_email": "<email of VIP contact, or null>",
  "clickup_sub_type": "<create_task | update_task | post_comment | null>",
  "clickup_task_keyword": "<keyword to find existing task, or null>",
  "clickup_task_name": "<name for new task, or null>",
  "clickup_priority": "<1-4 integer (1=urgent, 4=low), or null>",
  "clickup_due_date": "<ISO date string, or null>",
  "clickup_status": "<target status like 'complete', 'in progress', or null>",
  "clickup_comment_text": "<comment body, or null>",
  "clickup_project_name": "<project name for planning, or null>",
  "clickup_status_filter": "<'overdue', 'open', etc., or null>"
}

Your job is ONLY to classify the intent type. Do NOT judge complexity — that is handled separately.

Email action patterns (classify as email_action even if recipient is a NAME, not an email address):
- "Send [something] to [name/email]"
- "Email [name/email] about [topic]"
- "Forward [something] to [name/email]"
- "Share [something] with [name/email]"
- "Write an email to [name/email] about [topic]"
- "Send the same email to [name] and [name]"
- "Send this to [name]"
- "Email [name], [name], and myself about [topic]"
- "Please send this email to [name]"

WhatsApp action patterns (classify as whatsapp_action):
- "Send a WhatsApp to [name] about [topic]"
- "WhatsApp [name] about [topic]"
- "Message [name] on WhatsApp about [topic]"
- "Send [name] a WhatsApp message: [text]"
- "Tell [name] on WhatsApp that [message]"
- "Ask [name] on WhatsApp if [question]"
- "Send [name] a WA message about [topic]"
- "Send [name] the whats up with [message]" (misspelling of WhatsApp)
- Common misspellings: "whats up", "whats app", "watsapp", "whatsup" all mean WhatsApp

Deadline action patterns:
- "Dismiss the [X] deadline" → type: "deadline_action", deadline_action: "dismiss"
- "Cancel the [date] deadline" → type: "deadline_action", deadline_action: "dismiss"
- "This deadline is done" / "I completed [X]" → type: "deadline_action", deadline_action: "complete"
- "Confirm the [X] deadline for [date]" → type: "deadline_action", deadline_action: "confirm"
- "Confirm [X] for March 15" → type: "deadline_action", deadline_action: "confirm", deadline_date: "2026-03-15"
- "Disregard the [X] deadline" → type: "deadline_action", deadline_action: "dismiss"

Contact action patterns:
- "Add [name] to contacts" → type: "contact_action", vip_action_type: "add"
- "Remove [name] from contacts" → type: "contact_action", vip_action_type: "remove"

Fireflies fetch patterns:
- "Pull the Fireflies recording with [name]" → type: "fireflies_fetch"
- "Get the Fireflies transcript from [date]" → type: "fireflies_fetch"
- "Fetch the meeting with [name] from Tuesday" → type: "fireflies_fetch"
- "Check Fireflies for the [name] call" → type: "fireflies_fetch"
- "Find the recording of the [topic] meeting" → type: "fireflies_fetch"
- "Pull the Fireflies recording with John and draft a follow-up email" → type: "fireflies_fetch" (the email action will be chained after fetch)

ClickUp action patterns (classify as clickup_action):
- "Create a task in ClickUp called [name]" → clickup_sub_type: "create_task"
- "Mark the [task] as complete" → clickup_sub_type: "update_task", clickup_status: "complete"
- "Add a comment on the [task]: [text]" → clickup_sub_type: "post_comment"
- "Close the [task] task" → clickup_sub_type: "update_task", clickup_status: "complete"

ClickUp fetch patterns (classify as clickup_fetch):
- "What's overdue in ClickUp?" → clickup_status_filter: "overdue"
- "Check ClickUp for [keyword]" → clickup_task_keyword: "[keyword]"
- "What tasks are open?" → clickup_status_filter: "open"
- "Status of the [task]?" → clickup_task_keyword: "[task]"

ClickUp plan patterns (classify as clickup_plan):
- "Plan a project for [description]" → clickup_project_name: "[description]"
- "Break [project] into stages" → clickup_project_name: "[project]"
- "Create a project plan for migrating email" → clickup_project_name: "email migration"

Meeting declaration patterns (classify as meeting_declaration — Director is TELLING Baker about a meeting, NOT asking about meetings):
- "I have a meeting with [name] tomorrow at 10am" → type: "meeting_declaration"
- "Set up a call with [name] Wednesday afternoon" → type: "meeting_declaration"
- "Meeting with Rolf at the Mandarin, March 27 at 2pm" → type: "meeting_declaration"
- "Confirmed lunch with [name] on Friday" → type: "meeting_declaration"
- "Let's meet [name] at 3pm tomorrow" → type: "meeting_declaration"
- "I've got a call with [name] at 14:00" → type: "meeting_declaration"
- "Arrange a meeting with [name] next week" → type: "meeting_declaration"
Do NOT classify questions about existing meetings as meeting_declaration. "What meetings do I have?" is type: "question".

Critical item patterns (classify as critical_declaration — Director is marking something as urgent/must-do-today):
- "This is critical: call Rolf today" → type: "critical_declaration"
- "Priority 1: sign the Bellboy decision" → type: "critical_declaration"
- "Don't forget: send the data room request to MRG" → type: "critical_declaration"
- "Mark as critical: Minor Hotels meeting confirmation" → type: "critical_declaration"
- "Most important today: review Alric's torpedo draft" → type: "critical_declaration"
- "Top priority: finalize term sheet" → type: "critical_declaration"
- "Urgent: call Philip about tax" → type: "critical_declaration"
Do NOT classify general urgency in questions as critical_declaration. "What's the most urgent thing?" is type: "question".

If the message is a question, information request, or anything else → type: "question".
Only return the JSON object."""


def _quick_capability_detect(question: str) -> Optional[dict]:
    """
    AGENT-FRAMEWORK-1: Detect explicit capability invocations.
    'have the finance agent analyze...' → capability_task with hint='finance'.
    Returns None if no match.
    """
    pattern = re.compile(
        r"\b(?:have|ask|tell|get|use)\s+(?:the\s+)?(\w+)\s+(?:agent|capability)\b",
        re.IGNORECASE,
    )
    match = pattern.search(question)
    if match:
        return {
            "type": "capability_task", "capability_hint": match.group(1).lower(),
            "complexity": "deep", "complexity_confidence": 0.9,
            "complexity_reasoning": "Explicit specialist invocation implies analysis",
        }
    return None


def _quick_email_detect(question: str) -> dict:
    """
    EMAIL-DELIVERY-1: Fast regex pre-check for obvious email action patterns.
    Bypasses Haiku classifier entirely for clear email commands.
    Returns intent dict if detected, None otherwise.
    """
    import re
    q = question.lower()

    # Must contain an email-related verb
    email_verbs = [
        "send email", "send an email", "send a email",
        "email to ", "email about", "email regarding",
        "write email", "write an email", "write a email",
        "send to ", "forward to ", "share with ",
        "draft email", "draft an email", "compose email",
        "send a message to", "send message to",
    ]
    has_verb = any(v in q for v in email_verbs)

    # Must contain at least one email address
    emails = re.findall(r'[\w.+-]+@[\w.-]+\.\w+', question)

    if has_verb and emails:
        logger.info(f"Quick email detect: matched {len(emails)} recipients via regex (bypassing Haiku)")
        return {
            "type": "email_action",
            "recipient": ", ".join(emails),
            "subject": None,
            "content_request": question,
            "complexity": "deep", "complexity_confidence": 0.8,
            "complexity_reasoning": "Email drafting requires generation",
        }

    return None


def _quick_whatsapp_detect(question: str) -> dict:
    """
    WA-SEND-1: Fast regex pre-check for WhatsApp send patterns.
    Bypasses Haiku classifier for clear WhatsApp commands.
    Returns intent dict if detected, None otherwise.
    """
    import re
    q = question.lower().strip()

    # Questions and statements ABOUT WhatsApp are NOT send commands.
    # Only match explicit imperative commands like "send X a whatsapp"
    question_words = ("what ", "who ", "where ", "when ", "how ", "why ",
                      "do you ", "did you ", "can you tell", "have you ",
                      "is there", "are there", "do i ", "did i ",
                      "if ", "this ", "i am ", "i'm ", "he ", "she ",
                      "we ", "they ", "it ", "the ", "my ", "from ",
                      "about ", "know ", "check ", "show ", "find ",
                      "search ", "look ", "any ", "can i ", "could ")
    if any(q.startswith(qs) for qs in question_words):
        return None

    # Must mention WhatsApp / WA (including common misspellings)
    q_normalized = q.replace("whats app", "whatsapp").replace("watsapp", "whatsapp").replace("whatsup", "whatsapp").replace("whatssapp", "whatsapp").replace("watsap", "whatsapp").replace("whats-app", "whatsapp")
    if "whats up" in q_normalized and any(v in q_normalized for v in ("send", "write", "tell")):
        q_normalized = q_normalized.replace("whats up", "whatsapp")
    wa_refs = ["whatsapp", "wa message", "wa to ", "on wa "]
    has_wa = any(ref in q_normalized for ref in wa_refs)
    if not has_wa:
        return None
    q = q_normalized

    # Must contain an explicit send verb — NOT "ask" (too ambiguous) or "whatsapp" alone
    send_verbs = ["send", "write", "tell"]
    has_verb = any(re.search(r'\b' + v + r'\b', q) for v in send_verbs)
    if not has_verb:
        return None

    # Try to extract recipient name
    # Patterns: "whatsapp to Edita", "send a whatsapp to Edita", "send Edita the whatsapp"
    recipient = None
    patterns = [
        r'(?:whatsapp|wa)\s+(?:message\s+)?(?:to\s+)?(\w[\w\s]*?)\s+(?:about|regarding|that|if|whether|asking|saying|with)',
        r'(?:send|write|message|tell|ask)\s+(\w[\w\s]*?)\s+(?:a\s+|the\s+)?(?:whatsapp|wa)',
        r'(?:send|write)\s+(?:a\s+)?(?:whatsapp|wa)\s+(?:message\s+)?(?:to\s+)?(\w[\w\s]*?)(?:\s+about|\s+regarding|\s+that|\s+saying|\s+with|:|$)',
        r'(?:whatsapp|wa)\s+(?:to\s+)?(\w+)',
    ]
    for pat in patterns:
        m = re.search(pat, q)
        if m:
            candidate = m.group(1).strip()
            # Skip noise words
            if candidate.lower() not in ("a", "an", "the", "me", "my", "to", "with", "same", "message"):
                recipient = candidate.title()
                break

    if recipient:
        logger.info(f"Quick WhatsApp detect: matched recipient={recipient} (bypassing Haiku)")
        return {
            "type": "whatsapp_action",
            "whatsapp_recipient": recipient,
            "whatsapp_message": question,
            "content_request": question,
        }

    return None


def _quick_fireflies_detect(question: str) -> dict:
    """
    Fast regex pre-check for Fireflies fetch requests.
    Catches natural language like 'check my Fireflies', 'pull the recording',
    'find the meeting with X', etc. Bypasses Haiku entirely.
    """
    q = question.lower()

    # Must mention Fireflies OR meeting recordings
    fireflies_refs = [
        "fireflies", "fire flies", "firefly",
        "recording", "transcript", "meeting recording",
    ]
    has_fireflies_ref = any(ref in q for ref in fireflies_refs)

    if not has_fireflies_ref:
        return None

    # Must contain a fetch/search verb
    fetch_verbs = [
        "check", "pull", "fetch", "find", "get", "search",
        "look up", "look for", "go to", "open", "show",
        "retrieve", "grab", "bring up", "dig up",
    ]
    has_verb = any(v in q for v in fetch_verbs)

    if has_verb:
        logger.info(f"Quick fireflies detect: matched via regex (bypassing Haiku)")
        return {
            "type": "fireflies_fetch",
            "content_request": question,
        }

    return None


def _quick_deadline_detect(question: str) -> dict:
    """
    Fast regex pre-check for deadline/schedule/commitment queries.
    Catches natural language like 'check my schedule', 'any deadlines',
    'what are my commitments', 'upcoming deadlines', etc.
    """
    q = question.lower()

    deadline_refs = [
        "deadline", "deadlines",
        "schedule", "calendar",
        "commitment", "commitments",
        "due date", "due dates",
        "upcoming", "overdue",
        "what do i have", "what's coming up", "what is coming up",
        "what do i owe", "what am i supposed to",
        "remind me", "reminders",
    ]
    has_ref = any(ref in q for ref in deadline_refs)

    if not has_ref:
        return None

    # Check for action verbs OR question patterns
    action_patterns = [
        "check", "look", "see", "show", "list", "what", "any",
        "find", "get", "pull up", "review", "tell me",
        "do i have", "are there", "is there",
        "dismiss", "cancel", "complete", "done", "confirm",
    ]
    has_action = any(p in q for p in action_patterns)

    if has_action:
        # Determine if this is a query (list/check) or a management action (dismiss/complete)
        mgmt_words = ["dismiss", "cancel", "complete", "done", "confirm", "disregard"]
        is_mgmt = any(w in q for w in mgmt_words)

        if is_mgmt:
            logger.info("Quick deadline detect: management action (bypassing Haiku)")
            action = "dismiss"
            if any(w in q for w in ("complete", "done")):
                action = "complete"
            elif any(w in q for w in ("confirm",)):
                action = "confirm"
            return {
                "type": "deadline_action",
                "deadline_action": action,
                "deadline_search": question,
                "content_request": question,
            }
        else:
            # Query — return as question but with deadline context
            # The scan RAG pipeline will answer from the deadlines table
            # since deadlines are surfaced in daily briefings and dashboard
            logger.info("Quick deadline detect: query (letting RAG handle with context)")
            return None  # Let RAG answer — it has deadline data in context

    return None


def _quick_clickup_action_detect(question: str) -> Optional[dict]:
    """Fast regex for ClickUp task CRUD commands."""
    import re
    q = question.lower()
    pattern = re.compile(
        r"\b(create|add|make|new|mark|set|update|change|move|assign|close|complete|"
        r"comment|note|post)\b.*\b(task|clickup|ticket)\b",
        re.IGNORECASE,
    )
    if pattern.search(q):
        return {"type": "clickup_action"}
    return None


def _quick_clickup_fetch_detect(question: str) -> Optional[dict]:
    """Fast regex for ClickUp read queries."""
    import re
    q = question.lower()
    pattern = re.compile(
        r"\b(check|what|show|list|status|overdue|pending|open|search|find|"
        r"how many|get)\b.*\b(task|clickup|ticket|overdue)\b",
        re.IGNORECASE,
    )
    if pattern.search(q):
        return {"type": "clickup_fetch"}
    return None


def _quick_clickup_plan_detect(question: str) -> Optional[dict]:
    """Fast regex for project planning commands."""
    import re
    q = question.lower()
    pattern = re.compile(
        r"\b(plan|project plan|break.*into|stage|phase|roadmap)\b.*\b(project|migration|rollout|launch|implementation)\b",
        re.IGNORECASE,
    )
    if pattern.search(q):
        return {"type": "clickup_plan"}
    return None


def classify_intent(question: str, conversation_history: str = "") -> dict:
    """
    Classify the Director's input into action types.
    Uses fast regex pre-check first, then falls back to Claude Haiku.
    Falls back to {"type": "question"} on any error.
    conversation_history: optional recent turns for resolving references.
    """
    _log_action("classify_intent:start", f"question={question[:200]}")

    # AGENT-FRAMEWORK-1: Fast path — regex catches explicit capability invocations
    quick_cap = _quick_capability_detect(question)
    if quick_cap:
        _log_action("classify_intent:regex_match", f"type=capability_task, hint={quick_cap.get('capability_hint')}")
        return quick_cap

    # EMAIL-DELIVERY-1: Fast path — regex catches emails with explicit addresses
    # SMART-ROUTING-1: Only this + capability detect survive as regex fast-paths.
    # All other intents (WhatsApp, Fireflies, deadlines, ClickUp) go through Haiku
    # for better accuracy — regex was causing misroutes.
    quick = _quick_email_detect(question)
    if quick:
        _log_action("classify_intent:regex_match", f"type={quick.get('type')}, recipient={quick.get('recipient')}")
        return quick

    try:
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        # Include conversation history for resolving references like "the same message"
        user_content = question
        if conversation_history:
            user_content = f"Recent conversation:\n{conversation_history}\n\nCurrent message to classify:\n{question}"
        resp = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=_INTENT_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="classify_intent")
        except Exception:
            pass
        raw = resp.content[0].text.strip()
        # Strip markdown code fences if model adds them
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        result = json.loads(raw)

        _log_action(
            "classify_intent:haiku_result",
            f"type={result.get('type')}, raw={raw[:200]}",
        )
        return result
    except Exception as e:
        _log_action("classify_intent:haiku_failed", str(e))
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
        "You are Baker, CEO Chief of Staff AI. You MUST compose an email body NOW.\n\n"
        "CRITICAL RULES:\n"
        "- You MUST write the email body immediately. NEVER ask for clarification.\n"
        "- NEVER respond with questions like 'could you provide more detail' or 'who is the recipient'.\n"
        "- If details are sparse, write a brief, professional email with what you have.\n"
        "- Write only the email body. No salutation ('Dear X'), no subject line, no signature.\n"
        "- Plain text. Professional, concise tone.\n"
        "- Use facts from the retrieved context if relevant — do not invent information.\n"
        "- If no context is relevant, compose a general professional email based on the topic.\n"
        "- Write in plain text ONLY. Do NOT use markdown formatting — no bold (**), no headers (#),\n"
        "  no bullet points (-), no italic (*). Write naturally as in a professional email.\n"
        f"Today's date: {now}\n\n"
        f"RETRIEVED CONTEXT:\n{context_block}"
    )

    try:
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = claude.messages.create(
            model=config.claude.model,
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": f"Compose this email now: {content_request}"}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(config.claude.model, resp.usage.input_tokens, resp.usage.output_tokens, source="email_draft")
        except Exception:
            pass
        return resp.content[0].text.strip()
    except Exception as e:
        logger.error(f"Email body generation failed: {e}")
        return f"[Error generating email body: {e}]"


def _generate_whatsapp_body(content_request: str, retriever, recipient_name: str) -> str:
    """Generate a WhatsApp message body. Short, conversational, no markdown."""
    try:
        contexts = retriever.search_all_collections(
            query=content_request, limit_per_collection=5, score_threshold=0.3,
        )
        context_block = "\n\n".join(
            f"[{c.source.upper()}]\n{c.content[:400]}" for c in contexts[:6]
        )
    except Exception as e:
        logger.warning(f"RAG retrieval for WhatsApp body failed: {e}")
        context_block = ""

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    system = (
        "You are Baker, Dimitry Vallen's AI Chief of Staff. You ARE sending a WhatsApp message right now.\n\n"
        "CRITICAL RULES:\n"
        "- Write ONLY the message text. Nothing else.\n"
        "- WhatsApp style: short, warm, conversational. Not a formal email.\n"
        "- No markdown (no **, no #, no -). Plain text only.\n"
        "- No subject line, no signature block. Just the message.\n"
        "- If asked to introduce yourself as Baker, do so naturally in the message.\n"
        "- Do NOT say you cannot send WhatsApp. You ARE sending it.\n"
        "- Do NOT ask for clarification. Write the message now.\n"
        "- Keep it under 200 words.\n"
        f"Today's date: {now}\n"
        f"Recipient: {recipient_name}\n\n"
        f"CONTEXT:\n{context_block}"
    )

    try:
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = claude.messages.create(
            model=config.claude.model, max_tokens=500,
            system=system,
            messages=[{"role": "user", "content": f"Write this WhatsApp message now: {content_request}"}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(config.claude.model, resp.usage.input_tokens, resp.usage.output_tokens, source="whatsapp_draft")
        except Exception:
            pass
        return resp.content[0].text.strip()
    except Exception as e:
        logger.error(f"WhatsApp body generation failed: {e}")
        return content_request  # fallback: send the Director's original words


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
# Patch B: Name-to-email resolution via VIP contacts
# ---------------------------------------------------------------------------

def _resolve_names_to_emails(raw: str) -> list:
    """
    Resolve person names to email addresses using vip_contacts table.
    Handles "myself"/"me"/"Dimitry" -> dvallen@brisengroup.com.
    Returns list of resolved email addresses.
    """
    resolved = []
    raw_lower = raw.lower()

    # Self-references
    if any(w in raw_lower for w in ("myself", "me", "dimitry")):
        resolved.append(DIRECTOR_EMAIL)

    # VIP contact lookup
    try:
        from models.deadlines import get_vip_contacts
        vips = get_vip_contacts()
        import re
        # Split on comma, semicolon, "and" to get individual names
        name_parts = re.split(r'[,;]\s*|\s+and\s+', raw)
        for part in name_parts:
            part_clean = part.strip().lower()
            if not part_clean or part_clean in ("myself", "me", "dimitry"):
                continue
            for vip in vips:
                vip_name = (vip.get("name") or "").strip()
                vip_email = vip.get("email")
                if not vip_name or not vip_email:
                    continue
                first_name = vip_name.split()[0].lower()
                if part_clean == first_name or part_clean == vip_name.lower():
                    resolved.append(vip_email)
                    break
    except Exception as e:
        logger.warning(f"VIP name resolution failed: {e}")

    return list(set(resolved))


DIRECTOR_WHATSAPP = "41799605092@c.us"


def _resolve_names_to_whatsapp_ids(raw: str) -> list:
    """
    WA-SEND-1: Resolve person names to WhatsApp IDs using vip_contacts table.
    Handles "myself"/"me"/"dimitry" -> Director's WhatsApp ID.
    Returns list of (name, whatsapp_id) tuples.
    """
    resolved = []
    raw_lower = raw.lower()

    # Self-references
    if any(w in raw_lower for w in ("myself", "me", "dimitry")):
        resolved.append(("Dimitry", DIRECTOR_WHATSAPP))

    # VIP contact lookup
    try:
        from models.deadlines import get_vip_contacts
        vips = get_vip_contacts()
        import re
        # Split on comma, semicolon, "and" to get individual names
        name_parts = re.split(r'[,;]\s*|\s+and\s+', raw)
        for part in name_parts:
            part_clean = part.strip().lower()
            if not part_clean or part_clean in ("myself", "me", "dimitry"):
                continue
            for vip in vips:
                vip_name = (vip.get("name") or "").strip()
                vip_wa = vip.get("whatsapp_id")
                if not vip_name or not vip_wa:
                    continue
                first_name = vip_name.split()[0].lower()
                if part_clean == first_name or part_clean == vip_name.lower():
                    resolved.append((vip_name, vip_wa))
                    break
    except Exception as e:
        logger.warning(f"VIP WhatsApp resolution failed: {e}")

    return resolved


# ---------------------------------------------------------------------------
# Patch C: Strip meta-commentary from generated email body
# ---------------------------------------------------------------------------

def _clean_email_body(raw_body: str) -> str:
    """Remove Baker's meta-commentary from generated email text."""
    lines = raw_body.strip().split('\n')
    skip_patterns = [
        'based on the context',
        'based on available context',
        'here is the email',
        "here's the email",
        'i\'ll draft',
        'i will draft',
        'here is a draft',
        "here's a draft",
        'the email body',
        'email body for',
        'draft email:',
        'subject:',
        'here is the composed',
        "here's the composed",
        'based on the retrieved',
        'for all three recipients',
        'for all recipients',
    ]

    # Skip leading lines that match meta-patterns
    start_idx = 0
    for i, line in enumerate(lines):
        line_lower = line.strip().lower()
        if any(p in line_lower for p in skip_patterns):
            start_idx = i + 1
        elif line.strip() == '---':
            start_idx = i + 1
        elif line.strip():
            break

    cleaned = '\n'.join(lines[start_idx:]).strip()
    return cleaned if cleaned else raw_body.strip()


# ---------------------------------------------------------------------------
# Fix 3: Strip markdown formatting from email body
# ---------------------------------------------------------------------------

def _strip_markdown(text: str) -> str:
    """Convert markdown-formatted text to clean plain text for email."""
    import re
    if not text:
        return text

    # Remove bold: **text** or __text__ -> text
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)

    # Remove italic: *text* or _text_ -> text
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'(?<!\w)_(.+?)_(?!\w)', r'\1', text)

    # Remove headers: ## Header -> Header
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # Remove bullet markers: - item or * item -> item
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)

    # Remove numbered list markers: 1. item -> item
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)

    # Remove inline code: `code` -> code
    text = re.sub(r'`(.+?)`', r'\1', text)

    # Remove links: [text](url) -> text
    text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)

    # Remove horizontal rules: --- or *** -> blank line
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)

    # Clean up excessive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def handle_email_action(intent: dict, retriever, project=None, role=None,
                        channel: str = "scan") -> str:
    """
    Process a detected email action intent. Supports single or multiple recipients.
    - Internal (@brisengroup.com): auto-send, return confirmation.
    - External: save pending draft to PostgreSQL, return draft for confirmation.
    - Mixed: send internal immediately, draft external for confirmation.
    Returns the response text to stream back to the Director.
    channel: "scan" or "whatsapp" — determines where confirmations/replies go.
    """
    _log_action("handle_email_action:ENTERED", f"intent={json.dumps(intent)[:300]}, channel={channel}")

    raw_recipient = (intent.get("recipient") or "").strip()
    subject = (intent.get("subject") or "Email from Dimitry Vallen").strip()
    content_request = (intent.get("content_request") or intent.get("subject") or "general email").strip()

    # Parse multiple recipients (comma, semicolon, or "and" separated)
    # First extract any explicit email addresses
    recipients = _parse_recipients(raw_recipient)

    # Always also try name-to-email resolution (handles mixed: "Edita and pvallen@protonmail.com")
    if raw_recipient:
        resolved = _resolve_names_to_emails(raw_recipient)
        if resolved:
            recipients = list(set(recipients + resolved))
            _log_action("handle_email_action:name_resolved", f"raw={raw_recipient}, resolved={resolved}")

    _log_action("handle_email_action:recipients", f"raw={raw_recipient}, parsed={recipients}")

    if not recipients:
        return (
            "I couldn't identify a recipient email address in your request. "
            "Please specify who to send the email to (e.g. \"Send the meeting summary to john@example.com\")."
        )

    body = generate_email_body(content_request, retriever, project, role)
    # Patch C: Strip any meta-commentary Claude added to the email body
    body = _clean_email_body(body)
    # Fix 3: Strip markdown formatting — emails should be clean plain text
    body = _strip_markdown(body)
    # Note: send_composed_email() adds its own footer — don't double-add here
    full_body = body

    # SAFETY: ALL emails require Director approval — no auto-send (Director order 2026-03-25)
    # Internal and external both go through draft flow
    all_recipients = recipients
    results = []

    _log_action("handle_email_action:routing", f"all_draft={all_recipients}")

    # Draft for ALL recipients — Director must confirm before any email sends
    if all_recipients:
        _log_action("handle_email_action:DRAFTING_ALL", f"recipients={all_recipients}")
        first_recipient = all_recipients[0]
        all_recipients_str = ", ".join(all_recipients)
        _save_draft(first_recipient, subject, full_body, content_request, channel=channel)
        logger.info(f"Action: draft saved for {first_recipient} via {channel} (all emails require approval)")

        if len(all_recipients) > 1:
            _save_draft(all_recipients_str, subject, full_body, content_request, channel=channel)

        results.append(
            f'\U0001f4e7 Draft ready for {all_recipients_str} \u2014 reply "send" to confirm, '
            f'or "edit: [changes]" to modify.'
        )

    # Build final response — always show draft for approval
    return "\n".join(results) + f"\n\nTo: {all_recipients_str}\nSubject: {subject}\n\n---\n\n{full_body}"


def _parse_recipients(raw: str) -> list:
    """
    Parse a recipient string that may contain multiple addresses.
    Handles: "a@x.com, b@y.com", "a@x.com; b@y.com", "a@x.com and b@y.com"
    Returns list of valid email addresses.
    """
    if not raw:
        return []

    import re
    # Split on comma, semicolon, or " and "
    parts = re.split(r'[,;]\s*|\s+and\s+', raw)
    recipients = []
    for part in parts:
        addr = part.strip().strip("<>")
        if "@" in addr:
            recipients.append(addr)
    return recipients


def handle_confirmation(retriever=None, project=None, role=None) -> str:
    """Send the pending external draft. Clears state on success."""
    _log_action("handle_confirmation:ENTERED", "checking for pending draft")
    draft = _load_draft()
    if draft is None:
        _log_action("handle_confirmation:no_draft", "draft is None")
        return "No pending draft to send (it may have expired). Please start again with a new email command."
    _log_action("handle_confirmation:draft_found", f"to={draft.get('to')}, channel={draft.get('channel')}")

    try:
        from outputs.email_alerts import send_composed_email
        draft_channel = draft.get("channel", "scan")
        recipients = _parse_recipients(draft["to"])
        if not recipients:
            recipients = [draft["to"]]

        results = []
        for recipient in recipients:
            result = send_composed_email(recipient, draft["subject"], draft["body"])
            if result:
                message_id = result.get("message_id")
                thread_id = result.get("thread_id")
                _log_sent_email(recipient, draft["subject"], draft["body"], message_id, thread_id, draft_channel)
                results.append(f"\u2705 Sent to {recipient}")
                logger.info(f"Action: confirmed send to {recipient} via {draft_channel} (id={message_id})")
            else:
                results.append(f"\u274c Failed: {recipient}")

        _delete_draft()
        preview = draft["body"][:200].replace("\n", " ")
        return "\n".join(results) + f"\nSubject: {draft['subject']}\n\n{preview}\u2026"
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
    full_body = body  # send_composed_email adds footer

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
# MEETINGS-DETECT-1: Meeting declaration handler
# ---------------------------------------------------------------------------

def handle_meeting_declaration(question: str, channel: str = "ask_baker") -> str:
    """
    MEETINGS-DETECT-1: Director declared a meeting. Extract details via Haiku and store.
    Returns confirmation text.
    """
    _log_action("handle_meeting_declaration:ENTERED", f"q={question[:200]}, channel={channel}")
    try:
        from datetime import date
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        today = date.today().isoformat()
        resp = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system="You extract meeting details from messages. Return ONLY valid JSON, no markdown.",
            messages=[{"role": "user", "content": f"""Extract meeting details from this message:
"{question}"

Today's date is {today}.

Return JSON:
{{
  "title": "short meeting title",
  "participants": ["Name1", "Name2"],
  "date": "YYYY-MM-DD or null",
  "time": "HH:MM or descriptive like 'afternoon' or null",
  "location": "place or 'Zoom/Teams' or null",
  "status": "confirmed" | "proposed" | "pending"
}}

Status rules:
- "confirmed": message says "confirmed", "set", "booked", "see you at", or is clearly definite
- "proposed": message says "let's try", "how about", "would X work"
- "pending": needs to be arranged"""}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="meeting_detect")
        except Exception:
            pass
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        data = json.loads(raw)

        title = data.get("title") or "Meeting"
        participants = data.get("participants") or []
        meeting_date = data.get("date")
        meeting_time = data.get("time")
        location = data.get("location")
        status = data.get("status") or "pending"

        # Parse date
        parsed_date = None
        if meeting_date:
            try:
                from datetime import datetime as _dt
                parsed_date = _dt.strptime(meeting_date, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                pass

        # Store
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        mid = store.insert_detected_meeting(
            title=title,
            participant_names=participants,
            meeting_date=parsed_date,
            meeting_time=meeting_time,
            location=location,
            status=status,
            source=channel,
            raw_text=question[:500],
        )

        # Build confirmation
        parts = [f"Got it. Meeting recorded: **{title}**"]
        if participants:
            parts.append(f"With: {', '.join(participants)}")
        if meeting_date:
            parts.append(f"Date: {meeting_date}")
        if meeting_time:
            parts.append(f"Time: {meeting_time}")
        if location:
            parts.append(f"Location: {location}")
        parts.append(f"Status: {status}")
        result = "\n".join(parts)
        _log_action("handle_meeting_declaration:SUCCESS", f"id={mid}, title={title}")
        return result

    except Exception as e:
        logger.error(f"handle_meeting_declaration failed: {e}")
        return f"I understood you're telling me about a meeting, but I couldn't extract the details. Error: {e}"


# ---------------------------------------------------------------------------
# CRITICAL-CARD-1: Critical item declaration handler
# ---------------------------------------------------------------------------

def handle_critical_declaration(question: str, channel: str = "ask_baker") -> str:
    """CRITICAL-CARD-1: Director flagged something as critical/must-do-today."""
    _log_action("handle_critical_declaration:ENTERED", f"q={question[:200]}, channel={channel}")
    try:
        from datetime import date
        from models.deadlines import get_critical_count, insert_deadline, get_critical_items

        # Max 5 rule
        current_count = get_critical_count()
        if current_count >= 5:
            items = get_critical_items(5)
            listing = "\n".join(f"  {i+1}. {it['description'][:80]}" for i, it in enumerate(items))
            return f"You already have 5 critical items. Which one should I remove?\n\n{listing}\n\nSay \"remove #N\" to clear one first."

        # Haiku extraction
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        today = date.today().isoformat()
        resp = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system="Extract the critical task. Return ONLY valid JSON, no markdown.",
            messages=[{"role": "user", "content": f"""Extract the critical item from this message:
"{question}"

Today's date is {today}.

Return JSON:
{{
  "description": "what needs to be done",
  "context": "why it is critical (1 line) or null",
  "due_hint": "today / by 3pm / ASAP / null"
}}"""}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="critical_detect")
        except Exception:
            pass
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        data = json.loads(raw)

        description = data.get("description") or question[:200]
        context = data.get("context") or ""
        due_hint = data.get("due_hint") or "today"

        from datetime import datetime as _dt, timedelta
        due_date = _dt.now()
        if "tomorrow" in (due_hint or "").lower():
            due_date = _dt.now() + timedelta(days=1)

        # Create deadline with is_critical flag
        did = insert_deadline(
            description=description,
            due_date=due_date,
            source_type=channel,
            source_id=f"critical-{channel}:{_dt.now().strftime('%Y%m%d%H%M%S')}",
            confidence="high",
            priority="critical",
            source_snippet=context or question[:300],
        )

        # Set critical flag
        if did:
            from models.deadlines import set_critical
            set_critical(did, True)

        result = f"Critical item added: **{description}**"
        if context:
            result += f"\nContext: {context}"
        result += f"\nDue: {due_hint}"
        _log_action("handle_critical_declaration:SUCCESS", f"id={did}, desc={description[:60]}")
        return result

    except Exception as e:
        logger.error(f"handle_critical_declaration failed: {e}")
        return f"I understood this is critical, but couldn't process it. Error: {e}"


# ---------------------------------------------------------------------------
# WA-SEND-1: WhatsApp send action handler
# ---------------------------------------------------------------------------

def handle_whatsapp_action(intent: dict, retriever, channel: str = "scan",
                           conversation_history: str = "") -> str:
    """
    WA-SEND-1: Process a detected WhatsApp send action.
    Resolves recipient name → WhatsApp ID, generates message body,
    sends via WAHA, and returns confirmation.
    conversation_history: recent turns so "the same message" resolves.
    """
    _log_action("handle_whatsapp_action:ENTERED", f"intent={json.dumps(intent)[:300]}, channel={channel}")

    raw_recipient = (
        intent.get("whatsapp_recipient")
        or intent.get("recipient")
        or ""
    ).strip()
    content_request = (
        intent.get("whatsapp_message")
        or intent.get("content_request")
        or intent.get("subject")
        or "general message"
    ).strip()

    if not raw_recipient:
        return (
            "I couldn't identify who to send the WhatsApp message to. "
            "Please specify a name (e.g. \"Send a WhatsApp to Edita about dinner tonight\")."
        )

    # Check if a phone number was provided inline (e.g. "Sergey +1 860 309 9075")
    import re as _re
    _original_question = intent.get("original_question", "")
    _phone_match = _re.search(r'\+?[\d\s\-()]{10,}', _original_question)
    _inline_phone = None
    if _phone_match:
        _inline_phone = _re.sub(r'[\s\-()]', '', _phone_match.group().strip())
        if not _inline_phone.endswith('@c.us'):
            # Strip leading + and add @c.us suffix for WAHA
            _inline_phone = _inline_phone.lstrip('+') + '@c.us'
        _log_action("handle_whatsapp_action:phone_from_message", f"extracted={_inline_phone}")

    # Resolve name → WhatsApp ID
    resolved = _resolve_names_to_whatsapp_ids(raw_recipient)
    _log_action("handle_whatsapp_action:resolved", f"raw={raw_recipient}, resolved={resolved}")

    # If no VIP match but we have an inline phone number, use it and auto-add VIP
    if not resolved and _inline_phone:
        # Auto-add to VIP contacts for future use
        _clean_name = _re.sub(r'\+?[\d\s\-()]+', '', raw_recipient).strip()
        if not _clean_name:
            _clean_name = raw_recipient.split()[0] if raw_recipient.split() else raw_recipient
        try:
            from memory.store_back import StoreBack
            store = StoreBack()
            store.upsert_vip_contact(_clean_name, whatsapp_id=_inline_phone)
            _log_action("handle_whatsapp_action:auto_vip", f"added {_clean_name} with {_inline_phone}")
        except Exception as _e:
            logger.warning(f"Auto-VIP add failed (non-fatal): {_e}")
        resolved = [(_clean_name, _inline_phone)]

    if not resolved:
        return (
            f"I don't have {raw_recipient}'s WhatsApp number in the contacts list. "
            f"You can add it with: \"Add {raw_recipient} to contacts with WhatsApp [number]\""
        )

    # Generate WhatsApp message body
    enhanced_request = content_request
    if conversation_history:
        enhanced_request = (
            f"{content_request}\n\n"
            f"RECENT CONVERSATION (use this to resolve references like 'the same message'):\n"
            f"{conversation_history}"
        )
    body = _generate_whatsapp_body(enhanced_request, retriever, resolved[0][0])

    # SAFETY: Check if Director said "draft" — show preview instead of auto-sending
    import re as _re
    _original_q = (intent.get("original_question") or content_request or "").lower()
    _is_draft = bool(_re.search(r'\bdraft\b|\bwrite me\b|\bcompose\b|\bprepare\b|\bjust.*text\b|\bdo not send\b', _original_q))

    if _is_draft:
        _log_action("handle_whatsapp_action:DRAFT_MODE", f"draft detected, NOT sending")
        recipient_names = ", ".join(name for name, _ in resolved)
        return (
            f"Here's a draft WhatsApp message for **{recipient_names}**:\n\n"
            f"---\n{body}\n---\n\n"
            f"To send it, say: **Send this WhatsApp to {resolved[0][0]}**"
        )

    results = []
    from outputs.whatsapp_sender import send_whatsapp

    for name, wa_id in resolved:
        _log_action("handle_whatsapp_action:SENDING", f"to={name} ({wa_id})")
        try:
            success = send_whatsapp(text=body, chat_id=wa_id)
            if success:
                results.append(f"\u2705 WhatsApp sent to {name}")
                logger.info(f"Action: WhatsApp sent to {name} ({wa_id}) via {channel}")
            else:
                results.append(f"\u274c Message to {name} could not be delivered. Please check the WhatsApp connection.")
                _log_action("handle_whatsapp_action:send_failed", f"to={name}, returned False")
        except Exception as e:
            logger.error(f"WhatsApp send failed for {name}: {e}")
            _log_action("handle_whatsapp_action:send_exception", f"to={name}, error={e}")
            results.append(f"\u274c Failed to send to {name}: {e}")

    # Log the action
    _log_action("handle_whatsapp_action:DONE", f"recipients={[n for n, _ in resolved]}, results={results}")

    preview = body[:200].replace("\n", " ")
    return "\n".join(results) + f"\n\n{preview}\u2026"


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
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="fireflies_params")
        except Exception:
            pass
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

    # 1b. Check Baker's own memory first (PostgreSQL meeting_transcripts)
    try:
        from memory.retriever import SentinelRetriever
        _retriever = retriever or SentinelRetriever()
        search_term = keyword or date_hint or message[:100]
        memory_results = _retriever.get_meeting_transcripts(search_term, limit=5)
        if memory_results:
            reply_parts = [f"\U0001f4cb Found {len(memory_results)} recording(s) in Baker's memory:"]
            for ctx in memory_results:
                label = ctx.metadata.get("label", "?")
                date = ctx.metadata.get("date", "?")
                reply_parts.append(f"\u2022 {label} ({date})")
                # Include summary (first 500 chars of content)
                summary = ctx.content[:500].split("\n\n", 1)[-1][:300]
                if summary:
                    reply_parts.append(f"  {summary}")
            reply_parts.append("\nFull transcripts are available — ask me about any specific meeting.")
            # Still try to fetch new ones from API below, but return memory results if API has nothing new
            _memory_reply = "\n".join(reply_parts)
        else:
            _memory_reply = None
    except Exception as e:
        logger.warning(f"Memory search for Fireflies failed: {e}")
        _memory_reply = None

    # 2. Search Fireflies API for NEW recordings not yet in memory
    api_key = config.fireflies.api_key
    if not api_key:
        if _memory_reply:
            return _memory_reply
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
        if _memory_reply:
            return _memory_reply
        return f"Failed to search Fireflies: {e}"

    if not results:
        if _memory_reply:
            return _memory_reply
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

        # ARCH-3: Store full transcript in PostgreSQL
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            store.store_meeting_transcript(
                transcript_id=source_id,
                title=metadata.get("meeting_title", "Untitled"),
                meeting_date=metadata.get("date"),
                duration=metadata.get("duration"),
                organizer=metadata.get("organizer"),
                participants=metadata.get("participants"),
                summary=formatted["text"] if "Summary:" in formatted["text"] else None,
                full_transcript=formatted["text"],
            )
        except Exception as _e:
            logger.warning(f"Failed to store transcript {source_id} in PostgreSQL (non-fatal): {_e}")

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


# ---------------------------------------------------------------------------
# CLICKUP-V2: ClickUp PM Overlay — Natural Language Task Management
# ---------------------------------------------------------------------------

import re
import time
from datetime import timedelta

# BAKER space — the only space Baker is allowed to write to
_BAKER_SPACE_ID = "901510186446"
_DEFAULT_LIST_ID = "901521426367"  # Handoff Notes list
_ALL_WORKSPACES = ["2652545", "24368967", "24382372", "24382764", "24385290", "9004065517"]
_PLAN_TTL_SECONDS = 1800  # 30 minutes

# Approval / revision regex patterns
_RE_APPROVAL = re.compile(
    r"^\s*(approved?|yes|go ahead|do it|create it|execute|confirm|proceed|lgtm|looks good)\s*\.?\s*$",
    re.IGNORECASE,
)
_RE_REVISION = re.compile(
    r"\b(change|move|adjust|revise|update|modify|make it|add|remove|split|merge|extend|shorten)\b",
    re.IGNORECASE,
)

# In-memory pending plan state (per channel)
_pending_plans = {}


def _save_pending_plan(channel: str, plan: dict, original_request: str):
    _pending_plans[channel] = {
        "plan": plan,
        "request": original_request,
        "expires": time.time() + _PLAN_TTL_SECONDS,
    }


def _get_pending_plan(channel: str) -> Optional[dict]:
    entry = _pending_plans.get(channel)
    if not entry:
        return None
    if time.time() > entry["expires"]:
        del _pending_plans[channel]
        return None
    return entry


def _clear_pending_plan(channel: str):
    _pending_plans.pop(channel, None)


def check_pending_plan(question: str, channel: str = "scan") -> Optional[str]:
    """Check if a pending ClickUp plan exists and whether the message is approval/revision."""
    entry = _get_pending_plan(channel)
    if not entry:
        return None
    if _RE_APPROVAL.search(question):
        return "confirm"
    if _RE_REVISION.search(question):
        return f"revise:{question}"
    return None


def _find_clickup_task(keyword: str) -> dict:
    """Search clickup_tasks table by keyword (ILIKE). Returns status + task(s)."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return {"status": "error", "message": "Database unavailable"}
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """SELECT id, name, status, priority, due_date, list_name, space_id
               FROM clickup_tasks WHERE name ILIKE %s
               ORDER BY date_updated DESC NULLS LAST LIMIT 10""",
            (f"%{keyword}%",),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        if len(rows) == 1:
            return {"status": "found", "task": rows[0]}
        elif len(rows) > 1:
            return {"status": "multiple", "tasks": rows}
        else:
            try:
                from clickup_client import ClickUpClient
                client = ClickUpClient._get_global_instance()
                for ws_id in _ALL_WORKSPACES:
                    api_results = client.search_tasks(ws_id, keyword)
                    if api_results:
                        return {"status": "found", "task": api_results[0]}
            except Exception as e:
                logger.warning(f"ClickUp API search fallback failed: {e}")
            return {"status": "not_found"}
    except Exception as e:
        logger.error(f"Task lookup failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        store._put_conn(conn)


def _extract_clickup_params(message: str, intent_type: str) -> dict:
    """Use Haiku to extract structured params from a ClickUp command."""
    extraction_prompt = f"""Extract parameters from this ClickUp command.
Intent type: {intent_type}

Return JSON with these fields (omit if not mentioned):
- clickup_sub_type: "create_task", "update_task", or "post_comment"
- clickup_task_name: name for new task
- clickup_task_keyword: keyword to find existing task
- clickup_priority: 1-4 integer (1=urgent, 2=high, 3=normal, 4=low)
- clickup_due_date: ISO date if mentioned
- clickup_status: target status
- clickup_comment_text: comment body
- clickup_project_name: project name (for plan intent)
- clickup_status_filter: "overdue", "open", etc (for fetch intent)

Return ONLY valid JSON, no markdown."""

    claude = anthropic.Anthropic(api_key=config.claude.api_key)
    resp = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=extraction_prompt,
        messages=[{"role": "user", "content": message}],
    )
    try:
        from orchestrator.cost_monitor import log_api_cost
        log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="clickup_params")
    except Exception:
        pass
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
    return json.loads(raw)


# ---------------------------------------------------------------------------
# ClickUp Action Handler (single task CRUD)
# ---------------------------------------------------------------------------

def handle_clickup_action(intent: dict, retriever=None, channel: str = "scan") -> str:
    """Handle single-task ClickUp operations: create, update, comment."""
    from clickup_client import ClickUpClient
    client = ClickUpClient._get_global_instance()

    # If fast-path matched, extract params via Haiku
    if "clickup_sub_type" not in intent:
        try:
            params = _extract_clickup_params(
                intent.get("content_request", ""), "clickup_action"
            )
            intent.update(params)
        except Exception as e:
            logger.warning(f"ClickUp param extraction failed: {e}")

    sub_type = intent.get("clickup_sub_type", "create_task")

    try:
        if sub_type == "create_task":
            return _handle_create_task(client, intent)
        elif sub_type == "update_task":
            return _handle_update_task(client, intent)
        elif sub_type == "post_comment":
            return _handle_post_comment(client, intent)
        else:
            return f"Unknown ClickUp action sub-type: {sub_type}"
    except RuntimeError as e:
        return f"ClickUp write blocked: {e}"
    except ValueError as e:
        return f"ClickUp safety guard: {e}"
    except Exception as e:
        logger.error(f"ClickUp action failed: {e}")
        return f"ClickUp action failed: {e}"


def _handle_create_task(client, intent: dict) -> str:
    name = intent.get("clickup_task_name", "Untitled Task")
    priority = intent.get("clickup_priority")
    due_date = intent.get("clickup_due_date")
    status = intent.get("clickup_status")

    due_ms = None
    if due_date:
        try:
            dt = datetime.fromisoformat(due_date.replace("Z", "+00:00"))
            due_ms = int(dt.timestamp() * 1000)
        except (ValueError, TypeError):
            pass

    result = client.create_task(
        list_id=_DEFAULT_LIST_ID, name=name,
        priority=priority, due_date=due_ms, status=status,
    )
    if result:
        task_id = result.get("id", "unknown")
        task_url = result.get("url", f"https://app.clickup.com/t/{task_id}")
        prio_labels = {1: "Urgent", 2: "High", 3: "Normal", 4: "Low"}
        parts = [f"Task created: **{name}**", f"- ID: {task_id}"]
        if priority:
            parts.append(f"- Priority: {prio_labels.get(priority, priority)}")
        if due_date:
            parts.append(f"- Due: {due_date}")
        parts.append(f"- [Open in ClickUp]({task_url})")
        return "\n".join(parts)
    return "Failed to create task in ClickUp. Check logs for details."


def _handle_update_task(client, intent: dict) -> str:
    keyword = intent.get("clickup_task_keyword", "")
    if not keyword:
        return "I need a task name or keyword to find the task to update."

    lookup = _find_clickup_task(keyword)
    if lookup["status"] == "not_found":
        return f"No task found matching '{keyword}'. Try a different keyword."
    if lookup["status"] == "multiple":
        lines = [f"Multiple tasks match '{keyword}'. Which one?"]
        for t in lookup["tasks"][:5]:
            lines.append(f"- **{t['name']}** ({t['status']}) -- ID: {t['id']}")
        return "\n".join(lines)
    if lookup["status"] == "error":
        return f"Task lookup error: {lookup.get('message', 'unknown')}"

    task = lookup["task"]
    if task.get("space_id") and str(task["space_id"]) != _BAKER_SPACE_ID:
        return f"Task '{task['name']}' is not in BAKER space -- writes not allowed."

    updates = {}
    new_status = intent.get("clickup_status")
    new_priority = intent.get("clickup_priority")
    if new_status:
        status_map = {
            "complete": "complete", "completed": "complete", "done": "complete",
            "closed": "complete", "in progress": "in progress",
            "open": "Open", "to do": "to do", "todo": "to do",
        }
        updates["status"] = status_map.get(new_status.lower(), new_status)
    if new_priority:
        updates["priority"] = new_priority
    if not updates:
        return f"Found task '{task['name']}' but no update fields specified."

    result = client.update_task(task["id"], **updates)
    if result:
        parts = [f"Task updated: **{task['name']}**"]
        for k, v in updates.items():
            parts.append(f"- {k}: {v}")
        return "\n".join(parts)
    return f"Failed to update task '{task['name']}'. Check logs."


def _handle_post_comment(client, intent: dict) -> str:
    keyword = intent.get("clickup_task_keyword", "")
    comment_text = intent.get("clickup_comment_text", "")
    if not keyword:
        return "I need a task name or keyword to find the task."
    if not comment_text:
        return "No comment text provided. What should the comment say?"

    lookup = _find_clickup_task(keyword)
    if lookup["status"] == "not_found":
        return f"No task found matching '{keyword}'."
    if lookup["status"] == "multiple":
        lines = [f"Multiple tasks match '{keyword}'. Which one?"]
        for t in lookup["tasks"][:5]:
            lines.append(f"- **{t['name']}** -- ID: {t['id']}")
        return "\n".join(lines)
    if lookup["status"] == "error":
        return f"Task lookup error: {lookup.get('message', 'unknown')}"

    task = lookup["task"]
    if task.get("space_id") and str(task["space_id"]) != _BAKER_SPACE_ID:
        return f"Task '{task['name']}' is not in BAKER space -- writes not allowed."

    result = client.post_comment(task["id"], comment_text)
    if result:
        preview = comment_text[:100] + ("..." if len(comment_text) > 100 else "")
        return f'Comment posted on **{task["name"]}**: "{preview}"'
    return f"Failed to post comment on '{task['name']}'. Check logs."


# ---------------------------------------------------------------------------
# ClickUp Fetch Handler (read-only queries)
# ---------------------------------------------------------------------------

def handle_clickup_fetch(message: str, retriever=None, channel: str = "scan",
                         project=None, role=None) -> str:
    """Handle read-only ClickUp queries: status, overdue, search."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()

    try:
        params = _extract_clickup_params(message, "clickup_fetch")
    except Exception:
        params = {}

    keyword = params.get("clickup_task_keyword", "")
    status_filter = params.get("clickup_status_filter", "")

    conn = store._get_conn()
    if not conn:
        return "Database unavailable -- cannot query ClickUp tasks."

    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        if status_filter == "overdue":
            cur.execute(
                """SELECT id, name, status, priority, due_date, list_name
                   FROM clickup_tasks
                   WHERE due_date < NOW() AND status NOT IN ('complete', 'closed', 'Closed')
                   ORDER BY due_date ASC LIMIT 20""",
            )
        elif keyword:
            cur.execute(
                """SELECT id, name, status, priority, due_date, list_name
                   FROM clickup_tasks WHERE name ILIKE %s
                   ORDER BY date_updated DESC NULLS LAST LIMIT 20""",
                (f"%{keyword}%",),
            )
        else:
            cur.execute(
                """SELECT id, name, status, priority, due_date, list_name
                   FROM clickup_tasks
                   WHERE status NOT IN ('complete', 'closed', 'Closed')
                   ORDER BY date_updated DESC NULLS LAST LIMIT 20""",
            )

        rows = [dict(r) for r in cur.fetchall()]
        cur.close()

        if not rows:
            if status_filter == "overdue":
                return "No overdue tasks found in ClickUp."
            if keyword:
                return f"No tasks found matching '{keyword}'."
            return "No open tasks found in ClickUp."

        return _format_task_list(rows, status_filter or keyword or "open tasks")
    except Exception as e:
        logger.error(f"ClickUp fetch failed: {e}")
        return f"Failed to query ClickUp tasks: {e}"
    finally:
        store._put_conn(conn)


def _format_task_list(tasks: list, context: str) -> str:
    status_emoji = {
        "open": "[ ]", "to do": "[ ]", "in progress": "[~]",
        "complete": "[x]", "closed": "[x]", "review": "[?]",
    }
    lines = [f"**ClickUp: {context}** ({len(tasks)} tasks)", ""]
    for t in tasks:
        status = (t.get("status") or "unknown").lower()
        marker = status_emoji.get(status, "[-]")
        name = t.get("name", "Untitled")
        prio = t.get("priority", "")
        due = ""
        if t.get("due_date"):
            try:
                dt = t["due_date"]
                if isinstance(dt, str):
                    due = f" | due {dt[:10]}"
                else:
                    due = f" | due {dt.strftime('%Y-%m-%d')}"
            except Exception:
                pass
        prio_str = f" P{prio}" if prio else ""
        list_name = f" ({t.get('list_name', '')})" if t.get("list_name") else ""
        lines.append(f"{marker} **{name}**{prio_str}{due}{list_name}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ClickUp Plan Handler (project planning with approval loop)
# ---------------------------------------------------------------------------

def handle_clickup_plan(message: str, retriever=None, channel: str = "scan",
                        project=None, role=None) -> str:
    """Generate a project plan, store for approval, then execute."""
    pending = _get_pending_plan(channel)
    if pending:
        if _RE_APPROVAL.search(message):
            return execute_pending_plan(channel)
        elif _RE_REVISION.search(message):
            return revise_pending_plan(message, retriever, channel)
        _clear_pending_plan(channel)

    try:
        params = _extract_clickup_params(message, "clickup_plan")
        project_name = params.get("clickup_project_name", message[:100])
    except Exception:
        project_name = message[:100]

    context_block = ""
    if retriever:
        try:
            contexts = retriever.search_all_collections(
                query=message, limit_per_collection=5, score_threshold=0.3,
            )
            if contexts:
                snippets = [f"- {c.content[:200]}" for c in contexts[:5]]
                context_block = "\nRelevant context:\n" + "\n".join(snippets)
        except Exception:
            pass

    plan_prompt = f"""Create a project plan for ClickUp.

Project request: {message}
{context_block}

Return a JSON object with:
{{
  "project_name": "Short project name",
  "stages": [
    {{
      "name": "Stage 1: ...",
      "description": "What this stage covers",
      "days": 5,
      "tasks": [
        {{"name": "Task name", "description": "Details", "priority": 3}}
      ]
    }}
  ],
  "total_days": 20,
  "notes": "Any important considerations"
}}

Rules: 3-6 stages, 5-10 working days per stage unless specified,
2-5 tasks per stage. Priorities: 1=Urgent, 2=High, 3=Normal, 4=Low.
Return ONLY valid JSON, no markdown fences."""

    try:
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = claude.messages.create(
            model=config.claude.model, max_tokens=4096,
            system="You are a project planning assistant. Return only JSON.",
            messages=[{"role": "user", "content": plan_prompt}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(config.claude.model, resp.usage.input_tokens, resp.usage.output_tokens, source="clickup_plan")
        except Exception:
            pass
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        plan = json.loads(raw)
    except json.JSONDecodeError:
        return "Failed to generate a valid project plan. Please try rephrasing."
    except Exception as e:
        return f"Plan generation failed: {e}"

    _save_pending_plan(channel, plan, message)
    display = _format_plan_for_display(plan)
    display += "\n\n**Reply 'Approved' to create this in ClickUp, or describe changes.**"
    return display


def _format_plan_for_display(plan: dict) -> str:
    lines = [f"**Project Plan: {plan.get('project_name', 'Untitled')}**"]
    lines.append(f"Total duration: ~{plan.get('total_days', '?')} working days")
    lines.append("")
    prio_labels = {1: "URGENT", 2: "HIGH", 3: "NORMAL", 4: "LOW"}
    for i, stage in enumerate(plan.get("stages", []), 1):
        days = stage.get("days", "?")
        lines.append(f"**Stage {i}: {stage.get('name', 'Unnamed')}** ({days} days)")
        if stage.get("description"):
            lines.append(f"  {stage['description']}")
        for task in stage.get("tasks", []):
            prio = task.get("priority", 3)
            lines.append(f"  - {task.get('name', 'Task')} [{prio_labels.get(prio, str(prio))}]")
        lines.append("")
    if plan.get("notes"):
        lines.append(f"**Notes:** {plan['notes']}")
    return "\n".join(lines)


def execute_pending_plan(channel: str = "scan") -> str:
    """Execute the pending plan: create list + tasks in ClickUp."""
    entry = _get_pending_plan(channel)
    if not entry:
        return "No pending plan to execute. Plan may have expired (30 min TTL)."
    plan = entry["plan"]
    _clear_pending_plan(channel)
    try:
        return _execute_plan_in_clickup(plan)
    except RuntimeError as e:
        return f"Plan execution blocked: {e}"
    except Exception as e:
        logger.error(f"Plan execution failed: {e}")
        return f"Plan execution failed: {e}"


def _execute_plan_in_clickup(plan: dict) -> str:
    from clickup_client import ClickUpClient
    client = ClickUpClient._get_global_instance()
    client.reset_cycle_counter()

    project_name = plan.get("project_name", "New Project")
    new_list = client.create_list(_BAKER_SPACE_ID, project_name)
    if not new_list:
        return "Failed to create project list in ClickUp."

    list_id = new_list["id"]
    created_tasks = []
    base_date = datetime.now(timezone.utc)
    cumulative_days = 0

    for stage in plan.get("stages", []):
        stage_days = stage.get("days", 5)
        for task_def in stage.get("tasks", []):
            task_name = f"[{stage.get('name', 'Stage')}] {task_def.get('name', 'Task')}"
            due_offset = cumulative_days + stage_days
            due_dt = base_date + timedelta(days=due_offset)
            due_ms = int(due_dt.timestamp() * 1000)
            try:
                result = client.create_task(
                    list_id=list_id, name=task_name,
                    description=task_def.get("description", ""),
                    priority=task_def.get("priority"), due_date=due_ms,
                )
                if result:
                    created_tasks.append(result)
            except RuntimeError as e:
                logger.warning(f"Task creation stopped (write limit): {e}")
                break
        cumulative_days += stage_days

    list_url = new_list.get("url", f"https://app.clickup.com/24385290/v/li/{list_id}")
    return "\n".join([
        f"**Project created in ClickUp: {project_name}**",
        f"- List: {list_id}",
        f"- Tasks created: {len(created_tasks)}",
        f"- Timeline: ~{cumulative_days} working days",
        f"- [Open in ClickUp]({list_url})",
    ])


def revise_pending_plan(revision_text: str, retriever=None, channel: str = "scan") -> str:
    """Revise the pending plan based on Director feedback."""
    entry = _get_pending_plan(channel)
    if not entry:
        return "No pending plan to revise."
    plan = entry["plan"]
    original_request = entry["request"]

    revision_prompt = f"""Revise this project plan based on feedback.

Original request: {original_request}

Current plan:
{json.dumps(plan, indent=2)}

Revision requested: {revision_text}

Return the REVISED plan as JSON in the same format. Return ONLY valid JSON."""

    try:
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = claude.messages.create(
            model=config.claude.model, max_tokens=4096,
            system="You are a project planning assistant. Return only JSON.",
            messages=[{"role": "user", "content": revision_prompt}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(config.claude.model, resp.usage.input_tokens, resp.usage.output_tokens, source="clickup_plan_revise")
        except Exception:
            pass
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        revised_plan = json.loads(raw)
    except Exception as e:
        return f"Plan revision failed: {e}"

    _save_pending_plan(channel, revised_plan, original_request)
    display = _format_plan_for_display(revised_plan)
    display += "\n\n**Reply 'Approved' to create this in ClickUp, or describe further changes.**"
    return display
