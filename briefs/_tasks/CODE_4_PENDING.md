---
status: COMPLETE
brief_id: BACKFILL_VERIFY_1
to: b4
from: lead
dispatched_by: lead
dispatched_at: 2026-06-10
reply_target: lead (bus)
task_class: verification harness + arc close-out (read-mostly)
gate_plan: G1 harness pytest -> lead review -> RUN after b1+b2 runs complete -> POST_DEPLOY_AC_VERDICT v1 to lead + cc deputy
arc: EMAIL_HISTORY_BACKFILL (lane 5 of 5 — closes the arc; blocked-on: b1+b2 background runs finishing)
---

# BACKFILL_VERIFY_1 — backfill verification harness + arc close-out

## Context

Director-ratified 2026-06-10 backfill arc: b3 attachment store, b1 bluewin IMAP backfill, b2 Graph backfill, deputy-codex forward-parity. Backfill runs are long + background; "done" for the ARC = store contents match mailbox contents, proven. That proof is YOUR lane. Done-rubrics-stop-gate discipline applies: counts + spot-checks, no "looks complete".

## Problem

Nobody verifies a backfill that verifies itself. Independent harness needed: mailbox-side counts vs store-side counts + random deep spot-checks + a machine-checkable verdict.

## Files Modified

- scripts/verify_backfill.py — NEW (read-only against IMAP, Graph, and DB)
- tests/test_verify_backfill.py — NEW (mocked counts/verdict logic)

## Design constraints (locked)

- Counts: IMAP SELECT-EXAMINE per folder vs SELECT COUNT(*) email_messages WHERE source='bluewin'; Graph folder totalItemCount vs source='graph'. Tolerance: store >= 98% of mailbox count per folder (some messages unparseable — list failures, don't hide them).
- Spot-checks: 10 random historical messages per source — present in store, body non-empty, searchable via the email search path; 5 random attachments per source — sha256(data) == content_sha256, size matches.
- Output: single verdict block POST_DEPLOY_AC_VERDICT v1 (per _ops/skills/post-deploy-ac-bus-gate/SKILL.md) — PASS/FAIL per AC, posted to lead AND cc deputy (new convention 2026-06-10).
- Read-only everywhere: no writes except the verdict bus post. SELECT-only DB access.

## Run protocol

- Build + test harness NOW; RUN only after b1 + b2 post "run finished" (poll email_backfill_progress: done_count stable + cursor exhausted). If runs still going when your build is done: ship the harness PR, bus "harness ready, runs in flight", end session — re-dispatch will trigger the run.

## Verification

pytest literal green on harness logic (mocked).

## Acceptance criteria

- AC1: harness compares counts per folder per source with explicit numbers in output.
- AC2: spot-checks executed with named message-ids + attachment hashes (reproducible).
- AC3: verdict block emitted in exact POST_DEPLOY_AC_VERDICT v1 shape, to lead + cc deputy.
- AC4: failures listed loud (no silent tolerance eating).

## Done rubric / done-state class

Harness-done = PR merged + pytest literal. Arc-done = verdict posted with overall PASS. Two separate done-states — never conflate in ship reports.

## Context-economy rules (HARD — no auto-compaction exists)

- Read ONLY: post-deploy-ac-bus-gate SKILL.md, b3 schema block in CODE_3_PENDING.md, your new files. Do NOT read b1/b2 scripts — independence is the point.
- Output to /tmp; tails only. Context >70%: commit, push, bus handoff, STOP.
