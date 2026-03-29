# BRIEF: Conversation History Safety (CONV-SAFETY-1)

**Author:** AI Head (Claude Code, Session 36)
**Date:** 2026-03-25
**Status:** Ready for Code Brisen
**Priority:** HIGH — prevents wrong-context emails

## Problem

Baker's intent classifier and email generator use conversation history (up to 15 turns) to understand context. When the user switches topics mid-conversation (e.g., from Polish translation to Mandarin negotiations), Baker may generate emails based on the OLD topic instead of the current one.

This is especially dangerous for email_action intents because Baker was auto-sending internal emails (now fixed — all emails require approval). But even with drafts, generating a wrong-context email wastes time and confuses the Director.

## Root Cause

In `outputs/dashboard.py` → `scan_chat()`, the conversation history is passed to `classify_intent()` and then to the prompt builder. The history includes ALL previous turns in the session, not just the relevant ones.

When Baker sees "draft an email to Balazs" and the history contains a recent email about "Polish translation for Denis," it merges the contexts.

## Fix

### 1. Topic Detection on Email Actions

Before generating an email, check if the user's current message specifies a topic. If yes, use ONLY that topic. If no, use the most recent alert context (if opened from an alert) or ask the user to clarify.

**File:** `orchestrator/action_handler.py` → `handle_email_action()`

Add at the top of email generation:
```python
# If the user's current message specifies a topic, use it exclusively
# Don't fall back to conversation history for email content
current_topic = extract_topic_from_current_message(question)
if not current_topic:
    # Ask for clarification instead of guessing from history
    return "What should this email be about? Please specify the topic."
```

### 2. Limit History Window for Email Actions

When the intent is `email_action`, reduce the conversation history passed to the prompt from 15 turns to **2 turns** (just the current exchange). This prevents old context from bleeding in.

**File:** `outputs/dashboard.py` → `scan_chat()` or `orchestrator/prompt_builder.py`

```python
if intent_type == "email_action":
    # Use minimal history to prevent context bleed
    effective_history = conversation_history[-2:]  # Only last exchange
```

### 3. Context Anchor for Alert-Opened Scans

When Scan is opened from an alert, store the alert context in the session. All subsequent actions in that Scan session should use this alert as the primary context.

**File:** `outputs/dashboard.py`

```python
# Store alert context when opened from alert card
if req.alert_context:
    session_context = f"Current topic: {req.alert_context['title']}\n{req.alert_context['body']}"
    # Prepend to conversation for this session
```

## Files to Modify

| File | Changes |
|------|---------|
| `orchestrator/action_handler.py` | Topic extraction from current message |
| `outputs/dashboard.py` | Limit history for email actions, alert context anchor |
| `orchestrator/prompt_builder.py` | Reduced history for email_action intent |

## Testing

1. Chat about Topic A (Polish translation)
2. In same session, ask "draft email to Balazs about Mandarin negotiations"
3. Verify: email is about Mandarin, NOT Polish translation
4. Verify: if no topic specified ("draft email to Balazs"), Baker asks "What should this email be about?"

## Estimated Effort
~2.5 hours

## Relationship to Other Briefs
- **SCAN-CONTEXT-1**: Fixes the "Open in Scan" flow (alert → scan context injection)
- **This brief**: Fixes the conversation history bleed (general safety)
- Both should be implemented — they cover different entry points to the same bug class
