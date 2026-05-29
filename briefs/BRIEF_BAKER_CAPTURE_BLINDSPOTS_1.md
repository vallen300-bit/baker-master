# BRIEF: BAKER_CAPTURE_BLINDSPOTS_1 — close Director outbound capture gaps on email + WhatsApp

## Context

Director directive 2026-05-29: *"If we have a gap in what I send to other people by WhatsApp or email, there is a problem. Baker is blind."*

### Surface contract: N/A — pure backend. No clickable surface, no frontend route, no Slack Block Kit, no email-rendered HTML. Phase 1 extends IMAP poller; Phase 2 adds an auth-gated REST endpoint consumed via curl. Dashboard rendering of `source=exchange_sent` / `source=iphone_export` rows is downstream of this brief (existing renderers already key off `metadata.source`).

Surfaced by origination-desk bus #1338 (NVIDIA project room) — both Storer (Corinthia) and Bick (MOHG/AI Hotel) communication threads have explicit `outbound_gap` flags. Investigation found two distinct root causes:

1. **Email:** `triggers/exchange_poller.py:23` hardcodes `EXCHANGE_FOLDER = "INBOX"`. Sent Items is NEVER polled. Every email Director sends from Outlook (dvallen@brisengroup.com) via the EVOK Exchange tenant is invisible to Baker. Ongoing structural gap.
2. **WhatsApp:** Outbound capture (`fromMe=true`) shipped 2026-05-20 via PR #235 (`0e08ce5`) + hot-fix `5af2971`. Going-forward outbound IS captured. But all pre-2026-05-20 outbound — including the Storer/Bick threads (2026-03 → 2026-05-13) — was dropped at the webhook. Historical gap only.

This brief closes both.

## Estimated time: ~5h
## Complexity: Medium
## Prerequisites: `EXCHANGE_PASS` valid on Render (currently set per recent restoration); WAHA session healthy (not used by this brief — iPhone export is the data source for Phase 2).

---

## Fix 1: Exchange Sent-Items polling

### Problem

`triggers/exchange_poller.py` polls only INBOX. Director's outbound from Outlook → never reaches Baker → not retrievable by Scan / RAG / matter desks. Verified: `EXCHANGE_FOLDER = "INBOX"` (line 23); `conn.select(EXCHANGE_FOLDER, readonly=True)` (line 111).

### Current State

- IMAP host: `exchange.evok.ch:993` (line 19-20). EVOK-hosted Exchange tenant.
- Auth: `EXCHANGE_USER=dvallen@brisengroup.com`, `EXCHANGE_PASS=<env>` (lines 21-22).
- Pipeline: `poll_exchange()` returns dicts identical to Gmail poller format; same downstream classifier.
- Watermark: `state.get_watermark("exchange_poll")` → message UIDs since last fetch (line 99).
- Cap: `MAX_FETCH = 50` per cycle (line 28).
- Source tag: `SOURCE_TYPE = "exchange"` (line 25) — currently no direction tag.

### Implementation

**Step 1.1** — Probe Sent folder name at module load. Different IMAP servers use different conventions (`Sent`, `Sent Items`, `INBOX.Sent`). EVOK convention not documented; must probe.

Add to `triggers/exchange_poller.py` after line 28:

```python
SENT_FOLDER_CANDIDATES = ["Sent Items", "Sent", "INBOX.Sent"]
WATERMARK_KEY_SENT = "exchange_poll_sent"
SOURCE_TYPE_SENT = "exchange_sent"


def _detect_sent_folder(conn) -> str | None:
    """Probe IMAP LIST for the Sent folder. Returns actual folder name or None.

    EVOK Exchange may expose Sent under any of SENT_FOLDER_CANDIDATES.
    Returns the first match found in the server's folder list."""
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

**Step 1.2** — Add `poll_exchange_sent()` mirroring `poll_exchange()`. Reuse helpers `_decode_header_value()`, `_extract_body()`, `_extract_sender()` (do NOT duplicate).

Structure:

```python
def poll_exchange_sent() -> list:
    """Poll EVOK Exchange Sent folder. Mirrors poll_exchange() but selects
    the Sent folder + uses separate watermark + tags rows as outbound.

    Returns list of dicts matching Gmail poller format with:
      metadata.source = "exchange_sent"
      metadata.direction = "outbound"

    Empty list on:
      - EXCHANGE_PASS not set
      - IMAP connect/login failure
      - Sent folder not detected
    """
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
            logger.warning("Sent folder not detected — skipping")
            return []
        status, _ = conn.select(f'"{sent_folder}"', readonly=True)
        if status != "OK":
            logger.warning(f"IMAP select '{sent_folder}' failed: {status}")
            return []

        # Mirror lines 100-160 of poll_exchange() — same UID/SEARCH/FETCH loop.
        # Only differences vs INBOX path:
        #   - folder name above
        #   - metadata.source = "exchange_sent"
        #   - metadata.direction = "outbound"
        #   - capture To header into metadata.to (not just From)
        #   - dedup via _msgid_already_stored() before append (see Step 1.3)
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

**Step 1.3 — Dedup vs INBOX (Message-ID).** A Sent email's `Message-ID` may already exist in the email storage table from a prior INBOX poll (rare — only happens if Director sent to himself, or a recipient replied and quoted the original Message-ID). Add a one-shot lookup before append:

```python
def _msgid_already_stored(conn_pg, message_id: str) -> bool:
    """Check storage table for existing message_id. Skip the write if found.
    Conservative — wraps in try/except and returns False on error
    (better to occasionally duplicate than to lose an outbound row)."""
    if not message_id:
        return False
    try:
        with conn_pg.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM emails WHERE message_id = %s LIMIT 1",
                (message_id,)
            )
            return cur.fetchone() is not None
    except Exception as e:
        logger.debug(f"_msgid_already_stored probe failed (continuing): {e}")
        return False
```

⚠️ **Before referencing `emails` table name above, verify the actual table name in the storage layer.** Grep `triggers/email_trigger.py` and the storage helper for the exact PG table where Exchange/Gmail rows land. Most likely `emails` or `email_messages` — confirm before writing the SQL. Column name `message_id` is the de-facto natural key — verify.

**Step 1.4 — Wire into scheduler.** Find where `poll_exchange()` is called from. Most likely `triggers/scheduler.py` or `triggers/embedded_scheduler.py`. Add `poll_exchange_sent()` call IMMEDIATELY AFTER the existing `poll_exchange()` call, inside its OWN try/except so an INBOX failure doesn't kill Sent and vice-versa (lesson #45 — sequential pollers must be independent).

Example pattern:

```python
# In scheduler tick — mirror existing exchange handling
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

- Do NOT modify `poll_exchange()` itself. Adding a sibling, not refactoring.
- Reuse helpers — do not duplicate logic.
- Watermark key MUST be separate (`exchange_poll_sent`) so INBOX and Sent advance independently.
- Wrap each top-level call in its own try/except (lesson #45).
- Direction tag `outbound` must propagate into the downstream classifier / RAG so retrieval can filter.
- `MAX_FETCH = 50` per cycle keeps initial backfill from blowing memory; will catch up over multiple ticks.

### Verification

1. **Unit:** new test `tests/test_exchange_sent_poller.py` with `mock.patch("imaplib.IMAP4_SSL")` covering:
   - Sent folder probe finds "Sent Items" when LIST returns it.
   - Sent folder probe returns None when LIST has no candidate.
   - Watermark advances after a successful fetch.
   - Dedup skips a message whose Message-ID exists in `emails`.
2. **Manual smoke after deploy (Render):** Director sends a test email from Outlook to a third-party. Wait ~5 min (next poll cycle). Verify with SQL below.

---

## Fix 2: WhatsApp iPhone-export ingest endpoint

### Problem

Director outbound on WhatsApp pre-2026-05-20 was never captured. WhatsApp's multi-device protocol does NOT backfill history to linked devices, so WAHA cannot retroactively pull it. The only source is the iPhone "Export Chat" feature (per-counterparty .txt or .zip).

### Current State

- WAHA webhook (`triggers/waha_webhook.py`) captures live `fromMe=true` since 2026-05-20.
- Existing endpoints (verified via grep):
  - `POST /api/whatsapp/backfill` — pulls WAHA's own history range (not iPhone-sourced)
  - `GET /api/whatsapp/messages` at `outputs/dashboard.py:1016` — read endpoint
- Schema reuse target: `whatsapp_messages` table (used by live WAHA writes + existing backfill).
- Canonical helpers: `triggers/waha_message_utils.py` — `attribute_sender()`, chat_id normalization, `DIRECTOR_WHATSAPP_CUS/JID` constants. Reuse, do NOT re-implement.

### Implementation

**Step 2.1 — Verify the schema.** Before writing INSERTs, grep for the actual `whatsapp_messages` table definition and confirm column names. Don't guess. Brief writer owns the bug if the schema reference is wrong.

```bash
grep -rn "CREATE TABLE.*whatsapp_messages\|whatsapp_messages\s*(" migrations/ | head -5
grep -n "INSERT INTO whatsapp_messages" triggers/waha_webhook.py | head -5
```

Use the live insert in `waha_webhook.py` as the schema reference — match its column list exactly.

**Step 2.2 — New endpoint** `POST /api/whatsapp/import_iphone_export`. Mounted in `outputs/dashboard.py` next to existing `/api/whatsapp/*` routes (search for `/api/whatsapp/backfill` to find the local cluster).

Endpoint name choice: explicitly different from `/backfill` (WAHA-sourced) so it's unambiguous in logs and audit. Lesson #4: duplicate endpoint paths get silently shadowed by FastAPI; before adding, grep `outputs/dashboard.py` to confirm `/api/whatsapp/import_iphone_export` is not already taken.

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
    director_role: bool = Form(True),
):
    """Ingest iPhone WhatsApp 'Export Chat' .txt file as historical messages.

    iPhone export format: line-based, one message per line; multi-line bodies are
    continuation lines without [date] prefix. Pre-2026-05-20 Director outbound
    only-source until M365/WAHA backfill becomes possible (it won't — WhatsApp
    multi-device protocol does not sync historical to linked devices).

    Form fields:
      file: .txt from iPhone "Export Chat" (without media)
      counterparty_phone: e.g. "+393358345678" — used to canonicalize chat_id
      counterparty_name: human-readable label (e.g. "Peter Storer")
      director_role: when True (default), sender == Director's name → from_me=true.

    Returns:
      {ingested, skipped_duplicates, skipped_system, first_timestamp, last_timestamp}
    """
    # ... (see Step 2.3 for parser, Step 2.4 for storage)
```

**Step 2.3 — Parser.** iPhone export format (verified — iOS WhatsApp 24.x, English locale; brief author has NOT tested DE/FR locales — flag if the auto-detect fails on Director's actual export):

```
[YYYY-MM-DD, HH:MM:SS] <Sender Name>: <message body line 1>
<message body line 2 — no [date] prefix, continuation>
[YYYY-MM-DD, HH:MM:SS] <Other Sender>: <next message>
```

Parser rules:
- Lines starting with `[` + valid date → new message.
- Lines NOT starting with `[` → append to prior message body with `\n`.
- Skip messages where body equals `‎<encrypted>` or `<This message was deleted>` or starts with `‎`.
- Auto-detect date format from first 10 message lines: try `%Y-%m-%d, %H:%M:%S`, fall back to `%d/%m/%Y, %H:%M:%S`, fall back to `%m/%d/%Y, %H:%M:%S`. Stick with the first that parses on row 1; if none, return 422.

Skeleton:

```python
import re
from datetime import datetime

_IPHONE_WA_LINE = re.compile(r'^\[(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}), (\d{1,2}:\d{2}:\d{2})\] (.+?): (.*)$')


def parse_iphone_export(text: str, director_name: str = "Dimitry Vallen") -> list[dict]:
    """Return list of {timestamp, sender, body, from_me}. Caller maps to whatsapp_messages.

    director_name: case-insensitive substring used to set from_me=true. Configurable
    because iPhone exports use the contact name as Director saved it (e.g. "Dimitry V").
    """
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
                "from_me": director_name.lower() in sender.lower(),
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

**Step 2.4 — Storage.** Convert parsed dicts to `whatsapp_messages` rows. Use `attribute_sender()` from `triggers/waha_message_utils.py` to get canonical chat_id form. Insert with `source='iphone_export'`. Idempotency key: `(chat_id, original_timestamp, from_me, md5(body))`.

```python
def _ingest_to_whatsapp_messages(messages, counterparty_phone, counterparty_name):
    import hashlib
    from triggers.waha_message_utils import attribute_sender
    chat_id = f"{counterparty_phone.lstrip('+')}@c.us"

    ingested = 0
    skipped = 0
    conn = _get_db_conn()  # use existing helper from outputs/dashboard.py
    try:
        with conn.cursor() as cur:
            for m in messages:
                body_hash = hashlib.md5(m["body"].encode("utf-8")).hexdigest()
                cur.execute(
                    """
                    SELECT 1 FROM whatsapp_messages
                    WHERE chat_id = %s
                      AND original_timestamp = %s
                      AND from_me = %s
                      AND md5(full_text) = %s
                    LIMIT 1
                    """,
                    (chat_id, m["timestamp"], m["from_me"], body_hash),
                )
                if cur.fetchone():
                    skipped += 1
                    continue
                # INSERT — column list MUST match live waha_webhook.py insert.
                # Illustrative shape; verify before final implementation:
                cur.execute(
                    """
                    INSERT INTO whatsapp_messages
                    (chat_id, sender, full_text, from_me, original_timestamp,
                     source, imported_at, contact_name)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s)
                    """,
                    (chat_id, m["sender"], m["body"], m["from_me"],
                     m["timestamp"], "iphone_export", counterparty_name),
                )
                ingested += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    return ingested, skipped
```

⚠️ The column list above is illustrative — **before writing the final INSERT, verify against the live `waha_webhook.py` insert + `whatsapp_messages` schema**. Mismatched column names = brief writer's bug.

### Key Constraints

- Reuse `attribute_sender()` + chat_id helpers from `triggers/waha_message_utils.py`. Do NOT re-implement.
- Endpoint path MUST NOT collide with `/api/whatsapp/backfill` or `/api/whatsapp/messages` — use exact name `import_iphone_export`.
- Idempotent: re-uploading same .txt → 0 new rows.
- Auth: `dependencies=[Depends(verify_api_key)]` — match existing WhatsApp endpoint pattern.
- `.zip` upload (export-with-media): return 501 with "media import not yet supported" — out of scope.
- Skip placeholders: `‎<encrypted>`, `<This message was deleted>`, empty bodies.

### Verification

1. **Unit:** `tests/test_iphone_export_parser.py`:
   - Parses 3-message synthetic fixture (one continuation, one deleted-placeholder).
   - Date-format auto-detect handles `2026-05-12, 14:23:01` vs `12/05/2026, 14:23:01`.
   - `from_me` flag set correctly when sender matches `director_name`.
2. **Endpoint integration:** `tests/test_iphone_export_endpoint.py`:
   - 401 without `X-Baker-Key`.
   - 200 with valid auth + multipart upload.
   - Idempotency: 2nd upload of same file returns `ingested=0, skipped_duplicates=N`.
3. **Manual smoke (Director-provided file, post-deploy):**
   - Director taps "Export Chat" in iPhone WhatsApp for Storer thread → AirDrops .txt to MacBook → curls upload.
   - Verify with SQL below.

---

## Files Modified

- `triggers/exchange_poller.py` — add `_detect_sent_folder()`, `poll_exchange_sent()`, related constants. Do NOT modify `poll_exchange()`.
- `triggers/scheduler.py` (or `embedded_scheduler.py` — verify which calls `poll_exchange()`) — add sibling call to `poll_exchange_sent()` in its own try/except.
- `outputs/dashboard.py` — add `/api/whatsapp/import_iphone_export` endpoint + parser + ingest helper.
- `tests/test_exchange_sent_poller.py` — new.
- `tests/test_iphone_export_parser.py` — new.
- `tests/test_iphone_export_endpoint.py` — new.

## Do NOT Touch

- `poll_exchange()` itself — extending, not refactoring.
- `/api/whatsapp/backfill` endpoint — different data source, do not merge logic.
- `triggers/waha_webhook.py` — going-forward capture is already correct (PR #235); no changes.
- `triggers/waha_message_utils.py` — import helpers, do not modify.
- `whatsapp_messages` schema — no migrations needed; reuse existing columns. If a new `source` enum value isn't allowed by an existing CHECK constraint, surface as a blocker — do NOT silently add a migration without flagging.

## Quality Checkpoints

1. `poll_exchange()` (INBOX) still passes its existing tests — Sent addition didn't regress.
2. Sent poller failure does NOT crash INBOX poller (independent try/except).
3. `EXCHANGE_PASS` env-var presence verified on Render after deploy (lesson #45 — silent missing env caused 3-day Gmail silence).
4. iPhone parser handles `‎<This message was deleted>` and `‎<This message was edited>` placeholders.
5. `/api/whatsapp/import_iphone_export` returns 401 without auth header.
6. Idempotency proven — 2nd upload of same file returns 0 ingested.
7. New endpoint does NOT shadow existing `/api/whatsapp/*` route (FastAPI registers first match — verify with `grep -n "/api/whatsapp" outputs/dashboard.py`).
8. Migration check: confirm no new `source` enum value is needed for `iphone_export`, OR ship a migration if it is.

## Lessons applied

- **#27 (WAHA noweb store):** not relevant — this brief does not touch WAHA session state.
- **#45 (sequential pollers / env var missing):** independent try/except blocks; verify EXCHANGE_PASS post-deploy.
- **WAHA outbound subscription coupling (lessons.md anchor on PR #235 silent drop):** not relevant — Fix 2 uses iPhone export, not WAHA subscription. Phase 1 likewise doesn't touch WAHA.
- **Phantom helper / signature errors:** brief explicitly says "verify column list before INSERT" + "verify which scheduler file calls poll_exchange()".
- **Endpoint shadowing (lesson #4):** quality checkpoint #7 + Step 2.2 explicitly grep for existing routes.

## Verification SQL (post-deploy)

```sql
-- Phase 1: any Sent rows landed since deploy?
SELECT COUNT(*) AS sent_rows_24h
FROM emails
WHERE metadata->>'source' = 'exchange_sent'
  AND created_at > NOW() - INTERVAL '24 hours';

-- Phase 1: dedup didn't drop everything?
SELECT metadata->>'direction' AS dir, COUNT(*)
FROM emails
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY 1;

-- Phase 2: iPhone export rows present?
SELECT source, COUNT(*) AS rows, MIN(original_timestamp) AS earliest
FROM whatsapp_messages
WHERE source = 'iphone_export'
GROUP BY 1;
```

## Definition of Done

1. PR opened on baker-master against `main` — single PR covering both phases (small enough; tightly related).
2. Pytest passes on literal run — paste tail output in ship report (no "pass by inspection").
3. Render auto-deploy succeeds.
4. Manual smoke: ≥1 Sent Items row written after deploy (Director sends a test email; b1 verifies via SQL).
5. iPhone import endpoint returns 200 on synthetic fixture upload (b1 verifies in test).
6. Ship report at `briefs/_reports/B1_BAKER_CAPTURE_BLINDSPOTS_1_<YYYYMMDD>.md` — anchor commit hash, pytest output tail, verification SQL outputs.
7. Bus-post `from b1 to lead` on ship (per `agent-bus-posting-contract.md`).

## Reply target

`lead` (AH1). Ship report path above; bus-post `from b1 to lead` on completion with topic `ship/baker-capture-blindspots-1`.
