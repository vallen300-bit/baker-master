---
report: B1_WAHA_SESSION_POLL_HARDEN_1
ship_date: 2026-05-30
builder: b1
dispatched_by: lead
brief: briefs/BRIEF_WAHA_SESSION_POLL_HARDEN_1.md
brief_anchor_commit: a237be5
pr: 271
pr_url: https://github.com/vallen300-bit/baker-master/pull/271
branch: b1/waha-session-poll-harden-1
head_commit: a0bede0
bus_dispatch: 1366
bus_unblock: 1370
bus_blocker_posted: 1368
ship_topic: ship/waha-session-poll-harden-1
reply_target: lead
estimated_time: ~3h
actual_time: ~50 min
---

# B1 Ship Report — WAHA_SESSION_POLL_HARDEN_1

## What shipped

Hardened `triggers/sentinel_health.py:poll_waha_session()` along four axes per brief authored at a237be5 (codex pre-reviewed twice, all 9 findings folded):

1. **Cadence** — `triggers/embedded_scheduler.py:501-509` 30 min → 5 min. Coalesce / max_instances / replace_existing preserved.
2. **Grace policy** — STARTING tolerated 3 ticks (~15 min), UNKNOWN/missing tolerated 2 ticks (~10 min). DEAD (SCAN_QR_CODE/STOPPED/FAILED) immediate alert preserved.
3. **Webhook-drift check** (Lesson #69 invariant) — union of `config.webhooks[].events` checked for `{session.status, message.any}`; missing → T1 alert `WAHA WEBHOOK CONFIG DRIFT`.
4. **In-process counter** — `_WAHA_POLL_STATE` dict near other module-level state (`triggers/sentinel_health.py:374-379`). Scheduler is singleton-gated; brief accepts ~10 min re-grace window after each Render restart (weekly).

## Files modified

| File | Change |
|---|---|
| `triggers/sentinel_health.py` | +118 / -13 — module-level `_WAHA_POLL_STATE` + recut `poll_waha_session()` body |
| `triggers/embedded_scheduler.py` | +3 / -3 — IntervalTrigger(minutes=30) → minutes=5 + log line + brief-tag comment |
| `tests/test_waha_session_poll_harden.py` | +328 / -0 — new file, 12 cases per brief Verification list |
| `briefs/_tasks/CODE_1_PENDING.md` | +2 / -1 — status PENDING → CLAIMED, claimed_at + claimed_by |

## Quality checkpoints

### 1. Compile-clean

```
$ python3 -c "import py_compile; py_compile.compile('triggers/sentinel_health.py', doraise=True); py_compile.compile('triggers/embedded_scheduler.py', doraise=True); print('OK')"
OK
```

### 2. Singleton-pattern CI guard

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

### 3. Pytest — LITERAL output (Python 3.12 / pytest 9.0.3)

System python3 on Mac is 3.9 and cannot import `memory/store_back.py` (uses 3.10+ `int | None` syntax). Codebase requires Python 3.11+ per `CLAUDE.md`. Ran against `/opt/homebrew/bin/python3.12`:

```
$ python3.12 -m pytest tests/test_waha_session_poll_harden.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0 -- /opt/homebrew/opt/python@3.12/bin/python3.12
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b1
plugins: langsmith-0.7.38, anyio-4.12.1
collecting ... collected 12 items

tests/test_waha_session_poll_harden.py::test_case_1_starting_once_no_alert PASSED [  8%]
tests/test_waha_session_poll_harden.py::test_case_2_starting_three_ticks_alerts PASSED [ 16%]
tests/test_waha_session_poll_harden.py::test_case_3_working_after_starting_resets PASSED [ 25%]
tests/test_waha_session_poll_harden.py::test_case_4_unknown_once_no_alert PASSED [ 33%]
tests/test_waha_session_poll_harden.py::test_case_5_unknown_two_ticks_alerts PASSED [ 41%]
tests/test_waha_session_poll_harden.py::test_case_6_scan_qr_immediate_alert PASSED [ 50%]
tests/test_waha_session_poll_harden.py::test_case_7_drift_missing_session_status PASSED [ 58%]
tests/test_waha_session_poll_harden.py::test_case_8_drift_missing_message_any PASSED [ 66%]
tests/test_waha_session_poll_harden.py::test_case_9_drift_clean_no_alert PASSED [ 75%]
tests/test_waha_session_poll_harden.py::test_case_10_source_id_dedupe_stable_template PASSED [ 83%]
tests/test_waha_session_poll_harden.py::test_case_11_counter_reset_across_transitions PASSED [ 91%]
tests/test_waha_session_poll_harden.py::test_case_12_create_alert_raise_no_crash PASSED [100%]

============================== 12 passed in 0.03s ==============================
```

12/12 green. No `--tb=` redaction. No "passes by inspection."

### 4. PR opened

- PR #271 → https://github.com/vallen300-bit/baker-master/pull/271
- Base: `main` (4fc8cfd) — Head: `b1/waha-session-poll-harden-1` (a0bede0).

## Post-deploy AC (for lead + deputy)

Per brief Verification SQL:

```sql
-- AC 1: scheduler is actually firing the patched job (should be within 6 min)
SELECT job_id, MAX(fired_at) AS last_fired, COUNT(*) AS exec_count_24h
FROM scheduler_executions
WHERE job_id = 'waha_session_poll'
  AND fired_at >= NOW() - INTERVAL '24 hours'
GROUP BY job_id
LIMIT 1;

-- AC 2: no false-positive STARTING/UNKNOWN alerts within first 2h post-deploy
SELECT title, source_id, created_at
FROM alerts
WHERE source = 'waha_session_poll'
  AND created_at >= NOW() - INTERVAL '2 hours'
ORDER BY created_at DESC
LIMIT 20;
```

Not run from b1 — requires prod read-only DB access AH1/deputy hold.

## Trade-offs documented in brief, preserved here

- **Counter on Render restart**: ~10 min re-grace after weekly restart; brief accepts.
- **15-min STARTING grace**: 3 ticks × 5 min; matches archived `BRIEF_WAHA_SILENT_GUARD_1.md:379` invariant.
- **F6 (29-May 19:19Z scheduler death) RCA deferred**: post-deploy SQL smoke catches it if patched job also fails to fire. We ship-and-catch.
- **Generic scheduler liveness split** to `SCHEDULER_JOB_LIVENESS_1` (per codex Q1 + nit #2).

## Anchors

- Brief: `briefs/BRIEF_WAHA_SESSION_POLL_HARDEN_1.md` @ a237be5.
- Mailbox: `briefs/_tasks/CODE_1_PENDING.md` (PENDING → CLAIMED → ship pending).
- Bus dispatch: #1366 (lead → b1, 2026-05-30T09:58:55Z).
- Bus blocker (brief missing): #1368 (b1 → lead, 2026-05-30T10:06:58Z).
- Bus unblock (brief pushed): #1370 (lead → b1, 2026-05-30T10:13:32Z).
- Anchor incident: Bick iPhone export caught 4× 2026-05-29 WAHA-missed messages during BAKER_CAPTURE_BLINDSPOTS_1 smoke (PR #270 / 7a4799c).
- Lesson #27 (WAHA recreation w/o store config — no /restart call introduced).
- Lesson #69 (handler vs subscription drift — webhook union check implements).

## Open for AH1 review

- PR #271 awaits lead review + Tier-A gate.
- Mailbox to mark COMPLETE on merge.
- Bus-post on ship: `ship/waha-session-poll-harden-1` from `b1` to `lead`.
