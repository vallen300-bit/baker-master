# CODE BRIEF: SENTINEL-HEALTH-1 — Sentinel Health Monitor

**For:** Code Brisen (Claude Code CLI)
**From:** Code 300 (architect/supervisor)
**Priority:** CRITICAL
**Date:** 2026-03-09
**Branch:** `feat/sentinel-health`

---

## Context

4 sentinels ran for 9 days with missing credentials. Every poll silently failed. No alert.
Todoist masked the issue (unconditional watermark advance). An OOM crash went undetected.
This brief adds health monitoring so failures are detected within 15 minutes.

---

## H1 — sentinel_health Table

**NEW FILE:** `triggers/sentinel_health.py`

Create a module that manages the `sentinel_health` table. All sentinel triggers will call into this.

```sql
CREATE TABLE IF NOT EXISTS sentinel_health (
    source              TEXT PRIMARY KEY,
    last_success_at     TIMESTAMPTZ,
    last_error_at       TIMESTAMPTZ,
    last_error_msg      TEXT,
    consecutive_failures INT DEFAULT 0,
    status              TEXT DEFAULT 'unknown',
    last_alerted_at     TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
```

Status logic:
- `healthy` — consecutive_failures = 0
- `degraded` — 1-2 failures
- `down` — 3+ failures
- `unknown` — never polled

Provide two functions:

```python
def report_success(source: str):
    """Called after a successful poll. Resets failure count."""

def report_failure(source: str, error: str):
    """Called after a failed poll. Increments failure count. Fires alert at 3."""
```

Table creation: call `_ensure_sentinel_health_table()` on first DB access (same pattern as `api_cost_log` in `cost_monitor.py`).

## H2 — Instrument All Sentinel Triggers

Add `report_success()` / `report_failure()` calls to every sentinel trigger.
Wrap the main poll function body in try/except.

| File | Entry Function | Source Key |
|------|---------------|-----------|
| `triggers/email_trigger.py` | `check_new_emails()` | `email` |
| `triggers/slack_trigger.py` | `run_slack_poll()` | `slack` |
| `triggers/rss_trigger.py` | `run_rss_poll()` | `rss` |
| `triggers/clickup_trigger.py` | `run_clickup_poll()` | `clickup` (aggregate, not per-workspace) |
| `triggers/dropbox_trigger.py` | `run_dropbox_poll()` | `dropbox` |
| `triggers/whoop_trigger.py` | `run_whoop_poll()` | `whoop` |
| `triggers/todoist_trigger.py` | `run_todoist_poll()` | `todoist` |
| `triggers/fireflies_trigger.py` | `check_new_transcripts()` | `fireflies` |
| `triggers/calendar_trigger.py` | `check_calendar_and_prep()` | `calendar` |
| `triggers/browser_trigger.py` | `run_browser_poll()` | `browser` |

**Pattern for each trigger** (wrap existing function body):

```python
def run_xxx_poll():
    try:
        # ... existing poll logic ...
        report_success("xxx")
    except Exception as e:
        report_failure("xxx", str(e))
        logger.error(f"xxx poll failed: {e}")
```

**IMPORTANT:** For triggers that already have internal try/except (like email, clickup), add `report_success()` at the END of the function (after all processing), and `report_failure()` in the top-level except. Don't break existing error handling.

**For email_trigger.py specifically:** The function already has `_last_poll_error` / `_last_poll_success_at` tracking (Session 15). Replace those with `report_success` / `report_failure` calls. Remove the module-level `_last_poll_error` and `_last_poll_success_at` variables. Update `dashboard.py` `/api/status` to read from `sentinel_health` table instead.

**CRITICAL for Todoist:** `healthy` = API responded 200, regardless of items found. An empty inbox is healthy.

## H3 — Fix Todoist Watermark False-Positive

**MODIFY** `triggers/todoist_trigger.py`:

The `set_watermark()` at line ~395 currently runs unconditionally. Move it inside the success path so it only advances when the API actually responds.

Currently:
```python
    # Step 8: Update watermark
    trigger_state.set_watermark(_WATERMARK_KEY, datetime.now(timezone.utc))
```

Should be guarded — only set if no exception was raised during the poll. The H2 try/except wrapper naturally handles this: if an exception is thrown, the watermark line is never reached.

## H4 — Inline Alert on Sentinel Down

**INSIDE** `report_failure()` in `triggers/sentinel_health.py`:

When `consecutive_failures` reaches 3 (transition to `down`):
1. Read the previous status from DB
2. If transitioning TO `down` (previous was not `down`): fire T1 alert
3. Use `create_alert()` from `store_back.py` (same path as all other alerts — Slack + WhatsApp for T1)
4. Set `last_alerted_at` in sentinel_health
5. Re-alert if still down after 24h

**Recovery alert:** In `report_success()`, if previous status was `down`, fire a T2 recovery alert:
```
SENTINEL RECOVERED: {source} — was down, now healthy.
```

**Alert format for down:**
```
SENTINEL DOWN: {source}
Failed {consecutive_failures}x since {last_success_at}
Last error: {last_error_msg}
```

Use `source="sentinel_health"` in create_alert() calls.

## H5 — External Heartbeat (NO CODE)

Skip this — I (Code 300) will configure UptimeRobot separately. Not part of this build.

## H6 — All-Sentinels-Down Detection

**INSIDE** `report_failure()`, after updating a sentinel to `down`:

```python
# Check if ALL tracked sentinels are down
healthy_count = query("SELECT COUNT(*) FROM sentinel_health WHERE status IN ('healthy','degraded')")
if healthy_count == 0:
    fire_t1_alert("ALL SENTINELS DOWN — Baker may be disconnected from DB or missing env vars.")
```

## H7 — Dashboard Sentinel Status Widget

**MODIFY** `outputs/static/index.html` or `outputs/static/app.js`:

Add a "Sentinel Status" panel to the Morning Brief tab (or the existing system health section).
Show each source with a color dot: green (healthy), yellow (degraded), red (down), gray (unknown).

**NEW endpoint:** `GET /api/sentinel-health` (in `outputs/dashboard.py`):

```json
{
  "sentinels": [
    {"source": "email", "status": "healthy", "last_success": "...", "consecutive_failures": 0},
    {"source": "clickup", "status": "down", "consecutive_failures": 156, "last_error": "401 Unauthorized"}
  ],
  "summary": {"healthy": 7, "degraded": 1, "down": 2, "unknown": 0}
}
```

## H8 — /health Endpoint Extension

**MODIFY** the existing `/health` endpoint in `outputs/dashboard.py`:

Add sentinel summary to the response. Overall status = "degraded" if any sentinel is down.

```json
{
  "status": "degraded",
  "database": "connected",
  "scheduler": "running",
  "scheduled_jobs": 18,
  "sentinels_healthy": 7,
  "sentinels_down": 2,
  "sentinels_down_list": ["clickup", "whoop"]
}
```

---

## Execution Order

1. H1 — sentinel_health table + module (no dependencies)
2. H3 — Todoist watermark fix (quick, standalone)
3. H2 — Instrument all 10 triggers (depends on H1)
4. H4 + H6 — Inline alerts (inside H1 module, depends on H2)
5. H8 — /health extension (depends on H1)
6. H7 — Dashboard widget (depends on H1 + API endpoint)

## Files to Create

| File | Purpose |
|------|---------|
| `triggers/sentinel_health.py` | Health table, report_success/failure, alert logic |

## Files to Modify

| File | Changes |
|------|---------|
| `triggers/email_trigger.py` | Add report_success/failure, remove _last_poll_error vars |
| `triggers/slack_trigger.py` | Add report_success/failure wrapper |
| `triggers/rss_trigger.py` | Add report_success/failure wrapper |
| `triggers/clickup_trigger.py` | Add report_success/failure wrapper |
| `triggers/dropbox_trigger.py` | Add report_success/failure wrapper |
| `triggers/whoop_trigger.py` | Add report_success/failure wrapper |
| `triggers/todoist_trigger.py` | Add report_success/failure + fix watermark (H3) |
| `triggers/fireflies_trigger.py` | Add report_success/failure wrapper |
| `triggers/calendar_trigger.py` | Add report_success/failure wrapper |
| `triggers/browser_trigger.py` | Add report_success/failure wrapper |
| `outputs/dashboard.py` | /api/sentinel-health endpoint, /health extension, /api/status update |
| `outputs/static/app.js` | Sentinel status widget on Morning Brief |
| `outputs/static/index.html` | Widget HTML (if needed) |

## Coding Rules

- Syntax check ALL modified files: `python3 -c "import py_compile; py_compile.compile('file.py', doraise=True)"`
- All DB operations fault-tolerant (try/except, never crash the trigger)
- Use existing patterns: `SentinelStoreBack._get_global_instance()._get_conn()` for DB
- Use existing `create_alert()` for T1/T2 alerts (it handles Slack + WhatsApp routing)
- Commit with `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`
- Do NOT push to main. Push to `feat/sentinel-health`. Code 300 will review and merge.

## Verification

After building, confirm:
1. `python3 -c "import py_compile; py_compile.compile('triggers/sentinel_health.py', doraise=True)"`
2. All 13 modified files pass syntax check
3. `sentinel_health` table DDL is in the module
4. Each trigger file has exactly one `report_success` and one `report_failure` call
5. Todoist `set_watermark()` only runs on success path
6. `/api/sentinel-health` endpoint returns correct JSON
7. `/health` endpoint includes sentinel summary
