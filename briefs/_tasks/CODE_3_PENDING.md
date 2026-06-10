---
status: PENDING
brief_id: EMAIL_STORE_NEON_SSL_RCA_1
to: b3
from: lead
dispatched_by: lead
dispatched_at: 2026-06-10
reply_target: lead (bus)
task_class: ambiguous production bug — diagnose FIRST, fix only if root cause proven
gate_plan: G1 diagnosis verdict to lead -> fix (if any) gets its own gate
Harness-V2: N/A — diagnose-first lane; any code fix returns for a fresh brief w/ full blocks
---

# EMAIL_STORE_NEON_SSL_RCA_1 — intermittent "SSL connection has been closed unexpectedly" on email store

## Context

(Your EMAIL_ATTACHMENT_STORE_1 shipped + merged — good work, mailbox repurposed.) Deputy reproduced backend_unavailable=true on baker_email_search provider=store ~08:35Z + retries (Neon PG SSL closed). Director-impacting: blocked his Spanyi hearing-prep email pull. Lead re-tested 09:55Z: store WORKS (Spanyi 6 Jun returned). So intermittent. Same signature as the 2026-06-01 degradation arc (bus #1500/#1503 — Neon SSL flood). NOTE: bluewin backfill (pid on Mac, started 09:24Z) + b2 graph dry-runs (~09:38Z) hammer the same Neon DB but POST-date the 08:35Z repro — they are suspects for FUTURE pressure, not the original trigger.

## Problem

Why does the dashboard's email-store path intermittently lose Neon SSL connections, and does the running backfill make it worse?

## Files Modified

None expected this lane. Diagnosis only; fix briefs follow separately.

## Verification

- Render logs (baker-master srv-d6dgsbctgctc73f55730) around 08:30-09:00Z + last 2h: grep SSL/connection-closed/pool errors; correlate timestamps with email_messages ingested_at bursts.
- Conn-pool config: how does dashboard.py acquire PG conns for email search (pool size, keepalive, stale-conn recycle)? Neon idle-timeout vs our keepalive.
- Live watch: 3 store searches spaced 10 min while backfill runs; record pass/fail.
- Check 2026-06-01 arc notes (bus #1500/#1503) for what fixed/was left open.

## Acceptance criteria

- AC1: verdict — root cause named with log evidence OR explicitly "not reproducible, monitoring plan".
- AC2: backfill-pressure answer: does pid-4177 load correlate with store failures? yes/no with data.
- AC3: if fix needed: proposed fix as bus note to lead (no code this lane).

## Quality Checkpoints

Diagnosis verdict on bus to lead; deputy live-verifies with his Spanyi AC after any fix.

## Context-economy rules (HARD)

Render logs via API filtered greps only — never dump full logs into context. /tmp for anything bulky. Context >70%: post findings-so-far + stop.
