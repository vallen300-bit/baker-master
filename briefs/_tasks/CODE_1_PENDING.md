---
dispatch: BAKER_CAPTURE_BLINDSPOTS_1
to: b1
from: lead
dispatched_by: lead
status: PENDING
dispatched_at: 2026-05-29T21:45:00Z
brief_version: v4 (codex PASS bus #1346)
brief_anchor_commit: 49e2050
authored: 2026-05-29
brief_path: /Users/dimitry/bm-aihead1/briefs/BRIEF_BAKER_CAPTURE_BLINDSPOTS_1.md
target_repo: baker-master
estimated_time: ~5h
complexity: Medium
reply_to: lead
ship_topic: ship/baker-capture-blindspots-1
anchor_chat: Director 2026-05-29 — "If we have a gap in what I send to other people by WhatsApp or email, there is a problem. Baker is blind."
supersedes: AID_ON_BUS_1 (shipped 2026-05-25, ship report B1_AID_ON_BUS_1_20260525.md)
---

# CODE_1_PENDING — BAKER_CAPTURE_BLINDSPOTS_1

Close two Director outbound capture blind spots:

1. **Email (Exchange Sent-Items polling)** — `triggers/exchange_poller.py` polls only INBOX (`EXCHANGE_FOLDER = "INBOX"` line 23). All Outlook outbound from dvallen@brisengroup.com is invisible. Add sibling `poll_exchange_sent()` with separate watermark + `source=exchange_sent` + `direction=outbound` tag. Independent try/except in scheduler.

2. **WhatsApp (iPhone export ingest)** — outbound capture shipped 2026-05-20 (PR #235); pre-2026-05-20 outbound (Storer + Bick threads) only survives on Director's iPhone. New endpoint `POST /api/whatsapp/import_iphone_export` accepts iPhone "Export Chat" .txt + ingests into existing `whatsapp_messages` table with `source=iphone_export`. Idempotent.

**Full spec:** `briefs/BRIEF_BAKER_CAPTURE_BLINDSPOTS_1.md` — read in full before starting.

**Anchors:**
- `triggers/exchange_poller.py:23` (smoking gun, INBOX-only)
- `triggers/waha_webhook.py:830-877` (verified going-forward fromMe capture)
- PR #235 / commit `0e08ce5` + hot-fix `5af2971` (outbound capture ship 2026-05-20)
- origination-desk bus #1338 (NVIDIA project room — Storer + Bick gap inventory)
- Lesson #45 (sequential pollers must be independent — apply)

**Ship-gate discipline:**
- Pytest literal output (no "pass by inspection")
- Verify column names against actual schema BEFORE INSERT
- Verify scheduler caller of `poll_exchange()` before wiring sibling
- Surface contract: N/A (pure backend) — already documented in brief

**Ship report:** `briefs/_reports/B1_BAKER_CAPTURE_BLINDSPOTS_1_<YYYYMMDD>.md`
**Bus-post topic on ship:** `ship/baker-capture-blindspots-1` from `b1` to `lead`.
