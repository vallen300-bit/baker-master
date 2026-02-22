# BRIEF 9C — Fireflies Trigger Live Validation

> **For:** Claude Code execution
> **Predecessor:** Brief 9A PASS, Brief 9B PASS (or concurrent with 9B)
> **Successor:** Brief 9D (Scheduler Integration)
> **Estimated time:** 15-20 minutes
> **Modifies code:** YES — bug fixes only (see Phase 4)

---

## OBJECTIVE

Validate `triggers/fireflies_trigger.py` against the live Fireflies GraphQL API.
Confirm: fetch → format → classify → pipeline → store-back works end-to-end
with real meeting transcripts. Verify dedup prevents reprocessing.

## WORKING DIRECTORY

```
cd 01_build
```

---

## PHASE 1 — Fetch Test (API Connectivity)

### Step 1.1 — Fetch recent transcripts

```python
import sys
sys.path.insert(0, ".")
from triggers.fireflies_trigger import fetch_new_transcripts
from datetime import datetime, timezone, timedelta

# Use 30-day window to find any transcripts
since = datetime.now(timezone.utc) - timedelta(days=30)
transcripts = fetch_new_transcripts(since)

print(f"Transcripts found: {len(transcripts)}")
for t in transcripts[:5]:
    meta = t.get("metadata", {})
    print(f"  title: {meta.get('title', 'untitled')}")
    print(f"  date: {meta.get('date', 'no date')}")
    print(f"  organizer: {meta.get('organizer', 'unknown')}")
    print(f"  raw_id: {t.get('raw_id', 'none')}")
    print()
```

**Expected:** ≥ 1 transcript from the last 30 days.

**If 0 transcripts:**
1. Check Fireflies dashboard — are there recordings in the account?
2. Try `timedelta(days=90)` for wider window
3. If still 0 → Fireflies account may have no recordings. HUMAN GATE: user needs to
   upload or record a test meeting, then re-run this phase.

### Step 1.2 — Verify transcript content quality

```python
# Continue from 1.1
if transcripts:
    sample = transcripts[0]
    text = sample.get("text", "")
    meta = sample.get("metadata", {})

    print(f"Text length: {len(text)} chars")
    print(f"Text preview (first 300 chars):")
    print(text[:300])
    print()
    print(f"Metadata keys: {list(meta.keys())}")

    # Validate expected fields
    assert len(text) > 50, "WARN — transcript text suspiciously short"
    assert "title" in meta, "FAIL — missing 'title' in metadata"
    print("PASS — transcript content looks valid")
else:
    print("SKIP — no transcripts to inspect")
```

### Step 1.3 — Check timezone handling

This is the most likely failure point. The trigger code (line 44) converts naive
datetimes to UTC-aware. Verify this works with real data:

```python
import sys
sys.path.insert(0, ".")
from scripts.extract_fireflies import fetch_transcripts, transcript_date
from config.settings import config
from datetime import timezone

raw = fetch_transcripts(config.fireflies.api_key, limit=5)
for t in raw[:3]:
    t_date = transcript_date(t)
    print(f"title: {t.get('title', 'unknown')}")
    print(f"  raw date: {t_date}")
    print(f"  tzinfo: {t_date.tzinfo if t_date else 'None'}")

    if t_date and t_date.tzinfo is None:
        t_date_aware = t_date.replace(tzinfo=timezone.utc)
        print(f"  after replace: {t_date_aware} (tzinfo={t_date_aware.tzinfo})")
    elif t_date:
        print(f"  already aware: {t_date}")
    else:
        print(f"  WARNING: transcript_date returned None")
    print()

print("PASS — timezone handling verified (no TypeError)")
```

**If TypeError occurs:** The `transcript_date()` function is returning an unexpected
format. Log the raw value and fix in `scripts/extract_fireflies.py`.

---

## PHASE 2 — Full Pipeline Run

### Step 2.1 — Reset watermark and run

```python
import sys
sys.path.insert(0, ".")
from triggers.state import trigger_state
from datetime import datetime, timezone, timedelta

# Set watermark to 30 days ago so we pick up real transcripts
trigger_state.set_watermark("fireflies", datetime.now(timezone.utc) - timedelta(days=30))
print("Fireflies watermark reset to 30 days ago")
```

Now run the trigger:

```bash
cd 01_build
python triggers/scheduler.py --run-once fireflies 2>&1
```

**Expected log output contains ALL of these lines:**
1. `Fireflies trigger: scanning for new transcripts...`
2. `Fireflies watermark: <ISO timestamp ~30 days ago>`
3. `Fireflies trigger: N new transcripts found` (N > 0)
4. `Fireflies trigger complete: N transcripts processed`

**If line 3 shows "no new transcripts":**
- The `fetch_new_transcripts()` succeeded in Phase 1 but the watermark comparison is
  failing. Debug the comparison:

```python
import sys
sys.path.insert(0, ".")
from triggers.state import trigger_state
from triggers.fireflies_trigger import fetch_new_transcripts

wm = trigger_state.get_watermark("fireflies")
print(f"Watermark: {wm} (tzinfo={wm.tzinfo})")
transcripts = fetch_new_transcripts(wm)
print(f"Transcripts newer than watermark: {len(transcripts)}")
```

### Step 2.2 — Check for pipeline errors

Scan output from 2.1 for:
- `ERROR` lines → note the full error message
- `pipeline failed for transcript` → SentinelPipeline.run() crashed
- `ImportError` → missing module (check `scripts/extract_fireflies.py` is accessible)
- `TypeError: can't compare offset-naive and offset-aware` → timezone fix needed

If errors found → go to Phase 4 to fix.

---

## PHASE 3 — Dedup Verification

This is critical. Run the trigger a second time — same transcripts must NOT be reprocessed.

### Step 3.1 — Second run (should skip all)

```bash
cd 01_build
python triggers/scheduler.py --run-once fireflies 2>&1
```

**Expected:**
- `Fireflies trigger: no new transcripts` — because watermark was updated in Phase 2
- OR: logs show transcripts being skipped via `is_processed()` check

**FAIL if:** the same transcripts are processed again. This means dedup is broken.

### Step 3.2 — Explicit dedup test

```python
import sys
sys.path.insert(0, ".")
from triggers.state import trigger_state
from triggers.fireflies_trigger import fetch_new_transcripts
from datetime import datetime, timezone, timedelta

# Fetch transcripts with old watermark (should find some)
since_old = datetime.now(timezone.utc) - timedelta(days=30)
transcripts = fetch_new_transcripts(since_old)

if transcripts:
    test_id = transcripts[0].get("raw_id", "test-id")
    # Check if it's marked as processed
    is_dup = trigger_state.is_processed("meeting", test_id)
    print(f"Transcript {test_id} already processed: {is_dup}")
    if is_dup:
        print("PASS — dedup working correctly")
    else:
        print("WARN — transcript not marked as processed")
        print("Check: does pipeline.run() call trigger_state to mark processed?")
else:
    print("SKIP — no transcripts to test dedup")
```

---

## PHASE 4 — Bug Fix Pass

### Bug #3 — Timezone comparison

If Phase 1.3 or Phase 2 produced a TypeError:

**File:** `triggers/fireflies_trigger.py`, line 44

**Current code:**
```python
t_date_aware = t_date.replace(tzinfo=timezone.utc)
```

**Verify** this handles all cases:
1. `t_date` is None → should be caught by `if t_date is None: continue` on line 42
2. `t_date` is already aware → `replace(tzinfo=...)` overwrites, which is OK for UTC
3. `t_date` is naive → correct behavior

If `transcript_date()` returns a string instead of datetime, fix:
```python
if isinstance(t_date, str):
    from datetime import datetime as dt
    t_date = dt.fromisoformat(t_date.replace("Z", "+00:00"))
```

### Bug #5 — Fireflies rate limit (100 req/min)

```python
# Check how many transcripts we're pulling
import sys
sys.path.insert(0, ".")
from scripts.extract_fireflies import fetch_transcripts
from config.settings import config

raw = fetch_transcripts(config.fireflies.api_key, limit=50)
print(f"Total transcripts in account: {len(raw)}")

if len(raw) >= 50:
    print("WARN — may need pagination / rate limiting for large backlogs")
    print("FIX: Add retry with exponential backoff to fetch_transcripts()")
else:
    print("OK — under rate limit concern threshold")
```

**If fix needed**, wrap the GraphQL call in `scripts/extract_fireflies.py` with:
```python
import time
MAX_RETRIES = 3
for attempt in range(MAX_RETRIES):
    try:
        resp = httpx.post(...)
        if resp.status_code == 429:
            wait = 2 ** attempt * 10  # 10s, 20s, 40s
            logger.warning(f"Rate limited, waiting {wait}s...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        break
    except Exception as e:
        if attempt == MAX_RETRIES - 1:
            raise
```

---

## VERIFICATION SUMMARY

| # | Check | Expected | Result |
|---|-------|----------|--------|
| 1 | `fetch_new_transcripts()` returns data | ≥ 1 transcript | |
| 2 | Transcript text > 50 chars + has title | Valid content | |
| 3 | Timezone handling (no TypeError) | Clean comparison | |
| 4 | `--run-once fireflies` no errors | Clean log output | |
| 5 | Transcripts processed count > 0 | N processed | |
| 6 | Second run skips all (dedup) | No reprocessing | |
| 7 | Watermark updated after run | Recent timestamp | |

**Pass threshold:** 7/7 PASS (or SKIP for items dependent on data availability).

**Output:** Report the table above with PASS/FAIL/SKIP for each check.
List any bug fixes applied with file, line number, and change description.

---

## STOP CONDITIONS

1. Fireflies API returns error → re-check API key (Brief 9A Step 3)
2. `scripts/extract_fireflies.py` import fails → check file exists and has expected functions
3. Pipeline crashes repeatedly → log full traceback, attempt fix (max 3 attempts)
4. Dedup fails → investigate `trigger_state.is_processed()` — may need PostgreSQL check
5. All 7 checks PASS → proceed to Brief 9D
