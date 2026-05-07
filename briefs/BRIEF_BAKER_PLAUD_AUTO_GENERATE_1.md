# BRIEF: BAKER_PLAUD_AUTO_GENERATE_1 — Baker triggers Plaud auto-generation for stuck recordings

## Context

Plaud's web app, mobile app, desktop app, and REST API all separate **upload** from **generate transcript**. A recording uploaded by the Plaud Note Pro device, the iOS app, or the Plaud Desktop app (which captures Zoom / Teams / Meet system audio via macOS ScreenCaptureKit) lands at `is_trans=False, is_summary=False` and stays there indefinitely until someone manually clicks the per-file **Generate** button + confirms the **Generate now** modal in Plaud Web.

This produced a **25-day silent failure** between 2026-04-12 and 2026-05-07: 10 of Director's recordings (including the 165-min 2026-04-27 strategy meeting) sat un-transcribed. Baker had no signal — `is_trans=False` was treated as "still processing", not "blocked waiting for click". Recovery (2026-05-07) required manually clicking Generate on each file via Chrome MCP automation.

PR #168 (merged `8641a11a` 2026-05-07) shipped the **preventive Baker side**: stale-refresh lane re-ingests once `is_trans` flips True, alarm dedup avoids cockpit flooding, advisory lock prevents Render multi-instance Qdrant doubles. Those land transcripts AFTER Plaud generates — they don't trigger the generation.

**Cowork-verified 2026-05-07:** no account-level "auto-generate transcript on upload" toggle exists in Plaud Desktop (General / Recording / Private Cloud Sync / About), Plaud Web (Settings → Workspace → Preferences / Personalization / Notifications), or any discoverable Plaud REST endpoint. The Plaud Subscription tier is **Unlimited** (credits are not the issue).

This brief eliminates the manual click. Baker poller calls Plaud's auto-generate endpoint for any `is_trans=False` recording older than the dedup threshold, exactly once per `file_id`. Existing PR #168 stale-refresh lane lands the transcript on the next 15-min poll cycle.

---

## Estimated time: ~4-6 hours
## Complexity: Medium (Tier-A: external API integration + new poller surface area + sentinel)
## Prerequisites: PR #168 (`8641a11a`) on main — depended on for `_maybe_report_empty_body_alarm` dedup helper + `trigger_state.is_processed` synthetic-key pattern.

---

## Step 0 (BUILD-PHASE — MUST complete before writing implementation)

### Discover the exact Plaud auto-generate endpoint

AH1-T probed Plaud REST API and confirmed three PATCH endpoints exist (`/file/auto_setting`, `/file/auto`, `/file/setting`) — all `OPTIONS` returns `Allow: PATCH`. Body shape is unknown — empty body returns `{"status":-1,"msg":"file not found"}` even with valid `file_id` field, suggesting the field name or request format differs.

**B-code: discover the exact endpoint URL + verb + body + headers via one of three paths (in order of preference):**

**Path A — CDP network capture on a fresh stuck recording (preferred):**
1. List Plaud files: `curl -H "Authorization: Bearer $PLAUD_TOKEN" https://api-euc1.plaud.ai/file/simple/web?page=1&size=20 | jq '.data_file_list[] | select(.is_trans==false) | .id'`
2. If no `is_trans=False` files exist (Director may have caught up), wait for the next Director recording — typically <24h cadence.
3. Get the always-on Chrome's Plaud page WebSocket URL: `curl -s http://localhost:9222/json/list | jq '.[] | select(.url | contains("plaud.ai")) | .webSocketDebuggerUrl'` (or open one).
4. Connect via Python `websocket-client`, enable `Network.enable`, navigate to `https://web.plaud.ai/file/<stuck_file_id>`, dispatch click on the "Generate" button (text-match) + "Generate now" in modal, capture all `Network.requestWillBeSent` events to `api-euc1.plaud.ai/file/*` for 6 seconds.
5. Record the captured request: URL, HTTP verb, full `postData`, headers (`Authorization`, `Content-Type`, any `X-*`).
6. Verify with a second click on a different stuck file — the captured request must reproduce.

Reference implementation pattern AH1-T already attempted (use as starting point, adjust as needed):
```python
import json, websocket, time
ws = websocket.create_connection("ws://localhost:9222/devtools/page/<page_id>", timeout=15)
def cmd(m, p=None):
    msg = {"id": cmd.i, "method": m}
    if p: msg["params"] = p
    cmd.i += 1
    ws.send(json.dumps(msg))
    while True:
        ws.settimeout(8)
        r = json.loads(ws.recv())
        if r.get("id") == msg["id"]: return r
cmd.i = 1
cmd("Network.enable")
# ... navigate + click via Runtime.evaluate ...
# ... capture Network.requestWillBeSent events ...
```

**Path B — SPA bundle reverse (fallback if no fresh stuck recording):**
1. Download root SPA: `curl -s https://web.plaud.ai/ | grep -oE 'src="[^"]*\.js"'` → root chunk URL
2. Download all linked chunk files (`vendors-*.chunk.js`, `pages-*.chunk.js`, `file-*.chunk.js`)
3. For each chunk: `LC_ALL=C grep -aoE '"/file/[a-zA-Z_/-]+"' <chunk>` to find quoted endpoint paths
4. Locate the chunk containing `auto_setting` references; read surrounding code for verb + body shape (axios/fetch call signature)
5. Validate by calling the discovered endpoint with the exact body shape against a stuck `file_id`

**Path C — mitmproxy on Director's device (last resort, requires Director coordination):**
1. Install `mitmproxy` on the MacBook
2. Configure system proxy or Plaud Desktop app proxy
3. Click Generate in Plaud Desktop on a stuck file
4. Capture the request — Plaud Desktop should hit the same REST endpoint as the web app

**Acceptance for Step 0:** B-code records discovered endpoint + body shape in the ship report under §"Plaud auto-generate endpoint contract". The test suite (Step 4) mocks this exact request shape. Implementation (Step 1+) calls this exact request shape.

---

## Fix 1: `_request_auto_generate(file_id)` helper

### Problem
Baker has no function that triggers Plaud-side transcription for a `is_trans=False` recording. Existing `_plaud_api(path, timeout)` only does GET.

### Implementation

Add to `triggers/plaud_trigger.py` near the existing `_plaud_api` helper (around line 40-70). Use the **exact endpoint contract discovered in Step 0** — placeholders below assume the dispatch's best guess (`PATCH /file/auto_setting` body `{"file_id": <id>, "auto_mode": true}`); B-code substitutes the real values:

```python
def _request_auto_generate(file_id: str) -> bool:
    """Request Plaud-side auto-generation of transcript+summary for a stuck recording.

    Plaud separates upload (cloud sync) from transcription (manual Generate click).
    This helper triggers Plaud's auto-generate pipeline for the specified file_id;
    the existing 15-min poll then ingests via PR #168's stale-refresh lane once
    is_trans flips True.

    Returns True if Plaud accepted the request (HTTP 2xx + status 0 in body),
    False on any failure. Failures are logged + reported via sentinel.
    """
    if not file_id:
        return False

    domain = config.plaud.api_domain
    if not domain:
        return False

    headers = _plaud_headers()
    url = f"{domain}/file/auto_setting"  # <-- replace with Step-0-verified endpoint
    body = {"file_id": file_id, "auto_mode": True}  # <-- replace with Step-0-verified body shape

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.patch(url, json=body, headers=headers)
    except Exception as e:
        logger.warning(f"Plaud auto-generate request failed for {file_id}: {e}")
        return False

    if resp.status_code != 200:
        logger.warning(
            f"Plaud auto-generate {file_id}: HTTP {resp.status_code} body={resp.text[:200]}"
        )
        return False

    try:
        payload = resp.json()
    except Exception:
        return False

    if payload.get("status") != 0:
        logger.warning(
            f"Plaud auto-generate {file_id} rejected: status={payload.get('status')} msg={payload.get('msg','')[:200]}"
        )
        return False

    logger.info(f"Plaud auto-generate {file_id} accepted")
    return True
```

### Key constraints
- **15-second timeout** — Plaud API normally responds in <2s; cap protects scheduler
- **Fail soft** — return False on any error path, never raise; the 15-min poller must continue for other files
- **No retry inside helper** — single attempt; the 15-min poll cadence IS the retry mechanism (next cycle re-evaluates)
- **No sensitive logging** — never log the auth token; status + msg only

### Verification
B-code confirms: helper returns True for one stuck file, files transition `is_trans=False → True` within 5 minutes (Plaud queue typical), Director sees the recording transcribed without manual intervention.

---

## Fix 2: Modify `check_new_plaud_recordings()` to auto-request stale recordings

### Problem
Current loop at `triggers/plaud_trigger.py` line 297-302 reads:
```python
for rec in recordings:
    if not rec.get("is_trans"):
        continue  # Skip recordings still being transcribed
    rec_date = _recording_date(rec)
    if rec_date and rec_date > watermark:
        new_recordings.append(rec)
```

The `continue` silently abandons stuck files forever.

### Implementation

Replace the loop body to detect stale stuck recordings, request auto-generate for them (once per file_id), and continue skipping the iteration (the next 15-min cycle picks up the now-`is_trans=True` file via existing path):

```python
# Configurable in config/settings.py (defaults below)
PLAUD_AUTO_GENERATE_AGE_MIN = int(os.environ.get("PLAUD_AUTO_GENERATE_AGE_MIN", "30"))

# ... inside check_new_plaud_recordings() ...
for rec in recordings:
    if not rec.get("is_trans"):
        # Recording still un-transcribed Plaud-side. If it's old enough (>= threshold),
        # it's likely stuck waiting for manual Generate — request auto-generate once.
        file_id = _recording_id(rec)
        if not file_id:
            continue
        rec_date = _recording_date(rec)
        if not rec_date:
            continue
        age_min = (datetime.now(timezone.utc) - rec_date).total_seconds() / 60.0
        if age_min < PLAUD_AUTO_GENERATE_AGE_MIN:
            continue  # too fresh — Plaud may still be in normal queue

        # Dedup: don't re-request same file_id (mirrors PR #168 _maybe_report_empty_body_alarm pattern)
        dedup_key = f"plaud_auto_request_{file_id}"
        if trigger_state.is_processed("meeting", dedup_key):
            continue

        # Request auto-generate (single attempt, fail soft)
        if _request_auto_generate(file_id):
            trigger_state.mark_processed("meeting", dedup_key)
            logger.info(f"Plaud auto-generate requested for stale recording {file_id} (age={age_min:.0f}min)")
        else:
            # Sentinel — surface stuck-recording requests that Plaud rejects.
            # Use existing dedup helper to avoid alarm-flood.
            try:
                _maybe_report_empty_body_alarm(file_id, rec, formatted=None)  # adapt or new helper
            except Exception:
                pass
        continue  # Always continue — next poll cycle picks up the file once is_trans flips

    # is_trans=True path — unchanged
    rec_date = _recording_date(rec)
    if rec_date and rec_date > watermark:
        new_recordings.append(rec)
```

### Key constraints
- **Age threshold gates the call** — fresh uploads (<30min) skip the auto-generate request to avoid hammering Plaud's queue during normal user-initiated transcription
- **Dedup is mandatory** — without it, every 15-min poll re-fires the request for the same file_id forever (cockpit flood + Plaud rate limit risk)
- **Sentinel on rejection** — Plaud rejecting an auto-generate request (e.g., 429, 5xx, account quota hit) MUST surface in cockpit via `_maybe_report_empty_body_alarm` or equivalent; alarm dedup is per-day per-file_id (PR #168 pattern)
- **No effect on existing is_trans=True path** — only the un-transcribed branch changes; happy path unchanged

### Verification
1. Plant a fresh `is_trans=False` recording older than 30 min in test (mock `fetch_plaud_recordings`).
2. Run `check_new_plaud_recordings()` once → assert `_request_auto_generate(file_id)` called exactly once.
3. Run again on same listing → assert `_request_auto_generate` NOT called again (dedup hit).
4. After mock flips to `is_trans=True`, run again → assert recording ingested via existing happy path.

---

## Fix 3: Mirror change in `backfill_plaud()`

### Problem
`backfill_plaud()` at line 519+ has its own loop. Without the same auto-generate logic, Render restart (which runs backfill once on boot) skips stuck files silently — the next incremental poll catches it 15 min later, but boot-time restart wastes 15 min if the recording was already stale at startup.

### Implementation
Apply the SAME stale-detection-and-auto-request logic as Fix 2 inside `backfill_plaud()`. Use the same `_request_auto_generate` helper + same `plaud_auto_request_<file_id>` dedup key.

Important: backfill respects the `is_trans` filter added in PR #168 (line 519+ in post-merge HEAD). Do NOT remove that filter — append the auto-generate check BEFORE the filter:

```python
# inside backfill_plaud() loop
for rec in recordings:
    file_id = _recording_id(rec)
    if not file_id:
        continue

    if not rec.get("is_trans"):
        # Same auto-generate logic as Fix 2
        rec_date = _recording_date(rec)
        if rec_date:
            age_min = (datetime.now(timezone.utc) - rec_date).total_seconds() / 60.0
            if age_min >= PLAUD_AUTO_GENERATE_AGE_MIN:
                dedup_key = f"plaud_auto_request_{file_id}"
                if not trigger_state.is_processed("meeting", dedup_key):
                    if _request_auto_generate(file_id):
                        trigger_state.mark_processed("meeting", dedup_key)
        continue  # backfill always skips un-transcribed (PR #168 invariant)

    # rest unchanged — happy path
    source_id = f"plaud_{file_id}"
    if trigger_state.is_processed("meeting", source_id):
        continue
    # ...
```

### Key constraints
- DO NOT remove or weaken PR #168's `is_trans` filter. The auto-generate request is ADDITIVE: trigger Plaud server-side, then skip locally as before.
- Backfill runs under `pg_try_advisory_lock(867532)` — auto-generate requests inside that lock are fine (single-instance), no extra synchronization needed.

### Verification
Mock `fetch_plaud_recordings` returning 2 stuck + 1 done files; run `backfill_plaud()`; assert auto-generate called twice (one per stuck file_id) and exactly the 1 done file ingested.

---

## Fix 4: Config + env var

### Implementation
Add to `config/settings.py` near the existing `PlaudConfig` class:

```python
class PlaudConfig:
    # ... existing fields ...
    auto_generate_age_min: int = 30  # threshold in minutes; 0 disables auto-generate
```

Read from env var `PLAUD_AUTO_GENERATE_AGE_MIN` if set; default 30. Setting to 0 disables the feature (kill switch).

Add to `.env.example` (if it exists):
```
PLAUD_AUTO_GENERATE_AGE_MIN=30
```

### Key constraints
- Kill switch: setting env to 0 must completely disable auto-generate calls (defensive for Plaud API change / outage scenarios)
- Default 30 — half the 15-min poll cadence × 2 cycles; recordings stuck > 30 min are confidently abandoned by Plaud's normal flow

---

## Fix 5: Tests

### Implementation
Add to `tests/test_plaud_trigger.py`:

```python
def test_request_auto_generate_success():
    """Plaud accepts the request — helper returns True."""
    # mock httpx.Client.patch → returns 200 + {"status": 0, ...}
    # call _request_auto_generate("test_file_id")
    # assert returns True; assert exactly one PATCH call to /file/auto_setting; assert auth header present

def test_request_auto_generate_failure_logs_and_returns_false():
    """Plaud returns 500 — helper returns False, no exception, log captured."""
    # mock httpx returns 500
    # capture logs
    # assert returns False; warning log contains "auto-generate" and HTTP code; no token in log

def test_check_new_plaud_recordings_requests_auto_generate_once_for_stale():
    """Stale is_trans=False recording → auto-generate fires once + dedup blocks repeat."""
    # mock fetch_plaud_recordings returns 1 stuck file (age 60 min)
    # mock _request_auto_generate
    # mock trigger_state.is_processed → False initially, then True after mark_processed
    # call check_new_plaud_recordings() twice
    # assert _request_auto_generate called exactly once; assert mark_processed called with dedup key

def test_fresh_recording_below_age_threshold_skipped():
    """is_trans=False recording <30 min old → no auto-generate call."""
    # mock fetch_plaud_recordings returns 1 fresh stuck file (age 10 min)
    # call check_new_plaud_recordings()
    # assert _request_auto_generate NOT called

def test_kill_switch_zero_age_disables():
    """PLAUD_AUTO_GENERATE_AGE_MIN=0 → auto-generate never fires."""
    # set env / config to 0
    # mock 1 very old stuck file (age 24h)
    # call check_new_plaud_recordings()
    # assert _request_auto_generate NOT called

def test_backfill_path_also_requests_auto_generate():
    """backfill_plaud() handles stale stuck files identically to incremental."""
    # mock fetch_plaud_recordings returns 1 stuck (60 min) + 1 done file
    # call backfill_plaud()
    # assert _request_auto_generate called once for stuck file_id
    # assert done file ingested via store.store_meeting_transcript
```

### Key constraints
- All tests mock `httpx.Client` — never hit Plaud production API
- All tests mock `trigger_state` — never hit PostgreSQL
- All tests assert log content does NOT contain the auth token (security)
- Use `caplog` fixture for log capture (matches existing test_plaud_trigger.py pattern from PR #168)
- Run literal: `pytest tests/test_plaud_trigger.py -v` GREEN — no by-inspection (Lesson #52)

---

## Files Modified
- `triggers/plaud_trigger.py` — add `_request_auto_generate(file_id)`; modify `check_new_plaud_recordings()` loop (line ~297) + `backfill_plaud()` loop (line ~519)
- `config/settings.py` — add `auto_generate_age_min` to `PlaudConfig` + read env var
- `tests/test_plaud_trigger.py` — add 6 new tests
- `.env.example` (if it exists) — add `PLAUD_AUTO_GENERATE_AGE_MIN=30`

## Do NOT Touch
- PR #168 logic: `_maybe_report_empty_body_alarm`, `_stale_refresh_advisory_lock`, the `is_trans` filter at line 519+ — all stay as-is, this brief is ADDITIVE
- Existing `_plaud_api` GET helper signature
- `fetch_plaud_recordings` / `fetch_plaud_detail` / `format_plaud_transcript` — no change needed
- `meeting_transcripts` table schema — no migration

## Quality Checkpoints
1. Step 0 endpoint discovery: B-code captures real Plaud auto-generate request and records URL/verb/body/headers in ship report
2. `_request_auto_generate` returns True for one Director recording (live test on next stuck file)
3. Single auto-generate call per file_id per Render lifetime — verified by mocking 5 consecutive `check_new_plaud_recordings()` runs
4. Sentinel fires loud (cockpit Slack) on Plaud rejection — verified via mock 500 response
5. `pytest tests/test_plaud_trigger.py -v` literal GREEN — all 6 new tests pass + existing 7/7 PR #168 tests still pass
6. Full pytest suite GREEN — no regressions
7. Render deploy live + scheduler runs `check_new_plaud_recordings` → log line `Plaud auto-generate requested for stale recording <id>` appears
8. Director records a new Zoom call → Baker auto-fires Plaud Generate → recording transcribed without Director clicking anything

## Verification SQL

```sql
-- Confirm auto-generate dedup row landed in trigger_log for a real file_id (post-deploy)
SELECT source, source_id, processed_at
FROM trigger_log
WHERE source_id LIKE 'plaud_auto_request_%'
ORDER BY processed_at DESC
LIMIT 10;

-- Confirm subsequent transcript ingestion landed for the same file_id
SELECT source, source_id, length(full_transcript) AS body_chars, ingested_at
FROM meeting_transcripts
WHERE source = 'plaud'
  AND source_id IN (
    SELECT REPLACE(source_id, 'plaud_auto_request_', 'plaud_')
    FROM trigger_log
    WHERE source_id LIKE 'plaud_auto_request_%'
  )
ORDER BY ingested_at DESC
LIMIT 10;
```

Both queries should return rows after the first auto-generate cycle completes (typically within 15-30 min of deploy on a stuck recording).

## Director ratification anchors
- **2026-05-07 (current session):** Director ratified "follow your recoms" + asked AH1-T to "do" the brief. Cowork (Director-relay) verified Plaud Desktop has no account-level auto-generate toggle (General/Recording/Private Cloud Sync/About). AH1-T probed Plaud REST API and confirmed `/file/auto_setting`, `/file/auto`, `/file/setting` are PATCH endpoints — exact body shape pending Step 0 discovery.
- **PR #168 (`8641a11a`):** dependency — alarm dedup helper + advisory lock + stale-refresh lane all referenced.

## PL ship-report
End your chat ship report with the fenced PL paste-block per `_ops/skills/ai-head/SKILL.md` §"PL ship-report contract".
