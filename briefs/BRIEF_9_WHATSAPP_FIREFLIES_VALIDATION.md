# BRIEF 9 — WhatsApp + Fireflies Live Trigger Validation

**Date:** 2026-02-21
**Layer:** Sentinel (triggers) + Baker (pipeline)
**Priority:** HIGH — Last two untested live data sources before Baker v1 operational
**Predecessor:** Brief 8 (Scan & Contact Search) — PASS

---

## OBJECTIVE

Validate Baker's WhatsApp (Wassenger) and Fireflies (meeting transcript) triggers against
live APIs. Both trigger modules are code-complete but have only been tested with mock data.
This brief connects them to real APIs and verifies the full chain: fetch → format → classify →
pipeline → store-back → alert.

**End state:** Both `whatsapp_poll` and `fireflies_scan` scheduler jobs run against live APIs,
process real data through the pipeline, and produce correct alerts/vectors. All 3 trigger
sources (email, WhatsApp, meetings) are live.

---

## PHASE 0 — Prerequisites Check

### 0a. Verify environment variables

Check that `.env` has all required keys:

```bash
cd 01_build
grep -c "WASSENGER_API_KEY" config/.env
grep -c "WASSENGER_DEVICE_ID" config/.env
grep -c "FIREFLIES_API_KEY" config/.env
```

All three must return `1`. If any returns `0`, STOP and configure.

### 0b. Wassenger device health

```python
import os, httpx
api_key = os.getenv("WASSENGER_API_KEY")
device_id = os.getenv("WASSENGER_DEVICE_ID")
r = httpx.get(
    f"https://api.wassenger.com/v1/devices/{device_id}",
    headers={"Token": api_key},
    timeout=15,
)
print(r.status_code, r.json().get("status"), r.json().get("session", {}).get("status"))
```

Expected: `200`, device status `operative`, session status `online`.
If session is `offline` or `timeout`, check phone — WhatsApp Web may need re-scan.

### 0c. Fireflies API health

```python
import os, httpx
api_key = os.getenv("FIREFLIES_API_KEY")
r = httpx.post(
    "https://api.fireflies.ai/graphql",
    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    json={"query": "{ user { name email } }"},
    timeout=15,
)
print(r.status_code, r.json())
```

Expected: `200`, returns user name and email (Dimitry Vallen / dvallen@brisengroup.com).
If 401, the API key has expired — regenerate at app.fireflies.ai/integrations.

### 0d. Qdrant + PostgreSQL connectivity

```bash
cd 01_build
python -c "
from memory.retriever import SentinelRetriever
r = SentinelRetriever()
print('Qdrant OK:', r.client.get_collections())
"
python -c "
from triggers.state import trigger_state
print('PostgreSQL OK:', trigger_state.get_watermark('whatsapp'))
"
```

### Phase 0 success criteria
- [ ] All 3 env vars present in `.env`
- [ ] Wassenger device `operative` + session `online`
- [ ] Fireflies API returns user profile
- [ ] Qdrant and PostgreSQL reachable

---

## PHASE 1 — WhatsApp Trigger Live Validation

### 1a. Fetch test (API connectivity)

```bash
cd 01_build
python -c "
from triggers.whatsapp_trigger import fetch_new_messages, _get_api_key, _get_device_id
from datetime import datetime, timezone, timedelta

api_key = _get_api_key()
device_id = _get_device_id()
since = datetime.now(timezone.utc) - timedelta(hours=24)

groups = fetch_new_messages(api_key, device_id, since)
print(f'Chat groups: {len(groups)}')
for g in groups[:3]:
    print(f'  {g[\"chat_name\"]}: {len(g[\"messages\"])} messages')
"
```

Expected: Returns chat groups with real messages from the last 24 hours.
If `0 groups`, check Wassenger dashboard — device may have no recent chats.

### 1b. Format test (data shape)

```python
from triggers.whatsapp_trigger import fetch_new_messages, format_chat_messages
from triggers.whatsapp_trigger import _get_api_key, _get_device_id
from datetime import datetime, timezone, timedelta

api_key = _get_api_key()
device_id = _get_device_id()
since = datetime.now(timezone.utc) - timedelta(hours=24)

groups = fetch_new_messages(api_key, device_id, since)
if groups:
    formatted = format_chat_messages(groups[0])
    print("Keys:", list(formatted.keys()))
    print("Metadata source:", formatted["metadata"]["source"])
    print("Text preview:", formatted["text"][:200])
    assert "text" in formatted
    assert "metadata" in formatted
    assert formatted["metadata"]["source"] == "whatsapp"
    print("FORMAT OK")
```

### 1c. Full pipeline run (single chat)

```bash
cd 01_build
python triggers/scheduler.py --run-once whatsapp
```

Check logs for:
- `WhatsApp trigger: X new messages in Y chats`
- `pipeline.run` execution without errors
- `WhatsApp trigger complete: N processed, M queued for briefing`

### 1d. Verify data stores

```sql
-- PostgreSQL: trigger_log
SELECT type, source_id, processed, received_at
FROM trigger_log
WHERE type = 'whatsapp'
ORDER BY received_at DESC
LIMIT 5;

-- PostgreSQL: alerts (if any high/medium priority)
SELECT tier, title, status, created_at
FROM alerts
WHERE title ILIKE '%whatsapp%' OR source_id ILIKE 'wa-%'
ORDER BY created_at DESC
LIMIT 5;
```

```python
# Qdrant: check for new WhatsApp vectors
from memory.retriever import SentinelRetriever
r = SentinelRetriever()
results = r.search("recent WhatsApp message", collections=["baker-whatsapp"])
print(f"WhatsApp vectors found: {len(results)}")
```

### Phase 1 success criteria
- [ ] `fetch_new_messages()` returns real chat groups from Wassenger
- [ ] `format_chat_messages()` produces `{text, metadata}` with `source: "whatsapp"`
- [ ] `--run-once whatsapp` completes without error
- [ ] trigger_log has WhatsApp entries with `processed = true`
- [ ] Qdrant `baker-whatsapp` has new vectors (if messages processed)

---

## PHASE 2 — Fireflies Trigger Live Validation

### 2a. Fetch test (API connectivity)

```bash
cd 01_build
python -c "
from triggers.fireflies_trigger import fetch_new_transcripts
from datetime import datetime, timezone, timedelta

since = datetime.now(timezone.utc) - timedelta(days=30)
transcripts = fetch_new_transcripts(since)
print(f'Transcripts found: {len(transcripts)}')
for t in transcripts[:3]:
    meta = t.get('metadata', {})
    print(f'  {meta.get(\"title\", \"untitled\")} — {meta.get(\"date\", \"no date\")}')
"
```

Expected: Returns transcripts from the last 30 days.
If `0 transcripts`, check Fireflies dashboard — confirm recordings exist.

**Common issue:** `transcript_date()` returns naive datetime, but watermark is timezone-aware.
The trigger code (line 44) already handles this with `.replace(tzinfo=timezone.utc)`.
Verify no `TypeError: can't compare offset-naive and offset-aware datetimes`.

### 2b. Full pipeline run

```bash
cd 01_build
python triggers/scheduler.py --run-once fireflies
```

Check logs for:
- `Fireflies trigger: N new transcripts found`
- Pipeline execution per transcript
- `Fireflies trigger complete: N transcripts processed`

### 2c. Verify data stores

```sql
-- PostgreSQL: trigger_log
SELECT type, source_id, processed, received_at
FROM trigger_log
WHERE type = 'meeting'
ORDER BY received_at DESC
LIMIT 5;

-- PostgreSQL: alerts
SELECT tier, title, status, created_at
FROM alerts
WHERE source_id IN (
    SELECT source_id FROM trigger_log WHERE type = 'meeting'
    ORDER BY received_at DESC LIMIT 5
)
ORDER BY created_at DESC;
```

### 2d. Dedup verification

Run `--run-once fireflies` a second time. The same transcripts should NOT be reprocessed:

```bash
python triggers/scheduler.py --run-once fireflies
# Log should show: "Fireflies trigger: no new transcripts" or skip already-processed IDs
```

### Phase 2 success criteria
- [ ] `fetch_new_transcripts()` returns real transcripts from Fireflies API
- [ ] `--run-once fireflies` processes transcripts without error
- [ ] trigger_log has meeting entries with `processed = true`
- [ ] Second run skips already-processed transcripts (dedup works)

---

## PHASE 3 — Scheduler Integration Test

### 3a. Start scheduler with all triggers

```bash
cd 01_build
python triggers/scheduler.py --list
```

Verify all 4 jobs registered:
- `email_poll` (every 300s)
- `whatsapp_poll` (every 600s)
- `fireflies_scan` (every 7200s)
- `daily_briefing` (at 06:00 UTC)

### 3b. Run scheduler for 12 minutes

```bash
python triggers/scheduler.py
# Wait ~12 minutes, then Ctrl+C
```

During this window:
- `email_poll` should fire at least twice (300s interval)
- `whatsapp_poll` should fire at least once (600s interval)
- `fireflies_scan` will NOT fire (7200s interval) — that's expected

Check logs for:
- No crashes or unhandled exceptions
- No auth errors (token expiry, rate limits)
- Clean `Scheduler shutdown requested` → `Scheduler stopped` on Ctrl+C

### 3c. Cross-trigger watermark integrity

After scheduler run, verify watermarks are independent:

```python
from triggers.state import trigger_state
for source in ["email", "whatsapp", "fireflies"]:
    wm = trigger_state.get_watermark(source)
    print(f"{source}: {wm.isoformat()}")
```

Each should have a different, recent timestamp. No watermark should be reset to epoch.

### Phase 3 success criteria
- [ ] All 4 jobs registered correctly
- [ ] Scheduler runs 12 min with no crashes
- [ ] Each trigger fires on schedule
- [ ] Graceful shutdown works (no orphan processes)
- [ ] Watermarks are independent and correct

---

## PHASE 4 — Bug Fix Pass

Known issues to check during validation:

| # | Issue | Where | Symptom | Fix |
|---|-------|-------|---------|-----|
| 1 | Wassenger API returns paginated results | `whatsapp_trigger.py:60` | Missing chats if >50 active | Add pagination loop or increase `size` param |
| 2 | `senderName` null for some messages | `whatsapp_trigger.py:123` | Shows "Unknown" instead of contact name | Fallback to `chat_name` when `senderName` is null |
| 3 | Fireflies `transcript_date()` format mismatch | `fireflies_trigger.py:44` | TypeError on date comparison | Already handled — verify in live run |
| 4 | WhatsApp group messages flood pipeline | `whatsapp_trigger.py:186` | 50+ messages in active group → token bloat | Add max token check or message count cap per chat |
| 5 | Fireflies rate limit (100 req/min) | `fireflies_trigger.py:33` | 429 errors on large backlog | Add retry with backoff |
| 6 | Wassenger auth header format | `whatsapp_trigger.py:49` | `Token` vs `Authorization: Bearer` | Verify against Wassenger API docs — current `Token` header is correct per docs |

**Action:** During Phase 1-2, log any additional bugs found. Fix before proceeding to Phase 3.

---

## SUMMARY

| Phase | What | Checks |
|-------|------|--------|
| 0 | Prerequisites (env, device, API health) | 4 |
| 1 | WhatsApp trigger live validation | 5 |
| 2 | Fireflies trigger live validation | 4 |
| 3 | Scheduler integration test | 5 |
| 4 | Bug fix pass | — (fix as found) |
| **Total** | | **18** |

**Success:** 18/18 PASS, 0 FAIL. If WhatsApp has no recent messages or Fireflies has no
recent transcripts, those fetch tests can SKIP (but pipeline and store tests must still pass
with whatever data is available).

---

## HUMAN GATES

### Wassenger device offline
If Phase 0b shows session `offline`, Dimitry must:
1. Open WhatsApp on phone
2. Go to Linked Devices → Wassenger
3. Re-scan QR code if disconnected

### Fireflies API key expired
If Phase 0c returns 401, Dimitry must:
1. Go to app.fireflies.ai → Integrations → API key
2. Generate new key
3. Update `FIREFLIES_API_KEY` in `config/.env`

### No recent data
If both WhatsApp and Fireflies have zero new data in the last 30 days, validation cannot
be fully completed. In that case:
- Send a test WhatsApp message to the linked number
- Record or upload a test meeting to Fireflies
- Re-run the relevant phase

---

## FILES TOUCHED

| File | Change |
|------|--------|
| `triggers/whatsapp_trigger.py` | Bug fixes from Phase 4 (if any) |
| `triggers/fireflies_trigger.py` | Bug fixes from Phase 4 (if any) |
| `config/.env` | Verify env vars present |
| `config/whatsapp_poll_state.json` | Auto-updated (watermark) |
| `config/fireflies_poll_state.json` | Auto-updated (watermark) |

---

## DEPENDENCIES

- Phase 0 has no code dependencies (env check only)
- Phases 1-2 depend on Phase 0 passing
- Phase 3 depends on Phases 1-2 (both triggers must work individually before scheduler test)
- Phase 4 runs in parallel with Phases 1-2 (fix bugs as found)

---

## WHAT THIS UNLOCKS

With Brief 9 complete, all three live data sources are validated:
- **Email** (Brief 7) ✓
- **WhatsApp** (Brief 9 Phase 1) ✓
- **Fireflies** (Brief 9 Phase 2) ✓

Next priorities from Blueprint:
1. **Qdrant migration** — AWS → Azure EU (compliance + latency)
2. **Azure deployment** — containerize Sentinel for always-on operation
3. **Onboarding briefing completion** — Sections 3, 5, 6, 7 still empty
4. **Role-based categories** — expand beyond current classification
