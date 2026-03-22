# BRIEF: Baker 3.0 — Item 0b: Consumer Migration

**Author:** AI Head
**Date:** 2026-03-22
**Priority:** HIGH — switches downstream systems to use signal_extractions
**Effort:** 1 session
**Assigned to:** AI Head + Code Brisen
**Depends on:** Item 0a (extraction engine must be running and populated)

---

## What We're Building

6 downstream consumers currently scan raw text to find obligations, deadlines, patterns, etc. After Item 0a, all that structured data is already in the `signal_extractions` table. This brief migrates each consumer to read pre-extracted data instead of re-scanning raw content.

**Result:** Consumers become faster, cheaper, and more accurate — they read structured JSON instead of asking Claude to re-analyze thousands of words of raw text.

---

## Consumers to Migrate

### 1. Obligation Generator (`orchestrator/obligation_generator.py`)

**Current:** Daily 06:50 UTC. Haiku scans raw emails, WhatsApp, meetings from last 24h → extracts 5-15 task proposals.

**After migration:** Reads from `signal_extractions` WHERE `processed_at > NOW() - INTERVAL '24 hours'` AND `type IN ('commitment', 'action_item', 'deadline', 'follow_up')`. Haiku's job reduces from "find obligations in raw text" to "prioritize and format pre-extracted items into proposed actions."

**Change:**
```python
# OLD: query raw emails, WhatsApp, meetings → feed to Haiku for extraction
# NEW:
def _gather_extractions() -> list:
    """Read pre-extracted items from signal_extractions table."""
    cur.execute("""
        SELECT source_channel, source_id, extracted_items
        FROM signal_extractions
        WHERE processed_at > NOW() - INTERVAL '24 hours'
    """)
    items = []
    for row in cur.fetchall():
        for item in row["extracted_items"]:
            if item["type"] in ("commitment", "action_item", "deadline", "follow_up"):
                item["_source_channel"] = row["source_channel"]
                item["_source_id"] = row["source_id"]
                items.append(item)
    return items
```

Then Haiku prompt changes from "find obligations in this text" to "prioritize these pre-extracted items and format as proposed actions."

**Cost saving:** Eliminates 3-5 Haiku calls that currently scan raw text. Now 1 Haiku call to prioritize pre-extracted items.

### 2. Deadline Detector (in `orchestrator/pipeline.py` → `extract_deadlines`)

**Current:** Haiku scans each incoming email/WhatsApp for deadline mentions.

**After migration:** Check `signal_extractions` for items with `type = 'deadline'` and `when IS NOT NULL`. Cross-reference against existing `deadlines` table. Create new deadline if not already tracked.

**Change:** New function `_sync_extracted_deadlines()` runs after each extraction batch:
```python
def _sync_extracted_deadlines():
    """Create deadlines from signal_extractions that don't already exist."""
    # Query extractions with type='deadline' from last 24h
    # For each: check if deadline already exists (fuzzy match on text + date)
    # If new: create via store.create_deadline()
```

### 3. Convergence Detector (`orchestrator/convergence_detector.py`)

**Current:** Weekly. Haiku extracts entities per matter from raw alerts/emails.

**After migration:** Reads `related_matter`, `related_contacts`, and `type='financial'` items from `signal_extractions`. Entity extraction is already done — convergence detector just looks for overlap (same person/company in 2+ matters).

**Change:** Replace `_extract_entities_for_matter()` with a query against `signal_extractions`:
```python
def _get_entities_from_extractions(matter: str, days: int = 30) -> dict:
    """Get people, companies, amounts from pre-extracted data for a matter."""
    cur.execute("""
        SELECT extracted_items FROM signal_extractions
        WHERE processed_at > NOW() - INTERVAL '%s days'
          AND extracted_items @> '[{"related_matter": "%s"}]'
    """, (days, matter))
    # Aggregate: people, companies, amounts
```

### 4. Initiative Engine (`orchestrator/initiative_engine.py`)

**Current:** Daily 07:00 UTC. Gathers priorities, calendar, deadlines, cadence, unanswered emails → Haiku generates 2-3 initiatives.

**After migration:** Also reads recent `signal_extractions` for high-confidence action items and commitments that haven't been actioned yet. This gives the initiative engine structured data instead of re-scanning raw sources.

**Change:** Add `_gather_recent_extractions()` to the context gathering phase:
```python
def _gather_recent_extractions() -> list:
    """Get high-confidence extractions from last 48h for initiative context."""
    cur.execute("""
        SELECT source_channel, extracted_items FROM signal_extractions
        WHERE processed_at > NOW() - INTERVAL '48 hours'
          AND extraction_tier IN ('T1', 'T2')
    """)
    # Filter for high-confidence items only
```

### 5. Morning Briefing (in `outputs/dashboard.py` → `_build_morning_brief()`)

**Current:** Morning brief assembles data from multiple sources — alerts, deadlines, proposed actions, etc.

**After migration:** Add a "Yesterday's Intelligence" section that summarizes signal_extractions from the last 24h:
```python
def _get_yesterday_extractions() -> list:
    """Get extraction summary for morning brief."""
    cur.execute("""
        SELECT source_channel, COUNT(*) as count,
               jsonb_array_elements(extracted_items)->>'type' as item_type
        FROM signal_extractions
        WHERE processed_at > NOW() - INTERVAL '24 hours'
        GROUP BY source_channel, item_type
        ORDER BY count DESC
    """)
```

### 6. Action Completion Detector (`orchestrator/action_completion_detector.py`)

**Current:** Every 6h. Checks approved actions against sent_emails/email_messages.

**After migration:** Also checks `signal_extractions` for completion signals. If an extraction matches an approved action's completion_signals, mark it as done.

**Change:** Add signal_extractions check alongside existing email check:
```python
# In addition to checking sent_emails:
cur.execute("""
    SELECT * FROM signal_extractions
    WHERE processed_at > %s
      AND extracted_items @> '[{"type": "commitment"}]'
""", (action_approved_at,))
# Match against action.completion_signals
```

---

## Migration Strategy

**Gradual rollout — don't switch everything at once.**

1. **Day 1:** Deploy Item 0a. Extractions start populating signal_extractions.
2. **Day 2-3:** Verify extraction quality — check 20-30 extractions manually.
3. **Day 4:** Migrate obligation generator (highest impact, biggest cost saving).
4. **Day 5:** Migrate deadline detector + morning briefing.
5. **Day 6:** Migrate convergence detector + initiative engine + action completion.

Each migration: deploy, monitor for 1 day, then proceed.

---

## Backward Compatibility

Each consumer keeps its old code path as a fallback. If signal_extractions table is empty (extraction engine down), consumer falls back to scanning raw text:

```python
extractions = _gather_extractions()
if not extractions:
    logger.warning("No extractions found — falling back to raw text scan")
    return _legacy_raw_text_scan()  # existing code, renamed
```

---

## Testing

1. **Obligation generator:** Compare old output (raw scan) vs new output (pre-extracted) for same 24h window
2. **Deadline detector:** Verify new deadlines created from extractions match what Haiku would have found
3. **Morning briefing:** Verify "Yesterday's Intelligence" section renders correctly
4. **Convergence:** Verify entity overlap detection works from signal_extractions
5. **Fallback:** Stop extraction engine → verify consumers fall back to raw text

---

## Files Modified

| File | Change |
|------|--------|
| `orchestrator/obligation_generator.py` | Read from signal_extractions instead of raw text |
| `orchestrator/pipeline.py` | Deadline sync from extractions |
| `orchestrator/convergence_detector.py` | Entity extraction from signal_extractions |
| `orchestrator/initiative_engine.py` | Add extraction context to initiative gathering |
| `outputs/dashboard.py` | Morning brief "Yesterday's Intelligence" section |
| `orchestrator/action_completion_detector.py` | Check signal_extractions for completion signals |
