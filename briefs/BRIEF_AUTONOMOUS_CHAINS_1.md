# BRIEF: AUTONOMOUS-CHAINS-1 — Plan-Execute-Verify for Baker

**Status:** APPROVED (Batch 0 shipped) | **Author:** AI Head | **Date:** 19 March 2026
**Effort:** M (1-2 weeks) | **Risk:** Low | **Cost:** ~EUR 2-5/day incremental

---

## Problem Statement

Baker has three levels of reasoning, none of which connect triggers to autonomous action:

| Level | What it does | Limitation |
|-------|-------------|------------|
| **Pipeline** (pipeline.py) | Single-pass: Event → Score → Generate → Alert | No tool calling, no reasoning |
| **Agent loop** (agent.py) | Multi-step tool calling, 17 tools, up to 5 iterations | Only runs when user asks a question |
| **Capability framework** (capability_router.py) | Decompose → multi-specialist → synthesize | Only for answering questions, not taking actions |

Baker's 20 scheduled jobs (email polling, meeting prep, risk detection, cadence tracking) detect events and create alerts. But they don't *reason* about what to do — they run hardcoded logic. When something important happens, Baker creates a T1 alert and waits for the Director.

**The missing link:** Triggers detect events → **??? autonomous reasoning ???** → Actions executed.

---

## What "Autonomous Chains" Means

A chain is: **Trigger → Plan → Execute → Verify → Report**

### Example: Urgent Email from EVOK about M365 Migration Delay

**Today (reactive):**
1. Email trigger polls Gmail, finds EVOK email
2. Pipeline scores it T1, generates alert with analysis
3. Alert appears in Cockpit. Director reads it.
4. Director opens Scan, asks "What's the impact of this delay?"
5. Baker agent loop searches meetings, emails, ClickUp
6. Director asks "Draft a response to Dennis"
7. Baker drafts email, Director approves
8. Director asks "Create a deadline for the new migration date"
9. Baker creates deadline

**9 steps. 4 require Director intervention.**

**With autonomous chains:**
1. Email trigger polls Gmail, finds EVOK email
2. Pipeline scores it T1
3. **Chain activates:** Baker generates a plan:
   - Step 1: Pull M365 matter context (people, keywords, history)
   - Step 2: Search recent emails + WA from Dennis/BCOMM
   - Step 3: Check calendar for upcoming EVOK/BCOMM meetings
   - Step 4: Check deadlines at risk due to delay
   - Step 5: Draft response to Dennis acknowledging delay + requesting new timeline
   - Step 6: Create deadline for follow-up
   - Step 7: Prepare Director briefing summarizing situation + actions taken
4. Baker executes steps 1-4 autonomously (all read operations)
5. Baker executes steps 5-6 (write operations: email draft queued for approval, deadline created)
6. Baker sends Director a WhatsApp summary: "EVOK migration delayed. I've drafted a response to Dennis, created a follow-up deadline for April 2, and found 2 affected deadlines. Review in Cockpit."
7. Director approves email draft (1 tap)

**7 steps. 1 requires Director intervention (email approval).**

---

## Architecture

### New Component: `orchestrator/chain_runner.py`

```
┌─────────────────────────────────────────────────────┐
│                  CHAIN RUNNER                         │
│                                                       │
│  1. QUALIFY — Should this trigger start a chain?      │
│     - T1/T2 alerts only (T3 = info, no chain)        │
│     - Has a matched matter (context available)        │
│     - Not a batch trigger (dropbox, RSS)              │
│     - Circuit breaker allows it                       │
│                                                       │
│  2. PLAN — Generate a structured action plan          │
│     - Claude Opus call with chain planning prompt     │
│     - Input: trigger event + matter context           │
│     - Output: ordered step list with tool calls       │
│     - Max 7 steps per chain                           │
│                                                       │
│  3. EXECUTE — Run each step via ToolExecutor          │
│     - Read steps: auto-execute                        │
│     - Write steps: safety check per action type       │
│       - Deadlines, calendar: auto-execute             │
│       - Email drafts: queue for approval              │
│       - ClickUp tasks: auto-execute in BAKER space    │
│       - WhatsApp: only Director notification          │
│     - Each step result feeds into next step's context │
│     - 60s wall-clock timeout for entire chain         │
│                                                       │
│  4. VERIFY — Check outcomes                           │
│     - Did all steps complete?                         │
│     - Did any write actions fail?                     │
│     - Were there unexpected findings?                 │
│                                                       │
│  5. REPORT — Notify Director                          │
│     - WhatsApp summary (2-3 lines)                    │
│     - Full chain log stored in baker_tasks            │
│     - Alert updated with chain results                │
│                                                       │
└─────────────────────────────────────────────────────┘
```

### How It Connects to Existing Code

```
pipeline.py:run()
  └── store_back() creates alert
       └── IF tier <= 2 AND matter matched AND chain_enabled:
            └── chain_runner.run_chain(trigger, alert, matter)
                 └── Uses existing ToolExecutor (agent.py)
                 └── Uses existing safety rules (store_back.py)
                 └── Uses existing approval flow (pending_drafts)
                 └── Logs to existing baker_tasks table
```

**No new tables. No new tools. No new safety mechanisms.** The chain runner is purely an orchestration layer that uses Baker's existing 17 tools and safety rules.

---

## Planning Prompt (the core of the enhancement)

```
You are Baker, an AI Chief of Staff. An event has been detected that requires
autonomous action. Generate a structured action plan.

EVENT:
{trigger_summary}

MATTER CONTEXT:
{matter_context}

RECENT COMMUNICATIONS:
{recent_emails_wa}

ACTIVE DEADLINES:
{related_deadlines}

DIRECTOR PREFERENCES:
{relevant_preferences}

Generate a JSON action plan:
{
  "assessment": "2-3 sentence situation assessment",
  "urgency": "why this needs immediate attention",
  "steps": [
    {
      "tool": "search_emails",
      "input": {"query": "..."},
      "purpose": "Find latest correspondence on this matter",
      "auto_execute": true
    },
    {
      "tool": "draft_email",
      "input": {"to": "...", "subject": "...", "body": "..."},
      "purpose": "Respond to counterparty",
      "auto_execute": false  // requires Director approval
    }
  ],
  "director_summary": "2-3 line WhatsApp message for Director"
}

Rules:
- Max 7 steps
- Read tools (search_*, get_*) are always auto_execute: true
- draft_email is always auto_execute: false (Director approves)
- create_deadline and create_calendar_event are auto_execute: true
- clickup_create is auto_execute: true (BAKER space only)
- Do NOT send WhatsApp messages to anyone except Director
- Include a director_summary even if no write actions needed
```

---

## Safety Model

The chain runner inherits ALL of Baker's existing safety rules:

| Action | Safety | How |
|--------|--------|-----|
| Read operations | Always allowed | Same as agent loop |
| Create deadline | Auto-execute | Same as agent loop |
| Create calendar event | Auto-execute | Same as agent loop |
| Create ClickUp task | Auto-execute, BAKER space only | Same ClickUp write guard |
| Draft email (external) | **Queued for Director approval** | Same pending_drafts flow |
| Draft email (internal) | Auto-send | Same @brisengroup.com rule |
| WhatsApp message | **Director notification only** | Chain runner never sends WA to non-Director |
| Circuit breaker | Respected | check_circuit_breaker() before chain |

**New safety rule:** Max 1 chain per trigger. If a chain is already running for a matter, skip. Prevents cascade loops.

**Kill switch:** `BAKER_CHAINS_ENABLED=false` (env var). Defaults to `false` — opt-in, not opt-out.

---

## What Triggers Get Chains

Not everything should trigger autonomous action. The qualifier function:

```python
def should_chain(trigger: TriggerEvent, alert_tier: int, matter_slug: str) -> bool:
    """Only high-value, context-rich events get chains."""
    if not os.getenv("BAKER_CHAINS_ENABLED", "false").lower() == "true":
        return False
    if alert_tier > 2:          # T3 = info only
        return False
    if not matter_slug:         # No matter = no context to plan with
        return False
    if trigger.type in ("dropbox_file_new", "dropbox_file_modified", "rss_article"):
        return False            # Batch triggers = noise
    if not check_circuit_breaker()[0]:
        return False            # Budget exceeded
    return True
```

**Expected volume:** ~5-10 chains/day based on current T1/T2 alert rate with matched matters. Each chain = 1 Opus planning call + 3-5 tool executions. Incremental cost: ~EUR 2-5/day.

---

## Implementation Plan

### Batch 0: Chain Runner Core (3-4 days)

| # | Task | File | Notes |
|---|------|------|-------|
| 1 | Create `orchestrator/chain_runner.py` | New file | ChainRunner class with qualify, plan, execute, verify, report |
| 2 | Planning prompt | chain_runner.py | Structured JSON output, matter-aware |
| 3 | Step executor | chain_runner.py | Uses existing ToolExecutor, respects safety model |
| 4 | Verification loop | chain_runner.py | Check each step result, abort on critical failure |
| 5 | Director notification | chain_runner.py | WhatsApp summary via WAHA client |
| 6 | Chain logging | chain_runner.py | Extend baker_tasks with chain metadata |
| 7 | Integration hook | pipeline.py | Call chain_runner after alert creation for T1/T2 |
| 8 | Kill switch + env var | config/settings.py | BAKER_CHAINS_ENABLED default false |

### Batch 1: Standing Order Upgrade (3-4 days)

Upgrade existing standing order jobs to use chain runner instead of hardcoded logic:

| Job | Today | With chains |
|-----|-------|-------------|
| **Meeting prep** | Searches contacts + matters, generates briefing text | Chain: search contacts → pull recent comms → check open items → draft prep memo → create calendar block |
| **Deadline cadence** | Checks overdue, creates alerts | Chain: check overdue → identify responsible person → search last communication → draft follow-up email → alert Director |
| **Risk detection** | Calculates scores, creates risk alerts | Chain: detect risk → pull all signals → search for context → generate risk memo → create ClickUp task for tracking |

### Batch 2: Experience Learning (2-3 days)

| # | Task | Notes |
|---|------|-------|
| 1 | Chain outcome logging | Store plan + execution results + Director feedback |
| 2 | Experience retrieval | Before planning, retrieve similar past chains |
| 3 | Feedback integration | Director thumbs-up/down on chain results adjusts future planning |
| 4 | Chain analytics | Dashboard: chains/day, success rate, avg steps, Director edit rate |

---

## Success Metrics

| Metric | Target | How to measure |
|--------|--------|---------------|
| Director interventions per T1 event | Down from ~4 to ~1 (email approval only) | Count user actions per alert in baker_tasks |
| Time from event to full response | Down from ~30 min (manual) to ~2 min (chain) | Chain elapsed_ms in baker_tasks |
| Director edit rate on chain outputs | < 20% of email drafts need editing | Track pending_draft modifications |
| Chain completion rate | > 90% of chains complete all steps | Verify step in chain_runner |
| Cost per chain | < EUR 1.00 | 1 Opus plan + tool calls |

---

## What This Does NOT Do

- **Does not replace the agent loop.** The agent loop handles interactive questions (Scan, WhatsApp). Chains handle trigger-initiated autonomous actions. Different use cases.
- **Does not replace the capability framework.** Capabilities handle specialist analysis (legal, finance, sales). Chains handle operational responses (draft, deadline, follow-up). They can compose — a chain step could invoke a capability.
- **Does not change the safety model.** Same rules, same approval flows, same kill switches. Just orchestrated automatically instead of manually.
- **Does not require new infrastructure.** No new tables, no new services, no new dependencies. Pure Python orchestration using existing components.

---

## Director Decisions (LOCKED IN)

1. **Kill switch default:** `false` (opt-in). Director enables when ready.
2. **WhatsApp notification:** Write actions only — read-only chains stay silent in Cockpit.
3. **Auto-execute scope:** Deadlines, calendar, and ClickUp all auto-execute. Email drafts always queued.
4. **Standing order upgrade (Batch 1):** Evaluate Batch 0 results first (3-5 days), then decide.

---

## Comparison: This vs. OpenClaw vs. Agent SDK

| Dimension | AUTONOMOUS-CHAINS-1 | OpenClaw | Anthropic Agent SDK |
|-----------|---------------------|----------|---------------------|
| Effort | 1-2 weeks | 8-12 weeks (rewrite) | 2-3 weeks |
| Risk | Low (extends existing code) | High (alpha, security issues) | Medium (new dependency) |
| Incremental cost | EUR 2-5/day | Unknown | Similar |
| Baker tools | All 17, native | Must wrap as skills | Must wrap as SDK tools |
| Safety model | Inherited | Must rebuild | Must rebuild |
| Learning loop | Extends existing feedback | Build from scratch | Build from scratch |
| Production-ready | Yes (reuses battle-tested code) | No (alpha) | Mostly (SDK is stable) |

**Recommendation:** Build AUTONOMOUS-CHAINS-1 first. If it hits limits (complex multi-agent workflows, parallel execution), evaluate Anthropic Agent SDK as the next step. OpenClaw is not the right fit.
