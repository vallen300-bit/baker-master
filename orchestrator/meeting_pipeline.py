"""
Baker 3.0 — Item 3: Post-Meeting Auto-Pipeline

After every meeting, Baker automatically:
1. Runs extraction (via Item 0a engine)
2. Classifies meeting type (external/internal/standup/skip)
3. Generates a meeting summary package
4. Generates a follow-up email draft (if action items + external participants)
5. Posts summary to Slack #cockpit
6. Stores proposed actions for next push digest

Safety rule: Follow-up drafts are ALWAYS pending approval. Never auto-sent.
"""
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger("baker.meeting_pipeline")

# ─────────────────────────────────────────────────
# Meeting type classification
# ─────────────────────────────────────────────────

_SKIP_TITLE_PATTERNS = re.compile(
    r"\b(focus|blocked|personal|lunch|break|travel|flight)\b", re.IGNORECASE
)
_STANDUP_TITLE_PATTERNS = re.compile(
    r"\b(standup|stand.up|check.in|daily|sync|huddle)\b", re.IGNORECASE
)
_INTERNAL_DOMAINS = {"brisengroup.com", "brisen.com"}


def _classify_meeting_type(title, participants):
    """Classify meeting type from calendar metadata.
    Returns: external, internal, one_on_one, standup, skip"""
    title = title or ""
    participants = participants or ""

    # Skip detection
    if _SKIP_TITLE_PATTERNS.search(title):
        return "skip"

    # Standup detection
    if _STANDUP_TITLE_PATTERNS.search(title):
        return "standup"

    # Participant analysis
    participant_list = [p.strip() for p in participants.split(",") if p.strip()]

    if len(participant_list) <= 2:
        return "one_on_one"

    # Check for external domains in participant names/emails
    has_external = False
    for p in participant_list:
        # Check if participant email is from an external domain
        email_match = re.search(r'[\w.-]+@([\w.-]+)', p)
        if email_match:
            domain = email_match.group(1).lower()
            if domain not in _INTERNAL_DOMAINS:
                has_external = True
                break
        # If no email, assume external if it's a recognizable external name
        # (conservative: default to internal)

    return "external" if has_external else "internal"


# ─────────────────────────────────────────────────
# Summary generation
# ─────────────────────────────────────────────────

def _generate_summary(extracted_items, title, participants, meeting_date):
    """Format extracted items into a clean meeting summary."""
    decisions = [i for i in extracted_items if i.get("type") == "decision"]
    action_items = [i for i in extracted_items
                    if i.get("type") in ("action_item", "commitment")]
    follow_ups = [i for i in extracted_items if i.get("type") == "follow_up"]
    questions = [i for i in extracted_items if i.get("type") == "question"]
    deadlines = [i for i in extracted_items if i.get("type") == "deadline"]
    financials = [i for i in extracted_items if i.get("type") == "financial"]

    lines = []
    lines.append(f"**Meeting: {title}**")
    if meeting_date:
        lines.append(f"Date: {meeting_date}")
    if participants:
        lines.append(f"Participants: {participants}")
    lines.append("")

    if decisions:
        lines.append(f"**DECISIONS ({len(decisions)}):**")
        for d in decisions:
            lines.append(f"- {d.get('text', '')}")
        lines.append("")

    if action_items:
        lines.append(f"**ACTION ITEMS ({len(action_items)}):**")
        for a in action_items:
            owner = a.get("who", "TBD")
            deadline = f" (by {a['when']})" if a.get("when") else ""
            lines.append(f"- {owner} → {a.get('text', '')}{deadline}")
        lines.append("")

    if deadlines:
        lines.append(f"**DEADLINES ({len(deadlines)}):**")
        for dl in deadlines:
            lines.append(f"- {dl.get('text', '')} — {dl.get('when', 'no date')}")
        lines.append("")

    if follow_ups:
        lines.append(f"**FOLLOW-UPS ({len(follow_ups)}):**")
        for f in follow_ups:
            lines.append(f"- {f.get('text', '')}")
        lines.append("")

    if questions:
        lines.append(f"**OPEN QUESTIONS ({len(questions)}):**")
        for q in questions:
            lines.append(f"- {q.get('text', '')}")
        lines.append("")

    if financials:
        lines.append(f"**FINANCIAL ({len(financials)}):**")
        for fin in financials:
            lines.append(f"- {fin.get('text', '')}")
        lines.append("")

    if not any([decisions, action_items, follow_ups, questions, deadlines, financials]):
        lines.append("No structured items extracted from this meeting.")

    return "\n".join(lines)


# ─────────────────────────────────────────────────
# Follow-up email draft
# ─────────────────────────────────────────────────

def _generate_followup_draft(summary, title, participants, extracted_items,
                              transcript_id):
    """Generate follow-up email draft. Only for external meetings with action items.
    SAFETY: Always stored as pending draft. Never auto-sent."""
    action_items = [i for i in extracted_items
                    if i.get("type") in ("action_item", "commitment", "follow_up")]
    if not action_items:
        return None

    try:
        import anthropic
        client = anthropic.Anthropic()

        action_text = "\n".join(
            f"- {a.get('who', 'TBD')}: {a.get('text', '')} "
            f"{'(by ' + a['when'] + ')' if a.get('when') else ''}"
            for a in action_items
        )

        prompt = f"""Draft a brief, professional follow-up email for this meeting.

Meeting: {title}
Participants: {participants}

Action items agreed:
{action_text}

Rules:
- Address external participants by name
- List agreed action items with owners and deadlines
- Keep it under 200 words
- Professional but warm tone
- End with "Please let me know if I've missed anything."
- Do NOT include any information not discussed in the meeting"""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )

        draft_text = response.content[0].text.strip()

        # Store as pending draft (NEVER auto-sent — Cowork pushback #6)
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            conn = store._get_conn()
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO pending_drafts
                            (draft_type, subject, body, recipients, source, source_id, metadata)
                        VALUES ('email', %s, %s, %s, 'meeting_pipeline', %s, %s)
                    """, (
                        f"Follow-up: {title}",
                        draft_text,
                        participants,
                        transcript_id,
                        json.dumps({
                            "transcript_id": transcript_id,
                            "review_note": "Review full transcript before sending",
                            "auto_generated": True,
                        }),
                    ))
                    conn.commit()
                    cur.close()
                    logger.info(f"Follow-up draft stored for: {title}")
                finally:
                    store._put_conn(conn)
        except Exception as e:
            logger.warning(f"Failed to store follow-up draft: {e}")

        return draft_text

    except Exception as e:
        logger.error(f"Follow-up draft generation failed: {e}")
        return None


# ─────────────────────────────────────────────────
# Slack posting
# ─────────────────────────────────────────────────

def _post_to_slack(summary, title, meeting_date):
    """Post meeting summary to Slack #cockpit channel."""
    try:
        from outputs.slack_notifier import post_to_slack
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f"Meeting Summary: {title}"}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{meeting_date or 'Today'}_"}]},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": summary[:2900]}},
        ]
        post_to_slack(blocks=blocks, text=f"Meeting summary: {title}")
        logger.info(f"Meeting summary posted to Slack: {title}")
    except Exception as e:
        logger.warning(f"Slack post failed for meeting summary (non-fatal): {e}")


# ─────────────────────────────────────────────────
# Summary storage
# ─────────────────────────────────────────────────

def _store_summary(transcript_id, title, summary, meeting_type, extracted_items):
    """Store meeting summary as a baker_task for dashboard visibility."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        store.create_alert(
            tier=3,
            title=f"Meeting summary: {title}",
            body=summary[:4000],
            tags=["meeting_summary", meeting_type],
            source="meeting_pipeline",
            source_id=f"meeting-summary-{transcript_id}",
        )
    except Exception as e:
        logger.warning(f"Failed to store meeting summary: {e}")


# ─────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────

def process_meeting(transcript_id, title, participants, meeting_date,
                    full_transcript):
    """
    Process a meeting transcript through the full auto-pipeline.
    Called as a background thread from fireflies_trigger.py.

    Flow:
    1. Classify meeting type
    2. Run extraction engine (Item 0a)
    3. Generate summary
    4. Generate follow-up draft (if external + action items)
    5. Post to Slack #cockpit
    6. Store summary for dashboard
    """
    start = time.time()
    logger.info(f"Post-meeting pipeline starting: {title} ({transcript_id})")

    try:
        # 1. Classify meeting type
        meeting_type = _classify_meeting_type(title, participants)
        logger.info(f"Meeting type: {meeting_type}")

        if meeting_type == "skip":
            logger.info(f"Skipping meeting (type=skip): {title}")
            return

        # 2. Run extraction engine
        from orchestrator.extraction_engine import extract_signal_sync
        extracted_items = extract_signal_sync(
            source_channel="meeting",
            source_id=transcript_id,
            content=full_transcript,
            tier=2 if meeting_type == "external" else 3,
        )

        if not extracted_items:
            logger.info(f"No items extracted from meeting: {title}")
            # Still generate a minimal summary
            extracted_items = []

        logger.info(f"Extracted {len(extracted_items)} items from meeting: {title}")

        # 3. Generate summary
        summary = _generate_summary(extracted_items, title, participants, meeting_date)

        # 4. Follow-up email draft (external meetings with action items only)
        if meeting_type == "external":
            _generate_followup_draft(
                summary, title, participants, extracted_items, transcript_id
            )

        # 5. Post to Slack #cockpit
        _post_to_slack(summary, title, meeting_date)

        # 6. Store summary for dashboard
        _store_summary(transcript_id, title, summary, meeting_type, extracted_items)

        elapsed_ms = int((time.time() - start) * 1000)
        logger.info(
            f"Post-meeting pipeline complete: {title} "
            f"({meeting_type}, {len(extracted_items)} items, {elapsed_ms}ms)"
        )

    except Exception as e:
        logger.error(f"Post-meeting pipeline failed for {title}: {e}", exc_info=True)


def process_meeting_async(transcript_id, title, participants, meeting_date,
                          full_transcript):
    """Non-blocking wrapper — fires process_meeting in a background thread."""
    threading.Thread(
        target=process_meeting,
        args=(transcript_id, title, participants, meeting_date, full_transcript),
        daemon=True,
        name=f"meeting-pipeline-{transcript_id[:8]}",
    ).start()
