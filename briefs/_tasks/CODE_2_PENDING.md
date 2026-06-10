---
status: PENDING
brief_id: BACKFILL_GRAPH_1
to: b2
from: lead
dispatched_by: lead
dispatched_at: 2026-06-10
reply_target: lead (bus)
task_class: data backfill — standalone script + supervised run
gate_plan: G1 pytest + dry-run 50 msgs -> G3 codex code gate -> lead merge -> RUN in batches -> b4 verify lane closes arc
arc: EMAIL_HISTORY_BACKFILL (lane 3 of 5; depends on b3 EMAIL_ATTACHMENT_STORE_1 schema — build in parallel against locked schema in CODE_3_PENDING.md, rebase before merge)
---

# BACKFILL_GRAPH_1 — historical M365 Graph backfill, dvallen@brisengroup.com (messages + attachments)

## Context

Director-ratified 2026-06-10: backfill full brisengroup mailbox history into email_messages + email_attachments. Live graph poller ingests forward only (store holds 106 graph rows). You shipped M365_MAIL_BLINDSPOT_DIAGNOSE_FIX_1 (PR #342) — reuse that lane knowledge: Graph auth via existing cert/app-token path (M365 Graph cert in 1Password "Baker API Keys"; the working token helper is whatever triggers' graph poller uses — find via grep "graph_mail_poll").

## Problem

Brisen mailbox (migrated to M365 ~2026-06-03) has years of history; store has 106 rows. All historical messages + attachments missing.

## Files Modified

- scripts/backfill_graph.py — NEW standalone (env-driven; reuse existing Graph token helper via import)
- tests/test_backfill_graph.py — NEW (paging + dedup unit tests; mock Graph; no live creds in CI)

## Design constraints (locked)

- Folders: Inbox + SentItems (v1; other folders out of scope).
- Paging: Graph /messages?$top=100&$orderby=receivedDateTime asc + @odata.nextLink; attachments via /messages/{id}/attachments (fileAttachment contentBytes only; itemAttachment = metadata_only row).
- NO LLM classification on historical rows: priority=NULL, direct INSERT (dedup ON CONFLICT message_id) + insert_attachment() per file (b3's kbl/attachment_store.py).
- Resumable: cursor = nextLink (or last receivedDateTime) per folder in email_backfill_progress (source='graph:<folder>').
- Throttle: respect 429 Retry-After; 100 msgs/page, 0.3s between pages.
- Live graph_mail_poll watermark untouched — backfill is watermark-independent.

## Run protocol (context economy — HARD)

- nohup python3 scripts/backfill_graph.py >> /tmp/backfill_graph.log 2>&1 &
- One log line per page + email_backfill_progress update. tail -3 only, never cat.
- Start run, sanity-check 2 pages, bus "run started" to lead, end session. b4 verifies completion.

## Verification

- Dry-run (--limit 50) live: 50 rows + attachments; re-run 0 new (dedup). Literal output in ship report.
- pytest literal green.

## Acceptance criteria

- AC1: --limit 50 dry-run + dedup re-run 0.
- AC2: resumability proven (kill + resume from cursor; show progress rows).
- AC3: live graph watermark untouched (SELECT before/after identical).
- AC4: full run STARTED background with visible progress; finishing belongs to b4 lane.

## Done rubric / done-state class

Done = PR merged + G3 pass + dry-run ACs literal + run started + "run-in-progress" done-state class on bus to lead.

## Context-economy rules (HARD — no auto-compaction exists)

- Read ONLY: the graph poller file (locate via grep "graph_mail_poll" triggers/), b3's schema block, kbl/attachment_store.py when it lands, your new files.
- Output to /tmp logs; tails only. Context >70%: commit, push, bus handoff, STOP.
