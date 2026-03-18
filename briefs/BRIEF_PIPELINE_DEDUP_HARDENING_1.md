# BRIEF: Pipeline Alert Dedup Hardening

**For:** Code Brisen (Mac Mini)
**From:** AI Head (Session 26)
**Priority:** High — pipeline creates 2 alerts per event (near-identical titles)
**Branch:** `feat/pipeline-dedup-hardening-1`

## Context

- ALERT-DEDUP-3 shipped (universal title dedup in `create_alert()`, 6h window, case-insensitive, prefix-normalized)
- Email intelligence now passes `source_id` (just shipped)
- But pipeline.py `_generate_alerts()` still creates near-duplicate pairs because Haiku generates slightly different titles for the same event
- Examples from today: "Olga responded" vs "Olga Responded", "Torpedo Claim Poland — Edita approved" vs "Edita Approved"

## Root Cause

In `orchestrator/pipeline.py`, the classify step calls Haiku which returns `alerts[]`. When the same email/WA message triggers the pipeline twice (thread update, or 5-min re-poll overlap), Haiku generates a slightly different title each time. The external `alert_title_dedup()` check catches exact 60-char prefix matches but misses:
1. Case differences ("responded" vs "Responded")
2. Word order changes ("Edita approved, your sign-off" vs "your sign-off, Edita approved")
3. Prefix variations ("[ALERT]" sometimes added)

## Deliverables

### 1. Add `source_id` to pipeline alerts
- In `pipeline.py` where `_generate_alerts()` creates alerts, pass `source_id=trigger_id` or `source_id=f"pipeline-{message_id}"`
- This prevents the same source message from creating multiple alerts
- **File:** `orchestrator/pipeline.py`

### 2. Strip `[ALERT]` prefix in dedup normalization
- The `create_alert()` ALERT-DEDUP-3 regex strips "Intelligence:", "Commitment due today:", etc.
- Add `[ALERT]\\s*` to the normalization regex so `[ALERT] Trend Magazine...` matches `Trend Magazine...`
- **File:** `memory/store_back.py` lines 3238-3240 (the `_re.sub` pattern)

### 3. Verify: check dedup catches all known patterns
Test these title pairs and confirm the dedup catches them:
- "Olga responded to Piras..." vs "Olga Responded to Piras..." (case) → should match after DEDUP-3
- "[ALERT] Trend Magazine..." vs "Trend Magazine..." (prefix) → needs [ALERT] strip
- "Intelligence: Patrick Piras is terminating..." vs "Patrick Piras Resigning..." (different verbs) → won't match (acceptable — different enough)

## Files to Touch
- `orchestrator/pipeline.py` — add source_id to alert creation
- `memory/store_back.py` — add `[ALERT]` to normalization regex (lines 3238-3240 only)

## DO NOT Touch
- `orchestrator/deadline_manager.py` — AI Head modified
- `triggers/email_trigger.py` — AI Head modified
- `triggers/embedded_scheduler.py` — AI Head modified

## Test
1. Check git log for recent duplicate alert pairs
2. Verify the regex handles all prefix patterns
3. Syntax check all modified files
