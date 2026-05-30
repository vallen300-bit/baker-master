# BRIEF: BAKER_CAPTURE_BLINDSPOTS_1 — close Director outbound capture gaps on email + WhatsApp

> **REV 2 (2026-05-30):** Patched after codex review bus #1342 (FAIL-LIGHT, 4 findings). Phase 1 + Phase 2 storage paths rewritten against ACTUAL schemas (`email_messages` + `whatsapp_messages` per `memory/store_back.py:1665-1706`). Direction tagging via existing fields, not new columns. No migrations required. Helper calls go through `_get_store()` → `SentinelStoreBack` methods. Anchor patch commit: TBD; original commit `a77ea78`.

## Context

Director directive 2026-05-29: *"If we have a gap in what I send to other people by WhatsApp or email, there is a problem. Baker is blind."*

### Surface contract: N/A — pure backend. No clickable surface, no frontend route, no Slack Block Kit, no email-rendered HTML. Phase 1 extends IMAP poller; Phase 2 adds an auth-gated REST endpoint consumed via curl. Dashboard rendering surfaces outbound rows automatically because they land in the same `email_messages` / `whatsapp_messages` tables existing renderers already read.

Surfaced by origination-desk bus #1338 (NVIDIA project room) — both Storer (Corinthia) and Bick (MOHG/AI Hotel) communication threads have explicit `outbound_gap` flags. Investigation found two distinct root causes:

1. **Email:** `triggers/exchange_poller.py:23` hardcodes `EXCHANGE_FOLDER = "INBOX"`. Sent Items is NEVER polled. Every email Director sends from Outlook (dvallen@brisengroup.com) via the EVOK Exchange tenant is invisible to Baker. Ongoing structural gap.
2. **WhatsApp:** Outbound capture (`fromMe=true`) shipped 2026-05-20 via PR #235 (`0e08ce5`) + hot-fix `5af2971`. Going-forward outbound IS captured. But all pre-2026-05-20 outbound — including the Storer/Bick threads (2026-03 → 2026-05-13) — was dropped at the webhook. Historical gap only.

This brief closes both.

## Estimated time: ~5h
## Complexity: Medium
## Prerequisites: `EXCHANGE_PASS` valid on Render (currently set per recent restoration); WAHA session healthy (not used by this brief — iPhone export is the data source for Phase 2).

---

## Verified schema (CRITICAL — codex review #1342 caught these)

Brief v1 referenced non-existent columns. Live schema per `memory/store_back.py`:

**`email_messages`** (memory/store_back.py:1665-1668):
```
message_id, thread_id, sender_name, sender_email, subject, full_body,
received_date, priority, ingested_at
```
Helper: `SentinelStoreBack.store_email_message(...)` — has `ON CONFLICT (message_id) DO UPDATE` so calls are naturally idempotent.

**`whatsapp_messages`** (memory/store_back.py:1698-1715):
```
id TEXT PRIMARY KEY, sender, sender_name, chat_id, full_text,
timestamp TIMESTAMPTZ, is_director BOOLEAN, ingested_at,
media_mimetype, media_dropbox_path, media_size_bytes
```
Helper: `SentinelStoreBack.store_whatsapp_message(msg_id, sender, sender_name, chat_id, full_text, timestamp, is_director, ...)` at line 1751 — has `ON CONFLICT (id) DO UPDATE` so calls are naturally idempotent.

**Direction signal — no new columns needed:**
- Email outbound: `sender_email = "dvallen@brisengroup.com"` (Director's address) IS the direction marker. Retrievers / matter desks filter by sender to distinguish outbound.
- WhatsApp outbound: existing `is_director: BOOLEAN` column IS the direction marker. True for Director-sent.
- iPhone-export distinguishability: encode source into the `id` PK via prefix `iphone:<chat_id>:<timestamp_iso>:<is_director_bit>:<body_md5_short>`. Query `WHERE id LIKE 'iphone:%'` filters historical-backfill rows. Live-WAHA rows use the WAHA message id directly (existing pattern).

---

## Fix 1: Exchange Sent-Items polling

### Problem

`triggers/exchange_poller.py` polls only INBOX. Director's outbound from Outlook → never reaches Baker → not retrievable by Scan / RAG / matter desks. Verified: `EXCHANGE_FOLDER = "INBOX"` (line 23); `conn.select(EXCHANGE_FOLDER, readonly=True)` (line 111).

### Current State

- IMAP host: `exchange.evok.ch:993` (line 19-20). EVOK-hosted Exchange tenant.
- Auth: `EXCHANGE_USER=dvallen@brisengroup.com`, `EXCHANGE_PASS=<env>` (lines 21-22).
- Pipeline: `poll_exchange()` returns dicts identical to Gmail poller format; the dicts are fed into the same downstream classifier which ultimately calls `SentinelStoreBack.store_email_message()`.
- Watermark: `state.get_watermark("exchange_poll")` (line 99).
- Cap: `MAX_FETCH = 50` per cycle (line 28).

### Implementation

**Step 1.1 — Probe Sent folder name at runtime.** Different IMAP servers use different conventions (`Sent`, `Sent Items`, `INBOX.Sent`). EVOK convention undocumented; must probe via `IMAP LIST`.

Add to `triggers/exchange_poller.py` after line 28:

```python
SENT_FOLDER_CANDIDATES = ["Sent Items", "Sent", "INBOX.Sent"]
WATERMARK_KEY_SENT = "exchange_poll_sent"
SOURCE_TYPE_SENT = "exchange_sent"  # tag on the pipeline dict; helps debugging logs


def _detect_sent_folder(conn) -> str | None:
    """Probe IMAP LIST for the Sent folder. Returns actual folder name or None."""
    try:
        status, folders = conn.list()
        if status != "OK":
            logger.warning(f"IMAP LIST failed: {status}")
            return None
        folder_names = []
        for raw in folders:
            try:
                decoded = raw.decode("utf-8", errors="replace")
                if '"' in decoded:
                    folder_names.append(decoded.rsplit('"', 2)[-2])
            except Exception:
                continue
        for candidate in SENT_FOLDER_CANDIDATES:
            if candidate in folder_names:
                return candidate
        logger.warning(f"No Sent folder found in: {folder_names[:20]}")
        return None
    except Exception as e:
        logger.error(f"_detect_sent_folder error: {e}")
        return None
```

**Step 1.2 — Add `poll_exchange_sent()`.** Mirrors `poll_exchange()` body byte-for-byte except: (a) selects the detected Sent folder, (b) uses separate watermark key.

**Direction handling:** do NOT inject `metadata.source` / `metadata.direction` into the dict and expect them to persist — they will NOT. `email_messages` has no such columns (verified). The sender_email column IS the direction signal because every Sent-folder row will have `sender_email = "dvallen@brisengroup.com"`. Downstream retrievers and matter desks distinguish outbound by sender filter — no code change required there.

```python
def poll_exchange_sent() -> list:
    """Poll EVOK Exchange Sent folder. Mirrors poll_exchange() return shape.

    Direction is implicit: every Sent row has sender_email = EXCHANGE_USER
    (Director's address). No metadata.source / metadata.direction tagging
    needed — the storage layer has no such columns.

    Empty list on: EXCHANGE_PASS missing, IMAP failure, Sent folder not found."""
    if not EXCHANGE_PASS:
        logger.warning("EXCHANGE_PASS not set — skipping Exchange Sent poll")
        return []

    from triggers.state import TriggerState
    state = TriggerState()
    wm = state.get_watermark(WATERMARK_KEY_SENT)

    results = []
    conn = None
    try:
        conn = imaplib.IMAP4_SSL(EXCHANGE_IMAP_HOST, EXCHANGE_IMAP_PORT)
        conn.login(EXCHANGE_USER, EXCHANGE_PASS)
        sent_folder = _detect_sent_folder(conn)
        if not sent_folder:
            return []
        status, _ = conn.select(f'"{sent_folder}"', readonly=True)
        if status != "OK":
            logger.warning(f"IMAP select '{sent_folder}' failed: {status}")
            return []

        # Mirror poll_exchange() UID/SEARCH/FETCH loop EXACTLY (lines ~100-160).
        # Only differences:
        #   - folder name (above)
        #   - watermark key (WATERMARK_KEY_SENT)
        #   - tag the dict's metadata.source = SOURCE_TYPE_SENT for logs only
        # No dedup logic — downstream store_email_message() ON CONFLICT handles it.
    except Exception as e:
        logger.error(f"poll_exchange_sent failed: {e}")
        return []
    finally:
        if conn:
            try:
                conn.logout()
            except Exception:
                pass

    if results:
        latest_uid = max(r["metadata"]["uid"] for r in results)
        state.set_watermark(WATERMARK_KEY_SENT, str(latest_uid))

    return results
```

**Step 1.3 — Dedup is automatic.** `SentinelStoreBack.store_email_message()` at `memory/store_back.py:1665-1678` has `ON CONFLICT (message_id) DO UPDATE`. If a Sent-folder Message-ID already exists in `email_messages` (rare — only on self-CC or reply-quoting-original-id), the upsert is a no-op-equivalent. **Remove the brief v1 `_msgid_already_stored()` helper entirely.** No `emails` table exists; the brief v1 dedup helper queried a non-existent table.

**Step 1.4 — Wire into scheduler.** Find where `poll_exchange()` is called from (likely `triggers/scheduler.py` or `triggers/embedded_scheduler.py` — verify with grep before editing). Add `poll_exchange_sent()` call IMMEDIATELY AFTER the existing `poll_exchange()` call, inside its OWN try/except (lesson #45 — sequential pollers must be independent).

```python
try:
    inbox_results = poll_exchange()
    if inbox_results:
        process_messages(inbox_results)
except Exception as e:
    logger.error(f"exchange INBOX poll failed: {e}")

try:
    sent_results = poll_exchange_sent()
    if sent_results:
        process_messages(sent_results)
except Exception as e:
    logger.error(f"exchange Sent poll failed: {e}")
```

### Key Constraints

- Do NOT modify `poll_exchange()` itself. Adding a sibling.
- Reuse `_decode_header_value()`, `_extract_body()`, `_extract_sender()` — do not duplicate.
- Watermark key MUST be separate (`exchange_poll_sent`).
- Independent try/except per lesson #45.
- Do NOT add metadata.direction / metadata.source columns to email_messages. Sender-email-is-direction is the contract.
- `MAX_FETCH = 50` per cycle.

### Verification

1. **Unit:** `tests/test_exchange_sent_poller.py` with `mock.patch("imaplib.IMAP4_SSL")`:
   - Sent folder probe finds "Sent Items" when LIST returns it.
   - Returns None when no candidate.
   - Watermark advances.
   - (No dedup test — handled by store_email_message ON CONFLICT.)
2. **Manual smoke after deploy:** Director sends a test email from Outlook to a third-party. Wait one poll cycle. SQL:

```sql
-- Are any outbound rows landing?
SELECT COUNT(*) AS outbound_24h
FROM email_messages
WHERE sender_email = 'dvallen@brisengroup.com'
  AND ingested_at > NOW() - INTERVAL '24 hours';

-- Compare to inbound for sanity (should both be non-zero on active days):
SELECT
  CASE WHEN sender_email = 'dvallen@brisengroup.com' THEN 'outbound' ELSE 'inbound' END AS dir,
  COUNT(*)
FROM email_messages
WHERE ingested_at > NOW() - INTERVAL '7 days'
GROUP BY 1;
```

---

## Fix 2: WhatsApp iPhone-export ingest endpoint

### Problem

Director outbound on WhatsApp pre-2026-05-20 was never captured. WhatsApp multi-device protocol does NOT backfill history to linked devices, so WAHA cannot retroactively pull it. The only source is the iPhone "Export Chat" feature (per-counterparty .txt or .zip).

### Current State

- WAHA webhook (`triggers/waha_webhook.py`) captures live `fromMe=true` since 2026-05-20.
- Existing endpoints:
  - `POST /api/whatsapp/backfill` — pulls WAHA's own history range (not iPhone-sourced)
  - `GET /api/whatsapp/messages` (outputs/dashboard.py:1016) — read endpoint
- Storage helper: `SentinelStoreBack.store_whatsapp_message()` at `memory/store_back.py:1751`. Idempotent via ON CONFLICT on `id`.
- Schema (verified line 1698-1715): `id TEXT PK, sender, sender_name, chat_id, full_text, timestamp, is_director, ingested_at, media_*`. **No `source`, no `from_me`, no `original_timestamp`, no `imported_at`, no `contact_name`.**

### Implementation

**Step 2.1 — Endpoint.** Add `POST /api/whatsapp/import_iphone_export` to `outputs/dashboard.py` next to existing `/api/whatsapp/*` routes (search for `/api/whatsapp/backfill`). Confirm no existing collision: `grep -n "/api/whatsapp/import_iphone_export" outputs/dashboard.py` must return 0 hits.

```python
@app.post(
    "/api/whatsapp/import_iphone_export",
    tags=["whatsapp"],
    dependencies=[Depends(verify_api_key)],
)
async def whatsapp_import_iphone_export(
    file: UploadFile = File(...),
    counterparty_phone: str = Form(...),
    counterparty_name: str = Form(...),
    director_name: str = Form("Dimitry Vallen"),
):
    """Ingest iPhone WhatsApp 'Export Chat' .txt file as historical messages.

    Form fields:
      file: .txt from iPhone "Export Chat" (without media)
      counterparty_phone: e.g. "+393358345678" → canonical chat_id "393358345678@c.us"
      counterparty_name: human-readable label (e.g. "Peter Storer")
      director_name: substring used to set is_director=True (default "Dimitry Vallen")

    Returns:
      {ingested, skipped_duplicates, skipped_system, first_timestamp, last_timestamp}
    """
    content = (await file.read()).decode("utf-8", errors="replace")
    messages = parse_iphone_export(content, director_name=director_name)
    if not messages:
        raise HTTPException(status_code=422, detail="No parseable messages in upload")

    store = _get_store()
    ingested, skipped = _ingest_iphone_messages(
        store, messages, counterparty_phone, counterparty_name
    )
    return {
        "ingested": ingested,
        "skipped_duplicates": skipped,
        "first_timestamp": messages[0]["timestamp"].isoformat(),
        "last_timestamp": messages[-1]["timestamp"].isoformat(),
    }
```

**Step 2.2 — Parser** (unchanged from v1 — codex verified the regex pattern is sound):

```python
import re
from datetime import datetime

_IPHONE_WA_LINE = re.compile(r'^\[(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}), (\d{1,2}:\d{2}:\d{2})\] (.+?): (.*)$')


def parse_iphone_export(text: str, director_name: str = "Dimitry Vallen") -> list[dict]:
    """Return list of {timestamp, sender, body, is_director}."""
    messages = []
    current = None
    for raw in text.splitlines():
        m = _IPHONE_WA_LINE.match(raw)
        if m:
            if current is not None:
                messages.append(current)
            date_str, time_str, sender, body = m.groups()
            ts = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
                try:
                    ts = datetime.strptime(f"{date_str} {time_str}", fmt)
                    break
                except ValueError:
                    continue
            if ts is None:
                continue
            current = {
                "timestamp": ts,
                "sender": sender.strip(),
                "body": body,
                "is_director": director_name.lower() in sender.lower(),
            }
        elif current is not None:
            current["body"] = current["body"] + "\n" + raw
    if current is not None:
        messages.append(current)

    return [
        m for m in messages
        if m["body"].strip()
        and not m["body"].lstrip().startswith("‎")
        and "<This message was deleted>" not in m["body"]
    ]
```

**Step 2.3 — Storage via existing helper.** Use `SentinelStoreBack.store_whatsapp_message()`. **Deterministic `id` for idempotency + iphone_export filterability:**

```python
import hashlib


def _iphone_export_id(chat_id: str, timestamp: datetime, is_director: bool, body: str) -> str:
    """Deterministic PK for iPhone-export rows. Prefix 'iphone:' makes them
    queryable via `WHERE id LIKE 'iphone:%'`. Same key on re-upload → ON CONFLICT
    upsert (no duplicate row)."""
    body_md5 = hashlib.md5(body.encode("utf-8")).hexdigest()[:12]
    ts_iso = timestamp.strftime("%Y%m%dT%H%M%S")
    bit = "1" if is_director else "0"
    return f"iphone:{chat_id}:{ts_iso}:{bit}:{body_md5}"


def _ingest_iphone_messages(store, messages, counterparty_phone, counterparty_name):
    """Upsert parsed messages via SentinelStoreBack.store_whatsapp_message()."""
    DIRECTOR_PHONE = "41799605092@c.us"
    chat_id = f"{counterparty_phone.lstrip('+')}@c.us"

    ingested = 0
    skipped_existing = 0
    for m in messages:
        msg_id = _iphone_export_id(chat_id, m["timestamp"], m["is_director"], m["body"])
        sender_phone = DIRECTOR_PHONE if m["is_director"] else chat_id
        sender_label = "Dimitry Vallen" if m["is_director"] else counterparty_name
        ok = store.store_whatsapp_message(
            msg_id=msg_id,
            sender=sender_phone,
            sender_name=sender_label,
            chat_id=chat_id,
            full_text=m["body"],
            timestamp=m["timestamp"].isoformat(),
            is_director=m["is_director"],
        )
        if ok:
            ingested += 1
        else:
            skipped_existing += 1
    return ingested, skipped_existing
```

**Idempotency contract:** the `id` is deterministic over `(chat_id, timestamp, is_director, body_md5)`. Re-uploading the same `.txt` produces the same ids → `ON CONFLICT (id) DO UPDATE` makes the second upload effectively a no-op (it touches `full_text + ingested_at` but doesn't add rows). Counter `ingested` from the helper return value will be inflated on re-upload because the helper returns True for upserts too; if exact "new vs existing" reporting is needed, query `whatsapp_messages` for the id before calling and increment a separate `skipped_duplicates` counter. **Acceptable for v1: report `ingested` as upsert count; flag the nuance in the endpoint response.**

**Step 2.4 — Distinguishing iphone_export rows downstream.** Filter via the `id` prefix:

```sql
-- All iPhone-export rows
SELECT chat_id, COUNT(*), MIN(timestamp), MAX(timestamp)
FROM whatsapp_messages
WHERE id LIKE 'iphone:%'
GROUP BY chat_id;

-- iPhone-export rows for a specific counterparty
SELECT timestamp, is_director, full_text
FROM whatsapp_messages
WHERE id LIKE 'iphone:%'
  AND chat_id = '393358345678@c.us'  -- Storer / Bick / etc.
ORDER BY timestamp;
```

No new column, no migration. Matter desks add `WHERE id LIKE 'iphone:%'` when they want historical-only, or `WHERE id NOT LIKE 'iphone:%'` for live-WAHA-only.

### Key Constraints

- Use `_get_store()` from `outputs/dashboard.py:245` to get the SentinelStoreBack instance. Do NOT roll a new `_get_db_conn()` helper (codex finding 4 — that name does not exist in the dashboard).
- Use `SentinelStoreBack.store_whatsapp_message()` — do NOT write a parallel INSERT path.
- Endpoint path MUST NOT collide with `/api/whatsapp/backfill` or `/api/whatsapp/messages`. Confirmed no collision on `/import_iphone_export` (codex verified).
- Idempotent via deterministic `id` prefix + ON CONFLICT.
- Auth: `dependencies=[Depends(verify_api_key)]`.
- `.zip` uploads: return 501 with "media import not yet supported" — out of scope.
- Skip placeholders: `‎<encrypted>`, `<This message was deleted>`, empty bodies.
- Do NOT add `source` / `from_me` / `original_timestamp` / `imported_at` / `contact_name` columns. None exist; brief v1 invoked them in error.

### Verification

1. **Unit (`tests/test_iphone_export_parser.py`):**
   - 3-message synthetic fixture; one continuation; one deleted-placeholder.
   - Date auto-detect handles `2026-05-12, 14:23:01` vs `12/05/2026, 14:23:01`.
   - `is_director` flag correct when sender matches `director_name`.
2. **Endpoint (`tests/test_iphone_export_endpoint.py`):**
   - 401 without `X-Baker-Key`.
   - 200 on multipart upload with valid auth.
   - Idempotency: re-uploading the same file → second response has 0 NEW rows in DB (count via `SELECT COUNT(*) WHERE id LIKE 'iphone:%' AND chat_id = ?` before/after).
3. **Manual smoke (Director-provided file, post-deploy):**
   - Director taps "Export Chat" on iPhone WA for Storer thread → AirDrops .txt to MacBook → curl upload.
   - Verify:

```sql
SELECT COUNT(*) AS rows,
       MIN(timestamp) AS first_msg,
       MAX(timestamp) AS last_msg,
       SUM(CASE WHEN is_director THEN 1 ELSE 0 END) AS director_outbound
FROM whatsapp_messages
WHERE id LIKE 'iphone:%'
  AND chat_id = '<storer-phone>@c.us';
```

---

## Files Modified

- `triggers/exchange_poller.py` — add `_detect_sent_folder()`, `poll_exchange_sent()`, related constants.
- `triggers/scheduler.py` (or `embedded_scheduler.py` — verify which calls `poll_exchange()`) — add sibling call to `poll_exchange_sent()` in its own try/except.
- `outputs/dashboard.py` — add `/api/whatsapp/import_iphone_export` endpoint + `parse_iphone_export()` + `_iphone_export_id()` + `_ingest_iphone_messages()` helpers.
- `tests/test_exchange_sent_poller.py` — new.
- `tests/test_iphone_export_parser.py` — new.
- `tests/test_iphone_export_endpoint.py` — new.

## Do NOT Touch

- `poll_exchange()` itself.
- `/api/whatsapp/backfill` endpoint.
- `triggers/waha_webhook.py` — going-forward capture already correct (PR #235).
- `triggers/waha_message_utils.py` — import helpers if needed; do not modify.
- `whatsapp_messages` and `email_messages` schemas — no migrations. Direction encoded via existing fields.
- `SentinelStoreBack.store_*_message()` — call, do not modify.

## Quality Checkpoints

1. `poll_exchange()` (INBOX) still passes existing tests.
2. Sent poller failure does NOT crash INBOX poller (independent try/except).
3. `EXCHANGE_PASS` env-var presence verified on Render after deploy.
4. iPhone parser handles `‎<This message was deleted>` and `‎<This message was edited>` placeholders.
5. `/api/whatsapp/import_iphone_export` returns 401 without auth header.
6. Idempotency proven — 2nd upload produces 0 net-new rows (count delta).
7. New endpoint does NOT shadow existing `/api/whatsapp/*` route — `grep -n "/api/whatsapp" outputs/dashboard.py`.
8. NO migrations shipped. If b1 finds an unforeseen schema reason a migration is needed, **surface as a blocker** rather than ship a quiet migration.
9. Outbound email rows queryable via `sender_email = 'dvallen@brisengroup.com'`.
10. Historical WA rows queryable via `id LIKE 'iphone:%'`.

## Lessons applied

- **#45 (sequential pollers / env var missing):** independent try/except blocks; verify EXCHANGE_PASS post-deploy.
- **WAHA outbound subscription coupling lesson:** not relevant — this brief does not touch WAHA subscription state.
- **Phantom helper:** brief v1 referenced `_get_db_conn()` (does not exist) — codex finding 4 caught; v2 uses `_get_store()`.
- **Column-name guessing:** brief v1 used non-existent columns (`source`, `original_timestamp`, `from_me`, `imported_at`, `contact_name`) — codex findings 1 + 3 caught; v2 verified against `memory/store_back.py:1665-1715`.
- **Wrong table reference:** brief v1 queried `emails` (does not exist) — codex finding 3 caught; v2 uses `email_messages`.
- **Endpoint shadowing:** checkpoint #7 + Step 2.1 explicit grep.

## Verification SQL (post-deploy)

```sql
-- Phase 1: outbound rows landing?
SELECT COUNT(*) AS outbound_24h
FROM email_messages
WHERE sender_email = 'dvallen@brisengroup.com'
  AND ingested_at > NOW() - INTERVAL '24 hours';

-- Phase 1: in/outbound mix sanity check
SELECT
  CASE WHEN sender_email = 'dvallen@brisengroup.com' THEN 'outbound' ELSE 'inbound' END AS dir,
  COUNT(*)
FROM email_messages
WHERE ingested_at > NOW() - INTERVAL '7 days'
GROUP BY 1;

-- Phase 2: iPhone-export rows present?
SELECT COUNT(*) AS rows,
       COUNT(DISTINCT chat_id) AS counterparties,
       MIN(timestamp) AS earliest
FROM whatsapp_messages
WHERE id LIKE 'iphone:%';

-- Phase 2: per-counterparty breakdown
SELECT chat_id,
       COUNT(*) AS msgs,
       SUM(CASE WHEN is_director THEN 1 ELSE 0 END) AS director_outbound
FROM whatsapp_messages
WHERE id LIKE 'iphone:%'
GROUP BY chat_id;
```

## Definition of Done

1. PR opened on baker-master against `main` — single PR covering both phases.
2. Pytest passes on literal run — paste tail output in ship report.
3. Render auto-deploy succeeds.
4. Manual smoke: ≥1 outbound row written after deploy (Director sends a test email; b1 verifies via SQL).
5. iPhone import endpoint returns 200 on synthetic fixture upload.
6. Ship report at `briefs/_reports/B1_BAKER_CAPTURE_BLINDSPOTS_1_<YYYYMMDD>.md` — anchor commit hash, pytest tail, verification SQL outputs.
7. Bus-post `from b1 to lead` on ship with topic `ship/baker-capture-blindspots-1`.

## Reply target

`lead` (AH1). Ship report path above; bus-post on completion.
