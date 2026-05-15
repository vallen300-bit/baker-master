# BRIEF: SCHEDULER_WATCHDOG_WA_KILL_1 — Disable WhatsApp alert from scheduler watchdog

## Context

The watchdog at `outputs/dashboard.py:185` sends Director a WhatsApp every time it auto-restarts the scheduler. Cooldown is 5 min (`_watchdog_alert_cooldown_s = 300`). Today (2026-05-15) the scheduler is in a crash loop — `BRIEF_SCHEDULER_SINGLETON_HARDEN_1` shipped, but instability persists. Result: ~5-9 alerts/hour, 426 sends in 3 days, real alerts (Steininger / ORF) buried.

Director directive 2026-05-15 ~15:10 UTC: kill the alert outright. Underlying crash-loop diagnosis + fix tracked separately in `BRIEF_SCHEDULER_CRASHLOOP_RCA_2.md`.

## Estimated time: ~10 min
## Complexity: Trivial
## Prerequisites: None

---

## Fix: Replace `send_whatsapp(...)` call with `logger.warning(...)`

### Problem

`outputs/dashboard.py:200-207` calls `send_whatsapp()` inside the throttled branch. Goal: keep the watchdog's restart behaviour + the dashboard/log signal, but stop pushing to Director's WhatsApp.

### Current State (`outputs/dashboard.py:185-209`)

```python
def _check_scheduler_heartbeat():
    """If heartbeat stale >12 min, restart scheduler + WhatsApp alert (throttled)."""
    global _watchdog_last_alert_ts
    try:
        from triggers.state import trigger_state
        hb = trigger_state.get_watermark("scheduler_heartbeat")
        age_seconds = (datetime.now(timezone.utc) - hb).total_seconds()
        if age_seconds > 720:  # 12 minutes = missed 2 heartbeat cycles
            logger.error(f"SCHEDULER-WATCHDOG-1: Heartbeat stale ({age_seconds:.0f}s). Restarting...")
            from triggers.embedded_scheduler import restart_scheduler
            restart_scheduler()
            # Throttle: only alert if last alert was >cooldown ago
            now_ts = time.time()
            if now_ts - _watchdog_last_alert_ts > _watchdog_alert_cooldown_s:
                _watchdog_last_alert_ts = now_ts
                try:
                    from outputs.whatsapp_sender import send_whatsapp
                    send_whatsapp(
                        f"Baker scheduler was dead for {int(age_seconds/60)} minutes. "
                        f"Auto-restarted. Check dashboard for missed items."
                    )
                except Exception as wa_e:
                    logger.warning(f"Watchdog WhatsApp alert failed: {wa_e}")
    except Exception as e:
        logger.debug(f"Scheduler watchdog check failed (non-fatal): {e}")
```

### Implementation

Replace lines 200-207 with a `logger.warning(...)` call. Keep the throttle so logs don't spam either. Do NOT remove the `restart_scheduler()` call. Do NOT change the 720s threshold.

```python
def _check_scheduler_heartbeat():
    """If heartbeat stale >12 min, restart scheduler + log warning (throttled).

    WA push intentionally disabled 2026-05-15 — Director directive while
    BRIEF_SCHEDULER_CRASHLOOP_RCA_2 is in flight. Re-enable only after that
    RCA closes and crash-loop frequency is back to <1 event/day. Dashboard
    + server logs still capture every restart.
    """
    global _watchdog_last_alert_ts
    try:
        from triggers.state import trigger_state
        hb = trigger_state.get_watermark("scheduler_heartbeat")
        age_seconds = (datetime.now(timezone.utc) - hb).total_seconds()
        if age_seconds > 720:  # 12 minutes = missed 2 heartbeat cycles
            logger.error(f"SCHEDULER-WATCHDOG-1: Heartbeat stale ({age_seconds:.0f}s). Restarting...")
            from triggers.embedded_scheduler import restart_scheduler
            restart_scheduler()
            # Throttle log frequency (replaces the WA push, same cooldown)
            now_ts = time.time()
            if now_ts - _watchdog_last_alert_ts > _watchdog_alert_cooldown_s:
                _watchdog_last_alert_ts = now_ts
                logger.warning(
                    f"WATCHDOG_RESTART: scheduler was dead {int(age_seconds/60)} min. "
                    f"Auto-restart fired. WA push disabled pending CRASHLOOP_RCA_2."
                )
    except Exception as e:
        logger.debug(f"Scheduler watchdog check failed (non-fatal): {e}")
```

### Key Constraints

- DO NOT remove `restart_scheduler()` — watchdog still must restart the scheduler.
- DO NOT touch the 720s stale threshold.
- DO NOT delete `_watchdog_last_alert_ts` / `_watchdog_alert_cooldown_s` — same cooldown now throttles the WARN log instead.
- DO NOT touch `outputs/whatsapp_sender.py` — kill is scoped to the watchdog call site only.

### Verification

1. `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` — passes.
2. `pytest tests/test_watchdog_cooldown.py -v` — must still pass (if the test asserts `send_whatsapp` call count, B4 must update the test to assert `logger.warning` count instead; keep the throttle semantics).
3. After deploy + 30 min, query `SELECT COUNT(*) FROM baker_actions WHERE action_type='whatsapp_send' AND payload->>'text_preview' LIKE 'Baker scheduler was dead%' AND created_at > NOW() - INTERVAL '30 minutes'` → expect **0**.
4. Render logs still show `WATCHDOG_RESTART: scheduler was dead N min` lines at the same cadence as before.

## Files Modified

- `outputs/dashboard.py` (lines 185-209)
- `tests/test_watchdog_cooldown.py` — update assertion target if existing test mocked `send_whatsapp`

## Do NOT Touch

- `triggers/embedded_scheduler.py` — leave restart path intact
- `outputs/whatsapp_sender.py` — out of scope
- `triggers/scheduler_lease.py` — singleton-harden is fine; not the issue today

## Ship gate

Literal `pytest tests/test_watchdog_cooldown.py -v` green output pasted in ship report.

## Trigger class

LOW (single-file change, no auth, no DB, no external surface). No mandatory 2nd-pass review per `/security-review` skill rules.

## Co-Authored-By

```
Co-authored-by: Code Brisen #4 <b4@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
