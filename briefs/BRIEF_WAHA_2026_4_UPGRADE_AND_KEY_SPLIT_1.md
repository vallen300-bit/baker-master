# BRIEF: WAHA 2026.4 Upgrade + API Key Scope Split — Phased ship with rollback

## Context

WAHA 2026.4 release (2026-05-12 newsletter, https://waha.devlike.pro/blog/waha-2026-4/) ships:
- Scoped API keys via new `POST /api/keys` admin endpoint with `actions: {read,send,control,setting,app,delete}` map.
- Built-in MCP server (out of scope for this brief — see §"Explicitly out of scope").
- Query-param auth `?x-api-key=...` (out of scope — Baker uses header auth and should keep doing so).
- Multiple engine fixes: NOWEB missing-message timestamp bug, GOWS session-startup/media-download fixes, WEBJS call-event fix, **32-bit `setTimeout` overflow causing immediate file deletion** (relevant — past silent media drops on baker-waha could be this bug).

**Why this matters for Brisen:**
1. Single admin key `WHATSAPP_API_KEY` is used everywhere today (`triggers/waha_client.py:27`, `outputs/whatsapp_sender.py:17`, `scripts/extract_whatsapp.py:475`, indirectly `triggers/sentinel_health.py` via `get_session_status`). Full-power key in 4 code locations + 1 Render env. Compromise = total WhatsApp surface.
2. Engine fixes plausibly address silent failures we've eaten before (Lesson #25 — 35-day backlog; Lesson #27 — session corruption).

**Anchor:** Director ratification 2026-05-12 chat: upgrade + key split, skip MCP-server adoption.

## Estimated time: ~4h (1.5h upgrade + verify, 2h key-split + rotate, 0.5h docs/cleanup)
## Complexity: Medium
## Prerequisites:
- WAHA 2026.4 Docker image tag confirmed available on `devlikeapro/waha-plus` registry (verify before scheduling).
- **Confirmed Director-window for ~15 min WhatsApp dark during image swap — this is certain, not optional. Schedule outside business hours.** Single Render service, no HA, no staging.
- 1Password write access to store the 3 new scoped keys.
- **Phase 2 pre-flight by AH1 (NOT B-code, runs after Phase 1 24h soak):** one live probe of `POST /api/keys` against `baker-waha` to confirm the actual response shape (key field name) + that the `actions` map is the correct request schema. AH1 patches Step 2.1 commands with the verified field names BEFORE dispatching the B-code. Anchor: Lesson #61 "probe the third-party with a real call FIRST".

---

## Architecture decision — phased, NOT bundled

**Two PRs, sequenced. Not one.**

**Why split:** WAHA upgrade is service-level (Render image bump on `baker-waha`); key split is code-level (baker-master repo). Different blast radii, different rollback paths. Bundling would conflate failure modes — if WAHA upgrade regresses, you'd be debugging code-side env-var plumbing at the same time.

| | Phase 1 — Upgrade | Phase 2 — Key split |
|---|---|---|
| Service touched | `baker-waha` Render service | `baker-master` Render service |
| Code repo PR | None | `baker-master` PR |
| Rollback | Revert image tag, redeploy | `git revert` + Render env-var restore |
| Gate to next phase | 24h healthy run on 2026.4 with single admin key still working | (terminal) |

Phase 2 does NOT begin until Phase 1 has 24h clean signal-queue + smoke-tested send.

---

## Fix/Feature 1: Phase 1 — Upgrade baker-waha to 2026.4 (no code changes)

### Problem
`baker-waha` Render service runs an older WAHA image. 2026.4 ships fixes that may close past silent-failure root causes (32-bit setTimeout file-deletion overflow; NOWEB missing-message timestamp filtering).

### Current State
- Render service: `baker-waha` at `https://baker-waha.onrender.com` (`WAHA_BASE_URL` per `config/settings.py:233`).
- Auth: `X-Api-Key` header sourced from `WHATSAPP_API_KEY` env var on `baker-master` (NOT on `baker-waha` itself — that's the WAHA-side admin key set independently).
- Webhook secret separate: `WAHA_WEBHOOK_SECRET` (config/settings.py:236). NOT affected by this brief.
- Single session: `default` (config/settings.py:234).
- Current image: confirm via Render dashboard before starting (do not assume).

### Implementation

**Step 1.1 — Pre-flight (10 min):**

1. Confirm WAHA 2026.4 image is published. Check Docker Hub tags for `devlikeapro/waha-plus`. Note exact tag (e.g. `2026.4`, `2026.4.0`, or `latest` — pin to the explicit numeric tag, never `latest`).
2. Record current image tag (write to `BRIEF_..._upgrade_state.md` scratch file before swap — needed for rollback).
3. Verify WAHA-side admin key still works post-upgrade (read 2026.4 changelog for any breaking auth changes — at time of brief writing the release notes document no breaking changes, but verify in real release post).
4. Take a fresh snapshot of WAHA session state:
   ```bash
   curl -s -H "X-Api-Key: $WHATSAPP_API_KEY" \
     https://baker-waha.onrender.com/api/sessions/default | jq .
   ```
   Expected: `{"name":"default","status":"WORKING",...}`. If anything else, do NOT proceed — fix session first.

**Step 1.2 — Image bump on Render `baker-waha` service (15 min):**

- Render dashboard → `baker-waha` → Settings → Image tag → set to `2026.4` (or exact published numeric tag confirmed in 1.1).
- Trigger manual deploy.
- Watch logs until `WORKING` session re-established.

**Step 1.3 — Smoke verification (30 min):**

After Render reports deploy live:

1. **Session status read** (uses admin key, read path):
   ```bash
   curl -s -H "X-Api-Key: $WHATSAPP_API_KEY" \
     https://baker-waha.onrender.com/api/sessions/default
   ```
   Expect HTTP 200, `status: "WORKING"`.

2. **Inbound webhook smoke:** Director sends one test message from his phone to himself or to the Baker number. Within ~60s, verify the signal_queue ingestion:
   ```sql
   SELECT id, source, body, received_at
   FROM signal_queue
   WHERE source IN ('whatsapp','wa','waha')
   ORDER BY received_at DESC
   LIMIT 5;
   ```
   Expect: the test message present, `received_at` within the last 2 min.

3. **Outbound send smoke (DRY — Director-authorized only):**
   Per `BRIEF_WHATSAPP_RECIPIENT_RESOLVER_FIX_1.md` re-enable pattern: AH1 runs ad-hoc `send_whatsapp("WAHA 2026.4 upgrade smoke — please ignore")` to Director's own number. Confirms send path still works under the unchanged admin key. **Director must authorize this step (Tier B) — same authorization gate as the original 2026-05-08 re-enable.**

4. **NOWEB engine timestamp fix verification:** if Baker recently logged a "missed message" complaint from a low-frequency contact, recheck after 24h.

### Key Constraints
- **No code changes in Phase 1.** Phase 1 is image-tag swap + verification only.
- **Pin the tag** — never use `latest`. Future Render restart with `latest` could silently auto-upgrade past 2026.4 and re-break things.
- **Do not touch `WHATSAPP_API_KEY` env in Phase 1.** Admin key continues working.
- **Phase 2 gate:** 24h of healthy inbound (no `waha_silence` alerts in `triggers/sentinel_health.py` `check_waha_silence()`) AND one successful outbound smoke. Only then start Phase 2.

### Verification
- `signal_queue` shows a new WhatsApp inbound within 60s of Director's test message.
- `sentinel_health.poll_waha_session()` reports `WORKING` for 30 min.
- No new error rate in Render `baker-waha` logs.

### Rollback
- Render dashboard → `baker-waha` → revert image tag to value recorded in Step 1.1 → manual deploy.
- ~5 min rollback. Same session, same QR scan preserved across restart (WAHA persists session data to the disk volume).

---

## Fix/Feature 2: Phase 2 — Split admin key into 3 scoped keys

### Problem
Today, one env var (`WHATSAPP_API_KEY`) holds an admin-class WAHA key with full power: read, send, control (session start/stop/restart), setting (server config), app, delete. If leaked from baker-master env, attacker gets the whole WhatsApp surface — read messages, send messages, kill sessions.

Three Baker consumers do three different things; principle of least privilege says three scoped keys.

### Current State

| Consumer | File | Function | Operations needed |
|---|---|---|---|
| Webhook-side read path | `triggers/waha_client.py:27-28` | `_headers()` | `read` |
| Outbound sender | `outputs/whatsapp_sender.py:17,331-332` | `send_whatsapp()` | `send` |
| Backfill | `scripts/extract_whatsapp.py:475-476` | `backfill_whatsapp()` | `read` |
| Health probe | `triggers/sentinel_health.py:690` (via `get_session_status()`) | `poll_waha_session()` | `read` (one GET) |

All four read the same `config.waha.api_key` → `WHATSAPP_API_KEY` env var.

### Implementation

**Step 2.1 — Provision 3 scoped keys via WAHA admin API (15 min):**

Per WAHA 2026.4 docs (https://waha.devlike.pro/docs/how-to/security/), endpoint is `POST /api/keys`. Call once per key, using the existing admin key for auth:

```bash
# Key A — READ scope (ingest path: waha_client.py + extract_whatsapp.py)
curl -s -X POST https://baker-waha.onrender.com/api/keys \
  -H "X-Api-Key: $WHATSAPP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"isAdmin":false,"session":"default","isActive":true,
       "actions":{"read":true,"send":false,"control":false,
                  "setting":false,"app":false,"delete":false}}' | tee /tmp/waha_key_read.json

# Key B — SEND scope (outputs/whatsapp_sender.py)
curl -s -X POST https://baker-waha.onrender.com/api/keys \
  -H "X-Api-Key: $WHATSAPP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"isAdmin":false,"session":"default","isActive":true,
       "actions":{"read":false,"send":true,"control":false,
                  "setting":false,"app":false,"delete":false}}' | tee /tmp/waha_key_send.json

# Key C — MONITOR scope (sentinel_health.poll_waha_session, separate blast-radius)
curl -s -X POST https://baker-waha.onrender.com/api/keys \
  -H "X-Api-Key: $WHATSAPP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"isAdmin":false,"session":"default","isActive":true,
       "actions":{"read":true,"send":false,"control":false,
                  "setting":false,"app":false,"delete":false}}' | tee /tmp/waha_key_monitor.json
```

**Verify response shape before proceeding.** AH1's pre-flight probe (Prerequisites) has already confirmed the exact field name for the returned key value AND that `"session":"default"` in the request body is the correct scope field. B-code uses the AH1-patched commands directly. If response shape diverges from AH1's pre-flight result, STOP — do not improvise.

Additionally, after each `tee /tmp/waha_key_*.json`, verify the response includes the scope confirmation:
```bash
jq -e '.actions.read == true and .actions.send == false' /tmp/waha_key_read.json   # for READ key
jq -e '.actions.send == true and .actions.read == false' /tmp/waha_key_send.json   # for SEND key
jq -e '.actions.read == true and .actions.send == false' /tmp/waha_key_monitor.json # for MONITOR key
```
Each `jq -e` exits non-zero if assertion fails. If any fails, revoke that key via `DELETE /api/keys/{id}` and STOP — WAHA may have silently produced an unscoped key.

Extract each key value, store in 1Password under entries:
- `Baker Render env / WAHA_API_KEY_READ`
- `Baker Render env / WAHA_API_KEY_SEND`
- `Baker Render env / WAHA_API_KEY_MONITOR`

DO NOT echo plaintext into commit, brief, or chat. (Pre-commit `forbid-secrets` hook blocks anything resembling a key in tracked files.)

**Step 2.2 — Sanity test each scoped key BEFORE rotating Baker env (15 min):**

```bash
# Read key — should succeed on GET, fail on POST send
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "X-Api-Key: $WAHA_READ" \
  https://baker-waha.onrender.com/api/sessions/default
# Expect: 200

curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST -H "X-Api-Key: $WAHA_READ" -H "Content-Type: application/json" \
  -d '{"chatId":"41799605092@c.us","text":"scope-test (should fail)"}' \
  https://baker-waha.onrender.com/api/sendText
# Expect: 403 (forbidden — read key cannot send)

# Send key — should fail on read, succeed on send
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "X-Api-Key: $WAHA_SEND" \
  https://baker-waha.onrender.com/api/sessions/default
# Expect: 403

# (DO NOT actually fire a sendText smoke from $WAHA_SEND yet — wait for Director-authorized step in 2.4)
```

If any scope behaves unexpectedly (e.g. `read` key can send), STOP. Revoke the misbehaving key via `DELETE /api/keys/{id}` and re-open the WAHA security docs.

**Step 2.3 — Code changes (baker-master PR):**

**File 1: `config/settings.py:231-237` —** replace single `api_key` field with three:

```python
@dataclass
class WahaConfig:
    base_url: str = os.getenv("WAHA_BASE_URL", "https://baker-waha.onrender.com")
    session: str = os.getenv("WAHA_SESSION", "default")
    # Scoped keys (WAHA 2026.4+). Each consumer reads its scope-matched key.
    # Legacy admin key is retained as fallback for ops scripts only; not used by Baker code paths.
    api_key_read: str = os.getenv("WAHA_API_KEY_READ", "")
    api_key_send: str = os.getenv("WAHA_API_KEY_SEND", "")
    api_key_monitor: str = os.getenv("WAHA_API_KEY_MONITOR", "")
    webhook_secret: str = os.getenv("WAHA_WEBHOOK_SECRET", "")

    # Legacy admin key — kept ONLY for ops/CLI scripts.
    # Baker production code paths MUST NOT read api_key. Asserted in sanity check below.
    api_key: str = os.getenv("WHATSAPP_API_KEY", "")
```

**File 2: `triggers/waha_client.py:25-29` —** route header from `api_key_read` with explicit fallback chain (load-bearing for fast rollback per §Rollback):

```python
def _headers() -> dict:
    """Read-scope header. Fallback chain: read → legacy admin.
    The legacy fallback is INTENTIONAL and load-bearing for the fast-rollback path:
    if WAHA_API_KEY_READ is unset (rotation failure or rollback flip), Baker keeps
    working under the legacy admin key. Fold-back PR will remove this chain after
    7 days of stable scoped-key operation.
    """
    h = {}
    key = config.waha.api_key_read or config.waha.api_key
    if key:
        h["X-Api-Key"] = key
    return h
```

**File 3: `outputs/whatsapp_sender.py:17,331-332` —** module-level constant + header source, with the same legacy fallback (load-bearing for rollback):

```python
# OLD:
# WAHA_API_KEY = os.getenv("WHATSAPP_API_KEY", "")
# NEW (fallback to legacy admin key is intentional — see _headers() in waha_client.py):
WAHA_API_KEY = os.getenv("WAHA_API_KEY_SEND", "") or os.getenv("WHATSAPP_API_KEY", "")
```
(Constant name kept as `WAHA_API_KEY` for minimal diff; env-var source has fallback chain.)

**File 4: `triggers/sentinel_health.py:696` (the call site, NOT line 695 which is the import) —** `poll_waha_session()` calls `get_session_status()` in `waha_client.py`. To give monitor a separate key without forking the whole `_headers()` plumbing, add a public monitor-specific header helper in `waha_client.py`:

```python
def monitor_headers() -> dict:
    """Health-probe scope header. Fallback chain: monitor → read → legacy admin.
    Monitor → read fallback is INTENTIONAL and does NOT expand blast radius
    (both scopes are read-only). The read → legacy fallback exists for the
    same rollback reason as _headers().
    """
    h = {}
    key = (config.waha.api_key_monitor
           or config.waha.api_key_read
           or config.waha.api_key)
    if key:
        h["X-Api-Key"] = key
    return h
```

Then add an optional headers parameter to `get_session_status()`:

```python
def get_session_status(session: str = None, _headers_override=None) -> dict:
    if session is None:
        session = config.waha.session
    try:
        resp = httpx.get(
            f"{config.waha.base_url}/api/sessions/{session}",
            headers=(_headers_override if _headers_override is not None else _headers()),
            timeout=10,
        )
        ...
```

In `triggers/sentinel_health.py` — modify lines 695-696 ONLY (do NOT touch the surrounding `try` block):

```python
# OLD (line 695): from triggers.waha_client import get_session_status
# OLD (line 696): result = get_session_status()
# NEW:
from triggers.waha_client import get_session_status, monitor_headers
result = get_session_status(_headers_override=monitor_headers())
```

**File 5: `scripts/extract_whatsapp.py:475-476` —** rename guard to read-scope, keep legacy-key fallback awareness:

```python
if not (config.waha.api_key_read or config.waha.api_key):
    logger.info("WhatsApp backfill: WAHA_API_KEY_READ / WHATSAPP_API_KEY not set, skipping")
    return
```

**File 6: import-time sanity assert (NEW, in `config/settings.py` after `config = ...` instantiation, or wherever the config singleton lives):**

```python
# WAHA-KEY-SPLIT-1: prevent regression to single admin key in code paths
def _assert_waha_scoped_keys() -> None:
    """Production code paths must use scoped keys, not admin key.
    Soft warning only — never raises. Hard fail would brick the service
    if config singleton is partially constructed at import time.
    """
    try:
        if os.getenv("WAHA_REQUIRE_SCOPED_KEYS", "true").lower() != "true":
            return
        missing = [
            n for n, v in [
                ("WAHA_API_KEY_READ", config.waha.api_key_read),
                ("WAHA_API_KEY_SEND", config.waha.api_key_send),
                ("WAHA_API_KEY_MONITOR", config.waha.api_key_monitor),
            ] if not v
        ]
        if missing:
            import logging
            logging.getLogger("baker.config").warning(
                f"WAHA scoped keys missing: {missing}. "
                f"Code paths fall back to legacy WHATSAPP_API_KEY when scoped keys absent."
            )
    except Exception:
        # Never raise from a soft warning. Brick-safety > observability here.
        pass

_assert_waha_scoped_keys()
```

(Soft warning, not hard fail — first deploy after PR merge will have legacy key only; Step 2.4 env-var rotation flips the keys. All three scoped keys checked, including MONITOR — silent monitor-key drop must surface as a warning even though fallback chain prevents outage.)

**Step 2.4 — Render env-var rotation via MCP merge mode (Tier B, Director-authorized):**

Per `.claude/rules/python-backend.md`: **NEVER raw PUT; always merge mode.**

```python
# Pseudocode for the rotation — actual call via Render MCP from AH1 session
render_mcp.update_environment_variables(
    service_id="srv-baker-master-...",  # confirm exact ID from LONGTERM.md
    env_vars={
        "WAHA_API_KEY_READ":    "<from 1Password>",
        "WAHA_API_KEY_SEND":    "<from 1Password>",
        "WAHA_API_KEY_MONITOR": "<from 1Password>",
    },
    mode="merge",
)
# Then explicit POST /v1/services/{id}/deploys to actually restart.
```

After deploy, verify ALL THREE env vars present via `GET /v1/services/{id}/env-vars`. Do not assume any single key persisted (Lesson #45 — Exchange env-var silent drop).

**Step 2.5 — Post-rotation smoke (Director-authorized for the send-side):**

1. Inbound: Director sends one message. Verify `signal_queue` ingest within 60s. This exercises `_headers()` → `api_key_read`.
2. Health: `sentinel_health.poll_waha_session()` next tick (≤30 min) reports `WORKING`. This exercises `monitor_headers()` → `api_key_monitor`.
3. Outbound (Tier B authorize step): AH1 runs `send_whatsapp("WAHA key-split smoke — please ignore")` to Director's number. Verify message lands. This exercises `WAHA_API_KEY_SEND`. **Authorization gate identical to the 2026-05-08 re-enable pattern.**

   **Trigger surface (per Lesson #63):** AH1 invokes from Mac Mini local Python with prod env vars sourced from 1Password:
   ```bash
   ssh macmini "WAHA_API_KEY_SEND='$(op read 'op://Baker/WAHA_API_KEY_SEND/password')' \
     WAHA_BASE_URL=https://baker-waha.onrender.com \
     DATABASE_URL='$(op read 'op://Baker/DATABASE_URL/password')' \
     /opt/homebrew/bin/python3.12 -c \
     'from outputs.whatsapp_sender import send_whatsapp; \
      send_whatsapp(\"WAHA key-split smoke — please ignore\")'"
   ```
   This is the documented trigger path; do NOT improvise a different surface. If Mac Mini SSH is unavailable, escalate — do NOT fall back to the dashboard since no public endpoint exists for arbitrary sends.

4. **Fallback-chain exercise (rollback rehearsal — Director-authorized):** with all 3 scoped keys still present, unset `WAHA_API_KEY_READ` on Render (merge mode), redeploy, send inbound smoke message. Verify `signal_queue` still ingests (legacy fallback kicks in). Restore `WAHA_API_KEY_READ`. This proves fast-rollback works WITHOUT having to actually rollback in anger.

**Step 2.6 — Revoke the legacy admin key (after 24h healthy on scoped keys):**

```bash
# List keys to find the admin key ID
curl -s -H "X-Api-Key: $WAHA_NEW_ADMIN" \
  https://baker-waha.onrender.com/api/keys | jq .

# Revoke
curl -s -X DELETE -H "X-Api-Key: $WAHA_NEW_ADMIN" \
  https://baker-waha.onrender.com/api/keys/{LEGACY_ID}
```

**Open Q for Director:** Do we want to keep ONE admin-class key for AH1 emergency-ops (session recreation per Lesson #27), or revoke ALL admin keys and rely on the WAHA dashboard UI for emergency control? Recommendation: keep one admin key in 1Password, NOT in any Render env, for break-glass only. Reason: session recreation requires `control` + `setting` scope which we shouldn't put on Render at all.

Old `WHATSAPP_API_KEY` env var on baker-master: remove from Render after Step 2.6 confirms 24h healthy on the three scoped keys.

### Key Constraints
- **WAHA-side admin key for `POST /api/keys` is the same `WHATSAPP_API_KEY` we have today.** If WAHA 2026.4 changes the admin-key boot mechanism, Step 2.1 will 401 — STOP and re-read the WAHA migration docs.
- **Soft-warn, never hard-fail on missing scoped keys** during the rollout window. Hard-fail would brick Baker if any one of the three env vars fails to set.
- **`WAHA_WEBHOOK_SECRET` is not touched.** Webhook authentication is inbound-from-WAHA and uses a separate construct.
- **`WAHA_BASE_URL`, `DIRECTOR_WHATSAPP` constants not touched.**
- **No changes to MCP-server adoption.** Out of scope (see §"Explicitly out of scope" below).

### Verification

**Functional:**
```sql
-- Within 5 min of Step 2.5.1, expect the test inbound to appear:
SELECT id, source, body, received_at
FROM signal_queue
WHERE source IN ('whatsapp','wa','waha')
  AND received_at > NOW() - INTERVAL '5 minutes'
ORDER BY received_at DESC
LIMIT 5;
```

**Negative test (scope enforcement):**
```bash
# Read key should fail to send (returns 403):
curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST -H "X-Api-Key: $WAHA_API_KEY_READ" -H "Content-Type: application/json" \
  -d '{"chatId":"41799605092@c.us","text":"should-fail"}' \
  https://baker-waha.onrender.com/api/sendText
# Expect: 403

# Send key should fail to list sessions (returns 403):
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "X-Api-Key: $WAHA_API_KEY_SEND" \
  https://baker-waha.onrender.com/api/sessions/default
# Expect: 403
```

**Env-var presence (Render API — `curl`, not `gh api`):**
```bash
curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services/{SVC_ID}/env-vars" \
  | jq '.[] | .envVar.key' \
  | grep -E "WAHA_API_KEY_(READ|SEND|MONITOR)"
# Expect all three present. (gh api routes through api.github.com — wrong tool here.)
```

**Wiring verification (catch missed call-site edit):**
```bash
grep -n "_headers_override\|monitor_headers" triggers/sentinel_health.py
# Expect exactly one match on _headers_override AND one import of monitor_headers.
# Zero matches = sentinel_health.py:696 edit missed; monitor key silently unused.
```

### Rollback (Phase 2)
- **Fast (env-var only, no redeploy needed):** restore `WHATSAPP_API_KEY` on Render env via merge-mode. Code already has fallback chain in `_headers()` / `monitor_headers()` / `whatsapp_sender.py` (see Step 2.3 Files 2-3-4). Scoped-key env-vars can be cleared or left in place — `or` fallback picks up legacy admin key automatically.

  Optionally flip `WAHA_REQUIRE_SCOPED_KEYS=false` to silence the import-time warning. NOT required for functional rollback.

  **Fallback chain is mandatory in Step 2.3 — not optional.** This is what makes fast-rollback work. Quality Checkpoint added below to exercise it.

- **Code rollback (medium):** `git revert <PR_HASH>` on `main` → Render auto-deploys → restores pre-split single-key path. Keys provisioned in 2.1 remain unused but unrevoked (revoke separately via `DELETE /api/keys/{id}`).

- **Fold-back PR (planned, +7 days):** after 7 days of stable scoped-key operation, separate PR removes the `or config.waha.api_key` fallback chain from `_headers()` / `monitor_headers()` / `whatsapp_sender.py` and removes the legacy `api_key` field from `WahaConfig`. Eliminates the dual-mode debt. Tracked as follow-up brief `BRIEF_WAHA_KEY_SPLIT_FOLDBACK_1`.

---

## Explicitly out of scope (skipped per Director ratification 2026-05-12)

1. **WAHA built-in MCP server adoption** — adding agents that talk to WhatsApp directly via WAHA's MCP server bypasses Baker's `signal_queue` / Cortex pipeline. That's the wrong layer for outbound. Outbound WhatsApp must continue to flow through `outputs/whatsapp_sender.py` so it logs through `baker_actions` and is auditable.
2. **Query-param auth (`?x-api-key=...`)** — Baker uses header auth. Don't introduce a second auth path; URL params end up in logs / referers / browser history.
3. **WAHA-side admin key rotation** — out of scope this brief; future ops task if/when the admin key is suspected leaked.

---

## Files Modified

- `config/settings.py` — `WahaConfig` gains three scoped-key fields + retains legacy `api_key` field for fallback; import-time `_assert_waha_scoped_keys()` (try/except wrapped, soft-warn only, checks all 3 scoped keys)
- `triggers/waha_client.py` — `_headers()` reads `api_key_read` with `or api_key` legacy fallback; new public `monitor_headers()` with `monitor → read → legacy` fallback chain; `get_session_status()` accepts `_headers_override` keyword arg
- `outputs/whatsapp_sender.py` — module-level `WAHA_API_KEY` sources from `WAHA_API_KEY_SEND` with `or WHATSAPP_API_KEY` legacy fallback
- `triggers/sentinel_health.py:696` — replaces the call-site (NOT line 695, which is the import — separate edit) to pass `_headers_override=monitor_headers()`
- `scripts/extract_whatsapp.py:475-476` — guard checks `api_key_read or api_key`

## New env vars on Render `baker-master`

- `WAHA_API_KEY_READ` — scoped key, read scope (set in Step 2.4)
- `WAHA_API_KEY_SEND` — scoped key, send scope (set in Step 2.4)
- `WAHA_API_KEY_MONITOR` — scoped key, read scope (set in Step 2.4)
- `WAHA_REQUIRE_SCOPED_KEYS` — **do NOT set this** (defaults to `"true"`). Only set to `"false"` during rollback to silence the import-time warning. Remove from Render entirely after fold-back PR.
- `WHATSAPP_API_KEY` (legacy) — keep through fold-back PR for fallback chain. Remove after Step 2.6 confirms 24h healthy on scoped keys AND fold-back PR removes the chain.

## Do NOT Touch

- `triggers/waha_webhook.py` — inbound webhook auth uses `WAHA_WEBHOOK_SECRET`, not the API key. Unrelated.
- `DIRECTOR_WHATSAPP`, `DIRECTOR_PHONE_ROOTS` — recipient-resolver constants per `BRIEF_WHATSAPP_RECIPIENT_RESOLVER_FIX_1`. Not touched.
- `WAHA_BASE_URL` — kill-switch lever from the 2026-05-08 Marcus Pisani incident. Must stay clean.
- `slugs.yml`, `tasks/lessons.md` existing entries — per repo CLAUDE.md hard rules.
- `migrations/` — no schema changes in this brief.

## Quality Checkpoints

1. After Phase 1 deploy: `signal_queue` receives a new WhatsApp inbound within 60s of Director's test message.
2. After Phase 1 deploy: `sentinel_health.check_waha_silence()` reports no silence alerts for 24h.
3. After Phase 2 code merge but BEFORE env-var rotation: legacy `WHATSAPP_API_KEY` path still works (fallback chain exercised — Baker continues working under legacy key with soft warning logged).
4. After Phase 2 env-var rotation: each scoped key passes its positive case AND fails its negative case (cross-scope denials work).
5. After Phase 2 rotation: 3 new env vars confirmed present on Render via API check.
6. After Phase 2 rotation: outbound Tier-B smoke send works under `WAHA_API_KEY_SEND` via the Mac Mini trigger path (Step 2.5.3).
7. After Phase 2 rotation: `grep -n "_headers_override\|monitor_headers" triggers/sentinel_health.py` shows exactly one match on each — proves the call-site edit at line 696 landed.
8. After Phase 2 rotation: with `WAHA_API_KEY_READ` temporarily unset (rollback rehearsal Step 2.5.4), inbound ingest still works via legacy fallback — proves fast-rollback path is real.
9. After 24h on scoped keys: revoke legacy admin key, remove `WHATSAPP_API_KEY` from Render env.
10. CI: `python3 -c "import py_compile; py_compile.compile('config/settings.py', doraise=True)"` + same for the 4 other touched files.
11. CI: `pytest tests/test_whatsapp_sender_lid.py tests/test_hot_md_weekly_nudge.py -v` (and any other WAHA-touching tests) green on literal run, not "by inspection".
12. Pre-commit secret-scan hook does not flag the diff.

## Verification SQL

```sql
-- After Phase 1 smoke message:
SELECT id, source, body, received_at
FROM signal_queue
WHERE source IN ('whatsapp','wa','waha')
  AND received_at > NOW() - INTERVAL '5 minutes'
ORDER BY received_at DESC
LIMIT 5;

-- After Phase 2 inbound smoke (same query, separate run):
-- expect: at least 1 row in last 5 min

-- After 24h on scoped keys, verify no spike in waha-side errors:
SELECT date_trunc('hour', received_at) AS hr, COUNT(*) AS n
FROM signal_queue
WHERE source IN ('whatsapp','wa','waha')
  AND received_at > NOW() - INTERVAL '48 hours'
GROUP BY 1 ORDER BY 1 DESC LIMIT 48;
-- Expect: steady volume across the cutover hour. No multi-hour gap.
```

## Brief-Standards Self-Check

Per `_ops/skills/ai-head/SKILL.md` §"Brief Authoring Standards":

1. **API version/endpoint:** WAHA 2026.4, `POST /api/keys`, `DELETE /api/keys/{id}`, `GET /api/sessions/{name}`.
2. **Deprecation check date:** 2026-05-12 (today, day of newsletter announcement). Revisit if WAHA ships 2026.5+ before this brief is built.
3. **Fallback note:** No vendor deprecation announced. Legacy admin key continues working unless explicitly revoked.
4. **Migration-vs-bootstrap DDL check:** N/A — no DB schema change.
5. **Ship gate:** literal pytest output + cross-scope curl probes from §Verification.
6. **Test plan:** end-to-end inbound + outbound + negative-case probes per Phase 1 + Phase 2 verification blocks.
7. **`file:line` citation verification:** every `path:N` reference verified at brief-write time via Grep (Step 1 EXPLORE). Confirmed: `config/settings.py:231-237`, `triggers/waha_client.py:25-29`, `outputs/whatsapp_sender.py:17,331-332`, `triggers/sentinel_health.py:690`, `scripts/extract_whatsapp.py:475-476`. (If line numbers drift before B-code picks this up, B-code re-grep before editing.)
8. **Singleton pattern:** N/A — no `SentinelStoreBack` / `SentinelRetriever` touch.
9. **Post-merge script handoff rule:** Step 2.4 Render env-var rotation runs AFTER the code PR merges. AH1 must `git pull --rebase origin main` on any working tree before invoking the rotation.
10. **Invocation-path audit:** N/A — not a Pattern-2 capability touch.

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| WAHA 2026.4 image not yet published when Director schedules build | M | Blocker | Pre-flight Step 1.1 verifies tag exists |
| WAHA 2026.4 regresses NOWEB session or media handling | L-M | Inbound dark | Phase 1 24h soak before Phase 2; rollback = image-tag revert (~5 min) |
| `POST /api/keys` endpoint signature differs from docs at brief-write time | M | Phase 2 stuck | Step 2.1 verifies response shape before consuming; Lesson #61 applied |
| Existing admin key auto-loses some scope post-upgrade | L | Phase 1 smoke fails | Phase 1 Step 1.3 explicit smoke; rollback before Phase 2 |
| Render env-var rotation silent-drops one key | M | One scope path broken | Step 2.4 verifies all 3 keys via Render API (Lesson #45) |
| Scope enforcement weaker than expected (e.g. `read` key can send) | L | Security model wrong | Step 2.2 negative tests catch this; STOP rule documented |
| WAHA single-instance downtime during image swap | H (certain) | ~10-15 min WA dark | Schedule with Director; window outside business hours |
| MCP server adoption scope-creep into this PR | M | Bundling risk | Explicit out-of-scope section; B-code is instructed to reject scope additions |

---

**Anchor:** Brief drafted by AH1 2026-05-12 in response to Director ratification of WAHA 2026.4 newsletter (vallen300@gmail.com inbox, message id `19e1a21b29ac9178`). Director ratification: upgrade + 3-key split, skip MCP-server adoption.
