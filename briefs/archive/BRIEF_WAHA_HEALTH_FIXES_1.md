# BRIEF: WAHA-HEALTH-FIXES-1 — WhatsApp Health Monitoring + Sender Bug + Scheduled Restart

## Context
WAHA (WhatsApp HTTP API) silently dropped messages from low-frequency contacts due to memory exhaustion on 512MB Starter plan (39 days without restart). Director discovered missing Pisani messages. Root cause confirmed: NoWeb engine stores messages in-memory, evicts low-frequency contacts under pressure.

**Already done (AI Head, Apr 8):**
- Upgraded WAHA from Starter (512MB) → Standard (2GB) on Render
- Restarted WAHA (deploy `dep-d7avof6dqaus73c5dj40`)
- Stored Baker decision #11219

**This brief covers the remaining engineering fixes.**

## Estimated time: ~2h
## Complexity: Medium
## Prerequisites: WAHA restart + upgrade (DONE)

---

## Fix 1: Add WhatsApp to Sentinel Health Monitoring

### Problem
WhatsApp has **zero health tracking**. Every other sentinel (email, ClickUp, Slack, Fireflies, Todoist, Dropbox, Calendar, Browser) reports success/failure to `sentinel_health` table. WhatsApp does not. When ingestion silently fails, nobody knows.

### Current State
- `triggers/waha_webhook.py` — webhook receiver, no health reporting
- `scripts/extract_whatsapp.py` → `backfill_whatsapp()` — 6h re-sync, no health reporting
- `triggers/embedded_scheduler.py:137-145` — `whatsapp_resync` job registered, calls `backfill_whatsapp()`
- `triggers/sentinel_health.py` — has `report_success(source)`, `report_failure(source, error)`, `should_skip_poll(source)` API
- `_WATERMARK_MAX_AGE` dict (line 361) — does NOT include whatsapp

### Implementation

**File: `triggers/waha_webhook.py`**

Add health reporting after successful message processing. Find the main webhook handler (the `@router.post` function that processes incoming messages). At the end of successful processing, add:

```python
# WAHA-HEALTH-FIXES-1: Report WhatsApp health
try:
    from triggers.sentinel_health import report_success
    report_success("whatsapp")
except Exception:
    pass
```

Also add failure reporting in the exception handler(s):

```python
# WAHA-HEALTH-FIXES-1: Report WhatsApp health on failure
try:
    from triggers.sentinel_health import report_failure
    report_failure("whatsapp", str(e))
except Exception:
    pass
```

**File: `scripts/extract_whatsapp.py`**

Add health reporting to `backfill_whatsapp()` function. After successful completion (line ~563):

```python
        logger.info(
            f"WhatsApp backfill complete: {ingested} ingested, "
            f"{skipped} deduped, {errors} errors"
        )
        # WAHA-HEALTH-FIXES-1: Report backfill health
        try:
            from triggers.sentinel_health import report_success, report_failure
            if errors == 0 or ingested > 0:
                report_success("whatsapp_backfill")
            else:
                report_failure("whatsapp_backfill", f"{errors} errors, 0 ingested")
        except Exception:
            pass
```

In the outer except block (line ~567):

```python
    except Exception as e:
        logger.error(f"WhatsApp backfill failed: {e}")
        # WAHA-HEALTH-FIXES-1: Report backfill failure
        try:
            from triggers.sentinel_health import report_failure
            report_failure("whatsapp_backfill", str(e))
        except Exception:
            pass
```

**File: `triggers/sentinel_health.py`**

Add whatsapp to stale watermark monitoring. In `_WATERMARK_MAX_AGE` dict (line 361), add:

```python
_WATERMARK_MAX_AGE = {
    "email_poll": 2,         # polls every 5 min
    "fireflies": 48,         # polls every 15 min, but may have no new data
    "todoist": 2,            # polls every 5 min
    "dropbox": 6,            # polls every 5 min
    "slack": 2,              # polls every 5 min
    "whatsapp_resync": 12,   # WAHA-HEALTH-FIXES-1: re-syncs every 6h, 12h max tolerable
}
```

### Key Constraints
- **Non-fatal wrappers** — all health reporting in try/except. Never break message processing for health tracking.
- **Two separate sources** — `"whatsapp"` (webhook, real-time) and `"whatsapp_backfill"` (6h resync). Separate so dashboard shows both.
- **Lazy imports** — `from triggers.sentinel_health import ...` inside the try block to avoid circular imports.

### Verification
```sql
-- Check WhatsApp health entries exist after deploy
SELECT source, status, consecutive_failures, last_success_at
FROM sentinel_health
WHERE source IN ('whatsapp', 'whatsapp_backfill')
ORDER BY source;
```

---

## Fix 2: Fix Sender Attribution Bug

### Problem
When `fromMe=True` (Director's outbound messages), the code stores `sender = m.get("from")` which is the **remote party's JID** (e.g., Pisani's number), not the Director's. This means outbound messages have the wrong sender.

### Current State
`scripts/extract_whatsapp.py`, lines 58-64:
```python
sender_jid = m.get("from", "")
from_me = m.get("fromMe", False)
name = _sender_name(m)
body = m.get("body", "") or ""
ts = m.get("timestamp", 0)

is_director = from_me or sender_jid in (DIRECTOR_WHATSAPP_JID, DIRECTOR_WHATSAPP_CUS)
```

The `sender_jid` variable is used on line 76: `sender=sender_jid`. When `fromMe=True`, WAHA's `"from"` field contains the chat counterpart, not the Director.

### Implementation

**File: `scripts/extract_whatsapp.py`**

Replace lines 58-64 with:

```python
            sender_jid = m.get("from", "")
            from_me = m.get("fromMe", False)
            name = _sender_name(m)
            body = m.get("body", "") or ""
            ts = m.get("timestamp", 0)

            # WAHA-HEALTH-FIXES-1: Fix sender attribution for outbound messages.
            # When fromMe=True, WAHA's "from" field is the remote party, not Director.
            # Override sender to Director's JID for outbound messages.
            if from_me:
                sender_jid = DIRECTOR_WHATSAPP_CUS  # "41799605092@c.us"
                name = "Director"

            is_director = from_me or sender_jid in (DIRECTOR_WHATSAPP_JID, DIRECTOR_WHATSAPP_CUS)
```

### Key Constraints
- Only change the `sender_jid` and `name` for `fromMe=True` messages. Inbound messages remain untouched.
- `DIRECTOR_WHATSAPP_CUS` is already defined at line 39: `"41799605092@c.us"`
- The `is_director` check on the next line still works — `from_me` is True so it evaluates correctly.

### Verification
After deploy, wait for next backfill (or trigger manually via `POST /api/whatsapp/backfill?days=7`), then:
```sql
-- Check Director's outbound messages have correct sender
SELECT id, sender, sender_name, is_director, chat_id
FROM whatsapp_messages
WHERE is_director = TRUE
ORDER BY timestamp DESC
LIMIT 10;

-- All rows should show sender = '41799605092@c.us', sender_name = 'Director'
-- NOT the remote party's JID
```

---

## Fix 3: WAHA Scheduled Weekly Restart

### Problem
WAHA's NoWeb engine accumulates memory over time. Even with the 2GB upgrade, a preventive weekly restart avoids future accumulation issues.

### Current State
- No restart mechanism exists
- WAHA ran 39 days without restart on the old plan
- `triggers/embedded_scheduler.py` has APScheduler with CronTrigger support (used for daily briefing)

### Implementation

**File: `triggers/embedded_scheduler.py`**

Add a weekly WAHA restart job. After the `whatsapp_resync` registration block (around line 145), add:

```python
    # WAHA-HEALTH-FIXES-1: Weekly WAHA restart — prevents memory accumulation
    # Restarts WAHA service on Render every Sunday at 04:00 UTC
    def _restart_waha_service():
        """Restart WAHA via Render deploy API."""
        import os
        import requests
        render_api_key = os.getenv("RENDER_API_KEY", "")
        waha_service_id = "srv-d6hiiff5r7bs73euhd4g"
        if not render_api_key:
            logger.warning("WAHA restart: RENDER_API_KEY not set — skipping")
            return
        try:
            resp = requests.post(
                f"https://api.render.com/v1/services/{waha_service_id}/deploys",
                headers={"Authorization": f"Bearer {render_api_key}"},
                json={"clearCache": "do_not_clear"},
                timeout=30,
            )
            if resp.status_code in (200, 201):
                logger.info(f"WAHA restart: deploy triggered successfully")
                try:
                    from triggers.sentinel_health import report_success
                    report_success("waha_restart")
                except Exception:
                    pass
            else:
                logger.warning(f"WAHA restart failed: {resp.status_code} {resp.text[:200]}")
                try:
                    from triggers.sentinel_health import report_failure
                    report_failure("waha_restart", f"HTTP {resp.status_code}")
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"WAHA restart exception: {e}")
            try:
                from triggers.sentinel_health import report_failure
                report_failure("waha_restart", str(e))
            except Exception:
                pass

    scheduler.add_job(
        _restart_waha_service,
        CronTrigger(day_of_week="sun", hour=4, minute=0),
        id="waha_weekly_restart", name="WAHA weekly restart",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: waha_weekly_restart (Sunday 04:00 UTC)")
```

### Key Constraints
- **Requires `RENDER_API_KEY`** — must be set as Render env var on baker-master service. If not set, job logs a warning and skips (non-fatal).
- **Sunday 04:00 UTC** = 06:00 CET — low-traffic window
- **Does NOT restart baker-master itself** — only WAHA service via Render API
- **clearCache: do_not_clear** — preserves WAHA's Docker image cache for fast restart

### Verification
```
# Check scheduler registered the job
GET /api/scheduler-status
# Should show "waha_weekly_restart" in the job list

# Manual test (after RENDER_API_KEY is set):
# Check Render logs for "WAHA restart: deploy triggered successfully"
```

---

## Files Modified
- `triggers/waha_webhook.py` — Add `report_success("whatsapp")` / `report_failure("whatsapp", ...)` calls
- `scripts/extract_whatsapp.py` — Fix sender attribution (lines 58-64) + add backfill health reporting
- `triggers/sentinel_health.py` — Add `"whatsapp_resync": 12` to `_WATERMARK_MAX_AGE` dict
- `triggers/embedded_scheduler.py` — Add `_restart_waha_service()` function + weekly cron job

## Do NOT Touch
- `triggers/waha_client.py` — WAHA API client, no changes needed
- `memory/store_back.py` — `store_whatsapp_message()` works correctly
- `outputs/dashboard.py` — Webhook routing (`waha_router`) unchanged
- `config/settings.py` — No new config needed

## Quality Checkpoints
1. Syntax check all 4 modified files: `python3 -c "import py_compile; py_compile.compile('FILE', doraise=True)"`
2. After deploy, check Render logs for: `sentinel_health table verified`
3. Send a test WhatsApp message → check `sentinel_health` has `whatsapp` row with `status='healthy'`
4. Wait for backfill cycle (or trigger `POST /api/whatsapp/backfill?days=1`) → check `whatsapp_backfill` row
5. Verify sender fix: `SELECT sender, sender_name FROM whatsapp_messages WHERE is_director = TRUE ORDER BY timestamp DESC LIMIT 5` — should show `41799605092@c.us`
6. Verify `RENDER_API_KEY` is set on baker-master Render env vars (needed for Fix 3)
7. Verify waha_weekly_restart appears in scheduler status

## Verification SQL
```sql
-- Check health monitoring works
SELECT source, status, consecutive_failures, last_success_at, last_error_at
FROM sentinel_health
WHERE source IN ('whatsapp', 'whatsapp_backfill', 'waha_restart')
ORDER BY source;

-- Check sender attribution fixed
SELECT sender, sender_name, is_director, LEFT(full_text, 50) as preview
FROM whatsapp_messages
WHERE is_director = TRUE
ORDER BY timestamp DESC
LIMIT 10;

-- Check stale watermark monitoring picks up whatsapp
SELECT source, last_seen, updated_at
FROM trigger_watermarks
WHERE source LIKE '%whatsapp%'
ORDER BY source;
```

## Environment Variables Needed
- `RENDER_API_KEY` — Render API key for baker-master service (needed for Fix 3 only). Generate at https://dashboard.render.com/u/settings#api-keys. Set on baker-master Render env vars via MCP merge mode.
