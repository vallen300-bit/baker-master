# BRIEF: WAHA_SILENT_GUARD_1 — Three-Layer WAHA Session Death Detection

## Context
WAHA session corrupted Apr 8 (bad decrypt / AwaitingInitialSync). Baker was blind for 4+ days — Director's important messages from Siegfried and others never arrived. The webhook handler silently ignores session status events, and there is no "silence detection" for when inbound messages stop. This is the #1 reliability gap in Baker today.

Director request: "How to avoid WAHA silently dropping and nobody notices. There are important messages there that will influence the work of Baker."

**Prior work:** WAHA-HEALTH-FIXES-1 added basic health reporting (report_success/failure on webhook + backfill), weekly restart, and watermark staleness check. This brief adds the three missing detection layers.

## Estimated time: ~2h
## Complexity: Medium
## Prerequisites: WAHA-HEALTH-FIXES-1 (deployed, commit 304e547)

---

## Feature 1: Handle WAHA Session Status Events (Instant Alert)

### Problem
The webhook handler at `triggers/waha_webhook.py:772` ignores ALL non-message events:
```python
if event_type != "message":
    return {"status": "ignored", "event": event_type}
```
When WAHA sends `session.status` events (STOPPED, FAILED, SCAN_QR_CODE, AwaitingInitialSync), Baker discards them silently.

### Current State
- `triggers/waha_webhook.py:763-773` — webhook entry point, filters to `event_type == "message"` only
- WAHA sends events: `message`, `session.status`, `message.ack`, `message.reaction`, `message.waiting`, `state.change`
- Session status payload format: `{"event": "session.status", "session": "default", "payload": {"name": "default", "status": "SCAN_QR_CODE"}}` (also: WORKING, STOPPED, FAILED)

### Implementation

In `triggers/waha_webhook.py`, replace the early return at line 772-773 with session status handling:

```python
    # Only process incoming messages and session status events
    if event_type == "session.status":
        # WAHA-SILENT-GUARD-1: Detect session death immediately
        session_payload = body.get("payload", {})
        session_status = session_payload.get("status", "")
        logger.warning(f"WAHA session status event: {session_status}")

        _WAHA_DEAD_STATUSES = {"SCAN_QR_CODE", "STOPPED", "FAILED"}
        if session_status in _WAHA_DEAD_STATUSES:
            # Fire T1 alert — session needs manual QR re-scan
            try:
                from memory.store_back import SentinelStoreBack
                store = SentinelStoreBack._get_global_instance()
                store.create_alert(
                    tier=1,
                    title=f"WAHA SESSION DEAD: {session_status}",
                    body=(
                        f"WhatsApp session status changed to {session_status}. "
                        f"Inbound messages are NOT being received. "
                        f"Action: Re-scan QR code at https://baker-waha.onrender.com/#/sessions/default"
                    ),
                    source="waha_session",
                    source_id=f"session-{session_status}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}",
                )
            except Exception as alert_err:
                logger.error(f"Failed to create WAHA session alert: {alert_err}")

            # Also report to sentinel_health
            try:
                from triggers.sentinel_health import report_failure
                report_failure("whatsapp", f"Session status: {session_status}")
            except Exception:
                pass

            # Try WhatsApp alert (may fail if session is truly dead — that's OK)
            try:
                from outputs.whatsapp_sender import send_whatsapp
                send_whatsapp(
                    f"*WAHA SESSION DOWN*\n\nStatus: {session_status}\n"
                    f"Inbound WhatsApp messages are NOT being received.\n\n"
                    f"Re-scan QR: https://baker-waha.onrender.com/#/sessions/default"
                )
            except Exception:
                pass

        elif session_status == "WORKING":
            # Session recovered — report success
            try:
                from triggers.sentinel_health import report_success
                report_success("whatsapp")
            except Exception:
                pass
            logger.info("WAHA session status: WORKING — session healthy")

        return {"status": "session_event", "session_status": session_status}

    if event_type != "message":
        return {"status": "ignored", "event": event_type}
```

### Key Constraints
- Must come BEFORE the existing `event_type != "message"` check
- T1 alert uses unique `source_id` with timestamp to avoid dedup blocking repeat alerts
- WhatsApp send attempt is best-effort (if session is dead, send will fail — that's expected)
- `_WAHA_DEAD_STATUSES` is a set literal, not a config — these are WAHA protocol constants
- Do NOT add logging for every `session.status == "WORKING"` heartbeat — WAHA sends these frequently

### Verification
1. Check Render logs after deploy for "WAHA session status event" lines
2. If session is currently dead: should see T1 alert in dashboard immediately
3. `SELECT * FROM alerts WHERE source = 'waha_session' ORDER BY created_at DESC LIMIT 5`

---

## Feature 2: Inbound Silence Detection (Scheduled, Every 2h)

### Problem
If WAHA silently stops delivering webhook events (session dead, network issue, Render crash), there is no detection mechanism. The watermark check (`whatsapp_resync`) only flags if the 6h backfill itself fails — not if the webhook stops receiving messages.

### Current State
- `whatsapp_messages` table has `timestamp` (TIMESTAMPTZ), `is_director` (BOOLEAN) columns
- `triggers/sentinel_health.py:536-598` — `run_health_watchdog()` runs every 2h, checks for stuck-down sentinels
- No check for "zero inbound messages received recently"

### Implementation

Add new function to `triggers/sentinel_health.py` after `run_health_watchdog()` (after line 598):

```python
def check_waha_silence():
    """WAHA-SILENT-GUARD-1: Detect if no inbound WhatsApp messages in 4+ hours
    during business hours (06:00-22:00 UTC, roughly 08:00-00:00 CET).

    Fires T1 alert if silent. Skips overnight (low message volume is normal).
    """
    now = datetime.now(timezone.utc)
    hour_utc = now.hour

    # Only check during business hours (06:00-22:00 UTC = 08:00-00:00 CET)
    if hour_utc < 6 or hour_utc >= 22:
        logger.debug("WAHA silence check: outside business hours, skipping")
        return

    conn, store = _get_conn()
    if not conn:
        return

    try:
        _ensure_table(conn)
        cur = conn.cursor()

        # Check latest INBOUND message (not Baker's own outbound alerts)
        cur.execute("""
            SELECT MAX(timestamp) FROM whatsapp_messages
            WHERE is_director = false
            LIMIT 1
        """)
        row = cur.fetchone()
        latest_inbound = row[0] if row and row[0] else None
        cur.close()

        if latest_inbound is None:
            logger.warning("WAHA silence check: no inbound messages ever recorded")
            return

        # Calculate age
        if latest_inbound.tzinfo is None:
            from datetime import timezone as tz
            latest_inbound = latest_inbound.replace(tzinfo=tz.utc)

        age_hours = (now - latest_inbound).total_seconds() / 3600

        if age_hours > 4:
            alert_msg = (
                f"No inbound WhatsApp messages in {age_hours:.1f} hours. "
                f"Last inbound: {latest_inbound.strftime('%Y-%m-%d %H:%M UTC')}. "
                f"WAHA session may be dead. "
                f"Check: https://baker-waha.onrender.com/#/sessions/default"
            )
            logger.warning(f"WAHA silence detected: {alert_msg}")

            # Report failure to sentinel health
            report_failure("waha_silence", f"No inbound messages in {age_hours:.1f}h")

            # T1 alert
            try:
                from memory.store_back import SentinelStoreBack
                st = SentinelStoreBack._get_global_instance()
                st.create_alert(
                    tier=1,
                    title="WAHA SILENT — no inbound WhatsApp messages",
                    body=alert_msg,
                    source="waha_silence",
                    source_id=f"silence-{now.strftime('%Y%m%d-%H')}",
                )
            except Exception:
                pass

            # Try WhatsApp (may fail if session dead — falls through to dashboard alert)
            try:
                from outputs.whatsapp_sender import send_whatsapp
                send_whatsapp(f"*WAHA SILENT*\n\n{alert_msg}")
            except Exception:
                pass
        else:
            # Healthy — clear any previous silence failure
            report_success("waha_silence")
            logger.debug(f"WAHA silence check: last inbound {age_hours:.1f}h ago — OK")

    except Exception as e:
        logger.error(f"WAHA silence check failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        _put_conn(store, conn)
```

Register in `triggers/embedded_scheduler.py` after the `health_watchdog` registration (after line 343):

```python
    # WAHA-SILENT-GUARD-1: Detect WhatsApp inbound silence
    from triggers.sentinel_health import check_waha_silence
    scheduler.add_job(
        check_waha_silence,
        IntervalTrigger(hours=2),
        id="waha_silence_check", name="WAHA inbound silence detector",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: waha_silence_check (every 2 hours)")
```

### Key Constraints
- `is_director = false` — only check INBOUND messages (Director's outbound via Baker don't count)
- Business hours gate (06:00-22:00 UTC) — avoids false positives at night
- 4-hour threshold — Director typically receives messages throughout the day; 4h silence during business hours is abnormal
- `source_id` uses hour-granularity dedup (`silence-20260412-14`) — max 1 alert per hour
- Reports to a separate sentinel source `waha_silence` (not `whatsapp`) to avoid confusion with webhook health
- `LIMIT 1` on the MAX query (lessons.md rule)
- `conn.rollback()` in except block (lessons.md rule)

### Verification
```sql
-- Check latest inbound message age
SELECT MAX(timestamp), NOW() - MAX(timestamp) as age
FROM whatsapp_messages
WHERE is_director = false;

-- Check silence sentinel status
SELECT * FROM sentinel_health WHERE source = 'waha_silence' LIMIT 1;
```

---

## Feature 3: Active WAHA Session Health Poll (Every 30min)

### Problem
Features 1 and 2 are reactive — they detect problems after they happen. An active health poll calls WAHA's API directly to verify the session is alive, catching problems even when no messages are flowing.

### Current State
- `triggers/waha_client.py` — HTTP client for WAHA, uses `config.waha.base_url` and `_headers()`. Has no session status function.
- WAHA API endpoint: `GET /api/sessions/{session}` returns `{"name": "default", "status": "WORKING", ...}`. Status values: `WORKING`, `SCAN_QR_CODE`, `STOPPED`, `FAILED`, `STARTING`.

### Implementation

Add to `triggers/waha_client.py` after the `_rewrite_media_url` function (after line 36):

```python
def get_session_status(session: str = None) -> dict:
    """WAHA-SILENT-GUARD-1: Check WAHA session status.
    Returns {"status": "WORKING", ...} or {"error": "..."}.
    """
    if session is None:
        session = config.waha.session_name
    try:
        resp = httpx.get(
            f"{config.waha.base_url}/api/sessions/{session}",
            headers=_headers(),
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}
```

Add new function to `triggers/sentinel_health.py` after `check_waha_silence()`:

```python
def poll_waha_session():
    """WAHA-SILENT-GUARD-1: Actively poll WAHA session status every 30 min.
    Catches session death even when no messages are flowing.
    """
    try:
        from triggers.waha_client import get_session_status
        result = get_session_status()
    except Exception as e:
        logger.error(f"WAHA session poll: import/call failed: {e}")
        report_failure("waha_session_poll", str(e))
        return

    if "error" in result:
        error_msg = result["error"]
        logger.warning(f"WAHA session poll: error — {error_msg}")
        report_failure("waha_session_poll", error_msg)

        # T1 alert if WAHA is completely unreachable
        try:
            from memory.store_back import SentinelStoreBack
            st = SentinelStoreBack._get_global_instance()
            st.create_alert(
                tier=1,
                title="WAHA UNREACHABLE",
                body=f"Cannot reach WAHA API: {error_msg}. Check https://baker-waha.onrender.com",
                source="waha_session_poll",
                source_id=f"unreachable-{datetime.now(timezone.utc).strftime('%Y%m%d-%H')}",
            )
        except Exception:
            pass
        return

    status = result.get("status", "UNKNOWN")
    logger.info(f"WAHA session poll: status={status}")

    _HEALTHY = {"WORKING"}
    _DEAD = {"SCAN_QR_CODE", "STOPPED", "FAILED"}

    if status in _HEALTHY:
        report_success("waha_session_poll")
    elif status in _DEAD:
        report_failure("waha_session_poll", f"Session status: {status}")

        alert_msg = (
            f"WAHA session is {status}. Inbound WhatsApp messages are NOT being received.\n"
            f"Re-scan QR: https://baker-waha.onrender.com/#/sessions/default"
        )

        # T1 alert
        try:
            from memory.store_back import SentinelStoreBack
            st = SentinelStoreBack._get_global_instance()
            st.create_alert(
                tier=1,
                title=f"WAHA SESSION: {status}",
                body=alert_msg,
                source="waha_session_poll",
                source_id=f"poll-{status}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H')}",
            )
        except Exception:
            pass

        # Try WhatsApp (best effort)
        try:
            from outputs.whatsapp_sender import send_whatsapp
            send_whatsapp(f"*WAHA SESSION DOWN*\n\nStatus: {status}\n\n{alert_msg}")
        except Exception:
            pass
    else:
        # Unknown status — log but don't alert
        logger.warning(f"WAHA session poll: unexpected status '{status}'")
```

Register in `triggers/embedded_scheduler.py` after the silence check registration:

```python
    # WAHA-SILENT-GUARD-1: Active WAHA session health poll
    from triggers.sentinel_health import poll_waha_session
    scheduler.add_job(
        poll_waha_session,
        IntervalTrigger(minutes=30),
        id="waha_session_poll", name="WAHA session health poll",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: waha_session_poll (every 30 minutes)")
```

### Key Constraints
- 10-second timeout on WAHA API call — WAHA can be slow on cold start
- `session` param defaults to `config.waha.session_name` — no hardcoded session names
- Reports to separate sentinel source `waha_session_poll` — distinct from webhook health (`whatsapp`) and silence detection (`waha_silence`)
- Hour-granularity dedup on `source_id` — max 1 alert per status per hour (prevents alert flood if WAHA stays down)
- `STARTING` status is NOT treated as dead — WAHA may be mid-restart (weekly cron or manual)
- WhatsApp send is best-effort — if WAHA is dead, the send will fail (that's fine, T1 alert catches it)

### Verification
```sql
-- Check session poll sentinel status
SELECT * FROM sentinel_health WHERE source = 'waha_session_poll' LIMIT 1;

-- Check all WAHA-related alerts
SELECT id, tier, title, created_at FROM alerts
WHERE source IN ('waha_session', 'waha_silence', 'waha_session_poll')
ORDER BY created_at DESC LIMIT 10;
```

---

## Files Modified
- `triggers/waha_webhook.py` — handle `session.status` events before the `!= "message"` filter (~35 lines)
- `triggers/waha_client.py` — new `get_session_status()` function (~15 lines)
- `triggers/sentinel_health.py` — new `check_waha_silence()` + `poll_waha_session()` functions (~80 lines total)
- `triggers/embedded_scheduler.py` — register 2 new scheduler jobs (~15 lines)

## Do NOT Touch
- `outputs/dashboard.py` — no dashboard changes needed (sentinel health API already exposes all sources)
- `scripts/extract_whatsapp.py` — backfill logic unchanged
- `config/settings.py` — no new config needed (uses existing `config.waha.*`)
- `outputs/whatsapp_sender.py` — send function unchanged

## Quality Checkpoints
1. `python3 -c "import py_compile; py_compile.compile('triggers/waha_webhook.py', doraise=True)"`
2. `python3 -c "import py_compile; py_compile.compile('triggers/waha_client.py', doraise=True)"`
3. `python3 -c "import py_compile; py_compile.compile('triggers/sentinel_health.py', doraise=True)"`
4. `python3 -c "import py_compile; py_compile.compile('triggers/embedded_scheduler.py', doraise=True)"`
5. After deploy: check Render logs for "Registered: waha_silence_check" and "Registered: waha_session_poll"
6. After deploy: check `/api/sentinel-health` for `waha_silence` and `waha_session_poll` entries
7. If session is currently dead: T1 alert should appear within 30 minutes

## Verification SQL
```sql
-- All WAHA sentinel sources
SELECT source, status, consecutive_failures, last_success_at, last_error_at
FROM sentinel_health
WHERE source IN ('whatsapp', 'whatsapp_backfill', 'waha_restart', 'waha_silence', 'waha_session_poll')
ORDER BY source;

-- Recent WAHA alerts
SELECT id, tier, title, source, source_id, created_at
FROM alerts
WHERE source IN ('waha_session', 'waha_silence', 'waha_session_poll')
ORDER BY created_at DESC LIMIT 10;

-- Current inbound message freshness
SELECT MAX(timestamp) as latest_inbound,
       NOW() - MAX(timestamp) as age
FROM whatsapp_messages
WHERE is_director = false;
```

## Cost Impact
- **Zero LLM cost** — all checks are SQL queries or HTTP GETs
- **WAHA API:** 1 GET /api/sessions call per 30 min = 48/day (negligible)
- **PostgreSQL:** 1 MAX query per 2h = 12/day (negligible)
- **Alerts:** WhatsApp send attempt only on failure (pennies)

## Detection Timeline (After Deploy)

| Failure Type | Detection Time | Method |
|---|---|---|
| Session goes SCAN_QR / STOPPED / FAILED | **Instant** (seconds) | Feature 1: webhook session event |
| WAHA crashes, no events sent | **< 30 min** | Feature 3: active session poll |
| Session "WORKING" but silently not delivering | **< 4 hours** | Feature 2: silence detection |
| All methods fail | **< 6 hours** | Existing: watermark staleness check |
