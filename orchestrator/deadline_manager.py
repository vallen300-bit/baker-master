"""
DEADLINE-SYSTEM-1: Deadline Manager
Extraction, priority classification, escalation cadence, and management actions.

Components:
  extract_deadlines()  — Claude Haiku extraction from any ingested content
  classify_priority()  — Critical (Director), High (VIP), Normal
  run_cadence_check()  — Hourly escalation engine (30d→7d→2d→48h→day_of→overdue)
  run_expiry_check()   — Auto-expire deadlines 3+ months past due
  dismiss_deadline()   — Director dismisses via Scan or WhatsApp
  confirm_deadline()   — Director confirms soft deadline with hard date
  complete_deadline()  — Director marks deadline as completed
  add_vip() / remove_vip() — VIP contact management
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import anthropic

from config.settings import config

logger = logging.getLogger("baker.deadline_manager")

DIRECTOR_EMAIL = "dvallen@brisengroup.com"
DIRECTOR_WHATSAPP = "41799605092@c.us"
DIRECTOR_SPEAKER_LABELS = {"dimitry", "dimitry vallen", "director"}


# ---------------------------------------------------------------------------
# Deadline extraction via Claude Haiku
# ---------------------------------------------------------------------------

_EXTRACTION_SYSTEM = """You are a deadline extraction assistant for a CEO. Analyze the following content and extract any deadlines, commitments, or time-bound obligations.

For each deadline found, return:
- description: what needs to happen
- due_date: the specific date (ISO format YYYY-MM-DD). If vague ("mid-March"), estimate the most likely date.
- confidence: "hard" if a specific date is stated, "soft" if inferred from vague language
- speaker: who stated or imposed this deadline (name or role)

Rules:
- Only extract FUTURE deadlines (after today's date).
- Ignore dates more than 3 months in the past.
- Ignore purely historical references ("we signed the contract on January 5").
- Distinguish between commitments ("I will deliver by March 15") and reports ("the deadline was March 15").
- If the CEO (Dimitry Vallen) makes a commitment, mark speaker as "Director".

Return a JSON array. Empty array [] if no deadlines found. No other text."""


def extract_deadlines(
    content: str,
    source_type: str,
    source_id: str = "",
    sender_name: str = "",
    sender_email: str = "",
    sender_whatsapp: str = "",
) -> int:
    """
    Extract deadlines from ingested content using Claude Haiku.
    Inserts valid deadlines into PostgreSQL.
    Returns the number of deadlines inserted.

    Called by sentinel triggers after content ingestion.
    """
    if not content or len(content.strip()) < 20:
        return 0

    try:
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        resp = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=_EXTRACTION_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"Today's date: {today}\n\nContent to analyze:\n{content[:4000]}",
            }],
        )
        raw = resp.content[0].text.strip()
        # Strip markdown code fences
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        deadlines = json.loads(raw)
    except json.JSONDecodeError:
        logger.debug(f"Deadline extraction returned non-JSON for {source_type}:{source_id}")
        return 0
    except Exception as e:
        logger.warning(f"Deadline extraction failed for {source_type}:{source_id}: {e}")
        return 0

    if not isinstance(deadlines, list) or not deadlines:
        return 0

    from models.deadlines import insert_deadline, find_duplicate_deadline

    inserted = 0
    for dl in deadlines:
        description = dl.get("description", "").strip()
        due_date_str = dl.get("due_date", "").strip()
        confidence = dl.get("confidence", "soft")
        speaker = dl.get("speaker", "").strip()

        if not description or not due_date_str:
            continue

        # Parse due_date
        try:
            due_date = datetime.fromisoformat(due_date_str)
            if due_date.tzinfo is None:
                due_date = due_date.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            logger.debug(f"Skipping deadline with invalid date: {due_date_str}")
            continue

        # Skip past deadlines
        now = datetime.now(timezone.utc)
        if due_date < now - timedelta(days=7):
            continue

        # Dedup check
        existing = find_duplicate_deadline(description, due_date)
        if existing:
            # Append source to existing snippet
            from models.deadlines import update_deadline
            old_snippet = existing.get("source_snippet") or ""
            new_snippet = f"{old_snippet}\n[{source_type}] {content[:200]}".strip()[:500]
            update_deadline(existing["id"], source_snippet=new_snippet)
            logger.info(f"Deadline dedup: merged into existing #{existing['id']}")
            continue

        # Classify priority
        priority = _classify_priority(
            speaker=speaker,
            sender_email=sender_email,
            sender_whatsapp=sender_whatsapp,
            source_type=source_type,
        )

        snippet = content[:500]

        dl_id = insert_deadline(
            description=description,
            due_date=due_date,
            source_type=source_type,
            confidence=confidence,
            priority=priority,
            source_id=source_id,
            source_snippet=snippet,
        )
        if dl_id:
            inserted += 1
            conf_label = "SOFT" if confidence == "soft" else "HARD"
            logger.info(
                f"Deadline extracted: #{dl_id} [{conf_label}/{priority}] "
                f'"{description[:60]}" due {due_date_str} (from {source_type})'
            )

    return inserted


# ---------------------------------------------------------------------------
# Priority classification
# ---------------------------------------------------------------------------

def _classify_priority(
    speaker: str = "",
    sender_email: str = "",
    sender_whatsapp: str = "",
    source_type: str = "",
) -> str:
    """
    Classify deadline priority:
    - critical: Director made the commitment
    - high: VIP contact imposed the deadline
    - normal: everything else
    """
    # Check if Director made the commitment
    if speaker.lower() in DIRECTOR_SPEAKER_LABELS:
        return "critical"
    if sender_email and sender_email.lower() == DIRECTOR_EMAIL:
        return "critical"
    if sender_whatsapp and sender_whatsapp == DIRECTOR_WHATSAPP:
        return "critical"

    # Check VIP contacts
    try:
        from models.deadlines import get_vip_contacts
        vips = get_vip_contacts()
        speaker_lower = speaker.lower()
        for vip in vips:
            vip_name = (vip.get("name") or "").lower()
            vip_email = (vip.get("email") or "").lower()
            vip_wa = vip.get("whatsapp_id") or ""
            vip_speaker = (vip.get("fireflies_speaker_label") or "").lower()

            if speaker_lower and (speaker_lower in vip_name or speaker_lower == vip_speaker):
                return "high"
            if sender_email and sender_email.lower() == vip_email:
                return "high"
            if sender_whatsapp and sender_whatsapp == vip_wa:
                return "high"
    except Exception as e:
        logger.warning(f"VIP lookup failed during priority classification: {e}")

    return "normal"


# ---------------------------------------------------------------------------
# Escalation cadence engine (runs hourly)
# ---------------------------------------------------------------------------

def run_cadence_check():
    """
    Hourly escalation cadence check.
    For each active deadline, determine reminder stage and fire alerts/reminders.

    Stages: 30d → 7d → 2d → 48h → day_of → overdue (then stop at 48h overdue)
    """
    from models.deadlines import get_active_deadlines, update_deadline

    deadlines = get_active_deadlines(limit=200)
    now = datetime.now(timezone.utc)
    alerts_fired = 0

    for dl in deadlines:
        if dl.get("status") != "active":
            continue

        due_date = dl.get("due_date")
        if not due_date:
            continue
        if due_date.tzinfo is None:
            due_date = due_date.replace(tzinfo=timezone.utc)

        delta = due_date - now
        hours_remaining = delta.total_seconds() / 3600
        current_stage = dl.get("reminder_stage") or ""

        new_stage = _determine_stage(hours_remaining)
        if not new_stage:
            continue  # > 30 days out, no action

        # Skip if already reminded at this stage
        if new_stage == current_stage:
            continue

        # Fire the appropriate reminder
        _fire_reminder(dl, new_stage, hours_remaining)
        update_deadline(
            dl["id"],
            reminder_stage=new_stage,
            last_reminded_at=now,
        )
        alerts_fired += 1

    # Run expiry check in the same pass
    expired = run_expiry_check()

    # Auto-dismiss unconfirmed soft deadlines after 7 days
    dismissed = _auto_dismiss_soft_deadlines()

    if alerts_fired or expired or dismissed:
        logger.info(
            f"Cadence check: {alerts_fired} reminders fired, "
            f"{expired} expired, {dismissed} soft deadlines auto-dismissed"
        )


def _determine_stage(hours_remaining: float) -> Optional[str]:
    """Map hours remaining to escalation stage."""
    if hours_remaining < -48:
        return None  # Stop reminding after 48h overdue
    if hours_remaining < 0:
        return "overdue"
    if hours_remaining <= 24:
        return "day_of"
    if hours_remaining <= 48:
        return "48h"
    if hours_remaining <= 168:  # 7 days
        return "2d"
    if hours_remaining <= 720:  # 30 days
        return "7d"
    return "30d"


def _fire_reminder(deadline: dict, stage: str, hours_remaining: float):
    """Send a reminder via the appropriate channel based on stage."""
    description = deadline.get("description", "Untitled")
    priority = deadline.get("priority", "normal")
    due_date = deadline.get("due_date")
    due_str = due_date.strftime("%B %-d") if due_date else "TBD"

    priority_label = {"critical": "CRITICAL \u2014 your commitment",
                      "high": "HIGH \u2014 VIP request",
                      "normal": "NORMAL"}.get(priority, priority)

    # Stages 48h, day_of, overdue → push to digest buffer as alert
    if stage in ("48h", "day_of", "overdue"):
        try:
            from orchestrator.digest_manager import add_alert

            if stage == "overdue":
                title = f"OVERDUE: {description}"
            elif stage == "day_of":
                title = f"DUE TODAY: {description}"
            else:
                title = f"Due in 48h: {description}"

            # Critical + urgent stages bypass digest
            is_critical = priority == "critical" and stage in ("48h", "day_of")

            add_alert(
                title=title,
                source_type="Deadline",
                timestamp=datetime.now(timezone.utc).strftime("%H:%M UTC"),
                tier=1,
                source_id=f"deadline:{deadline.get('id')}",
                content=f"{description} (due {due_str}, {priority_label})",
                is_critical=is_critical,
            )
            logger.info(f"Deadline alert [{stage}]: {description}")
        except Exception as e:
            logger.warning(f"Deadline alert failed: {e}")

    # Stages 30d, 7d, 2d → included in daily briefing (no separate alert)
    else:
        logger.info(f"Deadline reminder [{stage}]: {description} (briefing inclusion)")


# ---------------------------------------------------------------------------
# Expiry and auto-dismiss
# ---------------------------------------------------------------------------

def run_expiry_check() -> int:
    """Expire deadlines with due_date more than 3 months past. Returns count expired."""
    from models.deadlines import get_conn, put_conn
    conn = get_conn()
    if not conn:
        return 0
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        cur = conn.cursor()
        cur.execute("""
            UPDATE deadlines
            SET status = 'expired', dismissed_reason = 'expired (3 months)',
                updated_at = NOW()
            WHERE status IN ('active', 'pending_confirm')
              AND due_date < %s
        """, (cutoff,))
        expired = cur.rowcount
        conn.commit()
        cur.close()
        return expired
    except Exception as e:
        logger.error(f"Expiry check failed: {e}")
        return 0
    finally:
        put_conn(conn)


def _auto_dismiss_soft_deadlines() -> int:
    """Auto-dismiss pending_confirm deadlines with no response after 7 days."""
    from models.deadlines import get_conn, put_conn
    conn = get_conn()
    if not conn:
        return 0
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        cur = conn.cursor()
        cur.execute("""
            UPDATE deadlines
            SET status = 'dismissed', dismissed_reason = 'auto-dismissed (no confirmation after 7 days)',
                updated_at = NOW()
            WHERE status = 'pending_confirm'
              AND created_at < %s
        """, (cutoff,))
        dismissed = cur.rowcount
        conn.commit()
        cur.close()
        return dismissed
    except Exception as e:
        logger.error(f"Auto-dismiss soft deadlines failed: {e}")
        return 0
    finally:
        put_conn(conn)


# ---------------------------------------------------------------------------
# Management actions (called from action_handler.py)
# ---------------------------------------------------------------------------

def dismiss_deadline(search_text: str) -> str:
    """
    Dismiss a deadline matching the search text.
    Returns a confirmation message for the Director.
    """
    deadline = _find_deadline_by_text(search_text)
    if not deadline:
        return f"I couldn't find an active deadline matching \"{search_text}\". Try being more specific."

    from models.deadlines import update_deadline
    update_deadline(
        deadline["id"],
        status="dismissed",
        dismissed_reason="Director dismissed",
    )
    due_str = deadline["due_date"].strftime("%B %-d") if deadline.get("due_date") else "TBD"
    return (
        f"\u2705 Deadline dismissed: \"{deadline['description']}\" "
        f"(was due {due_str})"
    )


def complete_deadline(search_text: str) -> str:
    """
    Mark a deadline as completed.
    Returns a confirmation message for the Director.
    """
    deadline = _find_deadline_by_text(search_text)
    if not deadline:
        return f"I couldn't find an active deadline matching \"{search_text}\". Try being more specific."

    from models.deadlines import update_deadline
    update_deadline(
        deadline["id"],
        status="completed",
        dismissed_reason="Director confirmed completion",
    )
    return (
        f"\u2705 Deadline completed: \"{deadline['description']}\""
    )


def confirm_deadline(search_text: str, confirm_date: str = "") -> str:
    """
    Confirm a soft deadline with a hard date.
    Returns a confirmation message.
    """
    deadline = _find_deadline_by_text(search_text)
    if not deadline:
        return f"I couldn't find a pending deadline matching \"{search_text}\"."

    from models.deadlines import update_deadline

    updates = {
        "status": "active",
        "confidence": "hard",
    }

    if confirm_date:
        try:
            new_date = datetime.fromisoformat(confirm_date)
            if new_date.tzinfo is None:
                new_date = new_date.replace(tzinfo=timezone.utc)
            updates["due_date"] = new_date
            date_str = new_date.strftime("%B %-d, %Y")
        except (ValueError, TypeError):
            return f"I couldn't parse the date \"{confirm_date}\". Please use YYYY-MM-DD format."
    else:
        date_str = deadline["due_date"].strftime("%B %-d, %Y") if deadline.get("due_date") else "TBD"

    update_deadline(deadline["id"], **updates)
    return (
        f"\u2705 Deadline confirmed: \"{deadline['description']}\" \u2014 due {date_str}"
    )


def add_vip(name: str, email: str = None, whatsapp_id: str = None, role: str = None) -> str:
    """Add a VIP contact. Returns confirmation message."""
    from models.deadlines import add_vip_contact
    vip_id = add_vip_contact(name=name, role=role, email=email, whatsapp_id=whatsapp_id)
    if vip_id:
        return f"\u2705 Added {name} to the VIP list (ID: {vip_id})"
    return f"\u274c Failed to add {name} to the VIP list."


def remove_vip(name: str) -> str:
    """Remove a VIP contact by name. Returns confirmation message."""
    from models.deadlines import remove_vip_contact
    removed = remove_vip_contact(name)
    if removed:
        return f"\u2705 Removed {name} from the VIP list."
    return f"I couldn't find a VIP contact matching \"{name}\"."


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_deadline_by_text(search_text: str) -> Optional[dict]:
    """Find the best-matching active deadline for a search term."""
    from models.deadlines import get_active_deadlines

    deadlines = get_active_deadlines(limit=100)
    if not deadlines:
        return None

    search_lower = search_text.lower()
    search_words = set(search_lower.split())

    best = None
    best_score = 0

    for dl in deadlines:
        desc = (dl.get("description") or "").lower()
        # Exact substring match
        if search_lower in desc:
            return dl

        # Word overlap scoring
        desc_words = set(desc.split())
        overlap = len(search_words & desc_words)
        if overlap > best_score:
            best_score = overlap
            best = dl

    return best if best_score >= 1 else None
