# Phase 3B — Proactive Upgrades: Deadline Proposals, VIP Auto-Drafts, Morning Proposals

**Author:** Code 300 (architect)
**Date:** 2026-03-08
**Branch:** `feat/phase-3b-proactive`
**Builds on:** Phase 3A (calendar trigger), existing deadline_cadence + vip_sla_check + morning_brief

---

## What This Does

Three existing background jobs get "proactive upgrades" — Baker stops just alerting and starts proposing actions.

| Standing Order | Current (reactive) | Upgrade (proactive) |
|---|---|---|
| #2 No deadline missed | Alert: "Deadline in 2 days" | Alert + proposal: "Draft reminder to Ofenheimer. Attach evidence summary." |
| #3 VIP 24h response | Alert: "Unanswered VIP message from Constantinos" | Alert + auto-drafted response ready to send |
| #4 Morning briefing with proposals | Narrative: "2 fires, 3 deadlines" | Narrative + per-fire proposals: "Hagenauer → draft status update" |

**Pattern:** Same as Phase 3A — direct Haiku calls in background jobs. No /api/scan, no agentic loop. Assemble context, call Haiku, attach result to alert.

---

## Step 1 — Deadline Proposals

**Where:** `orchestrator/deadline_manager.py`

**Current flow:** `run_cadence_check()` (every hour) → detects deadline stage → creates T1/T2 alert with title like "Deadline approaching: Hagenauer filing (2 days)"

**Upgrade:** After creating the deadline alert, generate an action proposal via Haiku and attach as `structured_actions`.

### Implementation

Add a new function `_generate_deadline_proposal()` in `deadline_manager.py`:

```python
DEADLINE_PROPOSAL_PROMPT = """You are Baker, AI Chief of Staff for Dimitry Vallen (Chairman, Brisen Group).

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
        {"label": "Action name", "description": "...", "type": "draft|analyze|plan", "prompt": "..."}
      ]
    }
  ]
}
"""
```

**Context assembly:** For each deadline, gather:
- Deadline title, due date, matter_slug, description
- Related alerts (query alerts WHERE matter_slug matches)
- Related contacts (from matter_registry people field)

**Integration point:** In `run_cadence_check()`, after the alert is created (where `alerts_fired` is incremented), call:

```python
if alert_id and tier <= 2:
    proposal = _generate_deadline_proposal(dl, context)
    if proposal:
        store.update_alert_structured_actions(alert_id, proposal)
```

**Same pattern as `_generate_structured_actions()` in pipeline.py** — Haiku call, JSON parse, store as structured_actions on the alert. The COCKPIT-V3 card renderer already knows how to display structured_actions with Run buttons.

### What changes

| File | Change |
|------|--------|
| `orchestrator/deadline_manager.py` | Add `_generate_deadline_proposal()`, call after alert creation |

---

## Step 2 — VIP Auto-Drafts

**Where:** `orchestrator/decision_engine.py`

**Current flow:** `run_vip_sla_check()` (every 5 min) → finds unanswered VIP messages → creates alert or sends WhatsApp notification to Director

**Upgrade:** When a VIP message has been unanswered >4 hours (Tier 2 threshold), auto-draft a response and attach it to the alert as a structured_action with type "draft".

### Implementation

Add a new function `_generate_vip_draft()` in `decision_engine.py`:

```python
VIP_DRAFT_PROMPT = """You are Baker, AI Chief of Staff for Dimitry Vallen (Chairman, Brisen Group).

A VIP contact has sent a message that hasn't been responded to. Draft a professional response.

Rules:
- Match the Director's tone: warm but direct, like a trusted advisor
- Keep it concise — VIP messages deserve quick, substantive replies
- If you need more context to draft properly, say what's missing
- Include a greeting and sign-off appropriate to the relationship
- If the message requires a decision the Director hasn't made, acknowledge receipt and set expectations

Return ONLY valid JSON:
{
  "problem": "VIP waiting for response — relationship risk",
  "cause": "Message received [time] ago, no reply detected",
  "solution": "Send response to maintain VIP relationship",
  "parts": [
    {
      "label": "Respond to [VIP name]",
      "actions": [
        {
          "label": "Send draft reply",
          "description": "Review and send Baker's draft response",
          "type": "draft",
          "prompt": "Draft a reply to [VIP name] regarding: [message summary]. Context: [relationship, recent history]"
        },
        {
          "label": "Acknowledge and defer",
          "description": "Quick acknowledgment — will reply in detail later",
          "type": "draft",
          "prompt": "Draft a short acknowledgment to [VIP name] saying you received their message and will reply with a full response by [timeframe]"
        }
      ]
    }
  ]
}
"""
```

**Context assembly:** For each VIP breach:
- VIP name, role, tier, communication_pref, expertise, role_context (from vip_contacts)
- The unanswered message content (from whatsapp_messages)
- Recent conversation history (last 5 messages in same chat)
- Related matters (from alerts WHERE title/body mentions VIP name)

**Integration point:** In `run_vip_sla_check()`, after an SLA breach is detected AND an alert/notification is created, call:

```python
# Only for Tier 2+ breaches (>4h) — don't auto-draft for 15-min T1 alerts
if wait_minutes >= 240:  # 4 hours
    draft = _generate_vip_draft(vip, msg, conversation_context)
    if draft and alert_id:
        store.update_alert_structured_actions(alert_id, draft)
```

**IMPORTANT:** The VIP SLA check currently creates alerts via different mechanisms (WhatsApp direct message, Slack notification, etc.). Find the exact point where an alert is created and attach the draft there. If no alert_id is available (e.g., only WhatsApp notification sent), create a T2 alert first, then attach the draft.

### What changes

| File | Change |
|------|--------|
| `orchestrator/decision_engine.py` | Add `_generate_vip_draft()`, integrate into `run_vip_sla_check()` |

---

## Step 3 — Morning Briefing with Proposals

**Where:** `outputs/dashboard.py`

**Current flow:** `_get_morning_narrative()` → Haiku generates 2-3 sentence summary from stats + fire titles → cached 30 min

**Upgrade:** For each top fire (up to 3), generate a one-line proposal. Append to narrative.

### Implementation

**Modify `_get_morning_narrative()`** — after generating the summary, add a proposals section:

```python
def _get_morning_narrative(fire_count, deadline_count, processed, top_fires, deadlines=None):
    # ... existing narrative generation ...

    # Phase 3B: Generate proposals for top fires
    if top_fires:
        proposals = _generate_morning_proposals(top_fires[:3], deadlines or [])
        if proposals:
            narrative += "\n\n" + proposals

    return narrative
```

**New function `_generate_morning_proposals()`:**

```python
MORNING_PROPOSALS_PROMPT = """You are Baker. Given the Director's top fires and upcoming deadlines, propose ONE specific action for each fire.

Rules:
- One line per fire. Start with the matter name.
- Be specific: name the person, document, or action.
- Format: "Matter → Action"
- Max 3 proposals.
- If a deadline is attached to a fire, mention the timeline.

Examples:
- "Hagenauer → Draft status update to Ofenheimer before Friday filing deadline"
- "BCOMM M365 → Schedule kickoff call with Benjamin Schuster"
- "Cupial → Review FM List counter-proposal, prepare negotiation position"
"""
```

**Context:** Pass fire titles + bodies (truncated to 200 chars each) + deadline info. Direct Haiku call, same as existing narrative generation.

**Caching:** The proposals are generated as part of the narrative, so they inherit the 30-min cache. When cache invalidates (T1 alert created), fresh proposals are generated.

**Frontend:** No changes needed — the narrative is already rendered as markdown in the Morning Brief. The proposals will appear as additional lines.

### What changes

| File | Change |
|------|--------|
| `outputs/dashboard.py` | Add `_generate_morning_proposals()`, call from `_get_morning_narrative()` |

---

## CRITICAL Rules

1. **All proposals use direct Haiku calls.** No /api/scan, no agentic RAG, no capability routing. Background jobs must be fast and cheap. Haiku is the right tool — same pattern as structured_actions generation.

2. **VIP auto-drafts only at Tier 2 threshold (>4h).** Don't auto-draft for 15-minute T1 alerts — those are urgent notifications, not draft opportunities.

3. **Deadline proposals use the same JSON format as structured_actions.** The COCKPIT-V3 card renderer already handles PCS + action parts with Run buttons. No frontend changes needed for Steps 1 and 2.

4. **Morning proposals are text appended to narrative.** No structured JSON — just additional lines in the markdown narrative. Keeps the Morning Brief simple and readable.

5. **All Haiku calls are fault-tolerant.** Wrap in try/except. If proposal generation fails, the alert still works — it just doesn't have proposals attached. Same pattern as existing `_generate_structured_actions()`.

6. **Don't break existing alert flows.** The proposal generation happens AFTER the alert is created. If it fails, the alert still exists. Never block alert creation on proposal generation.

---

## Existing Code Reference

| What | Where | Notes |
|------|-------|-------|
| `run_cadence_check()` | `deadline_manager.py:217` | Hourly deadline check, creates alerts by stage |
| `_determine_stage()` | `deadline_manager.py` | Stage logic: 30d→7d→2d→48h→day_of→overdue |
| `run_vip_sla_check()` | `decision_engine.py:499` | 5-min VIP check, T1 (15min) + T2 (4h) thresholds |
| `_get_morning_narrative()` | `dashboard.py:852` | Haiku narrative, 30-min cache |
| `_generate_structured_actions()` | `pipeline.py:125` | Pattern to follow: Haiku → JSON → store |
| `update_alert_structured_actions()` | `store_back.py:2571` | Stores structured_actions JSON on alert |
| `MEETING_PREP_PROMPT` | `calendar_trigger.py:95` | Reference for prompt style |
| `create_alert()` | `store_back.py:2444` | Returns alert_id for attaching proposals |

---

## Commit Plan

```
Step 1: feat: Phase 3B step 1 -- deadline proposals via Haiku
Step 2: feat: Phase 3B step 2 -- VIP auto-draft responses
Step 3: feat: Phase 3B step 3 -- morning briefing proposals
```

3 commits on branch `feat/phase-3b-proactive`. Push to origin when complete. Code 300 will review before merge.
