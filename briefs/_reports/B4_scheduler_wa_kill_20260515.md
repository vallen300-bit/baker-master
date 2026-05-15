---
brief: briefs/BRIEF_SCHEDULER_WATCHDOG_WA_KILL_1.md
phase: A of 2 (scheduler-wa-kill-and-rca dispatch)
status: SHIPPED
ship_date: 2026-05-15
author: B4
dispatch_thread: 7649545b-def0-4055-b908-66a94e139057
pr: 206 (merged ac8f707, squash, 2026-05-15T15:57:50Z)
hard_ship_gate: PASS (4/4 — see below)
---

# B4 ship report — SCHEDULER_WATCHDOG_WA_KILL_1 (Phase A)

## Hard ship gate (4/4 PASS)

### Gate 1 — Compile clean

```
$ python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"
COMPILE OK
```

### Gate 2 — Literal pytest output

Run under repo venv `.venv-test` (Python 3.12 — local system `python3` is 3.9, lacks PEP-604 `int | None` support used elsewhere in the codebase).

```
$ .venv-test/bin/pytest tests/test_watchdog_cooldown.py -v
tests/test_watchdog_cooldown.py::test_watchdog_alert_throttled PASSED                    [ 33%]
tests/test_watchdog_cooldown.py::test_watchdog_alert_fires_again_after_cooldown PASSED   [ 66%]
tests/test_watchdog_cooldown.py::test_watchdog_no_alert_when_heartbeat_fresh PASSED      [100%]
======================== 3 passed, 5 warnings in 0.32s =========================
```

Tests updated: `send_whatsapp` mock replaced with `patch.object(dash, "logger")`, asserting `logger.warning.call_args_list` filtered on `WATCHDOG_RESTART` prefix. Same throttle semantics, same cooldown variable.

### Gate 3 — PR opened + /security-review clean

- PR #206: https://github.com/vallen300-bit/baker-master/pull/206
- Title: `fix(scheduler): disable watchdog WA alert (CRASHLOOP_RCA_2 in flight)`
- Trigger class: LOW (single-file, no auth, no DB, no external surface). No mandatory 2nd-pass per `/security-review` skill rules.
- AH2 reviewed + merged at `ac8f707` (squash) 2026-05-15T15:57:50Z.

### Gate 4 — Post-merge SELECT verification (literal)

Ran 30+ min post-deploy (actual gap: 76 min — verification window already cleared before B4 picker re-opened).

```sql
SELECT COUNT(*) AS watchdog_wa_sends_last_30min
FROM baker_actions
WHERE action_type='whatsapp_send'
  AND payload->>'text_preview' LIKE 'Baker scheduler was dead%'
  AND created_at > NOW() - INTERVAL '30 minutes';
```

```
watchdog_wa_sends_last_30min: 0
```

**Tighter check — full post-merge window:**

```sql
SELECT COUNT(*) AS post_merge_total, MAX(created_at) AS latest_send
FROM baker_actions
WHERE action_type='whatsapp_send'
  AND payload->>'text_preview' LIKE 'Baker scheduler was dead%'
  AND created_at > '2026-05-15T15:57:50Z';
```

```
post_merge_total: 0
latest_send:      NULL
```

**Baseline (pre-merge 24h):**

```sql
SELECT COUNT(*) AS pre_merge_24h, MIN(created_at) AS first, MAX(created_at) AS last
FROM baker_actions
WHERE action_type='whatsapp_send'
  AND payload->>'text_preview' LIKE 'Baker scheduler was dead%'
  AND created_at > NOW() - INTERVAL '24 hours'
  AND created_at < '2026-05-15T15:57:50Z';
```

```
pre_merge_24h: 138
first:         2026-05-14 17:20:49.491491+00:00
last:          2026-05-15 15:57:30.284716+00:00
```

Last pre-merge send fired at `15:57:30Z` — 20 seconds before the merge SHA timestamp. Clean cutoff. 138 → 0 in the 30-min post-merge window.

## Files modified

- `outputs/dashboard.py` (lines 185-209)
  - Replaced `send_whatsapp(...)` call block with throttled `logger.warning("WATCHDOG_RESTART: ...")`.
  - Kept `restart_scheduler()`, 720s stale threshold, `_watchdog_alert_cooldown_s` (300s), and `_watchdog_last_alert_ts` semantics intact — same throttle, applied to WARN log instead of WA push.
- `tests/test_watchdog_cooldown.py` — test assertions updated per above (Gate 2).

## Not touched (per brief)

- `triggers/embedded_scheduler.py` — restart path intact.
- `outputs/whatsapp_sender.py` — out of scope.
- `triggers/scheduler_lease.py` — singleton-harden untouched; not today's issue.

## Re-enable path

Comment in `_check_scheduler_heartbeat` docstring (`outputs/dashboard.py:188-191`):

> Re-enable only after that RCA closes and crash-loop frequency is back to <1 event/day. Dashboard + server logs still capture every restart.

## Phase B status

Phase A merged. Phase B (`BRIEF_SCHEDULER_CRASHLOOP_RCA_2`) starts next — RCA only, ship report to `briefs/_reports/B4_scheduler_crashloop_rca2_<date>.md`. No code mutation.

## Co-Authored-By

```
Co-authored-by: Code Brisen #4 <b4@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
