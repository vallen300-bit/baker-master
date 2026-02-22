# BRIEF 9D — Scheduler Integration Test

> **For:** Claude Code execution
> **Predecessor:** Brief 9B PASS + Brief 9C PASS (both triggers validated individually)
> **Successor:** None — this completes the Brief 9 series
> **Estimated time:** 20 minutes (includes 12-min scheduler run)
> **Modifies code:** NO — integration test only

---

## OBJECTIVE

Confirm that all 3 trigger sources (email, WhatsApp, Fireflies) run together
under the APScheduler without conflicts, crashes, or watermark corruption.
This is the final gate before Baker v1 is declared operationally complete.

## WORKING DIRECTORY

```
cd 01_build
```

---

## PHASE 1 — Job Registration

### Step 1.1 — List all registered jobs

```bash
cd 01_build
python triggers/scheduler.py --list
```

**Expected output (4 jobs):**

| Job ID | Name | Interval |
|--------|------|----------|
| `email_poll` | Gmail polling | every 300s (5 min) |
| `whatsapp_poll` | WhatsApp polling | every 600s (10 min) |
| `fireflies_scan` | Fireflies scanning | every 7200s (2 hr) |
| `daily_briefing` | Morning briefing | at 06:00 UTC |

**FAIL if:**
- Fewer than 4 jobs registered → check imports in `scheduler.py`
- Any job shows `ERROR` on registration → import failure for that trigger module

### Step 1.2 — Verify job configuration matches settings.py

```python
import sys
sys.path.insert(0, ".")
from config.settings import config

print(f"email_check_interval: {config.triggers.email_check_interval}s")
print(f"whatsapp_check_interval: {config.triggers.whatsapp_check_interval}s")
print(f"fireflies_scan_interval: {config.triggers.fireflies_scan_interval}s")
print(f"daily_briefing_hour: {config.triggers.daily_briefing_hour} UTC")

assert config.triggers.email_check_interval == 300, "email interval != 300s"
assert config.triggers.whatsapp_check_interval == 600, "whatsapp interval != 600s"
assert config.triggers.fireflies_scan_interval == 7200, "fireflies interval != 7200s"
assert config.triggers.daily_briefing_hour == 6, "briefing hour != 6 UTC"
print("PASS — all intervals match expected values")
```

---

## PHASE 2 — Record Pre-Run State

### Step 2.1 — Snapshot watermarks before scheduler run

```python
import sys, json
sys.path.insert(0, ".")
from triggers.state import trigger_state

pre_state = {}
for source in ["email", "whatsapp", "fireflies"]:
    wm = trigger_state.get_watermark(source)
    pre_state[source] = wm.isoformat()
    print(f"PRE  {source}: {wm.isoformat()}")

# Save for comparison in Phase 3
with open("/tmp/pre_watermarks.json", "w") as f:
    json.dump(pre_state, f)
print("Watermarks saved to /tmp/pre_watermarks.json")
```

---

## PHASE 3 — Scheduler Run (12 minutes)

### Step 3.1 — Start scheduler

```bash
cd 01_build
timeout 720 python triggers/scheduler.py 2>&1 | tee /tmp/scheduler_output.log
```

**This runs the scheduler for exactly 12 minutes (720s) via `timeout`.**

During this window, expect:
- `email_poll` fires at ~0s, ~300s, ~600s (3 times)
- `whatsapp_poll` fires at ~0s, ~600s (2 times)
- `fireflies_scan` does NOT fire (7200s interval > 720s window) — this is expected
- `daily_briefing` does NOT fire (cron trigger, only at 06:00 UTC) — this is expected

### Step 3.2 — Analyze scheduler log

After the 12 minutes complete:

```python
import re

with open("/tmp/scheduler_output.log", "r") as f:
    log = f.read()

# Count job executions
email_runs = len(re.findall(r"Job email_poll completed successfully", log))
whatsapp_runs = len(re.findall(r"Job whatsapp_poll completed successfully", log))
fireflies_runs = len(re.findall(r"Job fireflies_scan completed successfully", log))

# Count errors
error_lines = [line for line in log.split("\n") if "ERROR" in line or "failed" in line.lower()]

print(f"email_poll executions: {email_runs} (expected: 2-3)")
print(f"whatsapp_poll executions: {whatsapp_runs} (expected: 1-2)")
print(f"fireflies_scan executions: {fireflies_runs} (expected: 0)")
print(f"Error lines: {len(error_lines)}")

if error_lines:
    print("\n--- ERRORS ---")
    for line in error_lines[:10]:
        print(f"  {line.strip()}")

# Validate execution counts
if email_runs >= 2 and whatsapp_runs >= 1 and len(error_lines) == 0:
    print("\nPASS — scheduler ran all triggers correctly")
elif len(error_lines) > 0:
    print("\nFAIL — errors during scheduler run (see above)")
else:
    print(f"\nWARN — unexpected execution counts")
```

### Step 3.3 — Check for concurrent execution issues

```python
# Check for overlapping job runs (max_instances=1 should prevent this)
with open("/tmp/scheduler_output.log", "r") as f:
    log = f.read()

overlap_warnings = [
    line for line in log.split("\n")
    if "skipped" in line.lower() or "already running" in line.lower()
        or "maximum number of running instances" in line.lower()
]

if overlap_warnings:
    print(f"INFO — {len(overlap_warnings)} overlap warnings (OK, APScheduler coalesce working)")
    for w in overlap_warnings[:3]:
        print(f"  {w.strip()}")
else:
    print("PASS — no overlap warnings")
```

---

## PHASE 4 — Verify Post-Run State

### Step 4.1 — Compare watermarks (pre vs post)

```python
import sys, json
sys.path.insert(0, ".")
from triggers.state import trigger_state

# Load pre-state
with open("/tmp/pre_watermarks.json", "r") as f:
    pre_state = json.load(f)

print("Watermark changes:")
all_ok = True
for source in ["email", "whatsapp", "fireflies"]:
    pre = pre_state[source]
    post = trigger_state.get_watermark(source).isoformat()
    changed = pre != post

    if source == "fireflies":
        # Fireflies should NOT change (didn't fire in 12 min window)
        if changed:
            print(f"  WARN — {source}: changed unexpectedly")
            print(f"    PRE:  {pre}")
            print(f"    POST: {post}")
        else:
            print(f"  OK — {source}: unchanged (expected, didn't fire)")
    else:
        # Email and WhatsApp SHOULD update
        status = "updated" if changed else "UNCHANGED"
        print(f"  {'OK' if changed else 'WARN'} — {source}: {status}")
        print(f"    PRE:  {pre}")
        print(f"    POST: {post}")
        if not changed:
            print(f"    (may be OK if no new messages since last run)")

print()
```

### Step 4.2 — Verify watermarks are independent

```python
import sys
sys.path.insert(0, ".")
from triggers.state import trigger_state

watermarks = {}
for source in ["email", "whatsapp", "fireflies"]:
    watermarks[source] = trigger_state.get_watermark(source)

# Check they're all different (shouldn't all be identical)
values = [wm.isoformat() for wm in watermarks.values()]
if len(set(values)) == 1:
    print("WARN — all watermarks identical (may indicate shared state bug)")
else:
    print("PASS — watermarks are independent")

# Check none are epoch (1970)
for source, wm in watermarks.items():
    if wm.year < 2024:
        print(f"FAIL — {source} watermark reset to epoch: {wm}")
    else:
        print(f"OK — {source}: {wm.isoformat()}")
```

### Step 4.3 — Graceful shutdown check

```python
with open("/tmp/scheduler_output.log", "r") as f:
    log = f.read()

# timeout sends SIGTERM, which should trigger graceful shutdown
if "Scheduler stopped" in log or "Scheduler shutdown" in log:
    print("PASS — graceful shutdown confirmed")
elif "SIGTERM" in log:
    print("PASS — SIGTERM handled")
else:
    # timeout may have killed it abruptly — this is OK for the test
    print("INFO — scheduler was killed by timeout (OK for test purposes)")
    print("In production, SIGTERM → graceful shutdown path should work")
```

---

## FINAL VERIFICATION SUMMARY

| # | Check | Expected | Result |
|---|-------|----------|--------|
| 1 | 4 jobs registered | All 4 present | |
| 2 | Intervals match settings.py | 300/600/7200/06:00 | |
| 3 | email_poll fired ≥ 2 times | 2-3 executions | |
| 4 | whatsapp_poll fired ≥ 1 time | 1-2 executions | |
| 5 | 0 error lines in log | No errors | |
| 6 | No concurrent execution issues | coalesce working | |
| 7 | Watermarks updated (email + whatsapp) | Changed from pre-state | |
| 8 | Watermarks independent | Not all identical | |
| 9 | No watermark reset to epoch | All > 2024 | |
| 10 | Graceful shutdown | SIGTERM handled | |

**Pass threshold:** 8/10 PASS minimum. Items 7 and 10 may be WARN/INFO depending
on data availability and timeout behavior.

---

## COMPLETION REPORT

When all checks pass, output this summary:

```
=== BRIEF 9 SERIES COMPLETE ===

Brief 9A: Environment Prerequisites — PASS
Brief 9B: WhatsApp Live Validation — PASS
Brief 9C: Fireflies Live Validation — PASS
Brief 9D: Scheduler Integration    — PASS

All 3 trigger sources now validated against live APIs:
  ✓ Email (Gmail OAuth) — Brief 7
  ✓ WhatsApp (Wassenger REST) — Brief 9B
  ✓ Fireflies (GraphQL) — Brief 9C

Baker v1 Sentinel layer is operationally complete.

Remaining items (from Blueprint):
  1. Qdrant migration: AWS → Azure EU
  2. Azure deployment: containerize for always-on
  3. Onboarding briefing: sections 3, 5, 6, 7
  4. Role-based categories: expand classification
```

---

## STOP CONDITIONS

1. Scheduler crashes during 12-min run → check if a specific trigger caused it
2. Jobs don't fire on schedule → check APScheduler version and interval config
3. Watermark corruption (epoch reset) → investigate trigger_state.set_watermark()
4. All checks PASS → Brief 9 series complete. Report to user.
