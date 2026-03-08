# Phase 3C — Commitment Tracker, Proactive Intelligence, Calendar Protection

**Author:** Code 300 (architect)
**Date:** 2026-03-08
**Branch:** `feat/phase-3c-advanced`
**Builds on:** Phase 3A (calendar trigger) + Phase 3B (proactive upgrades)

---

## Overview

Completes all 7 standing orders. 3 features in 3 commits.

| Step | Standing Order | What |
|------|---------------|------|
| **C1** | #5 Track commitments | Extract action items from meetings + emails, track follow-through |
| **C2** | #6 Proactive intelligence | Detect signals in RSS + emails, generate insight cards |
| **C3** | #7 Protect calendar | Auto-block prep time, detect conflicts |

---

## Step 1 — Commitment Tracker

### 1a. Schema

**Where:** `memory/store_back.py` — new `_ensure_commitments_table()` method

```sql
CREATE TABLE IF NOT EXISTS commitments (
    id SERIAL PRIMARY KEY,
    description TEXT NOT NULL,
    assigned_to TEXT,
    assigned_by TEXT DEFAULT 'director',
    due_date DATE,
    source_type TEXT NOT NULL,
    source_id TEXT,
    source_context TEXT,
    matter_slug TEXT,
    status TEXT DEFAULT 'open',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_commitments_status ON commitments(status);
CREATE INDEX IF NOT EXISTS idx_commitments_due ON commitments(due_date);
CREATE INDEX IF NOT EXISTS idx_commitments_assigned ON commitments(assigned_to);
```

Status values: `open`, `in_progress`, `completed`, `overdue`, `dismissed`

Call from `__init__` after `_ensure_alert_artifacts_table()`.

### 1b. Extraction from Fireflies transcripts

**Where:** `triggers/fireflies_trigger.py`

After storing a meeting transcript (around line 111-120), add commitment extraction:

```python
# Phase 3C: Extract commitments from transcript
if full_transcript:
    _extract_commitments_from_meeting(
        transcript_text=full_transcript,
        meeting_title=title,
        participants=participants,
        source_id=source_id,
        store=store,
    )
```

**New function `_extract_commitments_from_meeting()`:**

```python
COMMITMENT_EXTRACT_PROMPT = """You are Baker. Extract action items and commitments from this meeting transcript.

For each commitment found, return:
- description: What was promised or agreed to do
- assigned_to: Who is responsible (use their name as spoken in the meeting)
- due_date: When it's due (YYYY-MM-DD format, or null if no date mentioned)
- urgency: high/medium/low

Rules:
- Only extract EXPLICIT commitments — someone clearly agreed to do something
- Don't fabricate commitments from general discussion
- If "we" agreed, assign to "director" (Dimitry is the decision-maker)
- Include verbal promises: "I'll send you...", "We'll prepare...", "Let me follow up on..."
- Skip vague statements like "we should consider..."

Return ONLY valid JSON:
{"commitments": [
    {"description": "...", "assigned_to": "...", "due_date": "YYYY-MM-DD or null", "urgency": "high|medium|low"}
]}
"""
```

Implementation:
1. Call Haiku with transcript text (truncate to 8000 chars — Haiku context is generous)
2. Parse JSON response
3. For each commitment: INSERT into `commitments` table with `source_type='meeting'`, `source_id=transcript_id`
4. Auto-assign `matter_slug` via `_match_matter_slug()` on the description
5. Fault-tolerant — if extraction fails, transcript still stored normally

### 1c. Extraction from emails

**Where:** `triggers/email_trigger.py`

After processing an email through the pipeline (around line 188), add commitment extraction for high-priority emails:

```python
# Phase 3C: Extract commitments from high-priority emails
if trigger.priority in ("high", "medium"):
    _extract_commitments_from_email(
        email_text=thread["text"],
        subject=metadata.get("subject", ""),
        sender=metadata.get("primary_sender", ""),
        source_id=message_id,
        store=store,
    )
```

Same Haiku prompt pattern, adapted for email context. Use a slightly different prompt:

```python
EMAIL_COMMITMENT_PROMPT = """You are Baker. Extract commitments from this email.

Look for:
- Promises made BY the sender: "I'll send...", "We'll provide...", "Attached is..."
- Requests TO the Director: "Please review...", "Could you approve...", "We need your..."
- Deadlines mentioned: "by Friday", "before end of month", "within 5 business days"

Return ONLY valid JSON:
{"commitments": [
    {"description": "...", "assigned_to": "sender_name or director", "due_date": "YYYY-MM-DD or null", "urgency": "high|medium|low"}
]}

If no clear commitments found, return {"commitments": []}
"""
```

### 1d. Overdue commitment check

**Where:** `orchestrator/pipeline.py` or new file `orchestrator/commitment_checker.py`

**New scheduled job: `run_commitment_check()`**

```python
def run_commitment_check():
    """Check for overdue commitments. Runs every 6 hours.
    Creates T2 alert for each overdue commitment not yet alerted.
    """
```

Implementation:
1. Query: `SELECT * FROM commitments WHERE status = 'open' AND due_date IS NOT NULL AND due_date < CURRENT_DATE`
2. For each overdue commitment:
   - Check if already alerted (dedup via watermark: `commitment_overdue_{id}`)
   - Update status to `'overdue'`
   - Create T2 alert: "Overdue commitment: {description} (assigned to {assigned_to})"
   - Tags: `["commitment", "overdue"]`
3. Also check commitments due within 24h — create T3 reminder alert

**Schedule in `embedded_scheduler.py`:**
```python
from orchestrator.commitment_checker import run_commitment_check
scheduler.add_job(
    run_commitment_check,
    IntervalTrigger(hours=6),
    id="commitment_check", name="Commitment overdue check",
    coalesce=True, max_instances=1, replace_existing=True,
)
```

### 1e. Dashboard endpoint

**Where:** `outputs/dashboard.py`

**Endpoint: `GET /api/commitments`**

```python
@app.get("/api/commitments", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_commitments(
    status: Optional[str] = None,
    assigned_to: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
):
```

Response: `{"commitments": [...], "count": N, "overdue_count": M}`

No frontend tab for commitments in this phase — they surface as alert cards. Future: dedicated Commitments tab.

---

## Step 2 — Proactive Intelligence

### 2a. RSS relevance scoring

**Where:** `triggers/rss_trigger.py`

Currently, `_feed_to_pipeline()` sends every RSS article through the pipeline. The pipeline creates alerts for relevant ones. **But it doesn't proactively analyze for strategic relevance.**

**Upgrade:** After storing an RSS article (around line 156), run a quick Haiku relevance check. If the article is relevant to the Director's matters or VIPs, create an insight alert.

**New function `_check_article_relevance()`:**

```python
RELEVANCE_PROMPT = """You are Baker. Evaluate if this news article is strategically relevant to the Director (Dimitry Vallen, Chairman, Brisen Group).

Relevant topics: real estate (Vienna, Baden, Germany), hospitality (Mandarin Oriental), finance (Swiss banking, loans, LP structures), legal (Austrian law, construction disputes), M365/IT migration, competitors, regulatory changes.

Return ONLY valid JSON:
{
    "relevant": true/false,
    "relevance_score": 1-10,
    "reason": "One sentence explaining why this matters",
    "related_matter": "matter_slug or null",
    "action_needed": true/false,
    "suggested_action": "What Director should do, or null"
}

If relevance_score < 5, set relevant: false.
"""
```

Implementation:
1. For each new RSS article, call Haiku with title + summary (cheap — just ~200 tokens input)
2. If `relevant == true` and `relevance_score >= 7`:
   - Create T3 alert: "Intelligence: {article_title}"
   - Body: `{reason}\n\nSource: {feed_title}\n{url}\n\nSuggested action: {suggested_action}`
   - Tags: `["intelligence", "media"]`
   - Matter_slug from Haiku's response
3. If `relevance_score >= 5 and < 7`: store in `insights` table (existing) but don't create alert — visible in future Intelligence tab
4. If `relevance_score < 5`: skip (noise)

**Cost control:** Haiku call per article is ~$0.001. With ~50 articles/day, that's ~$0.05/day. Negligible.

### 2b. Email signal detection

**Where:** `triggers/email_trigger.py`

Currently, email classification is heuristic (keyword-based priority). **Don't replace it.** Add a lightweight post-classification step for high-priority emails:

After the email goes through the pipeline (around line 188), check if the email contains proactive intelligence signals:

```python
# Phase 3C: Check for intelligence signals in high-priority emails
if trigger.priority == "high":
    _check_email_intelligence(email_text=thread["text"], subject=subject, sender=sender, store=store)
```

**New function `_check_email_intelligence()`:**

Same Haiku relevance check, but with email-specific prompt:

```python
EMAIL_INTELLIGENCE_PROMPT = """You are Baker. Check if this email contains a signal the Director should know about proactively.

Signals: competitor moves, regulatory changes, market shifts, opportunity alerts, risk indicators, deadline changes, relationship changes (new contact, role change, departure).

Return ONLY valid JSON:
{
    "signal_detected": true/false,
    "signal_type": "competitor|regulatory|market|opportunity|risk|deadline|relationship",
    "summary": "One sentence",
    "urgency": "high|medium|low",
    "related_matter": "matter_slug or null"
}

If no clear signal, set signal_detected: false.
"""
```

If signal detected with urgency high/medium:
- Create T2 alert (high) or T3 alert (medium): "Intelligence: {summary}"
- Tags: `["intelligence", signal_type]`

**Guard:** Only process emails not already flagged by other mechanisms (deadline extraction, VIP SLA). Use a simple check — if the email already generated an alert through the pipeline, skip intelligence check.

---

## Step 3 — Calendar Protection

### 3a. Auto-block prep time

**Where:** `triggers/calendar_trigger.py`

After generating a meeting briefing in `check_calendar_and_prep()`, automatically create a 15-minute prep block before the meeting.

**New function `_block_prep_time()`:**

```python
def _block_prep_time(meeting: dict):
    """Create a 15-minute prep block before a meeting on the Director's calendar.
    Uses Google Calendar API write (calendar scope is already authorized).
    """
    service = _get_calendar_service()
    start_str = meeting.get('start', '')
    if not start_str:
        return

    from datetime import datetime, timedelta, timezone
    try:
        start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        prep_start = start - timedelta(minutes=15)
        prep_end = start

        event = {
            'summary': f'[Baker Prep] {meeting["title"]}',
            'description': 'Auto-blocked by Baker for meeting preparation.',
            'start': {'dateTime': prep_start.isoformat(), 'timeZone': 'Europe/Zurich'},
            'end': {'dateTime': prep_end.isoformat(), 'timeZone': 'Europe/Zurich'},
            'reminders': {'useDefault': False},
            'transparency': 'opaque',
        }

        service.events().insert(calendarId='primary', body=event).execute()
        logger.info(f"Prep block created: {prep_start.strftime('%H:%M')} - {prep_end.strftime('%H:%M')} for '{meeting['title']}'")
    except Exception as e:
        logger.warning(f"Failed to create prep block for '{meeting['title']}': {e}")
```

**Integration point:** In `check_calendar_and_prep()`, after successfully creating the briefing alert:

```python
if alert_id:
    trigger_state.set_watermark(watermark_key, ...)
    prepped_count += 1

    # Phase 3C: Block 15 min prep time on calendar
    _block_prep_time(meeting)
```

**Dedup:** The prep block creation is gated by the same watermark check as the briefing. If a meeting is already prepped, the prep block already exists.

### 3b. Conflict detection

**Where:** `triggers/calendar_trigger.py`

Add a conflict detection step to `check_calendar_and_prep()`. After polling meetings, check for overlaps:

```python
def _detect_conflicts(meetings: list) -> list:
    """Detect overlapping meetings. Returns list of conflict pairs."""
    conflicts = []
    for i in range(len(meetings)):
        for j in range(i + 1, len(meetings)):
            a_end = meetings[i].get('end', '')
            b_start = meetings[j].get('start', '')
            if a_end and b_start and a_end > b_start:
                conflicts.append((meetings[i], meetings[j]))
    return conflicts
```

For each conflict detected, create a T2 alert:
- Title: "Calendar conflict: {meeting1} overlaps {meeting2}"
- Tags: `["calendar", "conflict"]`
- Dedup via watermark: `calendar_conflict_{event_id_1}_{event_id_2}`

---

## CRITICAL Rules

1. **Commitment extraction is Haiku-only.** No agentic RAG, no /api/scan. Same pattern as all Phase 3 background jobs.

2. **Only extract EXPLICIT commitments.** The prompt says "don't fabricate from general discussion." If Haiku hallucinates commitments, they'll clutter the tracker. The prompt guards against this.

3. **RSS relevance threshold is 7/10 for alerts.** Below 7: store in insights table (queryable but not pushed). Below 5: discard. This prevents noise.

4. **Email intelligence only on high-priority emails.** Don't run Haiku on every email — only the ones already classified as high priority by the existing heuristic. Cost control + relevance filter.

5. **Prep blocks are marked `[Baker Prep]`** in the title. This makes them visually distinct and easy for the Director to identify/delete if unwanted.

6. **Calendar writes are fault-tolerant.** If the Calendar API rejects the write (e.g., prep block overlaps another event), log warning and continue. Never crash the prep job.

7. **Commitment dedup:** Before inserting, check if a similar commitment already exists (same source_id + similar description). Don't create duplicate commitments from the same meeting or email.

---

## Existing Code Reference

| What | Where | Notes |
|------|-------|-------|
| `store_meeting_transcript()` | `fireflies_trigger.py:111` | Hook point for commitment extraction |
| `full_transcript` field | `meeting_transcripts` table | Full text available for Haiku extraction |
| Email pipeline hook | `email_trigger.py:188` | After pipeline.run() for high-priority |
| `_feed_to_pipeline()` | `rss_trigger.py:427` | Hook point for relevance scoring |
| `insights` table | `store_back.py:498` | Already exists — use for mid-relevance RSS |
| `store_insight()` | `store_back.py` | Existing method to store insights |
| `_get_calendar_service()` | `calendar_trigger.py` | Returns Calendar v3 service with write scope |
| `check_calendar_and_prep()` | `calendar_trigger.py:247` | Hook for prep blocks + conflict detection |
| `trigger_state.watermark_exists()` | `triggers/state.py:128` | Dedup for all checks |
| `_match_matter_slug()` | `pipeline.py:25` | Auto-assign matters to commitments/alerts |
| `_auto_tag()` | `pipeline.py:94` | Auto-tag new alerts |
| `create_alert()` | `store_back.py:2444` | Create alert cards |
| `deadline_manager.py` extraction pattern | `deadline_manager.py` | Reference for Haiku extraction flow |

---

## Files Summary

| File | Type | What |
|------|------|------|
| `memory/store_back.py` | Modify | `_ensure_commitments_table()` + `store_commitment()` method |
| `triggers/fireflies_trigger.py` | Modify | Add commitment extraction after transcript storage |
| `triggers/email_trigger.py` | Modify | Add commitment extraction + intelligence signal detection |
| `triggers/rss_trigger.py` | Modify | Add relevance scoring after article storage |
| `triggers/calendar_trigger.py` | Modify | Add `_block_prep_time()` + `_detect_conflicts()` |
| `orchestrator/commitment_checker.py` | **New** | Overdue commitment check job |
| `triggers/embedded_scheduler.py` | Modify | Register commitment_check job |
| `outputs/dashboard.py` | Modify | `GET /api/commitments` endpoint |

---

## Endpoints Summary

| # | Endpoint | Method | Purpose |
|---|----------|--------|---------|
| 1 | `/api/commitments` | GET | List commitments with status/assignee filters |

---

## Commit Plan

```
Step 1: feat: Phase 3C step 1 -- commitment tracker
Step 2: feat: Phase 3C step 2 -- proactive intelligence (RSS + email signals)
Step 3: feat: Phase 3C step 3 -- calendar protection (prep blocks + conflicts)
```

3 commits on branch `feat/phase-3c-advanced`. Push to origin when complete. Code 300 will review before merge.
