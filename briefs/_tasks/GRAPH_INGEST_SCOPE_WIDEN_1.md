# GRAPH_INGEST_SCOPE_WIDEN_1

**Owner:** lead (AH1) · **Builder:** b-code · **Gate:** codex G3 (HIGH) → lead G4 /security-review
**Source:** Director-caught miss 2026-07-01 — a live Aukera/Annaberg deal signal (Siegfried→Balazs ESG email, 13:09 UTC) never reached Box 5 because it was never ingested.

## Problem

The Graph mail poller ingests **only the Inbox folder** of Dimitry's mailbox. Mail
that lands in any other folder (Outlook rule auto-filing, project subfolders,
conversation-move, categories) is **never ingested** into `email_messages` — so every
downstream consumer (Box 5 ticketing office, Cortex, desks) is blind to it.

## Evidence (verified this session)

- `triggers/graph_mail_trigger.py`: `_FOLDER = "Inbox"`; `poll_graph_mail()` calls
  `/users/{mail_user}/mailFolders/Inbox/messages/delta`.
- Siegfried Brandner → Balazs, 2026-07-01 13:09 UTC, subj "AW: AB Sprint FW: Q&A / ESG
  / Debt Model" (ESG schedule for the Aukera-requested Annaberg questionnaire).
- Present in live M365 whole-mailbox search; **absent** from `email_messages`
  (`SELECT ... WHERE sender_email ILIKE '%siegfried%' AND received_date >= '2026-06-30'`
  → 0 rows). Director confirms the mail is in a **folder** (not Inbox).
- Ingestion is otherwise **current** (graph source last ingested 15:05 UTC) → this is a
  folder-scope miss, NOT a poll lag or global stall.

## Root cause

Inbox-only folder scope. The whole-mailbox search sees the mail; the Inbox-scoped delta
poller does not.

## Design (target)

Widen ingestion from Inbox-only to the **whole mailbox**, minus folders that must not be
ingested as inbound signal.

1. **Scope switch:** poll `/users/{mail_user}/messages/delta` (mailbox-wide, all folders)
   instead of `/mailFolders/Inbox/messages/delta`. Confirm delta is supported at this
   scope; if not, enumerate `mailFolders` and run a per-folder delta with a per-folder
   watermark.
2. **Exclude non-inbound folders (HARD):** never ingest `Sent Items`, `Drafts`,
   `Deleted Items`, `Junk Email`. Rationale: Sent/Drafts would ingest Dimitry's own
   outbound as inbound signal (pollutes Box 5 direction logic); Deleted/Junk are noise.
   Prefer a well-known-folder-id allow/deny check on each message's `parentFolderId`
   over subject/heuristics. `isDraft` skip stays.
3. **Delta-reset safety (LOAD-BEARING):** switching scope invalidates the current Inbox
   delta token and a naive re-sync would re-pull ~119k historical messages. Seed the new
   scope's delta/watermark from **now** (or a bounded lookback, e.g. 14 days) so the
   cutover does NOT trigger a full-history backfill. Existing rows dedup via the current
   `ON CONFLICT` on message_id; confirm that key holds mailbox-wide.
4. **Fault-tolerance unchanged:** a folder/page fetch error must not abort the whole
   poll; log + continue (existing pattern). Watermark advances only on success.

## Constraints

- Surgical: `triggers/graph_mail_trigger.py` (+ its tests). Do not touch other pollers.
- All Graph/DB calls in try/except (repo hard rule); `.claude/rules/python-backend.md`.
- No dashboard change. No new env unless a folder-deny list is configurable (env optional).
- Do NOT re-ingest history — cutover must be watermark-bounded (AC below).

## Acceptance criteria

1. A message in a non-Inbox mail folder (e.g. a rule-filed subfolder) is ingested into
   `email_messages` after a poll — proven by a fixture/mock returning a message with a
   non-Inbox `parentFolderId`.
2. Messages in Sent Items / Drafts / Deleted Items / Junk are NOT ingested.
3. Cutover does not enqueue a full-history backfill: with a seeded watermark, only
   messages newer than the seed are pulled (assert the delta/watermark seed logic).
4. Dedup holds — re-polling an already-stored message_id is a no-op (no duplicate row).
5. A page-fetch error on one folder does not abort the poll (fault-tolerant).

## TDD plan

1. Repro: mock a mailbox-wide delta page containing the Siegfried-style message with a
   non-Inbox `parentFolderId`; assert pre-change (Inbox-scoped) skips it, post-change
   ingests it.
2. Folder-exclusion test: Sent/Drafts/Deleted/Junk parentFolderIds are dropped.
3. Watermark-seed test: cutover pulls only post-seed messages (no 119k backfill).
4. Dedup + fault-tolerance regressions.

## Out of scope

- Reprocessing already-missed historical mail (separate one-off backfill if Director wants).
- Routing/desk-delivery of ingested mail — see `THREAD_CONTINUITY_ROUTING_1`.
- Other mailboxes (office.vienna, bluewin) — this brief is Dimitry's M365 only.

## Gate

G1 (builder self-verify + new tests) → **codex G3, effort HIGH** (touches live ingestion
+ delta cutover risk) → **lead G4 /security-review** → lead merge → lead confirms live
that a non-Inbox message now ingests.
