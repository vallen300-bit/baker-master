# BRIEF: COST-OPT-WAVE2 — Model Routing & Complexity Router Activation

## Context
After Wave 1 bug fixes (EUR ~250/mo saved), this wave tackles model routing — sending cheap triggers to cheap models. Baker currently sends almost everything to Opus (EUR 15/M input, EUR 75/M output) when Haiku (EUR 0.80/M input, EUR 4/M output) handles 60%+ of triggers perfectly.

**Key insight:** A complexity router (COMPLEXITY-ROUTER-1) was already built in Session 36 and is sitting in shadow mode on Render. It classifies queries as "fast" (Haiku) or "deep" (Opus) using zero-cost regex rules. Before building custom per-trigger routing, we activate this first.

## Estimated time: ~4 hours
## Estimated savings: EUR ~400-450/month

---

## PHASE A: Activate Complexity Router (1 hour)

### Step 1: Check Shadow Mode Data

Before changing anything, pull the stats to see how the router has been classifying:

```bash
curl -s -H "X-Baker-Key: bakerbhavanga" \
  "https://baker-master.onrender.com/api/tasks/complexity-stats?days=30" | python3 -m json.tool
```

**What to look for:**
- `distribution`: How many tasks classified as "fast" vs "deep"?
- `misclassified_fast`: Any tasks classified "fast" that got rejected/thumbs-down?
- If `misclassified_fast` count is zero or very low → safe to activate

**Report this data in the commit message** so we have a record.

### Step 2: Enable Active Mode

**File:** Render Dashboard → Service `srv-d6dgsbctgctc73f55730` → Environment

Check current value of `COMPLEXITY_SHADOW_MODE`:
- If set to `true` → change to `false` (or delete the var entirely — default is `false`)
- If not set → it's already active (default `false`), skip this step

**How it works when active** (code is in `outputs/dashboard.py:6778` and `orchestrator/capability_runner.py:147`):
- "fast" queries → Haiku, 5 iterations max, 10s timeout, 3 tools, 1024 max tokens
- "deep" queries → Opus, 15 iterations, 90s timeout, all tools, 4096 max tokens
- Classification is pure regex (<1ms, zero LLM cost)

### Step 3: Verify

After enabling, monitor for 24 hours:
```bash
# Check fast vs deep distribution in real-time
curl -s -H "X-Baker-Key: bakerbhavanga" \
  "https://baker-master.onrender.com/api/tasks/complexity-stats?days=1" | python3 -m json.tool
```

**Safety net:** If quality drops, set `COMPLEXITY_SHADOW_MODE=true` on Render to revert instantly. No code change needed.

---

## PHASE B: Email 3-Tier Routing (2 hours)

Currently EUR ~357/month after Wave 1 dedup fix. Target: EUR ~132/month.

### Architecture

```
Email arrives
  │
  ├─ Tier 1: REGEX SKIP (~40% of emails)
  │   noreply@, unsubscribe headers, known automations
  │   → Store metadata only, no LLM call
  │
  ├─ Tier 2: HAIKU TRIAGE (~30%)
  │   Haiku reads email, classifies: "analyze" or "store_only"
  │   store_only → embed + store, no Opus call
  │
  └─ Tier 3: OPUS ANALYSIS (~30%)
      VIP senders (whitelist) OR Haiku said "analyze"
      → Full Opus pipeline as today
```

### Implementation

**File:** `orchestrator/pipeline.py`

1. **Add regex skip list** — create a constant near `_HAIKU_TRIGGER_TYPES`:

```python
_EMAIL_SKIP_PATTERNS = {
    # Sender patterns (exact or regex)
    "senders": [
        r"noreply@", r"no-reply@", r"notifications@", r"mailer-daemon@",
        r"@linkedin\.com", r"@github\.com", r"@jira\.atlassian",
        r"@newsletter\.", r"@marketing\.", r"@info\.",
    ],
    # Header patterns
    "headers": ["unsubscribe", "list-unsubscribe"],
    # Subject patterns
    "subjects": [
        r"^(Out of Office|Automatic reply|Abwesenheit)",
        r"newsletter", r"weekly digest", r"daily summary",
    ],
}
```

2. **Add VIP sender whitelist** — senders that ALWAYS get Opus:

```python
_EMAIL_VIP_SENDERS = set()  # Populated from vip_contacts table at startup
```

Load VIP email addresses from the database on trigger initialization. Cache for 1 hour. Any email from a Tier 1 or Tier 2 VIP → straight to Opus, skip triage.

3. **Add Haiku triage step** — in the email processing path, before `pipeline.run()`:

```python
def _triage_email(sender: str, subject: str, snippet: str) -> str:
    """Returns 'skip', 'store_only', or 'analyze'."""
    # Tier 1: regex skip
    for pattern in _EMAIL_SKIP_PATTERNS["senders"]:
        if re.search(pattern, sender, re.IGNORECASE):
            return "skip"
    # ... check headers, subjects ...

    # VIP fast-track
    if sender.lower() in _EMAIL_VIP_SENDERS:
        return "analyze"

    # Tier 2: Haiku triage
    response = call_haiku(
        f"Classify this email. Reply ONLY 'analyze' or 'store_only'.\n"
        f"From: {sender}\nSubject: {subject}\nSnippet: {snippet[:500]}"
    )
    return "analyze" if "analyze" in response.lower() else "store_only"
```

4. **Route based on triage result:**
- `skip` → log to trigger_log, no embedding, no LLM
- `store_only` → embed to Qdrant (for future retrieval), store to email_messages, no Opus
- `analyze` → full `pipeline.run()` with Opus (current behavior)

**File:** `triggers/email_trigger.py` — add the triage call before pipeline.run()

### Verification
```sql
-- After 24h, check distribution
SELECT
  CASE
    WHEN metadata->>'triage' = 'skip' THEN 'skip'
    WHEN metadata->>'triage' = 'store_only' THEN 'store_only'
    ELSE 'analyze'
  END as tier,
  COUNT(*)
FROM triggers_log
WHERE trigger_type = 'email' AND created_at > NOW() - INTERVAL '24 hours'
GROUP BY 1;
```
Target: ~40% skip, ~30% store_only, ~30% analyze.

---

## PHASE C: ClickUp → Haiku (30 min)

Currently EUR ~144/month. Target: EUR ~15/month.

**File:** `orchestrator/pipeline.py`

**Fix:** Add ClickUp trigger types to `_HAIKU_TRIGGER_TYPES`:

```python
_HAIKU_TRIGGER_TYPES = {
    "dropbox_file_new", "dropbox_file_modified", "rss_article_new",
    "clickup_task_updated", "clickup_task_overdue",  # NEW
    "todoist_task",  # NEW (Phase D)
}
```

**Exception:** ClickUp "Handoff Notes" (list 901521426367) contain instructions for Code Brisen — these need comprehension. Check if the task's list_id matches the Handoff Notes list. If yes, use Sonnet. If no, use Haiku.

```python
# In pipeline._call_claude() or wherever model is selected:
if trigger_type.startswith("clickup"):
    if metadata.get("list_id") == "901521426367":  # Handoff Notes
        model = "claude-sonnet-4-6-20250514"  # Sonnet for comprehension
    else:
        model = "claude-haiku-4-5-20251001"  # Haiku for status updates
```

Find the actual ClickUp trigger type names by searching `triggers/clickup_trigger.py` for what it passes as `trigger_type` to pipeline.run().

### Verification
```sql
SELECT trigger_type, COUNT(*) FROM triggers_log
WHERE trigger_type LIKE 'clickup%' AND created_at > NOW() - INTERVAL '24 hours'
GROUP BY 1;
```

---

## PHASE D: Todoist → Haiku (15 min)

Currently EUR ~49/month. Target: EUR ~2/month.

**File:** `orchestrator/pipeline.py`

**Fix:** Already included in Phase C — add `todoist_task` (or whatever the actual trigger_type is) to `_HAIKU_TRIGGER_TYPES`.

Find the actual type name in `triggers/todoist_trigger.py`.

### Verification
Same pattern as ClickUp — check triggers_log after 24h.

---

## PHASE E: Meeting Retrieval Reduction (15 min)

Currently EUR ~45/month after Wave 1 dedup. Target: EUR ~35/month.

**Problem:** Meeting triggers pull 15 retrieval results by default, but for meetings the transcript IS the context — extra retrieval is noise.

**File:** `orchestrator/pipeline.py` or wherever retrieval limits are set per trigger type.

**Fix:** When `trigger_type == 'fireflies'`, set retrieval limit to 3 results (down from default 10-15). The full meeting transcript is already in the trigger event content — retrieval is only needed for cross-referencing people/matters.

```python
# Per-trigger retrieval overrides
_RETRIEVAL_LIMITS = {
    "fireflies": 3,
    "clickup_task_updated": 3,
    "clickup_task_overdue": 3,
    "todoist_task": 3,
    "email": 10,       # Keep — emails need cross-reference
    "whatsapp": 5,     # Keep current
    "dropbox_file_new": 5,
}
```

Pass this to the retriever when called from pipeline.run().

---

## Deployment

1. `git pull origin main` (ensure Wave 1 is already deployed)
2. Phase A: Check complexity stats, enable if data looks good (Render env var change)
3. Phases B-E: Implement code changes
4. Syntax check all modified files
5. Commit: `feat: COST-OPT-WAVE2 — complexity router activation, email 3-tier routing, ClickUp/Todoist to Haiku, retrieval limits`
6. Push to main
7. Monitor `/api/tasks/complexity-stats` and trigger_log distribution for 48h

## Files Modified
- `orchestrator/pipeline.py` (Haiku trigger types, retrieval limits, email triage)
- `triggers/email_trigger.py` (email 3-tier routing integration)
- `triggers/clickup_trigger.py` (verify trigger type names)
- `triggers/todoist_trigger.py` (verify trigger type names)
- Render env: `COMPLEXITY_SHADOW_MODE` (delete or set to `false`)

## Do NOT Touch
- `orchestrator/agent.py` — interactive query quality
- `orchestrator/capability_runner.py` — specialist quality
- `tools/document_pipeline.py` — EUR 60/mo, not worth the risk for EUR 11 savings
- `outputs/dashboard.py` — no UI changes in this wave
