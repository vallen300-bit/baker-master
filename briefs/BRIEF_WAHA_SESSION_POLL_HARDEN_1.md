---
brief: WAHA_SESSION_POLL_HARDEN_1
to: b1
from: lead
authored: 2026-05-30
target_repo: baker-master
estimated_time: ~3h
complexity: Medium
codex_pre_review: PASS-WITH-NITS (bus #1364, all 3 nits folded into this brief)
prior_design_iterations:
  - v1 bus #1360 (codex FAIL-LIGHT #1362 — 6 findings)
  - v2 bus #1363 (codex PASS-WITH-NITS #1364 — 3 nits, folded here)
director_authorization: 2026-05-30 chat — "go" (cover rewrite + codex check + dispatch b1 path)
anchor_chat: Director 2026-05-30 — Bick iPhone export caught 4× 2026-05-29 WAHA-missed messages; existing `poll_waha_session` did not fire after 2026-05-29 19:19Z per codex prod-DB probe.
---

# BRIEF: WAHA_SESSION_POLL_HARDEN_1 — Harden existing WAHA session poll with grace policy, faster cadence, webhook-drift detection, and post-deploy recency AC

## Context

### Surface contract: N/A — pure backend hardening; no clickable surface. Alert outputs land in the existing `alerts` table consumed by dashboard alert rendering already shipped; no new UI route, panel, button, or anchor introduced. Dashboard team owns visual rendering.

On 2026-05-29 WAHA dropped at least 4 inbound messages from Raphael Bick that the iPhone export (#1358 family, BAKER_CAPTURE_BLINDSPOTS_1 phase 2) later recovered. The existing `poll_waha_session()` sentinel at `triggers/sentinel_health.py:685` did NOT catch the gap, for two compounding reasons:

1. The job appears to have stopped firing after `2026-05-29 19:19Z` per codex prod-DB probe (`SELECT MAX(fired_at) FROM scheduler_executions WHERE job_id='waha_session_poll'` is stale; other scheduler jobs fire fine).
2. Even if it had fired, the poll has a blind-spot class: unknown / missing statuses log a warning but never `report_failure` or alert. STARTING and any future WAHA status enum are silently swallowed.

This brief hardens the existing poll along four axes:
- Cadence: 30 min → 5 min.
- Grace policy: STARTING tolerated for ~15 min then alerted; unknown/missing alerted after 2 consecutive ticks.
- Webhook-drift check: same poll reads `config.webhooks[]` and alerts if Baker's subscription union lacks `session.status` or `message.any` (Lesson #69 invariant).
- Post-deploy AC: assert `scheduler_executions.fired_at` for `waha_session_poll` is within last 6 min.

**OUT OF SCOPE (split per codex nit #2):** a generic "every registered scheduler job stale > 2× interval" check. That needs its own design (expected-job registry + per-job intervals + singleton/replica semantics). Will be authored as `SCHEDULER_JOB_LIVENESS_1`.

**Pre-review:** This design was reviewed by codex twice before authoring. v1 bus #1360 → FAIL-LIGHT #1362 with 6 findings (greenfield duplicate, wrong endpoint, blind-spot, alert-only, webhook-drift, scheduler-recency). v2 bus #1363 folded all 6 → PASS-WITH-NITS #1364 with 3 nits (schema column `fired_at` not `executed_at`, split generic liveness, webhook-drift scoping). All 3 nits folded into this brief.

## Estimated time: ~3h
## Complexity: Medium
## Prerequisites: BAKER_CAPTURE_BLINDSPOTS_1 (PR #270, merged 7a4799c, deployed) already live.

---

## Fix 1: Recut `poll_waha_session()` with grace policy + webhook-drift check

### Problem

`triggers/sentinel_health.py:685-770` `poll_waha_session()`:
- Healthy = {WORKING}; Dead = {SCAN_QR_CODE, STOPPED, FAILED}; everything else → `logger.warning` only, no `report_failure`, no alert.
- Reads only `result["status"]`. Discards `config.webhooks[]` and other session fields.

### Current State

```python
# triggers/sentinel_health.py:685
def poll_waha_session():
    """WAHA-SILENT-GUARD-1: Actively poll WAHA session status every 30 min."""
    try:
        from triggers.waha_client import get_session_status, monitor_headers
        result = get_session_status(_headers_override=monitor_headers())
    except Exception as e:
        logger.error(f"WAHA session poll: import/call failed: {e}")
        report_failure("waha_session_poll", str(e))
        return

    if "error" in result:
        # ... T1 alert "WAHA UNREACHABLE" ...
        return

    status = result.get("status", "UNKNOWN")
    logger.info(f"WAHA session poll: status={status}")

    _HEALTHY = {"WORKING"}
    _DEAD = {"SCAN_QR_CODE", "STOPPED", "FAILED"}

    if status in _HEALTHY:
        report_success("waha_session_poll")
    elif status in _DEAD:
        report_failure("waha_session_poll", f"Session status: {status}")
        # ... T1 alert "WAHA SESSION: <status>" ...
    else:
        # Unknown status — log but don't alert
        logger.warning(f"WAHA session poll: unexpected status '{status}'")
```

`get_session_status()` (`triggers/waha_client.py:71`) hits `GET /api/sessions/{session}` (confirmed correct endpoint per codex #1362 F2; no path change needed). Returns full JSON on 200, `{"error": "..."}` otherwise. The full JSON includes `status`, `config.webhooks[]`, and other session fields.

### Implementation

Replace the `else` branch + add a grace counter + add a webhook-drift check. The counter is module-level (no JSON file, no DB write — see Trade-offs below).

**Step 1.1** — At top of `triggers/sentinel_health.py` (near other module-level state), add the counter:

```python
# WAHA_SESSION_POLL_HARDEN_1: consecutive-non-healthy tick counter for grace policy.
# In-process dict. Lost on Render restart → first 2 ticks post-restart re-grace.
# Acceptable because scheduler is singleton-gated (advisory lock); only one
# process is polling at any time.
_WAHA_POLL_STATE: dict[str, int] = {"non_healthy_streak": 0, "starting_streak": 0}
```

**Step 1.2** — Replace the entire body of `poll_waha_session()` (after the `result = get_session_status(...)` call) with:

```python
    if "error" in result:
        error_msg = result["error"]
        logger.warning(f"WAHA session poll: error — {error_msg}")
        report_failure("waha_session_poll", error_msg)
        # T1 alert if WAHA is completely unreachable (existing path preserved)
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
    _STARTING = {"STARTING"}

    # ---- Webhook-drift check (Lesson #69 invariant) -------------------
    # Baker's subscription union across all webhooks MUST include both
    # 'session.status' and 'message.any'. If the union is missing either,
    # we are silently dropping events that the handler is ready to process.
    try:
        webhooks = (result.get("config", {}) or {}).get("webhooks", []) or []
        subscribed_events = set()
        for wh in webhooks:
            for ev in (wh.get("events") or []):
                subscribed_events.add(ev)
        required = {"session.status", "message.any"}
        missing = required - subscribed_events
        if missing:
            from memory.store_back import SentinelStoreBack
            st = SentinelStoreBack._get_global_instance()
            st.create_alert(
                tier=1,
                title="WAHA WEBHOOK CONFIG DRIFT",
                body=(
                    f"Baker's WAHA webhook subscription union is missing: "
                    f"{sorted(missing)}. Handler at triggers/waha_webhook.py "
                    f"expects 'message.any' (inbound + fromMe) and 'session.status' "
                    f"(infra). Missing events are silently dropped. "
                    f"Currently subscribed (union): {sorted(subscribed_events)}. "
                    f"Anchor: tasks/lessons.md #69."
                ),
                source="waha_session_poll",
                source_id=f"webhook-drift-{datetime.now(timezone.utc).strftime('%Y%m%d-%H')}",
            )
    except Exception as e:
        logger.warning(f"WAHA webhook-drift check skipped: {e}")

    # ---- Status branches with grace policy ----------------------------
    if status in _HEALTHY:
        _WAHA_POLL_STATE["non_healthy_streak"] = 0
        _WAHA_POLL_STATE["starting_streak"] = 0
        report_success("waha_session_poll")
        return

    if status in _DEAD:
        _WAHA_POLL_STATE["non_healthy_streak"] = 0  # DEAD has its own immediate alert path
        _WAHA_POLL_STATE["starting_streak"] = 0
        report_failure("waha_session_poll", f"Session status: {status}")
        alert_msg = (
            f"WAHA session is {status}. Inbound WhatsApp messages are NOT being received.\n"
            f"Re-scan QR: https://baker-waha.onrender.com/#/sessions/default"
        )
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
        logger.warning(
            "WAHA SESSION DOWN (WA-suppressed, infra_only): status=%s — %s",
            status, alert_msg,
        )
        return

    if status in _STARTING:
        _WAHA_POLL_STATE["non_healthy_streak"] = 0  # different counter
        _WAHA_POLL_STATE["starting_streak"] += 1
        streak = _WAHA_POLL_STATE["starting_streak"]
        # 3 consecutive ticks × 5 min cadence = ~15 min grace; matches archived
        # BRIEF_WAHA_SILENT_GUARD_1.md:379 ("STARTING is NOT treated as dead").
        if streak >= 3:
            report_failure("waha_session_poll", f"STARTING stuck for {streak} ticks")
            try:
                from memory.store_back import SentinelStoreBack
                st = SentinelStoreBack._get_global_instance()
                st.create_alert(
                    tier=1,
                    title="WAHA SESSION STUCK STARTING",
                    body=(
                        f"WAHA session has been STARTING for {streak} consecutive ticks "
                        f"(~{streak * 5} min). Likely mid-restart that did not recover. "
                        f"Re-scan QR: https://baker-waha.onrender.com/#/sessions/default"
                    ),
                    source="waha_session_poll",
                    source_id=f"starting-stuck-{datetime.now(timezone.utc).strftime('%Y%m%d-%H')}",
                )
            except Exception:
                pass
        else:
            logger.info(f"WAHA session poll: STARTING (tick {streak}/3 grace) — no alert yet")
        return

    # Unknown / missing status (UNKNOWN, or any future WAHA enum value)
    _WAHA_POLL_STATE["starting_streak"] = 0
    _WAHA_POLL_STATE["non_healthy_streak"] += 1
    streak = _WAHA_POLL_STATE["non_healthy_streak"]
    logger.warning(f"WAHA session poll: unexpected status '{status}' (tick {streak}/2 grace)")
    # 2 consecutive ticks × 5 min = ~10 min grace before alerting
    if streak >= 2:
        report_failure("waha_session_poll", f"Unknown status '{status}' for {streak} ticks")
        try:
            from memory.store_back import SentinelStoreBack
            st = SentinelStoreBack._get_global_instance()
            st.create_alert(
                tier=1,
                title="WAHA SESSION UNKNOWN STATUS",
                body=(
                    f"WAHA session reports unexpected status '{status}' for "
                    f"{streak} consecutive ticks (~{streak * 5} min). "
                    f"Investigate: https://baker-waha.onrender.com/#/sessions/default"
                ),
                source="waha_session_poll",
                source_id=f"unknown-{status}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H')}",
            )
        except Exception:
            pass
```

### Key Constraints

- **Counter persistence**: in-process dict only. No JSON file, no DB write. Scheduler is singleton-gated (advisory lock in `embedded_scheduler.py`) so only one process polls. Lost on Render restart = first 2 ticks post-restart re-grace; acceptable cost (10 min re-grace × ~weekly restart = ~10 min/week false-quiet).
- **Webhook-drift uses union semantics** (per codex nit #3): we check Baker's subscription **union** across all webhooks for the required events. We do NOT alert if a single unrelated webhook lacks them. This is the Lesson #69 invariant.
- **DEAD path unchanged** in semantics. We preserved existing alert format + source_id pattern.
- **Source-id dedupe** uses `%Y%m%d-%H` (hourly bucket) for all alerts; rate-limits to one alert per status-class per hour.
- **No /restart calls**. Alert-only. (Codex F4 + Lesson #27 — WAHA recreation without store config breaks history fetch.)

### Verification

Pytest cases (add to `tests/test_waha_session_poll_harden.py`):

1. STARTING once → no alert; `starting_streak == 1`.
2. STARTING ×3 consecutive → T1 alert `WAHA SESSION STUCK STARTING`; `starting_streak == 3`.
3. WORKING after 2× STARTING → no alert; both streaks reset to 0; `report_success` called once.
4. UNKNOWN once → no alert; `non_healthy_streak == 1`.
5. UNKNOWN ×2 consecutive → T1 alert `WAHA SESSION UNKNOWN STATUS`.
6. SCAN_QR_CODE → T1 alert `WAHA SESSION: SCAN_QR_CODE` (existing path, both streak counters reset).
7. Webhooks union missing `session.status` → T1 alert `WAHA WEBHOOK CONFIG DRIFT` mentioning `['session.status']`.
8. Webhooks union missing `message.any` → T1 alert `WAHA WEBHOOK CONFIG DRIFT` mentioning `['message.any']`.
9. Webhooks union has both → no drift alert (status-branch alert still fires per scenario).
10. **Source-id dedupe stability**: STARTING ×3 within same hour-bucket emits source_id `starting-stuck-YYYYMMDD-HH` exactly once (re-firing in same hour collides → store_back dedupes). Verify the source_id template literal is stable.
11. **Counter reset across transitions**: STARTING → WORKING → STARTING — second STARTING should be tick 1 of 3, not tick 2 (counter reset by WORKING).
12. `report_failure` raises → poll does not crash (`try/except Exception` wrapping the store-back call already in place; verify still wraps in refactor).

Mock `get_session_status` via monkeypatch returning the response shape `{"status": "...", "config": {"webhooks": [{"events": [...]}]}}`.

---

## Fix 2: Tighten scheduler cadence 30 min → 5 min

### Problem

`triggers/embedded_scheduler.py:501-509` registers `waha_session_poll` every 30 min. Too slow for the silent-gap incident class.

### Current State

```python
# triggers/embedded_scheduler.py:501-509
from triggers.sentinel_health import poll_waha_session
scheduler.add_job(
    poll_waha_session,
    IntervalTrigger(minutes=30),
    id="waha_session_poll", name="WAHA session health poll",
    coalesce=True, max_instances=1, replace_existing=True,
)
logger.info("Registered: waha_session_poll (every 30 minutes)")
```

### Implementation

Single-line cadence change:

```python
# triggers/embedded_scheduler.py:501-509
from triggers.sentinel_health import poll_waha_session
scheduler.add_job(
    poll_waha_session,
    IntervalTrigger(minutes=5),
    id="waha_session_poll", name="WAHA session health poll",
    coalesce=True, max_instances=1, replace_existing=True,
)
logger.info("Registered: waha_session_poll (every 5 minutes)")
```

### Key Constraints

- Keep `coalesce=True, max_instances=1, replace_existing=True`. These prevent overlapping fires and ensure one job per worker.
- `get_session_status()` has a 10s timeout (`triggers/waha_client.py:79`). 5 min cadence × single GET × 10s timeout = bounded cost.
- 5 min × 12 polls/hour × 24 hours = 288 GETs/day. Negligible.

### Verification

After deploy, query prod read-only DB:

```sql
-- Most recent waha_session_poll firing should be within last 6 min
SELECT job_id, MAX(fired_at) AS last_fired
FROM scheduler_executions
WHERE job_id = 'waha_session_poll'
GROUP BY job_id
LIMIT 1;
```

(Column name is `fired_at`, confirmed via codex prod schema probe #1364 and repo precedent `triggers/audit_sentinel.py:48`.)

---

## Files Modified

- `triggers/sentinel_health.py` — recut `poll_waha_session()` body + add module-level `_WAHA_POLL_STATE` dict.
- `triggers/embedded_scheduler.py` — cadence `minutes=30` → `minutes=5` + log line update.
- `tests/test_waha_session_poll_harden.py` — new file, 12 test cases per Verification list above.

## Do NOT Touch

- `triggers/waha_client.py` — `get_session_status()` already correct (endpoint, timeout, response shape). No change needed.
- `triggers/waha_webhook.py` — handler-side event guards already correct. This brief is poll-side only.
- `triggers/sentinel_health.py:598` `check_waha_silence` — different blind-spot class (4h inbound silence); out of scope.
- `outputs/dashboard.py` — no dashboard surface change in this brief.
- `migrations/` — no schema change.

## Quality Checkpoints

1. Pytest passes literally: `pytest tests/test_waha_session_poll_harden.py -v` — paste the actual stdout in ship report.
2. Compile-clean: `python3 -c "import py_compile; py_compile.compile('triggers/sentinel_health.py', doraise=True); py_compile.compile('triggers/embedded_scheduler.py', doraise=True)"`.
3. Singleton guard still green: `bash scripts/check_singletons.sh`.
4. PR opened against `main`, linked from ship report.
5. After merge + Render auto-deploy + ~10 min, verify in dashboard alerts table that NO false-positive STARTING/UNKNOWN alerts fire on healthy WORKING traffic.
6. Post-deploy SQL smoke (Verification SQL below) — `MAX(fired_at) WHERE job_id='waha_session_poll'` returns a timestamp within last 6 min.

## Verification SQL

```sql
-- AC: scheduler is actually firing the patched job
SELECT job_id, MAX(fired_at) AS last_fired, COUNT(*) AS exec_count_24h
FROM scheduler_executions
WHERE job_id = 'waha_session_poll'
  AND fired_at >= NOW() - INTERVAL '24 hours'
GROUP BY job_id
LIMIT 1;

-- AC: no false-positive STARTING/UNKNOWN alerts within first 2h post-deploy
SELECT title, source_id, created_at
FROM alerts
WHERE source = 'waha_session_poll'
  AND created_at >= NOW() - INTERVAL '2 hours'
ORDER BY created_at DESC
LIMIT 20;
```

## Trade-offs Documented

- **Counter on-process-restart**: per codex Q2 ("in-process dict acceptable"), we accept ~10 min re-grace window after each Render restart (weekly). False-quiet cost is bounded; persistence cost is not worth it.
- **15-min STARTING grace**: per codex Q3, 3 ticks × 5 min = 15 min is the right number. Archived `BRIEF_WAHA_SILENT_GUARD_1.md:379` documents the same invariant.
- **F6 root-cause deferred** (per codex Q4): the 29-May 19:19Z scheduler death is NOT diagnosed by this brief. The post-deploy SQL smoke (AC) will catch it if the patched job also fails to fire; we ship-and-catch rather than block on a full RCA. Wording soften: F6 proves `waha_session_poll` did not fire after 19:19Z; it does NOT by itself prove why Bick messages were missed (that requires WAHA logs).
- **Generic scheduler liveness split** (per codex Q1 + nit #2): a follow-up brief `SCHEDULER_JOB_LIVENESS_1` will design an expected-job registry + per-job intervals + singleton/replica semantics. Out of scope here.

## Anchor

- Codex review v1 FAIL-LIGHT: bus #1362 (6 findings).
- Codex review v2 PASS-WITH-NITS: bus #1364 (3 nits, all folded above).
- AH1 v1 design: bus #1360.
- AH1 v2 design: bus #1363.
- Director "go" authorization: 2026-05-30 chat.
- Anchor incident: Bick iPhone export caught 4× 2026-05-29 WAHA-missed messages during BAKER_CAPTURE_BLINDSPOTS_1 smoke (PR #270 / commit 7a4799c).
- Lesson #27 (WAHA recreation w/o store config), Lesson #69 (handler vs subscription drift), Lesson #82 (canonical lead-inbox endpoint pattern, peripheral).
