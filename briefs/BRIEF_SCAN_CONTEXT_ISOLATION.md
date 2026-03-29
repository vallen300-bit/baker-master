# BRIEF: Scan Context Isolation (SCAN-CONTEXT-1)

**Author:** AI Head (Claude Code, Session 36)
**Date:** 2026-03-25
**Status:** Ready for Code Brisen
**Priority:** URGENT — caused wrong email sent to wrong person

## Incident

Director was viewing an alert about Mandarin/Davos negotiations. Tapped "Open in Scan." Asked Baker to "prepare a draft email to Balazs" about this topic. Baker used the **previous conversation context** (Polish translation → Denis) instead of the current alert context. Sent wrong email to Balazs without approval.

## Root Cause

When "Open in Scan" is tapped from an alert card, the Scan chat carries over the previous conversation history. Baker's intent classifier sees the old context and generates a response based on it, ignoring the alert the user is looking at.

## Fix — Three Parts

### Part 1: Inject Alert Context on "Open in Scan"

When the user taps "Open in Scan" from an alert card, the alert's title + body should be injected as the first message in a **new** conversation.

**File:** `outputs/static/mobile.js` (and `app.js` for desktop)

**Current behavior:** "Open in Scan" just switches to the Scan tab. No context passed.

**New behavior:** "Open in Scan" should:
1. Clear the current conversation (`newChat()`)
2. Auto-submit a system message like: `[Context: Alert — "{alert.title}". {alert.body}]`
3. Then let the user type their follow-up

**Implementation:**
```javascript
function openScanFromAlert(alert) {
    newChat();  // Clear previous conversation
    // Inject alert context as first message
    var contextMsg = 'Regarding: "' + alert.title + '"\n\n' + (alert.body || '').substring(0, 500);
    // Set the input field with context
    var input = document.getElementById('chatInput');
    input.value = contextMsg + '\n\nPlease help me with this.';
    // Switch to scan tab
    switchTab('scan');
}
```

### Part 2: Conversation Isolation

Even without "Open in Scan", Baker should not bleed context from old conversations into new email actions.

**File:** `outputs/dashboard.py` → `scan_chat()`

**Fix:** When `classify_intent()` returns `email_action`, validate that the email content matches the **current** conversation turn, not a previous one. Specifically:
- The subject line should be derived from the current user message, not from `conversation_history[-N]`
- If the user says "draft an email to X about Y", Y must come from the current message or the injected alert context

### Part 3: Draft Safety Reinforcement

The existing draft keyword detection (Session 35) should have caught "prepare a draft" but didn't prevent the send. Verify and strengthen.

**File:** `orchestrator/action_handler.py`

**Check:** The `handle_email_action()` now requires Director approval for ALL emails (fixed in Session 36). But also verify that `classify_intent()` doesn't bypass the draft flow when it detects email_action from conversation history.

## Files to Modify

| File | Changes |
|------|---------|
| `outputs/static/mobile.js` | "Open in Scan" injects alert context + clears old chat |
| `outputs/static/app.js` | Same for desktop |
| `outputs/dashboard.py` | Ensure scan_chat uses current context for email generation |

## Testing

1. View an alert about Topic A
2. Tap "Open in Scan"
3. Ask Baker to "draft an email to X about this"
4. Verify: email is about Topic A, not any previous topic
5. Verify: email is drafted (not sent), awaiting "send" confirmation

## Estimated Effort
~3 hours

## Priority
URGENT — this caused a real incident (wrong email sent to real person)
