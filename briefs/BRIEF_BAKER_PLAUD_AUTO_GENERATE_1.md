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

Reference implementation pattern (TWO-CHANNEL — CRITICAL: do NOT use a single-loop `cmd()` that drops events while waiting for a response.id match. Async `Network.requestWillBeSent` events arrive interleaved with command responses; the single-loop pattern silently discards them and Path A produces zero captures):
```python
import json, threading, websocket, time

ws = websocket.create_connection("ws://localhost:9222/devtools/page/<page_id>", timeout=15)
ws.settimeout(0.25)

_responses = {}        # id -> response payload
_events = []           # list of {"method": ..., "params": ...}
_next_id = [1]
_stop = threading.Event()

def _pump():
    while not _stop.is_set():
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue
        except Exception:
            return
        msg = json.loads(raw)
        if "id" in msg:
            _responses[msg["id"]] = msg
        elif "method" in msg:
            _events.append(msg)

t = threading.Thread(target=_pump, daemon=True); t.start()

def cmd(method, params=None, timeout=8.0):
    mid = _next_id[0]; _next_id[0] += 1
    payload = {"id": mid, "method": method}
    if params: payload["params"] = params
    ws.send(json.dumps(payload))
    deadline = time.time() + timeout
    while time.time() < deadline:
        if mid in _responses: return _responses.pop(mid)
        time.sleep(0.05)
    raise TimeoutError(f"CDP {method} timed out")

def drain_events(seconds: float):
    """Block for `seconds`, then return events captured during that window."""
    end = time.time() + seconds
    while time.time() < end: time.sleep(0.05)
    captured = list(_events)
    _events.clear()
    return captured

cmd("Network.enable")
cmd("Page.navigate", {"url": f"https://web.plaud.ai/file/{stuck_file_id}"})
time.sleep(2.0)  # allow SPA route mount
cmd("Runtime.evaluate", {"expression": "<JS click sequence Generate → Generate now>"})
captures = drain_events(6.0)
auto_gen = [e for e in captures
            if e.get("method") == "Network.requestWillBeSent"
            and "/file/" in e["params"]["request"]["url"]]

_stop.set(); ws.close()
```

Why two channels: responses and events share one socket but have different consumers. `pump` thread routes by structure (id → responses dict, method → events list). `cmd()` polls the dict for its own id; `drain_events()` reads the list. No event is ever discarded.

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

**Path D — escape hatch (if A + B + C all fail):**
STOP. Do NOT guess endpoint contract. Bus-post to `/msg/cowork-ah1` with topic `plaud-auto-generate/path-d-blocked` reporting which paths were attempted + their failure modes. Mark this brief as BLOCKED pending: (a) Director-coordinated mitmproxy session OR (b) Plaud support ticket request for the auto-generate REST contract. Implementation Fixes 1-5 do NOT proceed with placeholder values — silent failure on a wrong endpoint is the original 25-day bug repeated.

**Acceptance for Step 0:** B-code records discovered endpoint + body shape in the ship report under §"Plaud auto-generate endpoint contract". The test suite (Step 4) mocks this exact request shape. Implementation (Step 1+) calls this exact request shape. If Path D fires, ship report instead documents the failure path under §"Step 0 BLOCKED" and brief halts.

---

## Fix 1: `_request_auto_generate(file_id)` helper

### Problem
Baker has no function that triggers Plaud-side transcription for a `is_trans=False` recording. Existing `_plaud_api(path, timeout)` only does GET.

### Implementation

Add to `triggers/plaud_trigger.py` near the existing `_plaud_api` helper (around line 40-70). Use the **exact endpoint contract discovered in Step 0** — placeholders below assume the dispatch's best guess (`PATCH /file/auto_setting` body `{"file_id": <id>, "auto_mode": true}`); B-code substitutes the real values:

```python
# Module-level circuit breaker state (lives in triggers/plaud_trigger.py)
# Reset on any successful auto-generate or after cooldown window expires.
_AUTO_GEN_FAIL_COUNT = 0
_AUTO_GEN_BREAKER_OPEN_UNTIL = 0.0  # epoch seconds
_AUTO_GEN_BREAKER_THRESHOLD = 5     # consecutive failures before tripping
_AUTO_GEN_BREAKER_COOLDOWN_SEC = 1800  # 30 min after trip — auto-generate calls suppressed

def _request_auto_generate(file_id: str) -> bool:
    """Request Plaud-side auto-generation of transcript+summary for a stuck recording.

    Plaud separates upload (cloud sync) from transcription (manual Generate click).
    This helper triggers Plaud's auto-generate pipeline for the specified file_id;
    the existing 15-min poll then ingests via PR #168's stale-refresh lane once
    is_trans flips True.

    Returns True if Plaud accepted the request (HTTP 2xx + status 0 in body) OR
    if Plaud reports the file is already transcribed (treated as success-equivalent;
    the next poll cycle ingests the body via the existing happy path).
    Returns False on any failure. Failures are logged + reported via sentinel by callers.
    """
    import httpx  # per-function import — module pattern matches _plaud_api (line ~43)
    import time
    global _AUTO_GEN_FAIL_COUNT, _AUTO_GEN_BREAKER_OPEN_UNTIL

    if not file_id:
        return False

    # Circuit breaker: if open, suppress the call entirely. Do NOT re-attempt during cooldown.
    if time.time() < _AUTO_GEN_BREAKER_OPEN_UNTIL:
        logger.info(f"Plaud auto-generate breaker OPEN — skipping {file_id}")
        return False

    domain = config.plaud.api_domain
    if not domain:
        return False

    headers = _plaud_headers()
    if not headers:
        # PLAUD_TOKEN missing — _plaud_headers() returns {}. Without this guard the PATCH fires
        # unauthenticated and gets 401 every cycle indefinitely (H3 fold).
        logger.warning("Plaud auto-generate skipped: no auth headers (PLAUD_TOKEN missing)")
        return False

    url = f"{domain}/file/auto_setting"  # <-- replace with Step-0-verified endpoint
    body = {"file_id": file_id, "auto_mode": True}  # <-- replace with Step-0-verified body shape

    def _trip_breaker_on_fail():
        global _AUTO_GEN_FAIL_COUNT, _AUTO_GEN_BREAKER_OPEN_UNTIL
        _AUTO_GEN_FAIL_COUNT += 1
        if _AUTO_GEN_FAIL_COUNT >= _AUTO_GEN_BREAKER_THRESHOLD:
            _AUTO_GEN_BREAKER_OPEN_UNTIL = time.time() + _AUTO_GEN_BREAKER_COOLDOWN_SEC
            logger.error(
                f"Plaud auto-generate breaker TRIPPED after {_AUTO_GEN_FAIL_COUNT} consecutive "
                f"failures — suppressing calls for {_AUTO_GEN_BREAKER_COOLDOWN_SEC // 60} min"
            )

    def _reset_breaker():
        global _AUTO_GEN_FAIL_COUNT, _AUTO_GEN_BREAKER_OPEN_UNTIL
        _AUTO_GEN_FAIL_COUNT = 0
        _AUTO_GEN_BREAKER_OPEN_UNTIL = 0.0

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.patch(url, json=body, headers=headers)
    except Exception as e:
        logger.warning(f"Plaud auto-generate request failed for {file_id}: {e}")
        _trip_breaker_on_fail()
        return False

    if resp.status_code != 200:
        logger.warning(
            f"Plaud auto-generate {file_id}: HTTP {resp.status_code} body={resp.text[:200]}"
        )
        _trip_breaker_on_fail()
        return False

    try:
        payload = resp.json()
    except Exception:
        _trip_breaker_on_fail()
        return False

    status = payload.get("status")
    msg = (payload.get("msg") or "")[:200]

    # M1 race: if Plaud reports already-transcribed (status code TBD by Step 0 — replace constant),
    # treat as success-equivalent. The next 15-min poll's existing happy path ingests the body.
    if status == 0:
        logger.info(f"Plaud auto-generate {file_id} accepted")
        _reset_breaker()
        return True
    if "already" in msg.lower() and ("trans" in msg.lower() or "complete" in msg.lower()):
        logger.info(f"Plaud auto-generate {file_id} already-transcribed — success-equivalent")
        _reset_breaker()
        return True

    logger.warning(f"Plaud auto-generate {file_id} rejected: status={status} msg={msg}")
    _trip_breaker_on_fail()
    return False
```

### Key constraints
- **15-second timeout** — Plaud API normally responds in <2s; cap protects scheduler
- **Fail soft** — return False on any error path, never raise; the 15-min poller must continue for other files
- **No retry inside helper** — single attempt; the 15-min poll cadence IS the retry mechanism (next cycle re-evaluates) UNLESS the circuit breaker is open
- **Circuit breaker (G3-IMP1 fold)** — 5 consecutive failures opens a 30-min cooldown window during which all auto-generate calls are suppressed. Protects against cycle-after-cycle PATCH bombardment when Plaud API itself is down
- **Empty-headers guard (H3 fold)** — `if not headers: return False` after `_plaud_headers()` prevents unauthenticated 401 hammering when `PLAUD_TOKEN` is unset
- **httpx import is per-function (H2 fold)** — matches `_plaud_api` module pattern; first line inside function body
- **No sensitive logging** — never log the auth token; status + msg only
- **is_trans race success-equivalent (M1 fold)** — if Plaud responds with "already transcribed" between the file-list snapshot and the PATCH, the helper returns True so callers `mark_processed` and skip the alarm path

### Verification
B-code confirms: helper returns True for one stuck file, files transition `is_trans=False → True` within 5 minutes (Plaud queue typical), Director sees the recording transcribed without manual intervention.

---

## Fix 2: Extract `_maybe_request_auto_generate_for_stale(rec)` + call from `check_new_plaud_recordings()`

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

The `continue` silently abandons stuck files forever. Fix 3 (`backfill_plaud()`) needs the same logic; duplicating ~25 lines across both call sites guarantees future drift (G3-IMP3).

### Implementation — single helper called from both Fix 2 and Fix 3

Add this helper next to `_request_auto_generate` in `triggers/plaud_trigger.py`. Both incremental and backfill paths call this one function — no duplication, no drift:

```python
# Per-cycle rate cap (G3-suggestions): hard upper bound on auto-generate PATCHes per cycle.
# Defends against a sudden surge of stuck files (e.g., post-outage backlog) hammering Plaud.
_PLAUD_AUTO_GEN_MAX_PER_CYCLE = 10

# Cycle-scoped counter — caller resets to 0 at the start of each check_new / backfill loop.
_auto_gen_calls_this_cycle = {"count": 0}

def _reset_auto_gen_cycle_counter():
    _auto_gen_calls_this_cycle["count"] = 0

def _maybe_request_auto_generate_for_stale(rec: dict) -> None:
    """Detect a stale is_trans=False recording and request auto-generation exactly once.

    Single source of truth for the stale-recording auto-generate path; called from
    both check_new_plaud_recordings() and backfill_plaud(). Idempotent + fail-soft.

    Side effects:
      - On Plaud accept: mark_processed(plaud_auto_request_<file_id>) → no future re-fire
      - On Plaud reject: report_failure(...) with per-day dedup → cockpit sees ONE alarm/day
      - On rejection: NO mark_processed — the next 15-min cycle re-attempts (this is the
        retry mechanism; dedup must NOT short-circuit retries)
    """
    import time
    from datetime import datetime, timezone

    file_id = _recording_id(rec)
    if not file_id:
        return

    # Read config inside function — config is the single source of truth (H1 fold).
    age_threshold = config.plaud.auto_generate_age_min

    # Kill switch (C1 fold): threshold == 0 disables the feature entirely.
    # Must be checked BEFORE the age comparison; otherwise `age_min < 0` is always False
    # and every is_trans=False file fires PATCH.
    if age_threshold == 0:
        return

    rec_date = _recording_date(rec)
    if not rec_date:
        # M2 fold: log warning so silent permanent skips are visible — do not fail loud.
        logger.warning(f"plaud rec missing date — skipping auto-generate file_id={file_id}")
        return

    age_min = (datetime.now(timezone.utc) - rec_date).total_seconds() / 60.0
    if age_min < age_threshold:
        return  # too fresh — Plaud may still be in normal queue

    # Per-cycle rate cap (G3-suggestions): never fire more than N per cycle.
    if _auto_gen_calls_this_cycle["count"] >= _PLAUD_AUTO_GEN_MAX_PER_CYCLE:
        logger.info(f"plaud auto-generate cycle cap hit ({_PLAUD_AUTO_GEN_MAX_PER_CYCLE}) — deferring {file_id}")
        return

    # Dedup: only mark_processed on SUCCESS (G3-CRIT prose below). On Plaud reject,
    # the dedup row is NOT written, and the next 15-min cycle re-attempts.
    dedup_key = f"plaud_auto_request_{file_id}"
    if trigger_state.is_processed("meeting", dedup_key):
        return

    _auto_gen_calls_this_cycle["count"] += 1
    accepted = _request_auto_generate(file_id)
    if accepted:
        trigger_state.mark_processed("meeting", dedup_key)
        logger.info(f"plaud auto-generate requested for stale {file_id} (age={age_min:.0f}min)")
        return

    # Sentinel on rejection (C2 fold) — direct report_failure with per-day dedup
    # under the 'plaud_alarm' namespace, NOT the broken _maybe_report_empty_body_alarm.
    today = datetime.now(timezone.utc).date().isoformat()
    alarm_key = f"plaud_alarm_auto_gen_reject_{file_id}_{today}"
    if not trigger_state.is_processed("plaud_alarm", alarm_key):
        try:
            report_failure("plaud", f"auto-generate-rejected: {file_id} (age={age_min:.0f}min)")
            trigger_state.mark_processed("plaud_alarm", alarm_key)
        except Exception as e:
            logger.warning(f"plaud auto-generate sentinel failed for {file_id}: {e}")
```

Call site in `check_new_plaud_recordings()` (line ~297) becomes:

```python
_reset_auto_gen_cycle_counter()
for rec in recordings:
    if not rec.get("is_trans"):
        _maybe_request_auto_generate_for_stale(rec)
        continue  # next poll cycle picks up the file once is_trans flips True
    rec_date = _recording_date(rec)
    if rec_date and rec_date > watermark:
        new_recordings.append(rec)
```

### Key constraints
- **Age threshold gates the call** — fresh uploads (<30min) skip the auto-generate request to avoid hammering Plaud's queue during normal user-initiated transcription
- **Dedup is mandatory** — without it, every 15-min poll re-fires the request for the same file_id forever (cockpit flood + Plaud rate limit risk)
- **Dedup-on-failure invariant (G3-CRIT fold) — explicit prose:** `mark_processed(plaud_auto_request_<file_id>)` is written ONLY on `_request_auto_generate(...) == True`. On any failure path (httpx exception, non-200, status≠0, breaker open), the dedup row is NOT written, so the next 15-min cycle re-attempts. The retry mechanism is the poll cadence; the dedup row would convert it into a "tried-once-and-given-up" path. Sentinel dedup is a SEPARATE namespace (`plaud_alarm_*`) keyed per-day-per-file, so the alarm fires once per day even while the request is retried every cycle.
- **Sentinel on rejection** — Plaud rejecting an auto-generate request (e.g., 429, 5xx, account quota hit) MUST surface in cockpit via direct `report_failure('plaud', ...)` with per-day dedup under the `plaud_alarm` namespace. Do NOT call `_maybe_report_empty_body_alarm` (its internal `is_trans` guard short-circuits — sentinel never fires).
- **Single source of truth for age threshold (H1 fold)** — `config.plaud.auto_generate_age_min` is read inside the helper; no module-level constant. Tests patching `config.plaud.*` actually affect runtime.
- **Per-cycle rate cap (G3-suggestions fold)** — at most 10 auto-generate PATCHes per cycle; rest deferred to next cycle. Bounds Plaud-side rate-limit risk.
- **Circuit breaker (G3-IMP1 fold)** — `_request_auto_generate` opens a 30-min cooldown after 5 consecutive failures; helper inherits suppression automatically.
- **No effect on existing is_trans=True path** — only the un-transcribed branch changes; happy path unchanged

### Verification
1. Plant a fresh `is_trans=False` recording older than 30 min in test (mock `fetch_plaud_recordings`).
2. Run `check_new_plaud_recordings()` once → assert `_request_auto_generate(file_id)` called exactly once.
3. Run again on same listing → assert `_request_auto_generate` NOT called again (dedup hit).
4. After mock flips to `is_trans=True`, run again → assert recording ingested via existing happy path.
5. Mock `_request_auto_generate` to return False → assert `mark_processed("meeting", "plaud_auto_request_*")` NOT called; assert `report_failure` called once; assert second cycle re-attempts the PATCH.

---

## Fix 3: Call the same helper from `backfill_plaud()`

### Problem
`backfill_plaud()` at line 519+ has its own loop. Without the same auto-generate logic, Render restart (which runs backfill once on boot) skips stuck files silently. Before the helper extraction (G3-IMP3 fold), the backfill silently dropped PATCH rejections (H5) — no sentinel, no log line.

### Implementation
Backfill calls the SAME `_maybe_request_auto_generate_for_stale(rec)` helper as Fix 2. No duplicated logic, no drift, sentinel-on-rejection inherited automatically (H5 fold).

Important: backfill respects the `is_trans` filter added in PR #168 (line 519+ in post-merge HEAD). Do NOT remove that filter — invoke the helper BEFORE the filter, then continue to skip the iteration:

```python
# inside backfill_plaud() loop
_reset_auto_gen_cycle_counter()  # cycle-scoped rate cap, fresh count per backfill invocation
for rec in recordings:
    file_id = _recording_id(rec)
    if not file_id:
        continue

    if not rec.get("is_trans"):
        # Same helper as Fix 2 — handles age threshold, dedup, kill switch, breaker,
        # rate cap, sentinel on rejection. Single source of truth.
        _maybe_request_auto_generate_for_stale(rec)
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
- **H5 fold:** sentinel on rejection now fires automatically because backfill calls the same helper as Fix 2; backfill will no longer silently drop PATCH rejections.

### Verification
Mock `fetch_plaud_recordings` returning 2 stuck + 1 done files; run `backfill_plaud()`; assert `_request_auto_generate` called twice (one per stuck file_id), assert the 1 done file ingested. Mock `_request_auto_generate` to return False on one of the stuck files → assert `report_failure('plaud', ...)` called for that file (H5 verification).

---

## Fix 4: Config + env var

### Implementation
Add to `config/settings.py` near the existing `PlaudConfig` class:

```python
class PlaudConfig:
    # ... existing fields ...
    # Threshold in minutes for considering an is_trans=False recording "stuck" and
    # triggering Plaud-side auto-generation. Setting to 0 DISABLES the feature
    # entirely (kill switch). Default 30 = half the 15-min poll × 2 cycles —
    # recordings older than this are confidently past Plaud's normal queue.
    auto_generate_age_min: int = int(os.environ.get("PLAUD_AUTO_GENERATE_AGE_MIN", "30"))
```

Read from env var `PLAUD_AUTO_GENERATE_AGE_MIN` if set; default 30. Setting to 0 disables the feature (kill switch).

Add to `.env.example` (if it exists):
```
# Plaud auto-generate threshold (minutes). 0 disables. Default 30.
PLAUD_AUTO_GENERATE_AGE_MIN=30
```

### Env propagation note (G3-suggestions fold)
Production env-var must be set on the Render `srv-d6dgsbctgctc73f55730` baker-master service via Render MCP `update_environment_variables` (merge mode). If unset, default 30 applies — which is the intended ON-by-default state. To disable in production, AI Head sets `PLAUD_AUTO_GENERATE_AGE_MIN=0` (Tier-B Director ratification required for kill-switch flip on a live capability).

### Key constraints
- **Kill switch (C1 fold):** setting env to 0 disables auto-generate calls completely. Implementation reads `config.plaud.auto_generate_age_min` inside `_maybe_request_auto_generate_for_stale(rec)` and early-returns when value is 0 — BEFORE the age comparison, since `age_min < 0` is always False and would otherwise leave the feature ON.
- **Default 30 — empirical anchor (G3-suggestions fold):** Plaud's observed normal-queue transcription completes in <10 min for typical recordings (Director-confirmed via 2026-04-12 sample files transcribed in <2 min). 30 min = 3× the SLA, comfortable margin to avoid racing user-initiated transcription. Revisit if Plaud SLA changes.

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

def test_request_auto_generate_429_treated_as_failure(caplog):
    """G3-IMP2 fold: Plaud returns 429 → helper returns False; trips breaker counter."""
    # mock httpx returns 429
    # call _request_auto_generate("file_429")
    # assert returns False; assert _AUTO_GEN_FAIL_COUNT incremented; assert NO mark_processed
    # assert log contains "HTTP 429" and no auth token

def test_dedup_not_written_when_request_fails():
    """G3-IMP2 fold: on _request_auto_generate==False, mark_processed NOT called.
    The next 15-min cycle MUST re-attempt; dedup-on-failure would convert
    transient-failure into permanent-give-up."""
    # mock fetch_plaud_recordings returns 1 stuck file (age 60 min)
    # mock _request_auto_generate → False (transient failure)
    # spy on trigger_state.mark_processed
    # call check_new_plaud_recordings() once → assert _request_auto_generate called once;
    #   assert mark_processed("meeting", "plaud_auto_request_*") NOT called
    # call check_new_plaud_recordings() second time → assert _request_auto_generate
    #   called AGAIN (transient retry, dedup row absent)

def test_age_boundary_off_by_one():
    """G3-IMP2 fold: age == threshold fires; age == threshold-1 skipped.
    Catches off-by-one bugs in the age comparator (use >=, not >)."""
    # config.plaud.auto_generate_age_min = 30
    # mock recording with age = exactly 30 min → assert _request_auto_generate called
    # mock recording with age = 29.99 min → assert _request_auto_generate NOT called
    # mock recording with age = 30.01 min → assert _request_auto_generate called

def test_check_new_plaud_recordings_requests_auto_generate_once_for_stale():
    """Stale is_trans=False recording → auto-generate fires once + dedup blocks repeat."""
    # mock fetch_plaud_recordings returns 1 stuck file (age 60 min)
    # mock _request_auto_generate → True
    # call check_new_plaud_recordings() twice
    # assert _request_auto_generate called exactly once; assert mark_processed called with dedup key on success

def test_fresh_recording_below_age_threshold_skipped():
    """is_trans=False recording <30 min old → no auto-generate call."""
    # mock fetch_plaud_recordings returns 1 fresh stuck file (age 10 min)
    # call check_new_plaud_recordings()
    # assert _request_auto_generate NOT called

def test_kill_switch_zero_age_disables():
    """C1 fold: PLAUD_AUTO_GENERATE_AGE_MIN=0 → auto-generate never fires.
    Patches config.plaud.auto_generate_age_min = 0 (single source of truth — H1 fold).
    Without the kill-switch early-return guard, age_min<0 is always False and
    the helper would fire PATCH on every is_trans=False file."""
    # patch config.plaud.auto_generate_age_min = 0
    # mock 1 very old stuck file (age 24h)
    # call check_new_plaud_recordings()
    # assert _request_auto_generate NOT called

def test_backfill_path_also_requests_auto_generate():
    """backfill_plaud() handles stale stuck files identically to incremental
    (single helper — G3-IMP3 fold)."""
    # mock fetch_plaud_recordings returns 1 stuck (60 min) + 1 done file
    # call backfill_plaud()
    # assert _request_auto_generate called once for stuck file_id
    # assert done file ingested via store.store_meeting_transcript

def test_backfill_rejection_fires_sentinel():
    """H5 fold: backfill stuck-recording rejection fires report_failure (no longer silent)."""
    # mock fetch_plaud_recordings returns 1 stuck file (age 60 min)
    # mock _request_auto_generate → False
    # spy on report_failure
    # call backfill_plaud()
    # assert report_failure called once with topic 'plaud' + body containing file_id

def test_already_transcribed_race_is_success_equivalent():
    """M1 fold: if Plaud responds with status≠0 + msg containing 'already transcribed',
    helper returns True so callers mark_processed and skip the alarm path."""
    # mock httpx returns 200 + {"status": 1, "msg": "file already transcribed"}
    # call _request_auto_generate("race_file")
    # assert returns True; assert breaker reset; assert no warning log

def test_circuit_breaker_trips_after_threshold():
    """G3-IMP1 fold: 5 consecutive failures opens the breaker for the cooldown window."""
    # mock httpx → 500 every time
    # call _request_auto_generate 5 times → assert all return False
    # call _request_auto_generate 6th time → assert returns False AND no httpx call
    #   (breaker open — call suppressed)
    # advance time past _AUTO_GEN_BREAKER_COOLDOWN_SEC → assert next call hits httpx again
```

### Key constraints
- All tests mock `httpx.Client` — never hit Plaud production API
- All tests mock `trigger_state` — never hit PostgreSQL
- All tests assert log content does NOT contain the auth token (security)
- Tests for kill switch + age threshold patch `config.plaud.auto_generate_age_min` directly (single source of truth — H1 fold). Tests that patch a module-level constant will FAIL because no module-level constant exists.
- Use `caplog` fixture for log capture (matches existing test_plaud_trigger.py pattern from PR #168)
- Tests reset module-level breaker state in setup/teardown (`_AUTO_GEN_FAIL_COUNT = 0; _AUTO_GEN_BREAKER_OPEN_UNTIL = 0.0`) — otherwise test ordering can flake
- Run literal: `pytest tests/test_plaud_trigger.py -v` GREEN — no by-inspection (Lesson #52)

---

## Files Modified
- `triggers/plaud_trigger.py` — add `_request_auto_generate(file_id)` + module-level breaker state + `_maybe_request_auto_generate_for_stale(rec)` helper + `_reset_auto_gen_cycle_counter()`; modify `check_new_plaud_recordings()` loop (line ~297) + `backfill_plaud()` loop (line ~519)
- `config/settings.py` — add `auto_generate_age_min` to `PlaudConfig` + read env var
- `tests/test_plaud_trigger.py` — add 11 new tests (success, 500-failure, 429-failure, dedup-not-written-on-fail, age-boundary, fires-once-stale, fresh-skipped, kill-switch, backfill, backfill-rejection-sentinel, already-transcribed-race, circuit-breaker)
- `.env.example` (if it exists) — add `PLAUD_AUTO_GENERATE_AGE_MIN=30`
- (Optional, post-deploy DB optimization — G3-suggestions fold) `migrations/<next>_plaud_auto_request_partial_index.sql` — partial index `CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_trigger_log_plaud_auto_request ON trigger_log (processed_at) WHERE source_id LIKE 'plaud_auto_request_%';` if dedup-key lookups become slow at scale (defer until trigger_log row count > ~100K or query latency observed)

## Do NOT Touch
- PR #168 logic: `_maybe_report_empty_body_alarm`, `_stale_refresh_advisory_lock`, the `is_trans` filter at line 519+ — all stay as-is, this brief is ADDITIVE
- Existing `_plaud_api` GET helper signature
- `fetch_plaud_recordings` / `fetch_plaud_detail` / `format_plaud_transcript` — no change needed
- `meeting_transcripts` table schema — no migration

## Quality Checkpoints
1. Step 0 endpoint discovery: B-code captures real Plaud auto-generate request and records URL/verb/body/headers in ship report (or invokes Path D escape hatch and HALTS — Step 0 BLOCKED report)
2. `_request_auto_generate` returns True for one Director recording (live test on next stuck file)
3. Single auto-generate call per file_id while in flight — verified by mocking 5 consecutive `check_new_plaud_recordings()` runs WITH `_request_auto_generate→True`. On `_request_auto_generate→False`, the call MUST re-attempt next cycle (transient retry semantics) — verified by separate test
4. Sentinel fires loud (cockpit) on Plaud rejection via direct `report_failure('plaud', ...)` with per-day dedup — verified via mock 500 response. Confirm `_maybe_report_empty_body_alarm` is NOT called on auto-generate path (different concern)
5. Circuit breaker opens after 5 consecutive failures and suppresses calls for 30 min — verified via test_circuit_breaker_trips_after_threshold
6. Per-cycle rate cap = 10 — sixth+ stale file in same cycle deferred to next cycle
7. `pytest tests/test_plaud_trigger.py -v` literal GREEN — all 11 new tests pass + existing 7/7 PR #168 tests still pass
8. Full pytest suite GREEN — no regressions
9. Render deploy live + scheduler runs `check_new_plaud_recordings` → log line `plaud auto-generate requested for stale <id>` appears
10. Director records a new Zoom call → Baker auto-fires Plaud Generate → recording transcribed without Director clicking anything (the Step-8 happy-path acceptance — full closed loop)

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
- **2026-05-07 (V0.1):** Director ratified "follow your recoms" + asked AH1-T to "do" the brief. Cowork (Director-relay) verified Plaud Desktop has no account-level auto-generate toggle (General/Recording/Private Cloud Sync/About). AH1-T probed Plaud REST API and confirmed `/file/auto_setting`, `/file/auto`, `/file/setting` are PATCH endpoints — exact body shape pending Step 0 discovery.
- **2026-05-08 (V0.2):** Director ratified "concur with AH1-T's wait-and-fold-both" 2026-05-08 ~07:00Z. V0.2 folds 14 findings: Gate 1 (cowork-ah1 / `feature-dev:code-reviewer` agent `a411e9e9bff231fa0`) = 2 CRIT (C1 inverted kill-switch, C2 broken sentinel call) + 5 HIGH (H1 config split, H2 missing httpx import, H3 empty-headers guard, H4 CDP event-discard bug, H5 backfill silent rejection) + 2 MED (M1 is_trans race, M2 null-date silent skip); Gate 3 (AH1-T `architecture-reviewer`) = 1 CRIT (dedup-on-failure invariant prose) + 4 IMP (no circuit breaker, missing 3 tests, Fix 2/3 duplication, Step-0 Path-D escape hatch) + 5 SUGGESTIONS (empirical 30-min anchor, partial index, env propagation note, max-10/cycle rate cap, default-age-0 disabled).
- **PR #168 (`8641a11a`):** dependency — alarm dedup helper + advisory lock + stale-refresh lane all referenced.

## PL ship-report
End your chat ship report with the fenced PL paste-block per `_ops/skills/ai-head/SKILL.md` §"PL ship-report contract".
