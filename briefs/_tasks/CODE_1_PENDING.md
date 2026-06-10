---
status: PENDING
brief_id: BACKFILL_BLUEWIN_1
to: b1
from: lead
dispatched_by: lead
dispatched_at: 2026-06-10
reply_target: lead (bus)
task_class: data backfill — standalone script + supervised run
gate_plan: G1 pytest + dry-run 50 msgs -> G3 codex code gate -> lead merge -> RUN in batches -> b4 verify lane closes arc
arc: EMAIL_HISTORY_BACKFILL (lane 2 of 5; depends on b3 EMAIL_ATTACHMENT_STORE_1 schema — build in parallel against the locked schema in b3's brief CODE_3_PENDING.md, rebase before merge)
---

# BACKFILL_BLUEWIN_1 — historical IMAP backfill, dvallen@bluewin.ch (messages + attachments)

## Context

Director-ratified 2026-06-10: backfill full bluewin history (~33,686 INBOX msgs + sent folder) into email_messages + email_attachments. Live poller (triggers/bluewin_poller.py) already ingests forward from 2026-06-09; this lane fills everything BEFORE that. Credentials: BLUEWIN_USER/BLUEWIN_PASS — on Render env AND 1Password item "Bluewin IMAP" (vault "Baker API Keys", id ee5knghn2qax3rgxd237sjkn7a). imaps.bluewin.ch:993 verified working 2026-06-10.

## Problem

Store holds 7 bluewin rows (since 2026-06-09 18:53Z). 33,679+ historical messages + all attachments missing.

## Files Modified

- scripts/backfill_bluewin.py — NEW standalone (DATABASE_URL + BLUEWIN_* from env)
- tests/test_backfill_bluewin.py — NEW (parser + dedup unit tests; mock IMAP, no live creds in CI)

## Design constraints (locked)

- Reuse triggers/bluewin_poller.py parsing helpers via import — do NOT fork-copy logic; refactor-extract if needed (small PR-safe moves only).
- Folders: INBOX + sent (detect Bluewin sent-folder name via LIST; include both).
- NO LLM classification on historical rows: priority=NULL, skip _process_email_threads pipeline — direct INSERT to email_messages (dedup ON CONFLICT message_id) + insert_attachment() per part (b3's kbl/attachment_store.py).
- Resumable: cursor = IMAP UID per folder in email_backfill_progress (source='bluewin:<folder>'); crash-safe re-run.
- Batched: 200 msgs/batch, 0.5s sleep between batches (Swisscom throttle-safety), oldest -> newest.
- Watermark table for the LIVE poller must NOT be touched — backfill is watermark-independent.

## Run protocol (context economy — HARD)

- Run as: nohup python3 scripts/backfill_bluewin.py >> /tmp/backfill_bluewin.log 2>&1 &
- Progress: script writes one line per batch to the log + updates email_backfill_progress. Check with tail -3, NEVER cat the full log.
- You do NOT babysit the run in-context: start it, verify first 2 batches sane (tail), bus a "run started" note to lead, end your session. b4's verify lane checks completion.

## Verification

- Dry-run mode (--limit 50) against live IMAP: 50 inserted, re-run inserts 0 (dedup proven). Literal output in ship report.
- pytest literal green.

## Acceptance criteria

- AC1: --limit 50 live dry-run: 50 rows + attachments in store; second run 0 new (dedup).
- AC2: resumability proven: kill mid-batch, re-run continues from cursor (show progress rows).
- AC3: live bluewin_poll watermark untouched (SELECT before/after identical).
- AC4: full run STARTED in background with progress visible; not required finished to ship.

## Done rubric / done-state class

Done = PR merged + G3 pass + dry-run ACs shown literal + full run started + "run-in-progress" done-state class on bus to lead. Arc-done (counts match) belongs to b4's verify lane, NOT you.

## Context-economy rules (HARD — no auto-compaction exists)

- Read ONLY: triggers/bluewin_poller.py, b3's schema block in CODE_3_PENDING.md, kbl/attachment_store.py (when it lands), your own new files.
- All run output to /tmp logs; tails only. If context >70%: commit, push, bus handoff, STOP.
