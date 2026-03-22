# BRIEF: Baker 3.0 — Item 3: Post-Meeting Auto-Pipeline

**Author:** AI Head
**Date:** 2026-03-22
**Priority:** HIGH — zero-effort meeting follow-up
**Effort:** 1 session
**Assigned to:** AI Head + Code Brisen
**Depends on:** Item 0a (extraction engine)

---

## What We're Building

After every meeting, Baker automatically:
1. Detects the transcript has arrived (Fireflies)
2. Runs extraction (via Item 0a engine)
3. Produces a meeting summary package
4. Generates a follow-up email draft (if action items exist + external participants)
5. Posts summary to Slack #cockpit
6. Proposed actions appear in next push digest (Item 1)

---

## New File

### `orchestrator/meeting_pipeline.py` (NEW)

```python
def process_meeting(transcript_id: str, title: str, participants: str,
                    meeting_date: str, full_transcript: str):
    """
    Called by Fireflies trigger when a new transcript arrives.
    Runs extraction → summary → draft → Slack post.
    """

def _classify_meeting_type(title: str, participants: str) -> str:
    """
    Determine meeting type from calendar metadata.
    Returns: external | internal | one_on_one | standup | skip
    """

def _generate_summary(extracted_items: list, title: str,
                       participants: str, meeting_date: str) -> str:
    """
    Format extracted items into a clean meeting summary.
    Sections: DECISIONS, ACTION ITEMS, FOLLOW-UPS, OPEN QUESTIONS.
    """

def _generate_followup_draft(summary: str, participants: str,
                              extracted_items: list) -> str:
    """
    Generate follow-up email draft. Only called when:
    - Meeting type is 'external'
    - At least 1 action_item or commitment exists in extracted_items
    Returns draft text or None.
    """

def _post_to_slack(summary: str, title: str, meeting_date: str):
    """Post meeting summary to Slack #cockpit channel."""

def _store_summary(transcript_id: str, summary: str, meeting_type: str,
                   followup_draft: str = None):
    """Store summary in baker_tasks or a new meeting_summaries table."""
```

---

## Meeting Type Classification

| Type | How Detected | Processing |
|------|-------------|-----------|
| **external** | Participant email domains != brisengroup.com | Full package + follow-up email draft |
| **internal** | All participants @brisengroup.com | Full package, no follow-up email |
| **one_on_one** | 2 participants only | Action items only, light summary |
| **standup** | Title contains "standup", "check-in", "daily" (recurring) | Action items only if any |
| **skip** | Title contains "focus", "blocked", "personal" OR no transcript | Skip entirely |

---

## Integration: Fireflies Trigger Hook

### `triggers/fireflies_trigger.py` — Modify

After `store_meeting_transcript()` succeeds, add:

```python
# Existing: store to PostgreSQL
success = store.store_meeting_transcript(...)

if success and full_transcript:
    # NEW: trigger post-meeting pipeline
    try:
        from orchestrator.meeting_pipeline import process_meeting
        import threading
        threading.Thread(
            target=process_meeting,
            args=(source_id, title, participants, meeting_date, full_transcript),
            daemon=True
        ).start()
        logger.info(f"Post-meeting pipeline triggered for: {title}")
    except Exception as e:
        logger.warning(f"Post-meeting pipeline failed (non-fatal): {e}")
```

---

## Follow-Up Email Draft

**Safety rule (Cowork pushback #6):** Follow-up drafts are ALWAYS pending approval. Never auto-sent.

```python
def _generate_followup_draft(summary, participants, extracted_items):
    # Only generate if action items exist
    action_items = [i for i in extracted_items if i["type"] in ("action_item", "commitment")]
    if not action_items:
        return None

    prompt = f"""Draft a brief, professional follow-up email for this meeting.

Meeting participants: {participants}

Meeting summary:
{summary}

Action items agreed:
{json.dumps(action_items, indent=2)}

Rules:
- Address external participants by name
- List agreed action items with owners and deadlines
- Keep it under 200 words
- Professional but warm tone
- End with "Please let me know if I've missed anything"
- Do NOT include any information not discussed in the meeting
"""
    # Haiku call — cheap
    response = call_haiku(prompt)

    # Store as pending draft (existing pending_drafts table)
    store_pending_draft(
        draft_text=response,
        recipients=external_participants,
        subject=f"Follow-up: {title}",
        source="meeting_pipeline",
        source_id=transcript_id,
        # Include transcript link for Director review
        metadata={"transcript_id": transcript_id, "review_note": "Review full transcript before sending"}
    )
    return response
```

---

## Slack #cockpit Post

```python
def _post_to_slack(summary, title, meeting_date):
    from outputs.slack_notifier import post_to_slack

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"Meeting Summary: {title}"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{meeting_date}_"}]},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": summary}},
    ]
    post_to_slack(blocks=blocks, text=f"Meeting summary: {title}")
```

---

## Flow Diagram

```
Fireflies delivers transcript (30-90 min after meeting)
    ↓
fireflies_trigger.py detects new transcript
    ↓
store_meeting_transcript() → PostgreSQL (existing)
    ↓
process_meeting() starts in background thread
    ↓
1. _classify_meeting_type() → external/internal/standup/skip
    ↓ (if skip → return)
2. extraction_engine.extract_signal("meeting", ..., tier=tier)
    → Returns extracted_items (action items, decisions, deadlines, etc.)
    ↓
3. _generate_summary(extracted_items) → formatted summary text
    ↓
4. IF external + action items exist:
    _generate_followup_draft() → stored as pending_draft (NEVER auto-sent)
    ↓
5. _post_to_slack(summary) → Slack #cockpit
    ↓
6. _store_summary() → baker_tasks or meeting_summaries
    ↓
7. Proposed actions from extraction already in signal_extractions
    → Appear in next morning/evening push digest (Item 1)
```

---

## Testing

1. **Unit test:** Feed a sample transcript → verify summary has correct sections
2. **Unit test:** External meeting with action items → verify draft generated
3. **Unit test:** Internal meeting → verify no draft generated
4. **Unit test:** Standup with no action items → verify minimal output
5. **Integration test:** Trigger Fireflies sync → verify full pipeline fires
6. **Slack test:** Verify summary appears in #cockpit
7. **Safety test:** Verify follow-up draft is in pending_drafts, NOT in sent_emails

---

## Files Modified

| File | Change |
|------|--------|
| `orchestrator/meeting_pipeline.py` | NEW — all meeting pipeline logic |
| `triggers/fireflies_trigger.py` | Add hook to trigger pipeline after transcript storage |
