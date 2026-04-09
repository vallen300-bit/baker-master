# WhatsApp Ingestion Failure — Engineering Report
## Baker System / WAHA Integration
### Date: April 8, 2026 | Priority: HIGH

---

## 1. PROBLEM STATEMENT

WhatsApp messages from external contacts are being **silently dropped** — they never reach Baker's database. The Director discovered that messages from Marcus Pisani (Corinthia Hotels) containing critical business URLs sent on April 7 were missing entirely. No error was raised. No alert was triggered. Baker was blind.

**Impact:** This is not isolated to one contact. Any low-frequency WhatsApp contact's messages may be silently lost. High-frequency contacts (e.g., Balazs, active group chats) appear unaffected because their messages stay in WAHA's active memory cache.

---

## 2. DIAGNOSIS

### Root Cause: WAHA Memory Exhaustion on Starter Plan

WAHA (WhatsApp HTTP API) runs on Render's **Starter plan (512MB RAM)**. It uses the **NoWeb engine**, which stores messages in memory. The session has been running continuously since **February 28, 2026** without restart.

Under memory pressure, WAHA's NoWeb store silently drops messages from inactive/low-frequency chats. When a message is never stored, two things fail:

1. **Real-time webhook** (`POST /api/webhook/whatsapp`) never fires — WAHA only sends webhook events for messages it has stored
2. **Polling backfill** (`scripts/extract_whatsapp.py`) never sees the message — it queries WAHA's API, which returns only what's in its memory store

### Evidence

| Finding | Detail |
|---------|--------|
| WAHA warning log | `"got update for non-existent message"` for Pisani chat (`fromMe:false`, msg ID `2A15034345A9CDDC4A3D`) at 06:41 UTC Apr 8 — WAHA received a delivery receipt for a message it never stored |
| Corrupted timestamps | All 4 inbound Pisani messages have identical timestamp `1775554996`, suggesting memory store corruption |
| Message count | Only 9 total messages retained for Pisani chat (should be dozens) |
| Session age | WAHA running since Feb 28 — 39 days without restart on 512MB |
| Comparison | High-frequency contacts (Balazs/+36303005919) ingest normally — their messages stay in active cache |

### Secondary Bug: Sender Attribution

In `scripts/extract_whatsapp.py` (line 58-64), when `fromMe=True`, the `"from"` field contains the **remote party's JID** (e.g., Pisani's number), not the Director's. The code stores `sender=447468357311@c.us` with `is_director=True`. The sender field should be the Director's JID for outbound messages.

### Missing: WhatsApp Health Monitoring

There is **no `whatsapp` entry in `sentinel_health`**. Email, ClickUp, and Slack all have health tracking and alerting. WhatsApp has zero monitoring. When ingestion silently fails, nobody knows.

---

## 3. PROPOSED FIXES

### Fix 1: Restart WAHA Service (Immediate)
- Restart the WAHA service on Render to force a fresh WhatsApp session reconnect
- After reconnection, NoWeb engine re-syncs recent messages from WhatsApp's servers
- **Expected result:** Recover Pisani's last few days of messages
- **Risk:** Low — restart causes ~60s downtime, messages queue on WhatsApp's side

### Fix 2: Upgrade WAHA Plan — Starter → Standard (Immediate)
- Upgrade from 512MB to 2GB RAM on Render
- Prevents future memory pressure message drops
- **Cost:** ~$7/month → ~$25/month difference
- **Priority:** HIGH — current plan is fundamentally undersized for production use

### Fix 3: Add WhatsApp Sentinel Health Monitoring (Engineering Task)
- Add `whatsapp` row to `sentinel_health` table
- After each backfill cycle, report: messages ingested, last successful timestamp, WAHA session status
- Alert if: zero messages ingested for >6 hours, WAHA session disconnected, or backfill errors
- **Estimate:** 2-3 hours engineering work

### Fix 4: Fix Sender Attribution Bug (Engineering Task)
- In `scripts/extract_whatsapp.py`, when `fromMe=True`, set `sender` to the Director's JID (`41799605092@c.us`) instead of the remote party's JID
- **Estimate:** 15 minutes

### Fix 5: Scheduled WAHA Restart (Engineering Task)
- Add a weekly WAHA restart cron job (e.g., Sunday 04:00 UTC) to prevent long-running memory accumulation
- Or: implement WAHA's built-in session health check endpoint and restart automatically when memory exceeds threshold
- **Estimate:** 1 hour

---

## 4. DONE SO FAR

| Action | Status |
|--------|--------|
| Problem identified and diagnosed | DONE |
| Root cause confirmed (memory exhaustion + NoWeb store) | DONE |
| WAHA logs analyzed, evidence documented | DONE |
| Scope assessed (affects all low-frequency contacts, not just Pisani) | DONE |
| WAHA restart | NOT YET — awaiting approval |
| Plan upgrade | NOT YET — awaiting approval |
| Health monitoring | NOT YET — engineering task |
| Sender bug fix | NOT YET — engineering task |

---

## 5. RECOMMENDED PRIORITY ORDER

1. **Now:** Restart WAHA + upgrade to Standard plan (stops the bleeding)
2. **This week:** Add WhatsApp health monitoring to sentinel_health
3. **This week:** Fix sender attribution bug
4. **Next week:** Implement scheduled restart or memory-based auto-restart

---

*Report prepared by Baker AI Head | April 8, 2026*
*Investigation: 53 tool calls across WAHA API, Render logs, PostgreSQL diagnostics, and codebase analysis*
