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
from datetime import date, datetime, timedelta, timezone
from typing import Optional


from config.settings import config

logger = logging.getLogger("baker.deadline_manager")

DIRECTOR_EMAIL = "dvallen@brisengroup.com"
DIRECTOR_WHATSAPP = "41799605092@c.us"
DIRECTOR_SPEAKER_LABELS = {"dimitry", "dimitry vallen", "director"}

# AMEX_RECURRING_DEADLINE_1: recurrence types accepted on the deadlines.recurrence column.
RECURRENCE_VALUES = {"monthly", "weekly", "quarterly", "annual"}


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
    source_agent: str = "",
    subject: str = "",
) -> int:
    """
    Extract deadlines from ingested content using Claude Haiku.
    Inserts valid deadlines into PostgreSQL.
    Returns the number of deadlines inserted.

    Called by sentinel triggers after content ingestion.
    """
    if not content or len(content.strip()) < 20:
        return 0

    # DEADLINE_EXTRACTOR_QUALITY_1 — for source_type='email', gate the LLM
    # call behind a deterministic L1 (sender) + L2 (keyword) noise filter.
    # Drops are recorded in deadline_extractor_suppressions for tuning.
    _filter_action = "allow"
    try:
        if source_type == "email":
            from orchestrator.deadline_extractor_filter import classify, log_suppression
            _f_result = classify(sender_email or "", subject or "", content)
            if _f_result.action != "allow":
                log_suppression(
                    sender_email=sender_email or "",
                    subject=subject or "",
                    result=_f_result,
                    source_id=source_id,
                    source_type=source_type,
                )
                logger.info(
                    f"deadline_extractor_filter [{_f_result.layer}/{_f_result.action}] "
                    f"sender={sender_email!r} reason={_f_result.reason[:120]}"
                )
                if _f_result.action == "drop":
                    return 0
                _filter_action = _f_result.action  # 'downgrade'
    except Exception as _fe:
        logger.warning(f"deadline_extractor_filter: classify-error (non-fatal): {_fe}")

    try:
        from orchestrator.gemini_client import call_flash
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        resp = call_flash(
            messages=[{
                "role": "user",
                "content": f"Today's date: {today}\n\nContent to analyze:\n{content[:4000]}",
            }],
            max_tokens=1000,
            system=_EXTRACTION_SYSTEM,
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="extract_deadlines")
        except Exception:
            pass
        raw = resp.text.strip()
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
            new_snippet = f"{old_snippet}\n[{source_type}] {content}".strip()
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

        # DEADLINE_EXTRACTOR_QUALITY_1 — L2 mid-score → force priority='low'
        # so Director sees it once but it doesn't enter the cadence engine
        # at normal/high tier.
        if _filter_action == "downgrade" and priority not in ("critical", "high"):
            priority = "low"

        snippet = content

        # CORTEX-PHASE-2B-II: Route through event bus when flag ON
        _use_cortex = False
        try:
            from memory.store_back import SentinelStoreBack
            _cstore = SentinelStoreBack._get_global_instance()
            _use_cortex = _cstore.get_cortex_config('tool_router_enabled', False)
        except Exception:
            pass

        if _use_cortex:
            from models.cortex import cortex_create_deadline
            dl_id = cortex_create_deadline(
                description=description,
                due_date=due_date,
                source_type=source_type,
                source_agent=source_agent or f"{source_type}_pipeline",
                confidence=confidence,
                priority=priority,
                source_id=source_id,
                source_snippet=snippet,
            )
        else:
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

    # Auto-dismiss active deadlines that are overdue by 7+ days
    overdue_dismissed = _auto_dismiss_overdue_deadlines()

    # Auto-dismiss undated soft obligations after 14 days (Session 26)
    undated_dismissed = _auto_dismiss_undated_soft()

    logger.info(
        f"Cadence check complete: {alerts_fired} reminders fired, "
        f"{expired} expired, {dismissed} soft auto-dismissed, "
        f"{overdue_dismissed} overdue auto-dismissed, "
        f"{undated_dismissed} undated soft auto-dismissed, "
        f"{len(deadlines)} active deadlines checked"
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


# ---------------------------------------------------------------------------
# Phase 3B: Deadline proposal generation (Haiku)
# ---------------------------------------------------------------------------

_DEADLINE_PROPOSAL_PROMPT = """You are Baker, AI Chief of Staff for Dimitry Vallen (Chairman, Brisen Group).

A deadline is approaching. Generate 2-3 specific, actionable proposals the Director should consider.

For each proposal, specify:
- label: Short name (e.g., "Send status check")
- description: One line explaining what this produces
- type: draft|analyze|plan
- prompt: The full prompt Baker should execute if Director selects this

Be specific — reference people, matters, and context provided.
If the deadline is overdue, propose recovery actions.

Return ONLY valid JSON with this structure:
{
  "problem": "What's at stake if this deadline is missed",
  "cause": "Current status — what's been done, what hasn't",
  "solution": "What success looks like",
  "parts": [
    {
      "label": "Group label",
      "actions": [
        {"label": "Action name", "description": "...", "type": "draft", "prompt": "..."}
      ]
    }
  ]
}
"""


def _generate_deadline_proposal(deadline: dict, stage: str, hours_remaining: float) -> Optional[dict]:
    """Generate action proposals for a deadline alert using Haiku (fast + cheap)."""
    try:
        description = deadline.get("description", "")
        due_date = deadline.get("due_date")
        due_str = due_date.strftime("%Y-%m-%d") if due_date else "TBD"
        priority = deadline.get("priority", "normal")
        source_snippet = (deadline.get("source_snippet") or "")[:500]

        context = (
            f"Deadline: {description}\n"
            f"Due date: {due_str}\n"
            f"Stage: {stage} ({int(hours_remaining)}h remaining)\n"
            f"Priority: {priority}\n"
        )
        if source_snippet:
            context += f"Source context: {source_snippet}\n"

        from orchestrator.gemini_client import call_flash
        resp = call_flash(
            messages=[{"role": "user", "content": context}],
            max_tokens=1500,
            system=_DEADLINE_PROPOSAL_PROMPT,
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="deadline_proposal")
        except Exception:
            pass
        raw = resp.text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        parsed = json.loads(raw)
        if "parts" in parsed and isinstance(parsed["parts"], list):
            logger.info(f"Generated deadline proposal: {len(parsed['parts'])} parts")
            return parsed
        logger.warning("Deadline proposal missing 'parts' key — discarding")
        return None
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Deadline proposal generation failed: {e}")
        return None


def _is_travel_deadline(description: str) -> bool:
    """TRAVEL-HYGIENE-1: Check if deadline is travel-related."""
    travel_keywords = ['flight', 'departure', 'airport', 'check-in', 'travel', 'train']
    desc_lower = (description or "").lower()
    return any(kw in desc_lower for kw in travel_keywords)


def _update_travel_alert_for_deadline(deadline: dict, stage: str):
    """TRAVEL-HYGIENE-1: Find existing travel alert and update its title/body for new stage.
    Uses Europe/Zurich timezone for day labels. Never creates a second alert."""
    from memory.store_back import SentinelStoreBack
    from zoneinfo import ZoneInfo
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return
    try:
        import psycopg2.extras
        description = deadline.get("description", "Untitled")
        due_date = deadline.get("due_date")

        # Build stage-appropriate title with Europe/Zurich timezone
        director_tz = ZoneInfo("Europe/Zurich")
        now_local = datetime.now(director_tz).date()
        if due_date and hasattr(due_date, 'astimezone'):
            due_local = due_date.astimezone(director_tz).date()
        elif due_date and hasattr(due_date, 'date'):
            due_local = due_date.date()
        else:
            due_local = now_local
        days_until = (due_local - now_local).days

        if days_until <= 0:
            title = f"TODAY: {description}"
        elif days_until == 1:
            title = f"Tomorrow: {description}"
        else:
            title = f"In {days_until}d: {description}"

        priority = deadline.get("priority", "normal")
        body = f"{description} (due {due_local.strftime('%B %-d')}, {priority.upper()})"

        # Find existing travel alert and UPDATE it
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id FROM alerts
            WHERE status = 'pending'
              AND (tags ? 'travel' OR title ILIKE '%%flight%%' OR title ILIKE '%%departure%%')
              AND (title ILIKE %s OR body ILIKE %s)
            ORDER BY created_at DESC LIMIT 1
        """, (f"%{description[:30]}%", f"%{description[:30]}%"))
        existing = cur.fetchone()

        if existing:
            cur.execute(
                "UPDATE alerts SET title = %s, body = %s, updated_at = NOW() WHERE id = %s",
                (title, body, existing['id']),
            )
            conn.commit()
            logger.info(f"TRAVEL-HYGIENE-1: updated travel alert #{existing['id']} to '{title}'")
        else:
            # No existing alert — create one with travel tag
            conn.commit()  # close any pending txn
            store.create_alert(
                tier=2, title=title, body=body,
                action_required=False, tags=["travel", "deadline"],
                source="deadline_cadence",
                source_id=f"travel-deadline:{deadline.get('id')}",
            )
            logger.info(f"TRAVEL-HYGIENE-1: created new travel alert — {title}")
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.warning(f"_update_travel_alert_for_deadline failed: {e}")
    finally:
        store._put_conn(conn)


def _fire_reminder(deadline: dict, stage: str, hours_remaining: float):
    """Send a reminder via the appropriate channel based on stage.
    Creates a DB alert for urgent stages and attaches Haiku proposals (Phase 3B).
    """
    description = deadline.get("description", "Untitled")
    priority = deadline.get("priority", "normal")
    due_date = deadline.get("due_date")
    due_str = due_date.strftime("%B %-d") if due_date else "TBD"

    priority_label = {"critical": "CRITICAL \u2014 your commitment",
                      "high": "HIGH \u2014 VIP request",
                      "normal": "NORMAL"}.get(priority, priority)

    # TRAVEL-HYGIENE-1: Travel deadlines update existing alert, never create new
    if _is_travel_deadline(description) and stage in ("48h", "day_of", "overdue"):
        _update_travel_alert_for_deadline(deadline, stage)
        # Still push to digest buffer
        try:
            from orchestrator.digest_manager import add_alert
            from zoneinfo import ZoneInfo
            director_tz = ZoneInfo("Europe/Zurich")
            now_local = datetime.now(director_tz).date()
            _due = due_date
            if _due and hasattr(_due, 'astimezone'):
                _due_local = _due.astimezone(director_tz).date()
            elif _due and hasattr(_due, 'date'):
                _due_local = _due.date()
            else:
                _due_local = now_local
            _days = (_due_local - now_local).days
            if _days <= 0:
                _label = f"TODAY: {description}"
            elif _days == 1:
                _label = f"Tomorrow: {description}"
            else:
                _label = f"In {_days}d: {description}"
            add_alert(
                title=_label,
                source_type="Deadline",
                timestamp=datetime.now(timezone.utc).strftime("%H:%M UTC"),
                tier=2,
                source_id=f"deadline:{deadline.get('id')}",
                content=f"{description} (due {due_str})",
                is_critical=False,
            )
        except Exception:
            pass
        return

    # Stages 48h, day_of, overdue → push to digest buffer + create DB alert
    if stage in ("48h", "day_of", "overdue"):
        # TRAVEL-HYGIENE-1 Fix 6: Timezone-aware labels
        from zoneinfo import ZoneInfo
        director_tz = ZoneInfo("Europe/Zurich")
        now_local = datetime.now(director_tz).date()

        if stage == "overdue":
            title = f"OVERDUE: {description}"
        elif stage == "day_of":
            if due_date and hasattr(due_date, 'astimezone'):
                due_local = due_date.astimezone(director_tz).date()
            elif due_date and hasattr(due_date, 'date'):
                due_local = due_date.date()
            else:
                due_local = now_local
            if now_local == due_local:
                title = f"DUE TODAY: {description}"
            elif (due_local - now_local).days == 1:
                title = f"Due tomorrow: {description}"
            else:
                title = f"Due {due_str}: {description}"
        else:
            title = f"Due in 48h: {description}"

        body = f"{description} (due {due_str}, {priority_label})"
        tier = 1

        # Push to digest buffer
        try:
            from orchestrator.digest_manager import add_alert
            is_critical = priority == "critical" and stage in ("48h", "day_of")
            add_alert(
                title=title,
                source_type="Deadline",
                timestamp=datetime.now(timezone.utc).strftime("%H:%M UTC"),
                tier=tier,
                source_id=f"deadline:{deadline.get('id')}",
                content=body,
                is_critical=is_critical,
            )
        except Exception as e:
            logger.warning(f"Deadline digest alert failed: {e}")

        # Create DB alert + attach Haiku proposals (Phase 3B)
        # source_id dedup: same deadline + same stage = one alert only.
        # Prevents duplicate T1 alerts (and wasted Haiku proposal API calls).
        dl_source_id = f"deadline:{deadline.get('id')}:{stage}"
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            alert_id = store.create_alert(
                tier=tier,
                title=title,
                body=body,
                action_required=True,
                tags=["deadline"],
                source="deadline_cadence",
                source_id=dl_source_id,
            )
            if alert_id:
                proposal = _generate_deadline_proposal(deadline, stage, hours_remaining)
                if proposal:
                    store.update_alert_structured_actions(alert_id, proposal)
                    logger.info(f"Deadline proposal attached to alert #{alert_id}")
        except Exception as e:
            logger.warning(f"Deadline DB alert/proposal failed: {e}")

        logger.info(f"Deadline alert [{stage}]: {description}")

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


def _auto_dismiss_overdue_deadlines() -> int:
    """Auto-dismiss active deadlines that are overdue by 3+ days.
    Prevents stale overdue deadlines from accumulating indefinitely.
    Skips items flagged as critical — those persist until Director marks them done.
    """
    from models.deadlines import get_conn, put_conn
    conn = get_conn()
    if not conn:
        return 0
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        cur = conn.cursor()
        cur.execute("""
            UPDATE deadlines
            SET status = 'dismissed',
                dismissed_reason = 'auto-dismissed (overdue by 3+ days)',
                updated_at = NOW()
            WHERE status = 'active'
              AND due_date < %s
              AND (is_critical IS NOT TRUE)
              AND recurrence IS NULL
        """, (cutoff,))
        dismissed = cur.rowcount
        conn.commit()
        cur.close()
        if dismissed > 0:
            logger.info(f"Auto-dismissed {dismissed} deadlines overdue by 3+ days")
        return dismissed
    except Exception as e:
        logger.error(f"Auto-dismiss overdue deadlines failed: {e}")
        return 0
    finally:
        put_conn(conn)


def _auto_dismiss_soft_deadlines() -> int:
    """Auto-dismiss pending_confirm deadlines with no response after 3 days."""
    from models.deadlines import get_conn, put_conn
    conn = get_conn()
    if not conn:
        return 0
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        cur = conn.cursor()
        cur.execute("""
            UPDATE deadlines
            SET status = 'dismissed', dismissed_reason = 'auto-dismissed (no confirmation after 3 days)',
                updated_at = NOW()
            WHERE status = 'pending_confirm'
              AND created_at < %s
              AND (is_critical IS NOT TRUE)
              AND recurrence IS NULL
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


def _auto_dismiss_undated_soft() -> int:
    """Auto-dismiss soft obligations with no due_date after 7 days.
    These are extracted action items with no specific deadline — they accumulate
    indefinitely without this cleanup.
    """
    from models.deadlines import get_conn, put_conn
    conn = get_conn()
    if not conn:
        return 0
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        cur = conn.cursor()
        cur.execute("""
            UPDATE deadlines
            SET status = 'dismissed',
                dismissed_reason = 'auto-dismissed (undated soft obligation, 7+ days old)',
                updated_at = NOW()
            WHERE status = 'active'
              AND severity = 'soft'
              AND due_date IS NULL
              AND created_at < %s
              AND (is_critical IS NOT TRUE)
        """, (cutoff,))
        dismissed = cur.rowcount
        conn.commit()
        cur.close()
        if dismissed > 0:
            logger.info(f"Auto-dismissed {dismissed} undated soft obligations (7+ days old)")
        return dismissed
    except Exception as e:
        logger.error(f"Auto-dismiss undated soft failed: {e}")
        return 0
    finally:
        put_conn(conn)


# ---------------------------------------------------------------------------
# Management actions (called from action_handler.py)
# ---------------------------------------------------------------------------

def dismiss_deadline(search_text: str, scope: str = "instance") -> str:
    """
    Dismiss a deadline matching the search text.

    AMEX_RECURRING_DEADLINE_1: For recurring deadlines, scope distinguishes
    "this instance only" (default) from "stop the entire recurrence chain".

    Args:
        search_text: free-text search.
        scope: 'instance' (default — dismiss this row, recurrence keeps respawning),
               'recurrence' (dismiss this row AND null out recurrence to halt the chain).

    Returns confirmation message; if recurring + scope unset, asks Director to choose.
    """
    deadline = _find_deadline_by_text(search_text)
    if not deadline:
        return f"I couldn't find an active deadline matching \"{search_text}\". Try being more specific."

    from models.deadlines import update_deadline
    is_recurring = bool(deadline.get("recurrence"))
    due_str = deadline["due_date"].strftime("%B %-d") if deadline.get("due_date") else "TBD"

    if is_recurring and scope == "recurrence":
        # Halt recurrence on the chain root + this row.
        root_id = deadline.get("parent_deadline_id") or deadline["id"]
        _halt_recurrence_chain(root_id)
        update_deadline(
            deadline["id"],
            status="dismissed",
            dismissed_reason="Director dismissed (stop recurrence)",
        )
        return (
            f"\u2705 Recurrence stopped + deadline dismissed: "
            f"\"{deadline['description']}\" (was due {due_str})"
        )

    update_deadline(
        deadline["id"],
        status="dismissed",
        dismissed_reason="Director dismissed",
    )
    if is_recurring:
        return (
            f"\u2705 Deadline dismissed: \"{deadline['description']}\" "
            f"(was due {due_str}). Recurrence kept active — next instance will respawn. "
            f"Reply with `dismiss \"{search_text}\" stop` to halt the entire recurrence."
        )
    return (
        f"\u2705 Deadline dismissed: \"{deadline['description']}\" "
        f"(was due {due_str})"
    )


def _halt_recurrence_chain(root_id: int) -> bool:
    """AMEX_RECURRING_DEADLINE_1: null recurrence on root + active children."""
    from models.deadlines import get_conn, put_conn
    conn = get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            """UPDATE deadlines
               SET recurrence = NULL, updated_at = NOW()
               WHERE (id = %s OR parent_deadline_id = %s)
                 AND recurrence IS NOT NULL""",
            (root_id, root_id),
        )
        conn.commit()
        cur.close()
        logger.info(f"recurrence chain halted on root #{root_id}")
        return True
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"_halt_recurrence_chain failed for #{root_id}: {e}")
        return False
    finally:
        put_conn(conn)


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
    # AMEX_RECURRING_DEADLINE_1: spawn next instance if recurring (Amendment H path 1/3).
    _maybe_respawn_recurring(deadline["id"])
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
        return f"\u2705 Added {name} to contacts (ID: {vip_id})"
    return f"\u274c Failed to add {name} to contacts."


def remove_vip(name: str) -> str:
    """Remove a VIP contact by name. Returns confirmation message."""
    from models.deadlines import remove_vip_contact
    removed = remove_vip_contact(name)
    if removed:
        return f"\u2705 Removed {name} from contacts."
    return f"I couldn't find a contact matching \"{name}\"."


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


# ---------------------------------------------------------------------------
# AMEX_RECURRING_DEADLINE_1: recurrence helpers
# ---------------------------------------------------------------------------

def compute_next_due(recurrence: str, anchor: date) -> date:
    """Return the next due date for a recurring deadline.

    monthly  → +1 month   (relativedelta clamps Jan 31 → Feb 28/29 → Mar 31)
    weekly   → +7 days
    quarterly→ +3 months
    annual   → +1 year    (Feb 29 of leap year → Feb 28 next year via relativedelta)

    Raises ValueError on unknown recurrence string.
    """
    from dateutil.relativedelta import relativedelta

    if recurrence not in RECURRENCE_VALUES:
        raise ValueError(
            f"compute_next_due: unknown recurrence {recurrence!r} "
            f"(allowed: {sorted(RECURRENCE_VALUES)})"
        )
    if isinstance(anchor, datetime):
        anchor = anchor.date()
    if recurrence == "weekly":
        return anchor + timedelta(days=7)
    if recurrence == "monthly":
        return anchor + relativedelta(months=+1)
    if recurrence == "quarterly":
        return anchor + relativedelta(months=+3)
    if recurrence == "annual":
        return anchor + relativedelta(years=+1)
    raise ValueError(recurrence)  # unreachable


def _maybe_respawn_recurring(
    deadline_id: int,
    *,
    conn=None,
) -> Optional[int]:
    """Spawn next instance of a recurring deadline. Idempotent + capped.

    Behaviour:
      - If the row's `recurrence` is NULL → no-op, return None.
      - Compute next anchor via `compute_next_due()`.
      - Idempotency: if a child with same root + same anchor already exists, return its id.
      - Cap-rate: if any child of this root was created in the last 24h, log a
        warning, push a Slack DM to Director, and return None (silent loop guard).
      - Otherwise INSERT new row copying description/priority/source_type, link
        parent_deadline_id to the chain root, increment recurrence_count, return new id.

    Args:
        deadline_id: the deadline that was just completed.
        conn: optional psycopg2 connection (for tests).

    Returns:
        New child deadline id, OR existing child id (idempotent), OR None.
    """
    from models.deadlines import get_conn, put_conn

    own_conn = conn is None
    if own_conn:
        conn = get_conn()
        if conn is None:
            return None
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, description, priority, source_type, source_snippet,
                      recurrence, recurrence_anchor_date, recurrence_count,
                      parent_deadline_id, severity, matter_slug
               FROM deadlines WHERE id = %s""",
            (deadline_id,),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            return None
        (parent_id, description, priority, source_type, source_snippet,
         recurrence, anchor, count, parent_deadline_id, severity, matter_slug) = row

        if not recurrence:
            cur.close()
            return None
        if recurrence not in RECURRENCE_VALUES:
            logger.warning(
                f"_maybe_respawn_recurring: deadline #{parent_id} has unknown "
                f"recurrence {recurrence!r} — skipping"
            )
            cur.close()
            return None
        if anchor is None:
            logger.warning(
                f"_maybe_respawn_recurring: deadline #{parent_id} has "
                f"recurrence={recurrence!r} but no recurrence_anchor_date — skipping"
            )
            cur.close()
            return None

        root_id = parent_deadline_id or parent_id
        next_anchor = compute_next_due(recurrence, anchor)

        # Idempotency: child with same root + same anchor already exists.
        cur.execute(
            """SELECT id FROM deadlines
               WHERE parent_deadline_id = %s
                 AND recurrence_anchor_date = %s
               LIMIT 1""",
            (root_id, next_anchor),
        )
        existing = cur.fetchone()
        if existing:
            cur.close()
            return existing[0]

        # Cap-rate: any child of this root in last 24h → silent-loop guard.
        cur.execute(
            """SELECT COUNT(*) FROM deadlines
               WHERE parent_deadline_id = %s
                 AND created_at > NOW() - INTERVAL '1 day'""",
            (root_id,),
        )
        recent = cur.fetchone()[0]
        if recent > 0:
            cur.close()
            _alert_respawn_cap_hit(parent_id, root_id, recurrence)
            return None

        next_due = datetime.combine(next_anchor, datetime.min.time(), tzinfo=timezone.utc)
        cur.execute(
            """INSERT INTO deadlines
                 (description, due_date, source_type, source_id, source_snippet,
                  confidence, priority, status, severity, matter_slug,
                  recurrence, recurrence_anchor_date, recurrence_count, parent_deadline_id)
               VALUES (%s, %s, %s, %s, %s, 'hard', %s, 'active', %s, %s,
                       %s, %s, %s, %s)
               RETURNING id""",
            (
                description, next_due, source_type or "recurrence",
                f"recurrence_parent:{root_id}",
                (source_snippet or "")[:4000],
                priority or "normal",
                severity or "firm",
                matter_slug,
                recurrence, next_anchor, (count or 0) + 1, root_id,
            ),
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        logger.info(
            f"recurrence respawn: deadline #{parent_id} ({recurrence}) → #{new_id} "
            f"due {next_anchor} (root #{root_id}, count {(count or 0) + 1})"
        )
        return new_id
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"_maybe_respawn_recurring failed for #{deadline_id}: {e}")
        return None
    finally:
        if own_conn:
            put_conn(conn)


def _alert_respawn_cap_hit(deadline_id: int, root_id: int, recurrence: str) -> None:
    """Cap-rate alert: silent-infinite-loop guard fired. Push to Director Slack DM."""
    msg = (
        f":rotating_light: Deadline recurrence cap hit on root #{root_id} "
        f"(triggered by completion of #{deadline_id}, recurrence={recurrence}). "
        f"Respawn skipped — investigate misconfigured anchor."
    )
    logger.warning(f"recurrence cap-rate hit: deadline #{deadline_id} root #{root_id}")
    try:
        from triggers.ai_head_audit import _safe_post_dm
        _safe_post_dm(msg)
    except Exception as e:
        logger.warning(f"recurrence cap-rate alert: Slack DM failed (non-fatal): {e}")
