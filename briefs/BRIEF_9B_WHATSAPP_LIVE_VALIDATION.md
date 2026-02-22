# BRIEF 9B — WhatsApp Trigger Live Validation

> **For:** Claude Code execution
> **Predecessor:** Brief 9A PASS (all env/API checks green)
> **Successor:** Brief 9C (Fireflies), then 9D (Scheduler)
> **Estimated time:** 15-25 minutes
> **Modifies code:** YES — bug fixes only (see Phase 4)

---

## OBJECTIVE

Validate `triggers/whatsapp_trigger.py` against the live Wassenger API.
Confirm: fetch → format → classify → pipeline → store-back works end-to-end
with real WhatsApp messages.

## WORKING DIRECTORY

```
cd 01_build
```

---

## PHASE 1 — Fetch Test (API Connectivity)

### Step 1.1 — Fetch recent chats from Wassenger

```python
import sys
sys.path.insert(0, ".")
from triggers.whatsapp_trigger import fetch_new_messages, _get_api_key, _get_device_id
from datetime import datetime, timezone, timedelta

api_key = _get_api_key()
device_id = _get_device_id()
since = datetime.now(timezone.utc) - timedelta(hours=24)

groups = fetch_new_messages(api_key, device_id, since)
print(f"Chat groups returned: {len(groups)}")
for g in groups[:5]:
    print(f"  {g['chat_name']} ({g['contact_type']}): {len(g['messages'])} msgs")
```

**Expected:** ≥ 1 chat group with real messages.

**If 0 groups:**
1. Check: does Dimitry's WhatsApp have messages in last 24h?
2. Try widening the window: `timedelta(days=7)`
3. If still 0 with 7-day window → the Wassenger device may not be linked to the right number. STOP — HUMAN GATE.

### Step 1.2 — Inspect raw message structure

```python
# Continue from 1.1
if groups:
    sample = groups[0]["messages"][0]
    print("Message keys:", list(sample.keys()))
    print("type:", sample.get("type"))
    print("body:", (sample.get("body") or "")[:100])
    print("senderName:", sample.get("senderName"))
    print("fromNumber:", sample.get("fromNumber"))
    print("createdAt:", sample.get("createdAt"))
```

**Log the actual keys.** If the API returns different field names than expected
(`body` vs `text`, `senderName` vs `sender`), note the mismatch for Phase 4 fix.

---

## PHASE 2 — Format Test (Data Shape)

### Step 2.1 — Format a single chat group

```python
import sys
sys.path.insert(0, ".")
from triggers.whatsapp_trigger import fetch_new_messages, format_chat_messages
from triggers.whatsapp_trigger import _get_api_key, _get_device_id
from datetime import datetime, timezone, timedelta

api_key = _get_api_key()
device_id = _get_device_id()
since = datetime.now(timezone.utc) - timedelta(hours=24)

groups = fetch_new_messages(api_key, device_id, since)
if not groups:
    print("SKIP — no messages to format (widen window or send test message)")
else:
    formatted = format_chat_messages(groups[0])

    # Validate shape
    assert "text" in formatted, "FAIL — missing 'text' key"
    assert "metadata" in formatted, "FAIL — missing 'metadata' key"
    assert formatted["metadata"]["source"] == "whatsapp", "FAIL — source != 'whatsapp'"
    assert isinstance(formatted["metadata"]["message_count"], int), "FAIL — message_count not int"

    print("--- Formatted text (first 300 chars) ---")
    print(formatted["text"][:300])
    print("--- Metadata ---")
    for k, v in formatted["metadata"].items():
        print(f"  {k}: {v}")
    print("PASS — format_chat_messages produces correct shape")
```

### Step 2.2 — Check for "Unknown" sender issue

```python
# Continue from 2.1
if groups:
    text = format_chat_messages(groups[0])["text"]
    unknown_count = text.count("Unknown:")
    if unknown_count > 0:
        print(f"WARN — {unknown_count} messages show 'Unknown' sender")
        print("FIX NEEDED: fallback to chat_name when senderName is null")
        print("See Phase 4, Bug #2")
    else:
        print("PASS — no Unknown senders")
```

---

## PHASE 3 — Full Pipeline Run

### Step 3.1 — Run WhatsApp trigger via scheduler CLI

```bash
cd 01_build
python triggers/scheduler.py --run-once whatsapp 2>&1
```

**Expected log output contains ALL of these lines (in order):**
1. `WhatsApp trigger: checking for new messages...`
2. `WhatsApp watermark: <ISO timestamp>`
3. `WhatsApp trigger: X new messages in Y chats` (X > 0)
4. `WhatsApp trigger complete: N processed, M queued for briefing`

**If line 3 shows "no new messages":** The watermark was just updated in Phase 1.
Reset it first:

```python
import sys
sys.path.insert(0, ".")
from triggers.state import trigger_state
from datetime import datetime, timezone, timedelta

# Set watermark to 24h ago
trigger_state.set_watermark("whatsapp", datetime.now(timezone.utc) - timedelta(hours=24))
print("Watermark reset to 24h ago")
```

Then re-run `--run-once whatsapp`.

### Step 3.2 — Check for pipeline errors

Scan the output from 3.1 for:
- `ERROR` lines → note the full error message
- `pipeline failed for` → the pipeline.run() crashed for a specific chat
- `KeyError` → field name mismatch between Wassenger API and our code
- `TypeError` → data type issue (usually datetime comparison)

If errors found → go to Phase 4 to fix before verifying stores.

---

## PHASE 4 — Verify Data Stores

### Step 4.1 — Check trigger_state watermark updated

```python
import sys
sys.path.insert(0, ".")
from triggers.state import trigger_state

wm = trigger_state.get_watermark("whatsapp")
print(f"WhatsApp watermark after run: {wm.isoformat()}")
# Should be very recent (within last few minutes)
```

### Step 4.2 — Check Qdrant for new WhatsApp vectors

```python
import sys
sys.path.insert(0, ".")
from memory.retriever import SentinelRetriever

r = SentinelRetriever()

# Search for any recent WhatsApp content
results = r.search(
    "recent WhatsApp message",
    collections=["baker-whatsapp"],
    top_k=5,
)
print(f"WhatsApp vectors found: {len(results)}")
for res in results[:3]:
    print(f"  score={res.get('score', 0):.3f} | {str(res.get('text', ''))[:80]}")

if len(results) > 0:
    print("PASS — WhatsApp data stored in Qdrant")
else:
    print("WARN — no vectors in baker-whatsapp (check if pipeline stored to different collection)")
```

### Step 4.3 — Check trigger_log (if PostgreSQL trigger_log table exists)

```python
import sys
sys.path.insert(0, ".")

try:
    from triggers.state import trigger_state
    # Check if trigger_log query method exists
    if hasattr(trigger_state, 'is_processed'):
        print("trigger_state.is_processed() available — dedup operational")
    else:
        print("INFO — is_processed not in trigger_state (may use different dedup method)")
except Exception as e:
    print(f"INFO — trigger_log check: {e}")

print("PASS — Phase 4 complete")
```

---

## PHASE 5 — Bug Fix Pass

Check each known issue against live data. Fix only if the bug manifests.

### Bug #1 — Pagination (chats > 50)

```python
# Check if we're hitting the limit
import sys
sys.path.insert(0, ".")
from triggers.whatsapp_trigger import _get_api_key, _get_device_id
import httpx

api_key = _get_api_key()
device_id = _get_device_id()
r = httpx.get(
    f"https://api.wassenger.com/v1/devices/{device_id}/chats",
    headers={"Token": api_key},
    params={"size": 50, "sort": "-lastMessageAt"},
    timeout=30,
)
chats = r.json()
print(f"Chats returned: {len(chats)}")
if len(chats) == 50:
    print("WARN — exactly 50 chats returned, pagination may be needed")
    print("FIX: Add pagination loop in fetch_new_messages() or increase size to 100")
else:
    print("OK — under pagination limit")
```

**If fix needed**, modify `triggers/whatsapp_trigger.py` line 60:
Change `"size": 50` to `"size": 100` (quick fix) or add pagination (proper fix).

### Bug #2 — "Unknown" sender fallback

If Phase 2.2 showed Unknown senders, apply this fix in `triggers/whatsapp_trigger.py`:

**Find** (around line 123):
```python
sender = msg.get("senderName") or msg.get("fromNumber") or "Unknown"
```

**Replace with:**
```python
sender = msg.get("senderName") or msg.get("fromNumber") or chat_name or "Unknown"
```

This requires passing `chat_name` to the loop. Update `format_chat_messages`:

**Find** (around line 117-119):
```python
def format_chat_messages(chat_group: dict) -> dict:
    """Format a group of messages from one chat into pipeline-ready format."""
    chat_name = chat_group["chat_name"]
```

The `chat_name` variable is already in scope — verify the sender line can reference it.
If it's inside a nested function or the variable is shadowed, fix the scoping.

### Bug #4 — Group message flood

```python
# Check message counts per chat
import sys
sys.path.insert(0, ".")
from triggers.whatsapp_trigger import fetch_new_messages, _get_api_key, _get_device_id
from datetime import datetime, timezone, timedelta

groups = fetch_new_messages(
    _get_api_key(), _get_device_id(),
    datetime.now(timezone.utc) - timedelta(hours=24)
)
for g in groups:
    count = len(g["messages"])
    if count > 30:
        print(f"WARN — {g['chat_name']}: {count} messages (may cause token bloat)")
        print("CONSIDER: cap to 30 most recent messages per chat in format_chat_messages()")
    else:
        print(f"OK — {g['chat_name']}: {count} messages")
```

**If fix needed**, add at the top of `format_chat_messages()`:
```python
MAX_MESSAGES_PER_CHAT = 30
messages = chat_group["messages"][-MAX_MESSAGES_PER_CHAT:]  # keep most recent
```

---

## VERIFICATION SUMMARY

| # | Check | Expected | Result |
|---|-------|----------|--------|
| 1 | `fetch_new_messages()` returns data | ≥ 1 chat group | |
| 2 | Raw message has `body`, `senderName`, `createdAt` | All present | |
| 3 | `format_chat_messages()` shape | `{text, metadata}` with `source: "whatsapp"` | |
| 4 | No "Unknown" senders (or bug #2 fixed) | 0 Unknown entries | |
| 5 | `--run-once whatsapp` no errors | Clean log output | |
| 6 | Watermark updated after run | Recent timestamp | |
| 7 | Qdrant has WhatsApp vectors | ≥ 1 result | |

**Pass threshold:** 7/7 PASS (or SKIP for items dependent on data availability).

**Output:** Report the table above with PASS/FAIL/SKIP for each check.
List any bug fixes applied with file, line number, and change description.

---

## STOP CONDITIONS

1. `fetch_new_messages()` returns error → check Wassenger API key and device ID
2. Pipeline crashes with unhandled exception → log full traceback, attempt fix
3. After 3 fix attempts on same bug → STOP, report to user
4. All 7 checks PASS → proceed to Brief 9C
