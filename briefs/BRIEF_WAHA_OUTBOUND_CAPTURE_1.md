# BRIEF: BRIEF_WAHA_OUTBOUND_CAPTURE_1 — Capture Director outbound at webhook + canonicalize chat_id + RAG direction tagging

## Context

WhatsApp outbound from Director's phone (messages he types himself, not sent through Baker's `whatsapp_sender.py`) was never captured at real-time. The webhook explicitly drops every `fromMe=true` event at `triggers/waha_webhook.py:834`. The 6-hourly backfill was supposed to catch them but stores the same conversation under TWO different `chat_id` values (webhook = LID-form `<digits>@lid`, backfill = phone-form `<digits>@s.whatsapp.net`), which are not joined in the schema. Net effect: Julia Kvashnina chat shows 14 inbound, 0 outbound, even though Director replied today.

Full investigation + architect verdict + reviewer audit: `baker-vault/_ops/investigations/2026-05-20-waha-capture-gaps.md` (commit `dcf0c2a` + addendum). Director directive 2026-05-20 ~16:00Z: *"investigate fully first, then plan, then consult with architect and reviewer, then prepare brief, then check again, then commit and PR. etc. This is a persistent item that needs to be taken with care, please."* Director ratified Phase 5 brief draft 2026-05-21.

### Surface contract: N/A — pure backend; no clickable surface, no frontend route, no Slack Block Kit, no email-rendered HTML. The `/api/whatsapp/messages` change in Fix 7 exposes a new boolean field in an existing JSON response; UI visual indicator is deferred to a separate fast-follow brief (`BRIEF_DASHBOARD_WA_DIRECTION_INDICATOR_1`, PINNED §X #10).

## Estimated time: ~1.5-2.5h
## Complexity: High
## Prerequisites: none (no deploy ordering; migration script runs BEFORE deploy in Step 8)
## Trigger class: HIGH (capture-authority change — alters who is authoritative for outbound storage; lifts a filter that downstream consumers depend on). 2nd-pass `feature-dev:code-reviewer` fires per SKILL.md §Code-reviewer 2nd-pass criteria 4 (external-surface) + 7 (high-stakes judgment).

---

## API & Endpoint References (Rule 1-3)

| Surface | Version / Endpoint | Last verified | Fallback |
|---|---|---|---|
| WAHA webhook payload (`event=message`) | WAHA-Plus NoWeb engine | 2026-05-20 (logs + DB) | No vendor migration announced |
| WAHA `/api/{session}/chats` | GET, `limit=N` query | 2026-05-20 (direct call) | No fallback |
| WAHA `/api/{session}/lids/{lid}` | GET, returns `{"pn": "<phone>"}` | 2026-05-20 (via `resolve_lid()`) | None-cache existing |
| Baker `/api/whatsapp/messages` | GET, `X-Baker-Key` auth | 2026-05-20 (PR #218 ship) | n/a — backend endpoint |

WAHA-Plus has no formal API versioning; the engine version is pinned at deploy time on `baker-waha.onrender.com` (Render service `srv-d6hiiff5r7bs73euhd4g`). No deprecation notice from the upstream WAHA project as of today.

---

## DB Schema Check (Rule 4 — migration-vs-bootstrap DDL drift trap)

`whatsapp_messages` DDL lives at `memory/store_back.py:1531-1563` (`_ensure_whatsapp_messages_table`). Confirmed columns:

```
id TEXT PRIMARY KEY
sender TEXT
sender_name TEXT
chat_id TEXT
full_text TEXT
timestamp TIMESTAMPTZ
is_director BOOLEAN DEFAULT FALSE
ingested_at TIMESTAMPTZ DEFAULT NOW()
media_mimetype TEXT          (added via ALTER, line 1551-1556)
media_dropbox_path TEXT      (same)
media_size_bytes INTEGER     (same)
```

**No `direction` column exists.** `outputs/push_sender.py:138 + :143` reference `wm.direction` on `whatsapp_messages` — that query has been silently broken (caught by surrounding `try/except`). Fix 6 below replaces it with `is_director` semantics.

**No new column needed for this brief.** All changes are data normalization (chat_id values) + new code paths reading existing columns. This is NOT a schema migration; it is a one-shot Python data-patch script (Step 8).

---

## Implementation

### Fix 1 — Shared helper `attribute_sender()` (new file)

**Why:** webhook + backfill currently duplicate the "if fromMe then re-attribute" logic in two places (backfill has it at `scripts/extract_whatsapp.py:64-70`; webhook needs it for the first time). Architect Q3 verdict: single shared helper.

**File:** `triggers/waha_message_utils.py` (NEW)

```python
"""WhatsApp message attribution utilities — shared between webhook + backfill.

Anchor: BRIEF_WAHA_OUTBOUND_CAPTURE_1.
"""
from __future__ import annotations

# Director's WhatsApp identifiers. WAHA uses two JID formats interchangeably:
#   @c.us             — canonical "contact" form, what the webhook delivers
#   @s.whatsapp.net   — legacy "session" form, what backfill /chats returns
DIRECTOR_WHATSAPP_CUS = "41799605092@c.us"
DIRECTOR_WHATSAPP_JID = "41799605092@s.whatsapp.net"
DIRECTOR_WHATSAPP_IDS = (DIRECTOR_WHATSAPP_CUS, DIRECTOR_WHATSAPP_JID)


def attribute_sender(
    raw_sender: str,
    raw_sender_name: str,
    from_me: bool,
) -> tuple[str, str, bool]:
    """Return (sender, sender_name, is_director) given raw webhook/backfill fields.

    When fromMe=True, the upstream WAHA payload's `from` field is the REMOTE
    party (counterparty), not Director. Re-attribute to Director's canonical
    @c.us JID and label sender_name = "Director".

    When fromMe=False, pass through unchanged but still set is_director if the
    raw sender happens to be one of Director's known JIDs (defensive — should
    not occur in webhook flow but does occur in backfill of historic data).
    """
    if from_me:
        return DIRECTOR_WHATSAPP_CUS, "Director", True

    is_director = raw_sender in DIRECTOR_WHATSAPP_IDS
    return raw_sender, raw_sender_name, is_director
```

**Constraints:**
- Module is pure: no DB access, no network calls, no logging side-effects. Pure function = trivial to unit-test, no fault-tolerance wrapping needed.
- Constants are duplicated from `scripts/extract_whatsapp.py:38-39` deliberately — backfill will import from this new module in Fix 2 to retire the duplicate.

---

### Fix 2 — Webhook lift `fromMe` filter + call shared helper

**Current state:** `triggers/waha_webhook.py:829-835`:

```python
# Only process incoming messages (not our own outbound)
if event_type != "message":
    return {"status": "ignored", "event": event_type}

payload = body.get("payload", {})
if payload.get("fromMe", False):
    return {"status": "ignored", "reason": "outbound"}
```

**Change:** lift the `fromMe` filter. Inline sender extraction at lines 837-839 becomes the helper call. Keep the `event_type != "message"` guard (orthogonal).

**File:** `triggers/waha_webhook.py`

Replace lines 829-843 with:

```python
# Only process message events (session events handled above)
if event_type != "message":
    return {"status": "ignored", "event": event_type}

payload = body.get("payload", {})
from_me = payload.get("fromMe", False)

# Extract message data
raw_sender = payload.get("from", "")
raw_sender_name = payload.get("_data", {}).get("notifyName", raw_sender)

# BRIEF_WAHA_OUTBOUND_CAPTURE_1: shared sender attribution. When fromMe=True,
# re-attribute sender to Director (the "from" field is the remote party).
from triggers.waha_message_utils import attribute_sender
sender, sender_name, is_director_msg = attribute_sender(raw_sender, raw_sender_name, from_me)

message_body = payload.get("body", "")
timestamp = payload.get("timestamp", 0)
has_media = payload.get("hasMedia", False)
msg_id = payload.get("id", "")
```

**Constraints:**
- Do NOT remove the `event_type != "message"` guard. WAHA sends session events through the same endpoint.
- `is_director_msg` is a new local; existing downstream code paths use `sender == DIRECTOR_WHATSAPP` comparisons (`triggers/waha_webhook.py:34` defines `DIRECTOR_WHATSAPP = "41799605092@c.us"`). Those continue to work unchanged because attribute_sender returns `DIRECTOR_WHATSAPP_CUS = "41799605092@c.us"` for fromMe=True, which equals the existing constant.
- LID resolution block at lines 845-858 stays in place — runs after attribute_sender; for fromMe=True the sender is already `@c.us` form, so the `if sender.endswith("@lid")` branch becomes a no-op.

---

### Fix 3 — Chat-id normalization via `resolve_lid()`

**Why:** Phase 2 evidence — webhook stores `chat_id = '16462794231969@lid'`, backfill (when it can iterate) stores `chat_id = '41796720083@s.whatsapp.net'`, same conversation, not joined.

Architect Q2 verdict: normalize at webhook write time using the existing `resolve_lid()` at `triggers/waha_client.py:96-150`. No new column.

**File:** `triggers/waha_webhook.py`

After the LID-resolution block at lines 845-858 (which resolves `sender`), add chat_id normalization. The chat_id arrives in `payload["from"]` already (for non-fromMe events) OR `payload["to"]` (for fromMe events) — but both routes converge: the chat_id is the JID of the COUNTERPARTY in the conversation, regardless of direction.

Insert after line 858 (end of existing LID block for sender):

```python
# BRIEF_WAHA_OUTBOUND_CAPTURE_1: chat_id canonicalization.
# Webhook delivers chat_id in @lid form; backfill stores @s.whatsapp.net form
# for the same conversation. Normalize to @c.us (Director's outbound is
# addressed to @c.us when Baker initiates; counterparty inbound resolves to
# @c.us via resolve_lid). Store phone-form; fall back to raw LID with warning
# if resolution fails (so we don't drop the row).
chat_id = payload.get("chatId") or payload.get("from") or sender
if from_me:
    # On outbound events the chat_id is the recipient, in payload.to
    chat_id = payload.get("to") or chat_id

if chat_id.endswith("@lid"):
    try:
        from triggers.waha_client import resolve_lid as _resolve_chat_lid
        _resolved_chat = _resolve_chat_lid(chat_id)
        if _resolved_chat:
            logger.info(f"chat_id LID normalized: {chat_id} → {_resolved_chat}")
            chat_id = _resolved_chat
        else:
            logger.warning(f"chat_id LID unresolved (storing raw): {chat_id}")
    except Exception as e:
        logger.warning(f"chat_id LID resolution failed for {chat_id}: {e}")
```

Then locate all subsequent `store_whatsapp_message(...)` and `_record_*` calls inside this handler that currently pass either no `chat_id` argument or pass `sender` as chat_id. Update them to pass the normalized `chat_id` local.

**Specifically** — grep `store_whatsapp_message` inside `triggers/waha_webhook.py`. Pass the new `chat_id` local + `is_director_msg` (NOT recomputed inline).

**Constraints:**
- Do NOT remove the `None`-caching at `triggers/waha_client.py:141`. Repeated unresolvable LIDs would otherwise hammer the WAHA API.
- Do NOT block the write on resolution failure. Store raw `@lid` value + log warning. The migration script (Fix 8) catches up later if/when resolution becomes possible.
- Do NOT change `resolve_lid()` itself.

---

### Fix 4 — Director routing discriminator (HIGH — reviewer H1)

**Why:** the existing Director-block at `triggers/waha_webhook.py:1100-1159` invokes `_handle_director_question` (RAG-answer Director's question via Baker) on the assumption that every fromMe message went FROM Director TO Baker. Lifting the fromMe filter means this block fires for EVERY outbound — including Director's "see you Friday" reply to Julia. Baker would try to RAG-answer Julia's casual reply.

**Discriminator:** the chat_id distinguishes Director-to-Baker from Director-to-counterparty. Baker's own WhatsApp identity (the "self chat" / Baker's bot number) is the one chat_id where Director-to-Baker conversations land. Every other chat_id is a counterparty.

**Question for verification:** What is Baker's WhatsApp self-chat identifier? Grep `BAKER_WHATSAPP\|SELF_CHAT\|baker.*whatsapp_id` across the codebase to find the canonical constant; if none exists, the chat_id where Director's inbound currently lands (pre-lift) is the answer — find it via:

```sql
SELECT DISTINCT chat_id, COUNT(*) FROM whatsapp_messages
WHERE sender = '41799605092@c.us' OR is_director = TRUE
GROUP BY chat_id ORDER BY 2 DESC LIMIT 10;
```

The highest-count chat_id where Director writes is Baker's self-chat. **If grep finds an existing constant, use it. If grep finds nothing, define it in `triggers/waha_message_utils.py`** alongside the Director constants, with comment citing the SQL query above as derivation method.

**File:** `triggers/waha_webhook.py`

Replace the Director block guard at line 1077, 1086, 1102 (three locations all using `if sender == DIRECTOR_WHATSAPP and combined_body:`). Split into two distinct conditions:

```python
# BRIEF_WAHA_OUTBOUND_CAPTURE_1: Director routing discriminator.
# Director-to-Baker (chat_id == BAKER_SELF_CHAT) → full RAG / action / deadline path.
# Director-to-counterparty (any other chat_id) → storage + PM-signal-outbound only.
from triggers.waha_message_utils import BAKER_SELF_CHAT  # or constant location chosen

director_to_baker = (sender == DIRECTOR_WHATSAPP and chat_id == BAKER_SELF_CHAT and combined_body)
director_to_counterparty = (sender == DIRECTOR_WHATSAPP and chat_id != BAKER_SELF_CHAT and combined_body)
```

Then:
- Line 1077 (PM-SIGNAL outbound) — gate on `if (director_to_baker or director_to_counterparty):` (i.e. any Director outbound; PM signal IS the point of capturing outbound).
- Line 1086 (YouTube auto-ingest) — gate on `if director_to_baker:` only. Director sharing a YouTube link with a counterparty is not a Baker-ingest signal.
- Line 1100-1159 (action detection + deadline extraction + obligations + question handler) — gate on `if director_to_baker:` only. Director-to-counterparty messages do NOT fire `_handle_director_message`, `_handle_director_question`, `extract_deadlines`, or the obligations-detect block. They get stored (Fix 2/3) and that is all.

**Constraints:**
- Do NOT route Director-to-counterparty into the existing `_handle_director_question` RAG flow. That would have Baker RAG-answer Julia's "ok see you" as if it were a question for Baker — H1 anti-pattern.
- Do NOT remove PM-SIGNAL outbound for Director-to-counterparty — that flow at line 1077-1083 is exactly why we are capturing outbound. PM-signal fires for both.
- If BAKER_SELF_CHAT cannot be determined (grep + SQL query both empty), STOP and surface to AH1. Do NOT guess.

---

### Fix 5 — RAG direction tagging (HIGH — reviewer H2)

**Why:** `memory/retriever.py:1057` (`get_whatsapp_messages`) and `:1102` (`get_recent_whatsapp`) both emit `content = f"[WHATSAPP] {sender} ({date_str}): {text}"`. Once Director's outbound is in the DB, RAG context will surface "Dimitry Vallen: Let's sign on Friday" with no direction marker — the LLM cannot distinguish "Director committed to X" from "counterparty asked about X".

**File:** `memory/retriever.py`

Both methods need:
1. SELECT clause adds `is_director`.
2. Content prefix uses direction tag.

For `get_whatsapp_messages` (lines 1029-1074), replace the SELECT and the content-format line:

```python
cur.execute(
    """
    SELECT id, sender, sender_name, full_text, timestamp, is_director
    FROM whatsapp_messages
    WHERE sender_name ILIKE %s
       OR full_text ILIKE %s
    ORDER BY timestamp DESC NULLS LAST
    LIMIT %s
    """,
    (f"%{query}%", f"%{query}%", limit),
)
rows = cur.fetchall()
cols = ["id", "sender", "sender_name", "full_text", "timestamp", "is_director"]
cur.close()

contexts = []
for row in rows:
    data = {c: v for c, v in zip(cols, row) if v is not None}
    text = data.get("full_text", "")
    sender = data.get("sender_name") or data.get("sender") or "Unknown"
    date = data.get("timestamp", "")
    date_str = str(date)[:10] if date else ""
    # BRIEF_WAHA_OUTBOUND_CAPTURE_1: tag direction so LLM distinguishes
    # Director's outbound commitments from counterparty inbound asks.
    tag = "WHATSAPP-OUTBOUND" if data.get("is_director") else "WHATSAPP-INBOUND"

    content = f"[{tag}] {sender} ({date_str}): {text}"
    contexts.append(RetrievedContext(
        content=content,
        source="whatsapp",
        score=0.95,
        metadata={
            "type": "whatsapp_message",
            "label": f"WhatsApp: {sender}",
            "date": date_str,
            "msg_id": data.get("id"),
            "is_director": bool(data.get("is_director")),
        },
        token_estimate=self._estimate_tokens(content),
    ))
```

Apply equivalent change to `get_recent_whatsapp` (lines 1076-end of method) — same SELECT addition, same tag logic, same metadata addition. Keep the `score=0.85` value unchanged.

**Constraints:**
- Do NOT filter outbound OUT of RAG. Reviewer's recommendation explicitly favors the tag approach because Director's outbound IS valuable context ("what did Dimitry commit to Julia?").
- Do NOT change the score values. Tagging is orthogonal to relevance ranking.
- `is_director IS NULL` is treated as inbound (the boolean default is FALSE; historic rows that never set it still surface as INBOUND, which matches their behavior pre-fix).

---

### Fix 6 — SQL guards on consumers that assumed inbound-only (MEDIUM)

Reviewer's MEDIUM items 4 + 16. (Items 22 + 23 are covered by Fix 5; item 27 by Fix 7.)

#### 6a. Trip-context linker (`triggers/waha_webhook.py:993-1004`)

**Current state:** `link_to_trip_context` fires for every sender — once Director outbound flows in, "see you in Vienna" said by Director to a counterparty would link to the active trip and surface on the trip card as "incoming intelligence."

**Change:** wrap the block in `if sender != DIRECTOR_WHATSAPP:`. Director's mentions of his own trips are not signals.

```python
# BRIEF_WAHA_OUTBOUND_CAPTURE_1: only counterparty mentions link to trip
# intelligence — Director's own outbound is not "incoming intelligence."
if sender != DIRECTOR_WHATSAPP:
    try:
        from memory.store_back import SentinelStoreBack
        _store_tc = SentinelStoreBack._get_global_instance()
        _wa_ts2 = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat() if timestamp else None
        _store_tc.link_to_trip_context(
            content=combined_body[:500] if combined_body else "",
            source_type="whatsapp", source_ref=f"wa:{msg_id}",
            timestamp=_wa_ts2,
        )
    except Exception:
        pass
```

#### 6b. Morning push unanswered VIP (`outputs/push_sender.py:131-147`)

**Current state:** SQL references `wm.direction = 'inbound'` and `wm2.direction = 'outbound'`. The `whatsapp_messages` table has NO `direction` column — only `is_director`. This query has been silently failing (caught by an outer try/except).

**Change:** replace direction-column references with `is_director` semantics. Inbound = `is_director = FALSE`; outbound = `is_director = TRUE`. NOT a simple "add another WHERE clause" — the existing references are broken.

```python
# 4. Unanswered VIP messages (>4h)
# BRIEF_WAHA_OUTBOUND_CAPTURE_1: whatsapp_messages has no `direction` column;
# direction is encoded in is_director. Inbound = NOT is_director; outbound =
# is_director (Director's reply suppresses the alert).
cur.execute("""
    SELECT vc.name, wm.full_text, wm.timestamp
    FROM whatsapp_messages wm
    JOIN vip_contacts vc ON wm.sender = vc.whatsapp_id
    WHERE vc.tier <= 2
      AND wm.timestamp >= NOW() - INTERVAL '24 hours'
      AND wm.is_director = FALSE
      AND wm.timestamp <= NOW() - INTERVAL '4 hours'
      AND NOT EXISTS (
          SELECT 1 FROM whatsapp_messages wm2
          WHERE wm2.chat_id = wm.chat_id
            AND wm2.is_director = TRUE
            AND wm2.timestamp > wm.timestamp
      )
    ORDER BY wm.timestamp DESC LIMIT 5
""")
```

Positive side-effect: once outbound flows into the DB (Fix 2), the anti-join now actually suppresses alerts when Director has replied. Today it can't because there is no Director outbound to anti-join against.

#### 6c. Sister sites that already use `is_director` (no change needed)

For situational awareness; do NOT edit these — they already do the right thing. Listed so the build worker can confirm them at touch-time:

- `outputs/dashboard.py:2683` — `WHERE wm.is_director = FALSE`
- `outputs/dashboard.py:2688` — `AND reply.is_director = TRUE`
- `outputs/dashboard.py:3814` — `AND wm.is_director = false`
- `triggers/proactive_scanner.py:78` — `AND is_director = FALSE`
- `triggers/proactive_scanner.py:170` — `WHERE is_director = TRUE`
- `triggers/briefing_trigger.py:215` — `WHERE is_director = true`
- `orchestrator/decision_engine.py:649-663` — VIP SLA check (already uses anti-join on `reply.is_director=TRUE`; improves automatically)

---

### Fix 7 — `/api/whatsapp/messages` exposes `is_director`

**File:** `outputs/dashboard.py:1016-end-of-function`

The endpoint currently returns rows with `id, timestamp, sender, sender_name, chat_id, full_text, has_media`. Add `is_director` to the SELECT + response. UI visual indicator is deferred to a separate brief (PINNED §X #10 — `BRIEF_DASHBOARD_WA_DIRECTION_INDICATOR_1`).

Modify the SELECT at lines 1049-1058:

```python
cur.execute(
    """
    SELECT id, timestamp, sender, sender_name, chat_id, full_text,
           (media_dropbox_path IS NOT NULL) AS has_media,
           is_director
    FROM whatsapp_messages
    WHERE (sender ILIKE %s OR sender_name ILIKE %s OR chat_id ILIKE %s)
      AND timestamp >= %s
      AND timestamp < %s::date + INTERVAL '1 day'
    ORDER BY timestamp ASC
    LIMIT %s
    """,
    (f"%{contact}%", f"%{contact}%", f"%{contact}%", from_date, to_date, limit),
)
```

The downstream `dict(zip(cols, row))` at line 1064 picks up the new field automatically via `cur.description`. The `_format_wa_md` helper at lines around 1010 may need a tweak if it should display `[OUT]`/`[IN]` markers in markdown format — read the helper first and decide per existing style. Minimum: JSON format MUST return `is_director` as a boolean field.

**Constraints:**
- Do NOT rename existing fields. Downstream desks (Brisen Desk, AO Desk, etc.) consume this response and will break on a field rename.
- Do NOT add a `direction` derived field if there isn't one already. Pass `is_director` through; let desks compute the string label if they want it.

---

### Fix 8 — One-shot data migration script

**Why:** existing rows already store some chat_ids in @lid form. After Fix 3, NEW writes use phone-form; OLD rows stay in @lid form. The dashboard's WHERE ILIKE clause masks this for queries by phone substring (PR #232), but joins by chat_id (e.g. anti-join in Fix 6b) require canonical form.

Architect Q2 verdict: data patch, NOT a schema migration. Runs BEFORE the code deploy.

**File:** `scripts/migrate_whatsapp_chat_id_normalize.py` (NEW)

```python
"""One-shot: normalize whatsapp_messages.chat_id from @lid to @c.us form.

Reads distinct @lid chat_ids, calls resolve_lid(), UPDATEs rows. Idempotent —
re-running on already-normalized rows is a no-op. Unresolvable LIDs remain
as-is (logged).

Anchor: BRIEF_WAHA_OUTBOUND_CAPTURE_1.

Usage (on Render shell OR local with DATABASE_URL set):
    cd /opt/render/project/src && python scripts/migrate_whatsapp_chat_id_normalize.py
"""
from __future__ import annotations
import logging
import sys

from memory.store_back import SentinelStoreBack
from triggers.waha_client import resolve_lid

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        logger.error("No DB connection; aborting.")
        return 1

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT chat_id
            FROM whatsapp_messages
            WHERE chat_id LIKE %s
            LIMIT 5000
            """,
            ("%@lid",),
        )
        lid_chats = [row[0] for row in cur.fetchall()]
        cur.close()
    except Exception as e:
        logger.error(f"Failed to enumerate @lid chat_ids: {e}")
        conn.rollback()
        store._put_conn(conn)
        return 1

    logger.info(f"Found {len(lid_chats)} distinct @lid chat_ids to attempt normalization on.")

    resolved = 0
    unresolved = 0
    updated_rows = 0
    for lid_chat in lid_chats:
        phone = resolve_lid(lid_chat)
        if not phone:
            unresolved += 1
            logger.info(f"  unresolved: {lid_chat}")
            continue
        resolved += 1
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE whatsapp_messages SET chat_id = %s WHERE chat_id = %s",
                (phone, lid_chat),
            )
            updated_rows += cur.rowcount
            conn.commit()
            cur.close()
            logger.info(f"  normalized: {lid_chat} → {phone} ({cur.rowcount} rows)")
        except Exception as e:
            logger.warning(f"UPDATE failed for {lid_chat}: {e}")
            conn.rollback()

    store._put_conn(conn)
    logger.info(
        f"Migration complete: {resolved} resolved / {unresolved} unresolved / "
        f"{updated_rows} rows updated."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Constraints:**
- Script MUST be idempotent — re-running on a DB where all chat_ids are already phone-form should produce zero updates.
- LIMIT 5000 on the DISTINCT query caps the worst-case workload at one invocation. Re-run if more remain (log line surfaces this).
- DO NOT alter the schema. No `ALTER TABLE`. No new columns.
- Singleton pattern: `SentinelStoreBack._get_global_instance()` (Rule 8) — no direct `SentinelStoreBack()` construction.
- Run BEFORE the code deploy. If run AFTER, new writes from Fix 3 are already phone-form and the script becomes a no-op on the new rows but still catches up historic rows.

**Operational handoff (Rule 9):** if AH1 invokes this script from a working tree (not Render shell), the working tree MUST be at post-merge HEAD: `cd ~/baker-master && git pull --rebase origin main && python scripts/migrate_whatsapp_chat_id_normalize.py`. A stale checkout would import old `resolve_lid()` semantics.

---

### Fix 9 — Tests

**File:** `tests/test_waha_outbound_capture.py` (NEW)

Cover four classes:

1. **`attribute_sender` unit tests** (5 cases): fromMe=True returns Director; fromMe=False with random sender returns pass-through; fromMe=False with DIRECTOR_WHATSAPP_CUS as sender returns is_director=True; fromMe=False with DIRECTOR_WHATSAPP_JID returns is_director=True; empty sender + fromMe=False returns ("", "", False).

2. **Webhook integration — fromMe=True flow** (mock WAHA payload): assert `store_whatsapp_message` is called with `sender=DIRECTOR_WHATSAPP_CUS`, `sender_name="Director"`, `is_director=True`. Use existing webhook test fixtures if present at `tests/test_waha_*.py`; otherwise build minimal one.

3. **Webhook integration — Director-to-counterparty routing** (mock fromMe=True payload with chat_id != BAKER_SELF_CHAT): assert `_handle_director_question` is NOT called; assert `flag_pm_signal` (PM-SIGNAL outbound) IS called.

4. **Webhook integration — Director-to-Baker routing** (mock fromMe=True payload with chat_id == BAKER_SELF_CHAT): assert `_handle_director_question` IS called; assert `flag_pm_signal` IS also called (PM signal fires for both — see Fix 4 constraint).

5. **RAG tagging** (`memory/retriever.py`): insert one inbound + one outbound row into a test DB (`TEST_DATABASE_URL` is auto-skipped when unset per repo convention); call `get_whatsapp_messages(query=<keyword>)`; assert returned contexts contain `[WHATSAPP-OUTBOUND]` for is_director=True and `[WHATSAPP-INBOUND]` for is_director=False.

6. **chat_id normalization migration** (use ephemeral Neon branch via CI; locally skip): seed 2 rows with `chat_id = '16462794231969@lid'`; mock `resolve_lid` to return `'41796720083@c.us'`; run `migrate_whatsapp_chat_id_normalize.main()`; assert both rows now have `chat_id = '41796720083@c.us'`.

**Ship gate (Rule 5):** `pytest tests/test_waha_outbound_capture.py -v` MUST produce literal green output. No "pass by inspection." The full suite `pytest` must also pass.

---

## Files Modified

- `triggers/waha_message_utils.py` (NEW) — shared `attribute_sender()` + Director/Baker constants
- `triggers/waha_webhook.py` — lift fromMe filter, call shared helper, normalize chat_id, split Director routing discriminator, gate trip-context linker
- `memory/retriever.py` — `get_whatsapp_messages` + `get_recent_whatsapp` SELECT `is_director` + tag content with `[WHATSAPP-OUTBOUND]`/`[WHATSAPP-INBOUND]`
- `outputs/dashboard.py` — `/api/whatsapp/messages` SELECT exposes `is_director`
- `outputs/push_sender.py` — replace broken `wm.direction` references with `is_director` semantics
- `scripts/migrate_whatsapp_chat_id_normalize.py` (NEW) — one-shot data patch
- `scripts/extract_whatsapp.py` — refactor to import constants + helper from `triggers/waha_message_utils.py` (retire inline duplicate at lines 38-39, 64-70). Backfill semantics unchanged.
- `tests/test_waha_outbound_capture.py` (NEW) — 6 test classes per Fix 9

Estimated diff: ~250-350 LOC. Across 6 modified + 3 new files = 9 surfaces. Within scope envelope.

## Do NOT Touch

- `memory/store_back.py:1531-1626` — `_ensure_whatsapp_messages_table` DDL + `store_whatsapp_message` signature. Schema stays as-is.
- `triggers/waha_client.py:96-150` — `resolve_lid()` internals. Reuse, do not modify.
- `triggers/embedded_scheduler.py:225-233` — backfill scheduler. Confirmed firing per Phase 2; do not retune.
- `outputs/whatsapp_sender.py:329-444` — send path. Architect Q1: send-time keeps writing only to `baker_actions`, NOT to `whatsapp_messages`. No change here.
- `triggers/waha_webhook.py:34` — `DIRECTOR_WHATSAPP` constant. Equal to `DIRECTOR_WHATSAPP_CUS` by design. Do not rename.
- Anything outside the 9 surfaces above.

## Quality Checkpoints

1. `python3 -c "import py_compile; py_compile.compile('triggers/waha_webhook.py', doraise=True)"` clean
2. Same for `triggers/waha_message_utils.py`, `memory/retriever.py`, `outputs/dashboard.py`, `outputs/push_sender.py`, `scripts/migrate_whatsapp_chat_id_normalize.py`, `scripts/extract_whatsapp.py`
3. `bash scripts/check_singletons.sh` exits 0 (Rule 8 singleton pattern check)
4. `pytest tests/test_waha_outbound_capture.py -v` — literal green
5. Full `pytest` — literal green (or all existing failures predate this PR per `pytest` baseline)
6. **Production smoke after merge** (AH1 owns): post-deploy, send a test message from Director's phone to a non-Baker contact; within ~5s confirm:
   ```sql
   SELECT id, sender, sender_name, chat_id, is_director, timestamp
   FROM whatsapp_messages
   WHERE is_director = TRUE
   ORDER BY ingested_at DESC LIMIT 3;
   ```
   Latest row has `is_director=TRUE`, `sender='41799605092@c.us'`, `sender_name='Director'`, `chat_id` in `@c.us` form.
7. Confirm Render logs for that test message do NOT show `_handle_director_question` firing (because the test message went to a counterparty, not Baker).
8. Re-run migration script on Render shell after deploy: confirms idempotency (zero updates expected).

## Verification SQL

```sql
-- Q1: Director outbound now captured (compare to investigation baseline: 0 between May 18-20)
SELECT DATE(timestamp) AS day, COUNT(*) AS director_rows
FROM whatsapp_messages
WHERE is_director = TRUE
  AND timestamp >= NOW() - INTERVAL '7 days'
GROUP BY 1 ORDER BY 1 DESC;

-- Q2: Chat-id normalization — no @lid remaining (or only unresolvable ones)
SELECT chat_id, COUNT(*)
FROM whatsapp_messages
WHERE chat_id LIKE '%@lid'
GROUP BY 1 ORDER BY 2 DESC LIMIT 20;

-- Q3: Julia chat is now a single conversation (post-migration)
SELECT chat_id, is_director, COUNT(*)
FROM whatsapp_messages
WHERE chat_id ILIKE '%41796720083%' OR chat_id ILIKE '%16462794231969%'
GROUP BY 1, 2 ORDER BY 1, 2;

-- Q4: Unanswered VIP query produces non-error result (was silently failing on wm.direction)
-- Run the query body from outputs/push_sender.py:132-147 manually; expect a result set, not an error.
```

## Ship gate

Literal `pytest` output green (Rule 5). NO "pass by inspection" claims. Ship-report MUST include the actual pytest summary lines (PASS counts, failures = 0 OR pre-existing-baseline-only).

## Risk register

- **Lifting fromMe filter changes capture semantics fleet-wide.** Mitigated by Fix 4 routing discriminator (RAG / action handlers gated on `director_to_baker`) and Fix 5 RAG direction tagging. 2nd-pass code-reviewer fires per SKILL.md §Code-reviewer 2nd-pass — confirms no other downstream consumer was missed.
- **BAKER_SELF_CHAT determination** — if neither grep nor the SQL derivation finds a clear value, build worker STOPS and surfaces to AH1. Do not guess. Anchor: AID-engineering verification rule (memory `feedback_aid_proposals_need_engineer_verification.md`).
- **Render restart mid-deploy** — fix is stateless (no in-memory caches added). Restart is safe. WAHA session itself is stateful on the WAHA service (separate Render service); this PR does not touch WAHA service code.
- **WAHA contact-store integration for human names** — separate brief (`BRIEF_WHATSAPP_LID_HUMAN_NAME_RESOLVER_1`, PINNED §X #8). Do not solve here.
- **UI visual indicator** for direction in dashboard — separate brief (`BRIEF_DASHBOARD_WA_DIRECTION_INDICATOR_1`, PINNED §X #10). API change in Fix 7 makes the field available; UI ship is fast-follow.
- **3-day Julia gap recovery** — DROPPED per Director directive 2026-05-20 ~17:05Z. Out of scope; pre-fix Julia outbound is acceptable loss.

## Anchors

- Investigation: `baker-vault/_ops/investigations/2026-05-20-waha-capture-gaps.md` (commit `dcf0c2a` + addendum)
- PINNED §GG (this session): `baker-vault/_ops/agents/aihead1/PINNED.md` commit `4562f19`
- Director directive 2026-05-20 ~16:00Z (slow-path protocol)
- Director directive 2026-05-20 ~17:05Z (Q4 recovery dropped)
- Director ratification 2026-05-21 dawn ("go ahead, draft the brief")
- Architect verdict (`feature-dev:code-architect` `aecfa303efa9b50c7`, 2026-05-20 ~16:30Z)
- Reviewer audit (`feature-dev:code-reviewer` `aa9c81c3c1698e012`, 2026-05-20 ~16:45Z; 31 call sites scanned)

## Reporting

Brief dispatched by `lead` (AH1-Terminal). Worker bus-posts ship report back to `lead` per BRIEF_BUS_REPLY_TO_SENDER_RULE_1.
