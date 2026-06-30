---
status: SHIPPED_AWAITING_GATES
pr: 440
head_sha: b6c621c
shipped_at: 2026-06-30
brief_id: BOX5_RECEIPT_TTL_1
to: b4
from: lead
dispatched_by: cowork-ah1
dispatched_at: 2026-06-30
branch: box5-receipt-ttl-1
reply_target: cowork-ah1 (bus) for ship report; gate verdicts to lead
effort: medium
task_class: additive + tiny idempotent ALTER (new scheduler check-in reader + TTL/nudge sweep); ships DARK behind AIRPORT_CHECKIN_SWEEP_ENABLED (default false)
gate_plan: G1 builder self-check (pytest 3 new files + py_compile + check_singletons) -> codex G3 (bus, effort medium) -> lead G4 /security-review -> lead merge. Deploy = lead flips AIRPORT_CHECKIN_SWEEP_ENABLED post-merge (Director GO for ACTIVATION); POST_DEPLOY_AC_VERDICT v1 after flag-on.
full_brief: briefs/BRIEF_BOX5_RECEIPT_TTL_1.md
---

# BOX5_RECEIPT_TTL_1 — Airport-ticket check-in reader + stale-ticket TTL nudge (Box 5 Build Order 1-2)

## Read this first
The complete, copy-pasteable implementation is in **`briefs/BRIEF_BOX5_RECEIPT_TTL_1.md`** (673 lines, on main, committed alongside this dispatch). Implement exactly as written there. This envelope carries only dispatch metadata + acceptance gates. Brief authored via /write-brief + signature-verify by cowork-ah1; do not redesign.

## Context (one paragraph)
Baker OS V2 / Box 5 Build Order steps 1-2, the #439-INDEPENDENT receipt loop. Part 1: a check-in reply-reader polls the ticketing slug's bus inbox, maps desk replies to tickets (bus_message_id=parent_id, fallback bus_thread_id=thread_id), writes check_in_outcome/at/by + flips status sent->checked_in/rejected, ACKs AFTER the write commits (crash-safe dedup). Part 2: a stale-ticket TTL/nudge sweep re-pings the owning desk for sent+unacked tickets, escalates to lead after N nudges (FOR UPDATE SKIP LOCKED + cooldown = no double-nudge). Keeps matter desks asleep until a boarding pass or escalation exists.

## Scope (locked — do NOT exceed)
- NEW `orchestrator/airport_checkin_reader.py` (`run_checkin_sweep`) + thin `triggers/airport_checkin_tick.py` wrapper + ~6-line registration block in `triggers/embedded_scheduler.py`.
- ONE additive idempotent migration: `ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS last_nudged_at TIMESTAMPTZ; ADD COLUMN IF NOT EXISTS nudge_count INTEGER NOT NULL DEFAULT 0;` — mirrored inside `ensure_airport_ticket_table` (dodge migration-vs-bootstrap drift). Receipt columns already exist — untouched.
- Ships DARK behind `AIRPORT_CHECKIN_SWEEP_ENABLED` (default false). Single-replica via existing `scheduler_lease` (lock 8800100) — NO new lock.
- 3 new test files. No edits to the existing ticket-issue path.

## Acceptance criteria
- AC1: `python3 -c "import py_compile; py_compile.compile('orchestrator/airport_checkin_reader.py', doraise=True)"` + the tick wrapper compile clean.
- AC2: `pytest` the 3 new test files → all pass (live-PG auto-skip without TEST_DATABASE_URL; CI runs live).
- AC3: `bash scripts/check_singletons.sh` OK.
- AC4: With flag false, scheduler logs "skipping registration" — jobs do NOT register (dark-ship proof).
- AC5: ACK-after-commit ordering verified by test (crash before ACK → re-read is idempotent, no double-write).

## Done rubric
Build-done = PR merged + AC1-AC5 green. Arc-done (separate) = lead flips `AIRPORT_CHECKIN_SWEEP_ENABLED=true` (Director GO for activation) → `POST_DEPLOY_AC_VERDICT v1` with live receipt-loop + TTL-nudge proof. Two done-states — do not conflate.

## Context-economy (HARD — no auto-compaction)
- Read ONLY the files named in the brief's Context Contract. Output to /tmp; tails only. Context >70%: commit, push, bus handoff, STOP.
