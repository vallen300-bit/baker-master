# BRIEF: COCKPIT-ALERT-UI — Interactive Alert Command Interface

**Author:** Code 300 (Architect)
**Builder:** Code Brisen
**Depends on:** AGENT-FRAMEWORK-1 (merged, live)
**Priority:** High — transforms CEO Cockpit from chat to command interface

---

## 1. Summary

Replace Baker's plain-text alerts with interactive, structured command cards.
The Director reads the situation (problem/cause/solution), selects actions he wants
Baker to execute, and Baker routes each action to the right capability.

**Before:** Alert is a wall of text. Director reads, then manually types what he
wants Baker to do.

**After:** Alert arrives pre-analyzed with grouped action cards. Director taps
the actions he wants. Baker executes. No typing required for the 80% case.

---

## 2. Alert Format — Data Structure

### Stored in PostgreSQL (`alerts` table)

Add column to existing `alerts` table:

```sql
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS structured_actions JSONB;
```

### JSON Structure

```json
{
  "problem": "3-4 lines summarizing the issue",
  "cause": "2 lines — Baker's analysis of root cause",
  "solution": "2-3 lines — what solved looks like",
  "parts": [
    {
      "label": "Legal defense",
      "actions": [
        {
          "label": "Forward Neubauer letter to Aukera",
          "description": "Draft email with letter attached and proposed call times",
          "type": "draft",
          "prompt": "Draft an email to Aukera forwarding the Neubauer Fähnrich letter and proposing a joint call with E+H"
        },
        {
          "label": "E+H termination risk assessment",
          "description": "Instruction email to Arndt: probability this termination holds + available defenses",
          "type": "draft",
          "prompt": "Draft instruction to Arndt Blaschka asking for written assessment of termination risk under §1170b"
        }
      ]
    },
    {
      "label": "Financial response",
      "actions": [
        {
          "label": "Security options comparison",
          "description": "Table: bank guarantee vs escrow vs cash deposit — cost, speed, legal strength",
          "type": "analyze",
          "prompt": "Produce a comparison table of security provision options for the EUR 5.85M Hagenauer demand"
        },
        {
          "label": "Analyze set-off position",
          "description": "Net calculation showing security amount after valid deductions",
          "type": "analyze",
          "prompt": "Review the Stellungnahme and Hagenauer claims, produce a net position calculation showing what security should be after valid set-offs"
        }
      ]
    },
    {
      "label": "Project management",
      "actions": [
        {
          "label": "Create Hagenauer response plan",
          "description": "Staged ClickUp tasks: legal response → security provision → deadline management",
          "type": "plan",
          "prompt": "Create a ClickUp project plan for responding to the Hagenauer termination threat by 14 March"
        }
      ]
    }
  ]
}
```

### Four Action Types

| Tag | `type` value | What Baker Produces | Internal Route |
|-----|-------------|---------------------|----------------|
| 📋 | `plan` | ClickUp task structure, timeline, milestones | `action_handler.handle_clickup_plan()` |
| 🔍 | `analyze` | Report, comparison table, study, review | `CapabilityRunner.run_single()` |
| ✉️ | `draft` | Email, letter, memo, presentation outline | `action_handler.handle_email_action()` or `CapabilityRunner` |
| 🎯 | `specialist` | Deep domain analysis from named capability | `CapabilityRunner.run_single(named_capability)` |

---

## 3. Frontend — UI Layout

### Alert Card Layout

```
┌─────────────────────────────────────────────────────────────┐
│ ⚠️ HAGENAUER: Contract termination — 8 days          [T1]  │
│                                                             │
│ Problem: Hagenauer's lawyers demand EUR 5.85M security      │
│ by 14 March or contract terminates under §1170b. They       │
│ used Brisen's own Stellungnahme numbers.                    │
│                                                             │
│ Cause: The 05.03 letter acknowledged EUR 5.85M as           │
│ outstanding. Lawyers argue set-off doesn't reduce it.       │
│                                                             │
│ Solution: Security reduced via set-off, provided in a       │
│ form that protects cash, or deadline extended.              │
│─────────────────────────────────────────────────────────────│
│                                                             │
│ LEGAL DEFENSE                                               │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Draft email with letter attached        ✉️ Forward to  │ │
│ │ and proposed call times                    Aukera    [▶]│ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Instruction to Arndt: probability +     ✉️ E+H risk    │ │
│ │ defenses under §1170b                      assess.  [▶]│ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ I have a different idea for this part:  ✎ Something    │ │
│ │ [________________________________]         else     [▶]│ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │                                         ○ Skip this    │ │
│ │                                           part         │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ FINANCIAL RESPONSE                                          │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Table: guarantee vs escrow vs cash —    🔍 Security    │ │
│ │ cost, speed, legal strength                options  [▶]│ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Net calculation after valid deductions  🔍 Set-off     │ │
│ │                                            analysis [▶]│ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ I have a different idea for this part:  ✎ Something    │ │
│ │ [________________________________]         else     [▶]│ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │                                         ○ Skip this    │ │
│ │                                           part         │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Anything else not covered above:        ✎ Something    │ │
│ │ [________________________________]         else     [▶]│ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│          [ Execute Selected ]     [ Dismiss ]               │
└─────────────────────────────────────────────────────────────┘
```

### Card Layout Rules

Each action card has two columns:
- **Left (wider):** Description — what you're getting and why
- **Right (narrower):** Action type tag + action label + select button [▶]

Each part has three controls:
1. **Action cards** — multi-select (click [▶] to toggle selection, highlighted when selected)
2. **Something else** — free text input for that specific part
3. **Skip** — dismiss the entire part

Global **Something else** at bottom for anything outside all parts.

### Visual Design

- Action cards: dark background (`var(--card)`), border highlight on hover
- Selected cards: accent border (`var(--accent)`) + subtle background shift
- Type tags: color-coded pill badges
  - 📋 plan → cyan
  - 🔍 analyze → purple
  - ✉️ draft → gold
  - 🎯 specialist → green
- Skip: muted, smaller, no border — visually de-emphasized
- Something else: dashed border, text input visible on focus

---

## 4. Frontend — Interaction Flow

### User selects actions

```javascript
// State tracking
let selectedActions = {};  // partIndex -> [actionIndex, ...]
let freetextValues = {};   // partIndex -> string (or "global" -> string)
let skippedParts = {};     // partIndex -> true

// On action card click
function toggleAction(partIdx, actionIdx) {
    if (skippedParts[partIdx]) return;  // Can't select in skipped part
    selectedActions[partIdx] = selectedActions[partIdx] || [];
    const idx = selectedActions[partIdx].indexOf(actionIdx);
    if (idx >= 0) selectedActions[partIdx].splice(idx, 1);
    else selectedActions[partIdx].push(actionIdx);
    updateCardHighlights();
}

// On skip click
function skipPart(partIdx) {
    skippedParts[partIdx] = !skippedParts[partIdx];
    if (skippedParts[partIdx]) {
        selectedActions[partIdx] = [];
        freetextValues[partIdx] = "";
    }
    updatePartVisuals(partIdx);
}

// On something else input
function setFreetext(partIdx, text) {
    freetextValues[partIdx] = text;
}
```

### Execute selected

```javascript
async function executeSelected(alertId) {
    const prompts = [];

    // Collect selected action prompts
    for (const [partIdx, actionIdxs] of Object.entries(selectedActions)) {
        for (const actionIdx of actionIdxs) {
            const action = alertData.parts[partIdx].actions[actionIdx];
            prompts.push({
                prompt: action.prompt,
                type: action.type,
                label: action.label,
                part: alertData.parts[partIdx].label,
            });
        }
    }

    // Collect freetext prompts (per-part)
    for (const [partIdx, text] of Object.entries(freetextValues)) {
        if (text && text.trim() && partIdx !== "global") {
            prompts.push({
                prompt: text.trim(),
                type: "analyze",  // Default type for freetext
                label: "Custom request",
                part: alertData.parts[partIdx].label,
            });
        }
    }

    // Global freetext
    if (freetextValues.global && freetextValues.global.trim()) {
        prompts.push({
            prompt: freetextValues.global.trim(),
            type: "analyze",
            label: "Custom request",
            part: "General",
        });
    }

    if (prompts.length === 0) return;

    // Execute sequentially — each prompt goes to /api/scan
    for (const p of prompts) {
        showExecutionHeader(p.part, p.label, p.type);
        await streamScanRequest(p.prompt);  // Existing SSE stream handler
    }

    // Mark alert as actioned
    await bakerFetch(`/api/alerts/${alertId}/acknowledge`, { method: 'POST' });
}
```

---

## 5. Backend Changes

### 5a. Alert generation — structured_actions column

Add `structured_actions JSONB` to `alerts` table:

```sql
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS structured_actions JSONB;
```

### 5b. Pipeline alert generation

When the pipeline generates a Tier 1/2 alert, it should also produce structured actions.
This requires the alert generation prompt to output the JSON structure above.

Two approaches (implement approach A first):

**Approach A (simple):** After creating the alert with the existing text body, make a
second Claude call (Haiku, fast) to generate the structured actions JSON from the alert text.
Store in `structured_actions`. Cost: ~$0.002 per alert.

**Approach B (integrated, future):** Modify the pipeline prompt to produce both the text
alert AND the structured actions in one call. More efficient but requires prompt engineering.

### 5c. New endpoint: `POST /api/alerts/{id}/execute-action`

Receives a selected action prompt, routes it through the capability framework:

```python
@app.post("/api/alerts/{alert_id}/execute-action")
async def execute_alert_action(alert_id: int, body: ActionRequest):
    """Execute a single action from a structured alert."""
    # body.prompt = the action's prompt text
    # body.type = "plan" | "analyze" | "draft" | "specialist"
    # Route based on type:
    #   plan → handle_clickup_plan(body.prompt)
    #   analyze → CapabilityRouter().route(body.prompt) → CapabilityRunner
    #   draft → handle_email_action(classify_intent(body.prompt))
    #   specialist → CapabilityRunner.run_single(named_capability, body.prompt)
    # Stream result via SSE
```

Alternatively, the frontend can just POST each prompt to the existing `/api/scan`
endpoint — it already handles all routing. The action `type` is then just a frontend
hint for display, not a backend routing parameter.

**Recommended: Use existing `/api/scan`** for v1. The type tags are frontend-only visual
indicators. Baker's existing intent classification + capability routing will handle the rest.

### 5d. Alert acknowledge/dismiss endpoints

```python
@app.post("/api/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int):
    """Mark alert as acknowledged after Director acts on it."""

@app.post("/api/alerts/{alert_id}/dismiss")
async def dismiss_alert(alert_id: int):
    """Dismiss alert without acting."""
```

---

## 6. Frontend Files to Modify

### 6a. `outputs/static/app.js`

- New function: `renderStructuredAlert(alertData)` — builds the card UI
- New function: `toggleAction()`, `skipPart()`, `setFreetext()` — interaction handlers
- New function: `executeSelected()` — collects prompts, sends to `/api/scan` sequentially
- Modify existing alert display to check for `structured_actions` — if present, render
  the command interface; if absent, render the old plain-text format (backward compat)

### 6b. `outputs/static/index.html`

- CSS for action cards, type tags, selected state, skip state, freetext inputs
- CSS for the structured alert container

### 6c. No new HTML files needed

Everything renders inside the existing CEO Cockpit page.

---

## 7. Implementation Order

### Step 1: Database + API (backend only)
1. Add `structured_actions` JSONB column to `alerts` table
2. Add acknowledge/dismiss endpoints
3. No frontend change yet — alerts display as before

### Step 2: Structured action generation
1. After pipeline creates an alert, make a Haiku call to generate structured actions JSON
2. Store in `structured_actions` column
3. Test: check alert via API, confirm structured_actions is populated

### Step 3: Frontend — read-only display
1. When `structured_actions` exists, render the problem/cause/solution header
2. Render grouped parts with action cards (read-only, no interaction yet)
3. Old alerts without `structured_actions` display as before

### Step 4: Frontend — interactive execution
1. Action card selection (toggle highlight)
2. Skip part toggle
3. Something else freetext (per-part + global)
4. Execute Selected button → sends prompts to `/api/scan` sequentially
5. Results stream below the alert card
6. Acknowledge/dismiss buttons

### Step 5: Polish
1. Type tag color coding
2. Execution progress indicator (which action is running)
3. Completed action cards get a checkmark
4. Mobile responsive layout

---

## 8. Backward Compatibility

- Alerts without `structured_actions` display exactly as today (plain text)
- The structured format is additive — old alerts are never modified
- `/api/scan` handles all execution — no new execution endpoint needed for v1
- WhatsApp alerts continue as text (structured format is Cockpit-only for now)

---

## 9. Testing Checklist

- [ ] Alert with `structured_actions` renders the command interface
- [ ] Alert without `structured_actions` renders plain text (backward compat)
- [ ] Selecting an action card highlights it
- [ ] Deselecting an action card removes highlight
- [ ] Skip toggles off all selections for that part and grays it out
- [ ] Something else freetext accepts input per part
- [ ] Global freetext accepts input
- [ ] Execute Selected sends only selected prompts to `/api/scan`
- [ ] Results stream below the alert for each action
- [ ] Acknowledge marks the alert as actioned
- [ ] Dismiss marks the alert as dismissed
- [ ] Empty selection → Execute button disabled
- [ ] Multiple actions execute sequentially (not parallel)

---

## 10. Code Brisen — Opening Prompt

```
Read CLAUDE.md. Read briefs/BRIEF_COCKPIT_ALERT_UI.md.
This is the CEO Cockpit interactive alert system.
Implement Steps 1-5 in order.
Commit locally after each step. Do NOT push.
Each commit message: "feat: COCKPIT-ALERT-UI step N — [description]"
```
