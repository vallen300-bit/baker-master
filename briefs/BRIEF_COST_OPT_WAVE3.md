# BRIEF: COST-OPT-WAVE3 — Architecture Improvements (Context Reduction)

## Context
After Wave 1 (bug fixes, EUR ~250/mo saved) and Wave 2 (model routing, EUR ~400/mo saved), this wave tackles the #1 cross-cutting cost driver: **context stuffing**. Baker's pipeline calls average 74K input tokens but only 726 output tokens. Baker pays to READ, not THINK. Reducing what gets retrieved saves money and likely improves quality (less noise = better focus).

## Estimated time: ~4 hours
## Estimated savings: EUR ~200-250/month
## Prerequisites: Wave 1 and Wave 2 deployed and stable (wait at least 48h between waves)

---

## Fix 3a: Per-Trigger Retrieval Limits (EUR ~150/mo saved)

**Problem:** Every pipeline call retrieves the same amount of context regardless of trigger type. A ClickUp status update gets the same 10-15 results across 11 Qdrant collections as a VIP legal email. Most of that context is irrelevant noise that Opus reads (and we pay for) before generating a 50-word alert.

**Current state:** Default `limit_per_collection=10` across all calls (in `memory/retriever.py`).

### Implementation

**File:** `memory/retriever.py`

1. Add a retrieval config map:

```python
# Retrieval budget per trigger type
# Format: {trigger_type: {collections_to_search: limit}}
RETRIEVAL_PROFILES = {
    "email_vip": {
        # VIP emails get full context — cross-reference everything
        "default_limit": 10,
        "collections": None,  # search all
        "full_text_enrichment": True,
        "max_enrichments": 5,
    },
    "email_routine": {
        # Routine emails: minimal context, just enough for matter matching
        "default_limit": 5,
        "collections": ["baker-emails", "baker-contacts", "baker-documents"],
        "full_text_enrichment": False,
        "max_enrichments": 2,
    },
    "clickup": {
        # ClickUp: task context only
        "default_limit": 3,
        "collections": ["baker-clickup", "baker-contacts"],
        "full_text_enrichment": False,
        "max_enrichments": 0,
    },
    "todoist": {
        # Todoist: minimal
        "default_limit": 3,
        "collections": ["baker-todoist"],
        "full_text_enrichment": False,
        "max_enrichments": 0,
    },
    "fireflies": {
        # Meetings: the transcript IS the context
        "default_limit": 3,
        "collections": ["baker-contacts", "baker-emails"],
        "full_text_enrichment": False,
        "max_enrichments": 1,
    },
    "whatsapp": {
        # WhatsApp: moderate context
        "default_limit": 5,
        "collections": ["baker-whatsapp", "baker-contacts", "baker-emails", "baker-documents"],
        "full_text_enrichment": True,
        "max_enrichments": 3,
    },
    "dropbox_file_new": {
        "default_limit": 5,
        "collections": ["baker-documents"],
        "full_text_enrichment": False,
        "max_enrichments": 1,
    },
    "default": {
        "default_limit": 10,
        "collections": None,
        "full_text_enrichment": True,
        "max_enrichments": 5,
    },
}
```

2. Modify the main retrieval function to accept `trigger_type` and use the profile:

```python
def retrieve(query: str, trigger_type: str = "default", ...):
    profile = RETRIEVAL_PROFILES.get(trigger_type, RETRIEVAL_PROFILES["default"])
    limit = profile["default_limit"]
    collections = profile["collections"]  # None = search all
    # ... use these limits when querying Qdrant ...
```

3. Pass `trigger_type` from `pipeline.run()` to the retriever.

**File:** `orchestrator/pipeline.py` — where it calls the retriever, pass the trigger_type through.

### Key constraint
- Do NOT change retrieval for interactive queries (Ask Baker, Ask Specialist, WhatsApp questions). Those go through `dashboard.py` → `_scan_chat_deep()` and should keep full retrieval. This change only affects **pipeline triggers** (background processing).

### Verification
```sql
-- Monitor average input tokens per trigger type (if logged in baker_tasks or api_cost_log)
SELECT trigger_type, AVG(input_tokens) as avg_input, COUNT(*)
FROM api_cost_log  -- or wherever token usage is logged
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY trigger_type
ORDER BY avg_input DESC;
```

Target: email_routine drops from ~74K to ~30K input tokens. ClickUp/Todoist drop to ~15K.

---

## Fix 3b: Briefing Two-Pass Architecture (EUR ~42/mo saved)

**Problem:** Morning briefings average 138K input tokens because they stuff ALL sources into one Opus call. The model reads 138K tokens to produce a 2K-token briefing. Most of that input is redundant.

**Current state:** Single Opus call gathers + synthesizes. Find the briefing generation code — likely in `orchestrator/pipeline.py` or a dedicated briefing module, possibly called from `triggers/embedded_scheduler.py`.

### Architecture

```
PASS 1: Haiku Gather (5-7 parallel calls, ~5K tokens each)
  ├─ Haiku: "Summarize critical alerts from last 24h" (500 tokens out)
  ├─ Haiku: "List deadline changes" (200 tokens out)
  ├─ Haiku: "Summarize VIP communications" (500 tokens out)
  ├─ Haiku: "List ClickUp task updates" (300 tokens out)
  ├─ Haiku: "Summarize new documents" (200 tokens out)
  ├─ Haiku: "List WhatsApp highlights" (500 tokens out)
  └─ Haiku: "Summarize meeting outcomes" (300 tokens out)

PASS 2: Opus Synthesize (1 call, ~5K input tokens)
  Input: 7 Haiku summaries (~2.5K tokens total) + Director preferences
  Output: Structured morning briefing (~2K tokens)
```

### Implementation

1. Find the briefing generation function (search for "briefing" or "morning" in scheduler and pipeline)
2. Break the single call into:
   - 5-7 Haiku calls (can run in parallel with `asyncio.gather`)
   - 1 Opus call that takes only the Haiku summaries as input
3. Each Haiku call gets its own focused query + limited context retrieval (use profiles from 3a)
4. Opus gets a structured input: each section clearly labeled

### Key constraint
- The final briefing quality must stay the same or improve. The Haiku calls are just data gathering — Opus does the judgment and prioritization.
- Keep the briefing format/structure identical to what the Director sees today.

### Verification
- Compare token usage before/after: input should drop from ~138K to ~5-10K for the Opus call
- Compare briefing quality: have the Director read both and confirm no regression

---

## Fix 3c: Agent Loop Iteration Cap for Pipeline Triggers (EUR ~51/mo saved)

**Problem:** Pipeline triggers (background processing of emails, ClickUp, etc.) can run the agent loop for up to 15 iterations. But pipeline triggers don't need deep research — they need classification, alerting, and storage. 3 iterations covers 90%+ of the value.

**Current state:** Agent loop iterations are set in `orchestrator/agent.py` or wherever `run_agent_loop()` is called from pipeline. The complexity router already caps "fast" queries at 5 iterations, but pipeline triggers may bypass the complexity router entirely.

### Implementation

**File:** `orchestrator/pipeline.py` — where it calls the agent loop (likely `_scan_chat_agentic()` or similar)

1. When the agent loop is called from pipeline.run() (background trigger processing), cap at 3 iterations:

```python
# In pipeline trigger processing path:
max_iterations = 3  # Pipeline triggers: quick classify + alert
timeout = 15  # seconds — pipeline triggers don't need 90s
```

2. When called from dashboard.py (interactive queries), keep current settings:
```python
# In interactive query path (Ask Baker, WhatsApp questions):
max_iterations = 15  # or whatever complexity router decides
timeout = 90  # full thinking time
```

The key is distinguishing **pipeline triggers** (background, automatic) from **interactive queries** (user-initiated). Pipeline triggers call through `pipeline.run()`. Interactive queries call through `scan_chat()` in dashboard.py.

### Key constraint
- Do NOT cap iterations for interactive queries (Ask Baker, Ask Specialist, WhatsApp director questions)
- Only cap for automatic pipeline triggers that process incoming data
- If a pipeline trigger hits the 3-iteration cap, it should still produce a valid alert — just not do deep research

### Verification
```sql
-- Check iteration counts for pipeline vs interactive
SELECT
  source,  -- 'pipeline' vs 'dashboard' vs 'whatsapp'
  AVG(iterations) as avg_iter,
  MAX(iterations) as max_iter,
  COUNT(*)
FROM baker_tasks
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY source;
```

Pipeline should max at 3. Interactive should remain as-is.

---

## Deployment

1. `git pull origin main` (ensure Wave 1 + Wave 2 deployed and stable)
2. Implement 3a → 3c
3. Syntax check all modified files
4. Commit: `feat: COST-OPT-WAVE3 — per-trigger retrieval limits, briefing two-pass, pipeline iteration cap`
5. Push to main
6. Monitor for 48h: check token usage trends, briefing quality, alert quality

## Files Modified
- `memory/retriever.py` (3a: retrieval profiles per trigger type)
- `orchestrator/pipeline.py` (3a: pass trigger_type to retriever, 3c: iteration cap)
- Briefing module — TBD, find it first (3b: two-pass architecture)
- `orchestrator/agent.py` (3c: accept max_iterations parameter from caller)

## Do NOT Touch
- `outputs/dashboard.py` — interactive query path stays unchanged
- `orchestrator/capability_runner.py` — specialist quality unchanged
- `orchestrator/agent.py` tool definitions — don't remove or restrict tools
- `triggers/waha_webhook.py` — WhatsApp director message path stays full-power

## Quality Checkpoints
After each fix, verify:
1. Morning briefing still covers all sections (3b)
2. VIP emails still generate proper alerts with full context (3a)
3. Interactive queries (Ask Baker) still produce deep, comprehensive answers (3c)
4. No increase in "missed" alerts — check `alerts` table for gap in critical items
