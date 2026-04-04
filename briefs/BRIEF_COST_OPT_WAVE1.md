# BRIEF: COST-OPT-WAVE1 — Bug Fixes & Dedup Hardening

## Context
Baker's API spend is EUR ~1,378/month. Analysis found EUR ~250/month of pure waste from dedup bugs and misconfigurations. These are zero-risk fixes — no quality impact, just stop paying for duplicate processing.

## Estimated time: ~2 hours
## Estimated savings: EUR ~250/month

---

## Fix 1a: Email Dedup Race Condition (EUR 76/mo saved)

**Problem:** `pipeline.run()` is called BEFORE the trigger_log write. If two poll cycles overlap, the same email thread gets processed twice. Some threads were processed 300-513 times in early March.

**File:** `triggers/email_trigger.py`

**Fix:**
1. Find where `pipeline.run()` is called for email triggers
2. Write the `trigger_log` entry BEFORE calling `pipeline.run()`, not after
3. Add a PostgreSQL partial UNIQUE index as a safety net:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_trigger_log_dedup
ON triggers_log (trigger_type, source_id)
WHERE trigger_type IN ('email', 'email_labeled');
```

Add this index creation to `memory/store_back.py` in the schema initialization section (search for `CREATE TABLE IF NOT EXISTS triggers_log` or `_ensure_` methods).

**Verification:** After deploy, check for duplicates:
```sql
SELECT source_id, COUNT(*) FROM triggers_log
WHERE trigger_type = 'email' AND created_at > NOW() - INTERVAL '24 hours'
GROUP BY source_id HAVING COUNT(*) > 1;
```
Should return zero rows.

---

## Fix 1b: RSS Type Mismatch (EUR 52/mo saved)

**Problem:** RSS articles are stored with trigger_type `rss_article_new` but `_HAIKU_TRIGGER_TYPES` in pipeline.py contains `rss_article`. The type doesn't match, so RSS articles get processed by Opus instead of Haiku.

**File:** `orchestrator/pipeline.py`

**Fix:** In `_HAIKU_TRIGGER_TYPES` set (around line 462), change `rss_article` to `rss_article_new`. Also check `orchestrator/chain_runner.py` (around line 179) for the same mismatch — it excludes `rss_article` from chains but the actual type is `rss_article_new`.

**How to find the actual trigger type:** Search `triggers/rss_trigger.py` for the `trigger_type` value it passes to `pipeline.run()`. Match exactly.

**Verification:** After deploy, tail the logs:
```
grep "rss_article" /var/log/baker/* | grep "model"
```
Should show Haiku, not Opus.

---

## Fix 1c: Research Trigger Dedup (EUR 74/mo saved)

**Problem:** The research trigger (`orchestrator/research_trigger.py`) calls Haiku to classify every WhatsApp message, even messages it already classified. The 6-hour WA backfill re-processes all recent messages, causing ~40K Haiku calls for ~3K unique messages.

**File:** `orchestrator/research_trigger.py`

**Fix:** Add a `trigger_state.is_processed()` check BEFORE the Haiku classification call:

1. Find the function that processes WhatsApp messages for research classification (around line 224-261)
2. Before calling Haiku (the `_passes_content_prefilter()` or classification call), add:
```python
source_ref = f"wa-research-{message_id}"  # or however the message is identified
if trigger_state.is_processed("research", source_ref):
    continue
```
3. After successful processing, add:
```python
trigger_state.mark_processed("research", source_ref)
```

**Verification:**
```sql
SELECT COUNT(*) FROM research_proposals
WHERE created_at > NOW() - INTERVAL '24 hours';
```
Should be dramatically lower (3-10 per day, not hundreds).

---

## Fix 1d: Meeting Dedup (EUR 40/mo saved)

**Problem:** Meeting transcripts (Fireflies) have 47.5% duplication — same pattern as emails. The trigger_log write happens after pipeline processing.

**File:** `triggers/fireflies_trigger.py`

**Fix:** Same pattern as Fix 1a:
1. Write trigger_log BEFORE calling `pipeline.run()`
2. Add UNIQUE partial index:
```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_trigger_log_meeting_dedup
ON triggers_log (trigger_type, source_id)
WHERE trigger_type = 'fireflies';
```

Add this to `memory/store_back.py` alongside the email index from Fix 1a.

**Verification:** Same query as 1a but for fireflies trigger_type.

---

## Fix 1e: Slack mark_processed Bug (EUR 0 — stability fix)

**Problem:** In `triggers/slack_trigger.py`, the feedback path calls `trigger_state.mark_processed()` correctly, but the normal message handling paths (Director messages + pipeline feed) do NOT. Same Slack mention gets re-ingested every 5-minute poll cycle.

**File:** `triggers/slack_trigger.py`

**Fix:** Find the message handling block (around lines 196-220). There are two paths after `is_processed` check:
1. Director message path (likely calls `_handle_director_slack_message()`)
2. Pipeline feed path (likely calls `pipeline.run()` or `_feed_to_pipeline()`)

Add `trigger_state.mark_processed("slack", source_id)` at the end of BOTH paths, same as the feedback path already does.

**Verification:** Check Slack trigger logs — each message_id should appear only once per 24h period.

---

## Fix 1f: Cost Guardrail Adjustment (EUR 0 — reduces alert fatigue)

**Problem:** The EUR 50/day soft alert fires almost every active day. The Director ignores it. Alert fatigue.

**File:** `config/settings.py`

**Fix:** Find the cost guardrail settings (search for `50` near cost/budget/guardrail). Change:
- Soft alert: EUR 50 → EUR 75
- Hard limit: (if exists) → EUR 150

If these are env vars on Render, note the var names and values to set. If hardcoded, change in settings.py.

---

## Fix 1g: Trigger Log UNIQUE Index (safety net for all triggers)

**Problem:** Even after fixing the write-order in 1a/1d, a UNIQUE index prevents any future dedup regression across ALL trigger types.

**File:** `memory/store_back.py`

**Fix:** Add a general partial UNIQUE index (if not already covered by 1a/1d):
```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_trigger_log_source_dedup
ON triggers_log (trigger_type, source_id)
WHERE source_id IS NOT NULL;
```

**Note:** If `source_id` can legitimately repeat for different events of the same type (e.g., ClickUp task updated multiple times), use a narrower WHERE clause — only for types where duplication is a bug: `email`, `email_labeled`, `fireflies`, `rss_article_new`.

---

## Deployment

1. `git pull origin main`
2. Implement all fixes
3. Syntax check every modified file: `python3 -c "import py_compile; py_compile.compile('FILE', doraise=True)"`
4. Commit with message: `fix: COST-OPT-WAVE1 — dedup bugs, RSS type mismatch, Slack mark_processed, cost guardrails`
5. Push to main (Render auto-deploys)
6. After deploy, run the verification queries above

## Files Modified
- `triggers/email_trigger.py` (1a: write trigger_log before pipeline)
- `orchestrator/pipeline.py` (1b: fix `_HAIKU_TRIGGER_TYPES` type name)
- `orchestrator/chain_runner.py` (1b: fix RSS type name in chain exclusion)
- `orchestrator/research_trigger.py` (1c: add trigger_state dedup)
- `triggers/fireflies_trigger.py` (1d: write trigger_log before pipeline)
- `triggers/slack_trigger.py` (1e: add mark_processed calls)
- `config/settings.py` (1f: raise cost guardrails)
- `memory/store_back.py` (1g: UNIQUE indexes on trigger_log)

## Do NOT Touch
- `orchestrator/agent.py` — agent loop quality layer, not a cost issue
- `orchestrator/capability_runner.py` — interactive query quality, EUR 178/mo is earned
- `outputs/dashboard.py` — no changes needed for this wave
