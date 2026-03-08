# BRIEF: Slack Bot Integration (SLACK-BOT-1)

**Author:** Code 300 (Session 12)
**Status:** Ready for implementation
**Priority:** High
**Prerequisite:** Director must set `SLACK_BOT_TOKEN` on Render first

---

## Context

Baker already has Slack integration (polling + #cockpit notifications). But:
- `SLACK_BOT_TOKEN` is **not set on Render** — polling logs a warning every 5 min and skips
- Current model polls every 5 min — 0-5 min latency on @Baker mentions
- No real-time events (message.channels, reactions, DMs)

## What Exists (DO NOT REWRITE)

| Component | File | Status |
|-----------|------|--------|
| Polling trigger | `triggers/slack_trigger.py` | Working code, needs SLACK_BOT_TOKEN |
| Alert notifier | `outputs/slack_notifier.py` | Working code, needs SLACK_BOT_TOKEN |
| Scheduler job | `triggers/embedded_scheduler.py:120-128` | Registered (slack_poll, every 5 min) |
| Config | `config/settings.py:184-196` | SlackConfig dataclass |

### Current capabilities (once token is set):
- Poll configured channels every 5 min (watermark-based)
- Embed all human messages to Qdrant `baker-slack`
- @Baker mentions → full Sentinel pipeline → thread reply
- Post T1/T2 alerts to #cockpit with 2-level dedup
- Post morning briefings to #cockpit
- Post pipeline results (email/WA/meeting triggers)

## What to Build

### Step 1: Events API Webhook (replaces polling)

**New file:** `triggers/slack_events.py`

**FastAPI endpoint:** `POST /webhook/slack`

Flow:
```
Slack Events API → POST /webhook/slack
  ├─ url_verification challenge → return challenge
  ├─ event_callback:
  │   ├─ message (human, not bot) → _embed_message() (reuse from slack_trigger.py)
  │   ├─ message with @Baker mention → _feed_to_pipeline() (reuse from slack_trigger.py)
  │   ├─ app_mention → same as @Baker mention
  │   └─ reaction_added (optional) → log/store
  └─ verify signature (SLACK_SIGNING_SECRET)
```

**Rules:**
1. Reuse `_embed_message()` and `_feed_to_pipeline()` from `slack_trigger.py` — extract them to shared functions if needed
2. Verify Slack request signature using `SLACK_SIGNING_SECRET` (env var)
3. Return HTTP 200 within 3 seconds (Slack requirement) — use background task for pipeline
4. Deduplicate by event_id (Slack may retry)
5. Keep polling as fallback — don't remove it. Add env var `SLACK_MODE=events|polling` (default: polling)

### Step 2: Register webhook in dashboard.py

```python
from triggers.slack_events import router as slack_events_router
app.include_router(slack_events_router, prefix="/webhook")
```

### Step 3: DM Support (optional, if Director wants it)

If a user DMs Baker directly:
- Subscribe to `message.im` event
- Route through classify_intent() → same as WhatsApp Director messages
- Reply in DM thread

### Env Vars Needed

| Var | Purpose | Who sets |
|-----|---------|----------|
| `SLACK_BOT_TOKEN` | Bot OAuth token (xoxb-...) | Director |
| `SLACK_SIGNING_SECRET` | Request signature verification | Director |
| `SLACK_MODE` | `events` or `polling` (default: polling) | Code (after webhook verified) |
| `SLACK_CHANNEL_IDS` | Channels to monitor (already has default) | Already set |

### Slack App Configuration (Director task)

1. Go to api.slack.com/apps → select Baker app
2. **Event Subscriptions** → Enable → Request URL: `https://baker-master.onrender.com/webhook/slack`
3. **Subscribe to bot events:** `message.channels`, `app_mention`
4. **Bot Token Scopes** (should already have): `channels:history`, `chat:write`, `users:read`
5. Reinstall app to workspace
6. Copy Bot Token → set as `SLACK_BOT_TOKEN` on Render
7. Copy Signing Secret → set as `SLACK_SIGNING_SECRET` on Render

## Implementation Notes

- **Respond within 3 seconds:** Slack retries if no 200 response within 3s. Use FastAPI `BackgroundTasks` for pipeline processing. Return `{"ok": true}` immediately.
- **Event dedup:** Slack sends retry headers (`X-Slack-Retry-Num`). Check event_id against a simple in-memory set (TTL 5 min) or trigger_watermarks.
- **Signature verification:** Use `slack_sdk.signature.SignatureVerifier` — already in slack_sdk dependency.
- **Don't break existing code:** Polling + notifier stay unchanged. Events webhook is additive.

## Files to Create/Modify

| Action | File | What |
|--------|------|------|
| CREATE | `triggers/slack_events.py` | Events API webhook handler (~100 lines) |
| MODIFY | `outputs/dashboard.py` | Include slack events router |
| MODIFY | `config/settings.py` | Add signing_secret + mode to SlackConfig |

## Verification Checklist

1. `POST /webhook/slack` with url_verification → returns challenge
2. Message in monitored channel → embedded to Qdrant within 2s
3. @Baker mention in channel → pipeline runs, thread reply posted within 10s
4. Bot message in channel → ignored (no echo loop)
5. Request without valid signature → 401
6. Duplicate event_id → ignored
7. `SLACK_MODE=polling` → webhook still accepts but doesn't process (or vice versa: both can coexist)
8. Polling still works as fallback when SLACK_MODE=polling

## Scope

- **In scope:** Events webhook, signature verification, event dedup, DM support (optional)
- **Out of scope:** Slash commands, interactive components, home tab, modals — these are Phase 4+
- **Estimated size:** ~100-150 lines new code, ~10 lines config changes
