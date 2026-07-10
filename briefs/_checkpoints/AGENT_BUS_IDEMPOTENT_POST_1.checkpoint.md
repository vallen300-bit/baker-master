---
brief_id: AGENT_BUS_IDEMPOTENT_POST_1
attempt: 1
status: HOLDING — recon done; scope-overlap escalated to lead #8365 (fleet/bus-idempotency). Build NOT started, pending lead answer to 2 questions. NO code written yet.
repos: brisen-lab (work branch b1/bus-idempotent-post off main @6b75f70) + baker-master (~/bm-b1, no work branch yet)
dispatched_by: lead (#8362, 2026-07-10T06:11Z)
updated: 2026-07-10T06:21Z
---

# AGENT_BUS_IDEMPOTENT_POST_1 — checkpoint

## KEY FINDING (recon done, do NOT redo)
The DAEMON side of this brief is ALREADY MERGED ON MAIN under a different ticket:
**TICKET_ID_DEDUP_1** (brisen-lab commit `92e3ae6`, on origin/main — daemon half of lead ruling #7342).
It already satisfies brief Task-1 + AC2 + AC4:
- bus.py 943-952: optional `idempotency_key` param, str + <=200 validation, empty->None.
- bus.py 968-1007: INSERT ... ON CONFLICT (from_terminal, idempotency_key) WHERE idempotency_key IS NOT NULL
  DO NOTHING; on conflict re-SELECT + return ORIGINAL row. Returns (row, is_new).
- bus.py ~1020: is_new gating — no re-broadcast / no re-wake / no wake_events on replay.
- db.py 500-506 + 737-763: nullable idempotency_key column + partial unique index
  `uq_brisen_lab_msg_idempotency` via catalog-guarded additive bootstrap ALTER (no migration rewrite).
- tests/test_ticket_id_dedup_1_daemon.py PASSES: 3x same key->one row+same message_id, keyless->distinct,
  scoped-per-sender. (Client wiring in TICKET_ID_DEDUP_1 was ONLY orchestrator/airport_ticketing_bridge.py.)
- `origin/b2/ticket-id-dedup-1` is STALE/merged (git log main..that-branch is empty) — no active collision.

## TWO GENUINE GAPS vs this brief
1. **AC1 `deduped:true` NOT met** — daemon returns original message_id on replay but never sets
   `deduped:true` (string 'deduped' is nowhere in brisen-lab repo). Fix = set resp['deduped']=True when
   is_new is False (bus.py ~1075, the resp dict) + a test assertion. Small.
2. **Fleet clients NOT wired** — scripts/bus_post.sh + scripts/bus_post.py (baker-master) do NOT
   generate/send a key. THIS is the brief's core: my stand-down dup storm (#8331-#8335) came from a
   bus_post.sh CALLER loop, not the ticketing bridge.

## DESIGN FORK (escalated — lead must pick before client build)
bus_post.sh AND bus_post.py have NO internal retry loop; the storm was the CALLER (ad-hoc bash for-loop)
re-invoking bus_post.sh. So:
- A) mint per invocation only (literal brief): does NOT fix caller-loop storms (each attempt = new key).
- B) additive passthrough: script auto-mints if none given BUT accepts --idempotency-key / BUS_IDEMPOTENCY_KEY
  so a caller loop mints ONE key + reuses across invocations. Keyless byte-identical. Kills the real failure mode.
- C) internal retry-with-backoff loop reusing one key + move callers off ad-hoc loops — brief forbids new retry loops.
b1 leaned B in the escalation.

## NEXT CONCRETE STEP
AWAIT lead reply on fleet/bus-idempotency (answer to #8365: (i) close deduped:true gap yes/no; (ii) client
approach A/B/C). Do NOT rebuild the daemon (already merged). Do NOT guess the client approach. On lead's pick:
TDD-first, brisen-lab PR (deduped flag if approved) + baker-master PR (client scripts), one codex-medium
covering both, live prod AC, POST_DEPLOY_AC_VERDICT v1 on fleet/bus-idempotency.

## KEY PATHS
- brisen-lab checkout: ~/bm-b1-brisen-lab (branch b1/bus-idempotent-post off main @6b75f70; clean, no edits).
- baker-master: ~/bm-b1 (client scripts scripts/bus_post.sh + scripts/bus_post.py).
- Existing daemon test to mirror/extend: tests/test_ticket_id_dedup_1_daemon.py.
- brisen-lab test harness: conftest.py `client`/`fresh_db` fixtures; POST helper `_post(client,term,key,**kw)`.
