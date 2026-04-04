# BRIEF: Slack Interactive Workflow — Draft/Triage/Action Support

**Priority:** High — Director's Slack instructions to Baker are silently dropped
**Ticket:** SLACK-INTERACTIVE-1

## Problem

When Baker pushes an alert to Slack (e.g., "Sandra PR Meeting — Prep Needed Tomorrow") and the Director replies "Please draft", **nothing happens**. The message is stored in `slack_messages` but the draft is never created.

**Root cause:** Slack messages go through `_feed_to_pipeline()` (raw RAG analysis), NOT through `scan_chat()` which has:
- `classify_intent()` — detects draft/WhatsApp/action intents
- `check_pending_draft()` — draft approval loop
- `handle_email_action()` / `handle_whatsapp_action()` — action execution
- Conversation history awareness

Meanwhile, WhatsApp and Dashboard both use `scan_chat()` and work correctly.

**Second problem:** Even if routed correctly, "Please draft" has no context on its own. Baker doesn't know it's a reply to alert #14599 about Sandra/PR. The alert context must be linked.

## Solution — Two Changes

### Change 1: Route Director Slack Messages Through `scan_chat()`

**File:** `triggers/slack_trigger.py`

Currently, Director @Baker mentions go to `_feed_to_pipeline()`. Change this: when the message is from the Director, route through the same `scan_chat()` logic used by WhatsApp's `_handle_director_message()`.

Find the section where Director messages are detected and routed (look for `_feed_to_pipeline()` call for Director messages). Replace with a call that mirrors the WhatsApp Director handler flow:

```python
async def _handle_director_slack_message(text: str, channel_id: str, thread_ts: str, user_name: str):
    """
    Handle Director messages on Slack using the same interactive flow
    as WhatsApp and Dashboard (scan_chat path).
    """
    from orchestrator.action_handler import classify_intent, check_pending_draft, check_pending_plan
    from orchestrator.action_handler import ActionHandler
    from memory.retriever import Retriever

    retriever = Retriever()
    ah = ActionHandler()

    # --- Step 1: Build conversation history from recent Slack messages ---
    # Pull last 4 messages from same channel for context (2 turns = CONV-SAFETY-1)
    try:
        conn = get_pg_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT user_name, full_text FROM slack_messages
            WHERE channel_id = %s
            ORDER BY received_at DESC LIMIT 4
        """, (channel_id,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        history_lines = []
        for uname, ftxt in reversed(rows):
            role = "Director" if uname == user_name else "Baker"
            history_lines.append(f"{role}: {ftxt}")
        conversation_history = "\n".join(history_lines) if history_lines else ""
    except Exception:
        conversation_history = ""

    # --- Step 2: Check pending draft/plan (same as WhatsApp) ---
    draft_response = check_pending_draft(text)
    if draft_response:
        _post_slack_thread_reply(channel_id, thread_ts, draft_response)
        return

    plan_response = check_pending_plan(text)
    if plan_response:
        _post_slack_thread_reply(channel_id, thread_ts, plan_response)
        return

    # --- Step 3: Enrich with alert context if this looks like a reply ---
    enriched_text = await _enrich_with_alert_context(text, channel_id, thread_ts)

    # --- Step 4: Classify intent (same as scan_chat) ---
    intent = classify_intent(enriched_text, conversation_history=conversation_history)
    intent["original_question"] = enriched_text

    # --- Step 5: Route to appropriate handler ---
    intent_type = intent.get("type", "question")

    if intent_type == "email_action":
        result = ah.handle_email_action(intent, retriever, channel="slack",
                                         conversation_history=conversation_history)
        _post_slack_thread_reply(channel_id, thread_ts, result)

    elif intent_type == "whatsapp_action":
        result = ah.handle_whatsapp_action(intent, retriever, channel="slack",
                                            conversation_history=conversation_history)
        _post_slack_thread_reply(channel_id, thread_ts, result)

    elif intent_type == "capability_task":
        # Run specialist capability and post result
        result = await _run_capability_for_slack(intent, retriever, enriched_text)
        _post_slack_thread_reply(channel_id, thread_ts, result)

    elif intent_type == "question":
        # Fall back to existing pipeline for general questions
        # But use scan_chat-style RAG, not raw pipeline
        result = await _run_scan_for_slack(enriched_text, retriever, conversation_history)
        _post_slack_thread_reply(channel_id, thread_ts, result)

    else:
        # Other action types (clickup, deadline, vip, etc.)
        result = ah.handle_action(intent, retriever, channel="slack")
        _post_slack_thread_reply(channel_id, thread_ts, result)

    # Store to conversation_memory (same as scan_chat does)
    try:
        from memory.store_back import store_conversation_memory
        store_conversation_memory(enriched_text, result, project="general")
    except Exception as e:
        logger.warning(f"Slack conversation memory store failed: {e}")
```

**Important:** The existing `_feed_to_pipeline()` path should remain for NON-Director messages (team members, external contacts). Only Director messages get the interactive `scan_chat` treatment.

### Change 2: Link Slack Replies to Alert Context

When the Director says "Please draft" — that's meaningless without knowing WHAT to draft. The context comes from Baker's previous alert in the same Slack channel/thread.

**File:** `triggers/slack_trigger.py`

Add a function that enriches bare replies with the alert they're responding to:

```python
async def _enrich_with_alert_context(text: str, channel_id: str, thread_ts: str) -> str:
    """
    If the Director's message is short and looks like a reply to a Baker alert
    (e.g., "Please draft", "Run it", "Yes"), find the most recent Baker message
    in the same thread/channel and prepend it as context.
    """
    # Only enrich short messages that look like replies
    if len(text) > 200:
        return text  # Long enough to be self-contained

    _reply_patterns = [
        r'(?i)^(please\s+)?(draft|run|do it|yes|go ahead|send|proceed|approve|execute)',
        r'(?i)^(ok|okay|sure|confirmed?|agreed)',
    ]
    import re
    is_reply = any(re.match(p, text.strip()) for p in _reply_patterns)
    if not is_reply:
        return text

    # Find the most recent Baker message in this channel (not from Director)
    try:
        conn = get_pg_connection()
        cur = conn.cursor()

        # Option A: Check thread — if thread_ts exists, look for Baker's message in that thread
        # Option B: Check last Baker alert pushed to this channel
        # We use Option B since Baker's Slack posts may not be in slack_messages table

        # Find the most recent alert that was pushed to Slack (within last 24h)
        cur.execute("""
            SELECT id, title, body, structured_actions
            FROM alerts
            WHERE created_at > NOW() - INTERVAL '24 hours'
              AND status != 'dismissed'
            ORDER BY created_at DESC
            LIMIT 5
        """)
        recent_alerts = cur.fetchall()
        cur.close()
        conn.close()

        if not recent_alerts:
            return text

        # Use the most recent actionable alert as context
        # Prefer alerts with structured_actions (they're the ones that ask for draft/run)
        best_alert = None
        for alert_id, title, body, actions in recent_alerts:
            if actions and ('draft' in str(actions).lower() or 'run' in str(actions).lower()):
                best_alert = (alert_id, title, body)
                break
        if not best_alert:
            best_alert = (recent_alerts[0][0], recent_alerts[0][1], recent_alerts[0][2])

        alert_id, alert_title, alert_body = best_alert

        # Prepend alert context to the Director's reply
        enriched = (
            f"CONTEXT — This is a reply to Baker alert #{alert_id}: \"{alert_title}\"\n"
            f"Alert details: {alert_body[:500]}\n\n"
            f"Director's instruction: {text}"
        )
        logger.info(f"Enriched Slack reply with alert #{alert_id}: {alert_title[:60]}")
        return enriched

    except Exception as e:
        logger.warning(f"Alert context enrichment failed: {e}")
        return text
```

### Change 3: Store Baker's Slack Replies in `slack_messages`

Currently Baker's own Slack posts (thread replies) are NOT stored in `slack_messages` — only user messages are. This means conversation history is one-sided.

**File:** `triggers/slack_trigger.py`

After `_post_slack_thread_reply()` succeeds, also store Baker's reply:

```python
def _post_slack_thread_reply(channel_id, thread_ts, text):
    """Post a thread reply to Slack and store it."""
    # ... existing Slack API post logic ...

    # Store Baker's reply in slack_messages for history
    try:
        conn = get_pg_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO slack_messages (id, channel_id, channel_name, user_id, user_name, full_text, thread_ts, received_at, ingested_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (id) DO NOTHING
        """, (
            f"slack:{channel_id}:baker_{int(time.time())}",
            channel_id,
            '',  # channel_name — fill if available
            'baker',
            'Baker',
            text[:5000],  # Truncate very long responses
            thread_ts
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning(f"Failed to store Baker Slack reply: {e}")
```

## Implementation Sequence

1. **Change 3 first** — store Baker's replies (small, safe, no behavioral change)
2. **Change 2** — alert context enrichment (standalone function, testable in isolation)
3. **Change 1** — route Director messages through interactive flow (biggest change, depends on 2 and 3)

## Files to Modify

| File | Change |
|------|--------|
| `triggers/slack_trigger.py` | All 3 changes — Director routing, alert enrichment, reply storage |

## Testing

1. **Baker pushes alert to Slack** (e.g., deadline reminder with draft option)
2. **Director replies "Please draft"** → Baker should:
   - Detect it's a reply to an alert
   - Enrich with alert context
   - Classify intent as `email_action`
   - Generate a draft
   - Post draft to Slack thread: "📧 Draft ready — reply 'send' to confirm"
3. **Director replies "send"** → Baker should detect pending draft and send the email
4. **Director says "@Baker What's outstanding for Balazs?"** → Should work as before (question intent, RAG response)
5. **Non-Director team member says something** → Should go through old `_feed_to_pipeline()` path (no change)

## Edge Cases

- **Director says "Please draft" with no recent alert** → enrichment finds nothing → classify_intent gets bare "Please draft" → Baker asks "What would you like me to draft?"
- **Multiple recent alerts** → enrichment picks the most recent one with draft/run actions
- **Director sends long message** → enrichment skips (>200 chars = self-contained instruction)
- **Slack thread vs. channel** → use thread_ts when available to scope context to the right conversation

## Verification

```bash
python3 -c "import py_compile; py_compile.compile('triggers/slack_trigger.py', doraise=True)"
```

## Safety

- Only Director messages get the interactive flow — team/external stay on pipeline
- Email drafts still require "send" confirmation (same as dashboard/WhatsApp)
- Conversation history limited to 2 turns (CONV-SAFETY-1)
- Alert enrichment capped at 24h lookback and 500 chars of body
