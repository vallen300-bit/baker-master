# BRIEF: INTERACTION-PIPELINE-1 — Contact Interaction Extraction

**Status:** READY FOR REVIEW
**Author:** AI Head (Claude Code, Session 24)
**Date:** 2026-03-16
**Priority:** HIGH — unlocks Networking tab intelligence (going cold, unreciprocated, interaction timeline)
**Estimated cost:** ~$0 (pure SQL, no LLM calls)

---

## Problem

The `contact_interactions` table exists with proper schema but has **zero rows**. Three dashboard features depend on it:

1. **"Unreciprocated" alerts** — 2+ outbound messages with no inbound reply in 14 days → never fires
2. **Contact interaction timeline** — expand a contact → "Recent interactions" always empty
3. **Relationship scoring** — can't compute engagement frequency without interaction data

Meanwhile, the raw data exists: **2,500+ emails**, **1,490+ WhatsApp messages**, **200+ meetings** — all stored in PostgreSQL. The missing piece is the **link layer** that connects messages to contacts.

---

## Solution

A SQL-based extraction pipeline that:
1. **Backfills** historical interactions from email_messages, whatsapp_messages, meeting_transcripts
2. **Hooks into triggers** to extract interactions from new messages as they arrive
3. **Keeps `last_contact_date` in sync** automatically

---

## Target Table

```sql
-- Already exists (store_back.py line 1405)
contact_interactions (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER REFERENCES vip_contacts(id),
    channel VARCHAR(30),        -- 'email', 'whatsapp', 'meeting'
    direction VARCHAR(10),      -- 'inbound', 'outbound', 'bidirectional'
    timestamp TIMESTAMPTZ,
    subject TEXT,               -- email subject / WA snippet / meeting title
    sentiment VARCHAR(20),      -- NULL initially (Phase 2: Haiku classification)
    source_ref TEXT,            -- 'email:msg_id', 'wa:msg_id', 'meeting:transcript_id'
    created_at TIMESTAMPTZ
)
```

---

## Batch 1: SQL Backfill (one-time)

### 1A. Email → Interactions

Match contacts by: exact name, exact email, reversed name, last-name substring.

```sql
INSERT INTO contact_interactions (contact_id, channel, direction, timestamp, subject, source_ref)
SELECT
    vc.id,
    'email',
    CASE WHEN LOWER(em.sender_email) LIKE '%@brisengroup.com' THEN 'outbound' ELSE 'inbound' END,
    em.received_date,
    LEFT(em.subject, 200),
    'email:' || em.message_id
FROM email_messages em
JOIN vip_contacts vc ON (
    LOWER(em.sender_name) = LOWER(vc.name)
    OR LOWER(em.sender_email) = LOWER(vc.email)
    OR (POSITION(' ' IN vc.name) > 0 AND LOWER(em.sender_name) = LOWER(
        SPLIT_PART(vc.name, ' ', 2) || ' ' || SPLIT_PART(vc.name, ' ', 1)
    ))
)
WHERE em.received_date IS NOT NULL
ON CONFLICT DO NOTHING;
```

**Direction logic:** `@brisengroup.com` sender = outbound (Director or team sent it). Everything else = inbound.

### 1B. WhatsApp → Interactions

Match contacts by: exact name, WhatsApp ID, last-name substring.

```sql
INSERT INTO contact_interactions (contact_id, channel, direction, timestamp, subject, source_ref)
SELECT
    vc.id,
    'whatsapp',
    CASE WHEN wm.is_director THEN 'outbound' ELSE 'inbound' END,
    wm.timestamp,
    LEFT(wm.full_text, 200),
    'wa:' || wm.id
FROM whatsapp_messages wm
JOIN vip_contacts vc ON (
    LOWER(wm.sender_name) = LOWER(vc.name)
    OR wm.sender = vc.whatsapp_id
    OR (vc.whatsapp_id IS NOT NULL AND wm.chat_id = vc.whatsapp_id)
)
WHERE wm.timestamp IS NOT NULL
ON CONFLICT DO NOTHING;
```

**Direction logic:** `is_director = true` → outbound. Otherwise → inbound.

### 1C. Meetings → Interactions

Match contacts by: full name or last name appearing in participants string.

```sql
INSERT INTO contact_interactions (contact_id, channel, direction, timestamp, subject, source_ref)
SELECT
    vc.id,
    'meeting',
    'bidirectional',
    mt.meeting_date,
    LEFT(mt.title, 200),
    'meeting:' || mt.id
FROM meeting_transcripts mt
JOIN vip_contacts vc ON (
    LOWER(mt.participants) LIKE '%' || LOWER(vc.name) || '%'
    OR (POSITION(' ' IN vc.name) > 0
        AND LOWER(mt.participants) LIKE '%' || LOWER(SPLIT_PART(vc.name, ' ', 2)) || '%')
)
WHERE mt.meeting_date IS NOT NULL
ON CONFLICT DO NOTHING;
```

**Direction:** All meetings are `bidirectional` — both parties present.

### 1D. Sync `last_contact_date`

After backfill, update all contacts' last_contact_date from the fresh interaction data:

```sql
UPDATE vip_contacts vc
SET last_contact_date = sub.max_ts
FROM (
    SELECT contact_id, MAX(timestamp) as max_ts
    FROM contact_interactions
    GROUP BY contact_id
) sub
WHERE vc.id = sub.contact_id
  AND (vc.last_contact_date IS NULL OR vc.last_contact_date < sub.max_ts);
```

---

## Batch 2: Ongoing Extraction (trigger hooks)

### 2A. Email trigger hook

**File:** `triggers/email_trigger.py`
**Where:** After storing to `email_messages` table, before pipeline.run()

```python
# After store to email_messages
_extract_email_interaction(store, message_id, sender_name, sender_email, subject, received_date)
```

Logic: Query `vip_contacts` for name/email match → INSERT into `contact_interactions` → UPDATE `last_contact_date`.

### 2B. WhatsApp webhook hook

**File:** `triggers/waha_webhook.py`
**Where:** After storing to `whatsapp_messages` table

```python
# After store to whatsapp_messages
_extract_wa_interaction(store, msg_id, sender_name, sender_id, body_snippet, timestamp, is_director)
```

Logic: Query `vip_contacts` for name/whatsapp_id match → INSERT → UPDATE `last_contact_date`.

### 2C. Fireflies trigger hook

**File:** `triggers/fireflies_trigger.py`
**Where:** After storing to `meeting_transcripts` table

```python
# After store to meeting_transcripts
_extract_meeting_interactions(store, transcript_id, title, participants, meeting_date)
```

Logic: Parse participants string → match each against `vip_contacts` → INSERT one row per matched contact → UPDATE `last_contact_date`.

### 2D. Shared extraction function

**File:** `memory/store_back.py` — new method

```python
def record_interaction(self, contact_id, channel, direction, timestamp, subject, source_ref):
    """Insert a contact interaction and update last_contact_date. Idempotent by source_ref."""
```

Idempotent: `INSERT ... ON CONFLICT (source_ref) DO NOTHING` — requires adding a UNIQUE constraint on `source_ref`.

---

## Batch 3: Dedup & Index

### 3A. Add unique constraint

```sql
ALTER TABLE contact_interactions ADD CONSTRAINT uq_interaction_source UNIQUE (source_ref);
```

Prevents duplicate interactions when backfill runs multiple times or trigger processes same message twice.

### 3B. Add performance indexes

```sql
CREATE INDEX IF NOT EXISTS idx_ci_timestamp ON contact_interactions(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_ci_channel ON contact_interactions(channel, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_ci_direction ON contact_interactions(contact_id, direction, timestamp DESC);
```

### 3C. Schedule periodic sync

Add to `embedded_scheduler.py`:
- **Backfill refresh** — run 1D (last_contact_date sync) daily at 05:00 UTC
- Lightweight: single UPDATE query, no LLM cost

---

## Implementation Sequence

| Step | What | Where | Effort |
|------|------|-------|--------|
| 1 | Add `record_interaction()` + unique constraint | store_back.py | Small |
| 2 | Add backfill endpoint `POST /api/networking/backfill-interactions` | dashboard.py | Small |
| 3 | SQL backfill: emails → interactions | Endpoint call | One-time |
| 4 | SQL backfill: WhatsApp → interactions | Endpoint call | One-time |
| 5 | SQL backfill: meetings → interactions | Endpoint call | One-time |
| 6 | Sync last_contact_date | Endpoint call | One-time |
| 7 | Hook into email_trigger.py | triggers/ | Small |
| 8 | Hook into waha_webhook.py | triggers/ | Small |
| 9 | Hook into fireflies_trigger.py | triggers/ | Small |
| 10 | Add daily last_contact_date refresh to scheduler | embedded_scheduler.py | Tiny |

**Total: ~200 lines of code. Zero LLM cost. Pure SQL + Python.**

---

## What This Unlocks

| Feature | Before | After |
|---------|--------|-------|
| Unreciprocated alerts | Never fires (empty table) | Detects 2+ outbound with no reply |
| Contact interaction timeline | Always blank | Shows last 50 interactions per contact |
| Going cold detection | Only checks last_contact_date | Can check interaction frequency + recency |
| Relationship health dots | Based on one timestamp | Based on interaction pattern |
| Networking action buttons | Baker guesses from memory search | Baker sees actual interaction history |

---

## What This Does NOT Do (deferred)

- **Sentiment classification** — schema has `sentiment VARCHAR(20)` column ready, but no Haiku call. Phase 2.
- **Auto-contact creation** — doesn't create new contacts from unknown senders. Separate concern.
- **LinkedIn/Proxycurl enrichment** — TRIP-INTELLIGENCE-1 Batch 3.
- **Network graph visualization** — Networking Phase 5.

---

## Verification

1. `SELECT COUNT(*) FROM contact_interactions;` → should be 1,000+ after backfill
2. `SELECT channel, COUNT(*) FROM contact_interactions GROUP BY channel;` → email, whatsapp, meeting all represented
3. `SELECT direction, COUNT(*) FROM contact_interactions GROUP BY direction;` → inbound, outbound, bidirectional
4. Dashboard → Networking tab → expand a contact → "Recent interactions" shows data
5. Dashboard → Networking tab → alert strip shows "X unreciprocated" if applicable
6. Send a test email → check interaction auto-created within 5 min
7. `SELECT COUNT(*) FROM vip_contacts WHERE last_contact_date IS NOT NULL;` → all matched contacts have dates

---

## Risk

**Low.** Pure SQL operations on existing data. No new dependencies. No LLM cost. Idempotent backfill (safe to re-run). Trigger hooks are try/except wrapped — pipeline continues if interaction extraction fails.

**Name matching false positives:** Short names (e.g. "Ali") may match multiple contacts. Mitigation: last-name matching only for multi-word names. Single-word contacts match by exact name or WhatsApp ID only.
