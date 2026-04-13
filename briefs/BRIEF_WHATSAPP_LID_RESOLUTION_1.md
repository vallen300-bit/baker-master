# BRIEF: WHATSAPP-LID-RESOLUTION-1 — Resolve @lid WhatsApp IDs to phone numbers

## Context
WhatsApp completed migration from `@c.us` (phone-based) to `@lid` (opaque numeric) chat IDs. 100% of incoming messages now arrive as `@lid`. Baker's VIP contacts store `@c.us` phone numbers → no match → all contacts appear "unidentified." AO has 25+ messages stored without name resolution. Even Director detection (`sender == "41799605092@c.us"`) is at risk. WAHA provides a LID resolution API (since v2025.5.4) that we're not using.

## Estimated time: ~2-3h
## Complexity: Low-Medium
## Prerequisites: None — WAHA API already supports this

---

## Feature 1: LID Resolution Cache Table

### Problem
No persistent mapping between `@lid` and `@c.us` IDs. Each webhook would need to call WAHA API every time.

### Current State
No `whatsapp_lid_map` table exists. VIP contacts store `whatsapp_id` as `@c.us` format (496 contacts). Only 1 contact has `@lid` format (auto-created).

### Implementation

**File: `memory/store_back.py`**

Add table creation in `_ensure_tables()` (after whatsapp_messages table creation):

```python
cur.execute("""
    CREATE TABLE IF NOT EXISTS whatsapp_lid_map (
        lid TEXT PRIMARY KEY,
        phone TEXT,
        resolved_at TIMESTAMPTZ DEFAULT NOW(),
        source TEXT DEFAULT 'api'
    )
""")
conn.commit()
```

Add two methods after `store_whatsapp_message()`:

```python
def get_lid_phone(self, lid: str) -> Optional[str]:
    """Look up cached phone number for a @lid ID. Returns @c.us format or None."""
    conn = self._get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("SELECT phone FROM whatsapp_lid_map WHERE lid = %s LIMIT 1", (lid,))
        row = cur.fetchone()
        cur.close()
        return row[0] if row else None
    except Exception as e:
        logger.warning(f"LID cache lookup failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    finally:
        self._put_conn(conn)

def cache_lid_phone(self, lid: str, phone: str, source: str = "api") -> None:
    """Cache a @lid → @c.us mapping. Upsert — updates if exists."""
    conn = self._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO whatsapp_lid_map (lid, phone, source, resolved_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (lid) DO UPDATE SET phone = EXCLUDED.phone, resolved_at = NOW()
        """, (lid, phone, source))
        conn.commit()
        cur.close()
    except Exception as e:
        logger.warning(f"LID cache write failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        self._put_conn(conn)
```

### Key Constraints
- Table is small (hundreds of rows max) — no pagination needed
- Upsert pattern — safe for concurrent webhook calls
- `conn.rollback()` in all except blocks

---

## Feature 2: LID Resolution Function

### Problem
Need to resolve `@lid` → phone number using WAHA API, with caching to avoid repeated calls.

### Current State
`waha_client.py` has `_headers()` and `config.waha.base_url` already available. No LID resolution exists.

### Implementation

**File: `triggers/waha_client.py`**

Add after `get_session_status()` function (around line 65):

```python
# ------------------------------------------------------------------
# LID Resolution (WHATSAPP-LID-RESOLUTION-1)
# ------------------------------------------------------------------

# In-memory LRU to avoid DB hit on every message in same process
_lid_mem_cache: dict[str, Optional[str]] = {}

def resolve_lid(lid: str) -> Optional[str]:
    """Resolve a @lid WhatsApp ID to a @c.us phone number.

    Resolution order:
    1. In-memory cache (instant)
    2. PostgreSQL whatsapp_lid_map table (fast)
    3. WAHA API GET /api/{session}/lids/{lid} (network call)

    Returns @c.us phone string or None if unresolvable.
    Caches result at all levels (including None to avoid re-querying).
    """
    if not lid or not lid.endswith("@lid"):
        return None

    # 1. Memory cache
    if lid in _lid_mem_cache:
        return _lid_mem_cache[lid]

    # 2. PostgreSQL cache
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        cached = store.get_lid_phone(lid)
        if cached:
            _lid_mem_cache[lid] = cached
            return cached
    except Exception:
        pass

    # 3. WAHA API
    phone = None
    try:
        lid_escaped = lid.replace("@", "%40")
        url = f"{config.waha.base_url}/api/{config.waha.session}/lids/{lid_escaped}"
        resp = httpx.get(url, headers=_headers(), timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            pn = data.get("pn")  # e.g. "41799605092@c.us" or None
            if pn:
                phone = pn
                logger.info(f"LID resolved via API: {lid} → {phone}")
    except Exception as e:
        logger.warning(f"WAHA LID API call failed for {lid}: {e}")

    # Cache result (even None — avoids re-querying unresolvable LIDs)
    _lid_mem_cache[lid] = phone
    if phone:
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            store.cache_lid_phone(lid, phone, source="api")
        except Exception:
            pass

    return phone
```

### Key Constraints
- **5-second timeout** on WAHA API call — must not block webhook processing
- Cache `None` results too — prevents hammering API for permanently unresolvable LIDs
- In-memory cache survives for process lifetime (cleared on Render restart — that's fine, PG cache persists)
- `_lid_mem_cache` is process-local. Two Render instances may both call API once — acceptable, PG dedup handles it

---

## Feature 3: Hook into Webhook Handler

### Problem
`waha_webhook.py` line 833-834 extracts `sender` and `sender_name` from payload. All downstream logic (Director check, contact matching, PM signal detection, auto-contact creation) uses these raw values. When `sender` is `@lid`, everything breaks.

### Current State
```python
# Line 833-834
sender = payload.get("from", "")
sender_name = payload.get("_data", {}).get("notifyName", sender)
```

`DIRECTOR_WHATSAPP = "41799605092@c.us"` (line 34) — hardcoded `@c.us`.

### Implementation

**File: `triggers/waha_webhook.py`**

**Step 1:** After line 834 (after extracting sender and sender_name), add LID resolution block:

```python
    sender = payload.get("from", "")
    sender_name = payload.get("_data", {}).get("notifyName", sender)
    message_body = payload.get("body", "")
    timestamp = payload.get("timestamp", 0)
    has_media = payload.get("hasMedia", False)
    msg_id = payload.get("id", "")

    # WHATSAPP-LID-RESOLUTION-1: Resolve @lid to @c.us phone number
    original_lid = None
    if sender.endswith("@lid"):
        original_lid = sender
        try:
            from triggers.waha_client import resolve_lid
            resolved = resolve_lid(sender)
            if resolved:
                sender = resolved
                logger.info(f"LID resolved: {original_lid} → {sender}")
            else:
                logger.info(f"LID unresolved: {original_lid} (sender_name={sender_name})")
        except Exception as e:
            logger.warning(f"LID resolution failed for {sender}: {e}")

    # If sender_name is still a raw LID number, try VIP name lookup by resolved phone
    if sender_name and sender_name.replace("@lid", "").replace("@c.us", "").isdigit():
        try:
            from memory.store_back import SentinelStoreBack
            _store_name = SentinelStoreBack._get_global_instance()
            _conn_name = _store_name._get_conn()
            if _conn_name:
                try:
                    _cur_name = _conn_name.cursor()
                    _cur_name.execute(
                        "SELECT name FROM vip_contacts WHERE whatsapp_id = %s LIMIT 1",
                        (sender,),
                    )
                    _row_name = _cur_name.fetchone()
                    if _row_name and _row_name[0]:
                        sender_name = _row_name[0]
                        logger.info(f"Resolved sender_name from VIP: {sender_name}")
                    _cur_name.close()
                finally:
                    _store_name._put_conn(_conn_name)
        except Exception:
            pass
```

**Step 2:** In `store_whatsapp_message()` call (line 906-917), store BOTH the resolved sender AND original LID:

Change line 910 from:
```python
            chat_id=sender,
```
to:
```python
            chat_id=original_lid or sender,
```

This preserves the original `@lid` as `chat_id` for traceability while `sender` is the resolved `@c.us`.

**Step 3:** In auto-contact creation (line 963-989), the `sender` is now resolved to `@c.us`, so the VIP lookup `WHERE whatsapp_id = %s` will match existing contacts correctly. New contacts will be stored with `@c.us` format. No code change needed — the resolution above handles it.

### Key Constraints
- Resolution happens ONCE at the top of the handler — all downstream code uses resolved `sender`
- If resolution fails, `sender` stays as `@lid` — existing behavior, no worse than today
- `original_lid` preserved for `chat_id` storage — audit trail
- Director check `sender == DIRECTOR_WHATSAPP` now works because `sender` is resolved to `@c.us`
- No changes to `DIRECTOR_WHATSAPP` constant needed

### Verification
After deploy, send a WhatsApp message from AO's number. Check:
```sql
-- Should show resolved sender for new messages
SELECT id, sender, sender_name, chat_id, LEFT(full_text, 50) as preview
FROM whatsapp_messages
WHERE timestamp > NOW() - INTERVAL '1 hour'
ORDER BY timestamp DESC LIMIT 10;

-- Should have cached mappings
SELECT * FROM whatsapp_lid_map ORDER BY resolved_at DESC LIMIT 20;

-- AO should now be identified
SELECT sender, sender_name, COUNT(*)
FROM whatsapp_messages
WHERE sender LIKE '%79167717771%' OR chat_id LIKE '%2847596888279%'
GROUP BY sender, sender_name LIMIT 10;
```

---

## Feature 4: Backfill Existing @lid VIP Contacts

### Problem
1 VIP contact already has `@lid` as `whatsapp_id`. Future auto-created contacts from before this fix also have `@lid`. Need a one-time update.

### Implementation

**One-time SQL (run manually after deploy):**

```sql
-- Check how many VIP contacts have @lid format
SELECT name, whatsapp_id FROM vip_contacts WHERE whatsapp_id LIKE '%@lid' LIMIT 20;
```

Then use the WAHA bulk endpoint to get all known mappings:
```
GET /api/{session}/lids?limit=500
```

And update VIP contacts accordingly. This is manual — not worth automating for 1 contact.

---

## Files Modified
- `memory/store_back.py` — `whatsapp_lid_map` table + `get_lid_phone()` + `cache_lid_phone()`
- `triggers/waha_client.py` — `resolve_lid()` function with 3-layer resolution
- `triggers/waha_webhook.py` — LID resolution block after sender extraction (line ~835)

## Do NOT Touch
- `outputs/dashboard.py` — no dashboard changes needed
- `orchestrator/capability_runner.py` — no agent changes
- `config/settings.py` — no new env vars (uses existing WAHA config)
- `triggers/embedded_scheduler.py` — no scheduler changes (daily group refresh deferred to separate brief if needed)

## Quality Checkpoints
1. Syntax check all 3 modified files
2. Send WhatsApp message from a known VIP → verify sender resolved in `whatsapp_messages`
3. Check `whatsapp_lid_map` table has cached entries
4. Verify Director messages are recognized (pipeline routes correctly)
5. Verify auto-contact creation stores `@c.us` not `@lid` for resolved contacts
6. Verify unresolvable LIDs don't crash the webhook (graceful fallback)
7. Check WAHA API timeout doesn't slow webhook response (should be <5s)

## Verification SQL
```sql
-- Confirm table exists and has data
SELECT COUNT(*) FROM whatsapp_lid_map;

-- Confirm new messages have resolved senders
SELECT sender, sender_name, chat_id, LEFT(full_text, 50)
FROM whatsapp_messages
WHERE timestamp > NOW() - INTERVAL '2 hours'
ORDER BY timestamp DESC LIMIT 10;

-- Confirm no more "unidentified" contacts being created with @lid
SELECT name, whatsapp_id FROM vip_contacts
WHERE whatsapp_id LIKE '%@lid'
ORDER BY added_at DESC LIMIT 10;
```
