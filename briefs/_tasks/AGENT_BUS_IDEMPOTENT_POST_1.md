# AGENT_BUS_IDEMPOTENT_POST_1

dispatched_by: lead
assigned_to: b1
task_class: cross-layer-feature (brisen-lab daemon + fleet client scripts)
Harness-V2: Context Contract below; done rubric + gate plan inline.
effort: medium

## Context

During the 2026-07-09/10 latency incident, bus clients retried POSTs that had actually landed
(first attempt timed out or returned 503 `bus_busy_retry` AFTER the row committed). Live evidence:
b1's stand-down confirm posted 5× (#8331/#8332/#8333/#8334/#8335), b1 RCA 3× (#8293/#8294/#8296),
b2 preflight 2× (#8278/#8279), lead's own researcher nudge double-landed (#8290 + retry). Every
duplicate costs a wake + an ack + reader attention fleet-wide. Latency fix PR #110 reduces the
trigger but does NOT remove the failure mode: any timeout-after-commit still double-posts.

## Problem

The bus POST path has no idempotency: a client cannot retry safely, and cannot distinguish
"failed before commit" from "failed after commit". Fix = idempotency key, dedupe at the daemon.

## Task

1. **Daemon (brisen-lab):** accept optional `idempotency_key` (UUID string) on POST `/msg/{slug}`.
   Dedupe on `(from_terminal, idempotency_key)` — on repeat, return the ORIGINAL `message_id`
   (200, `deduped: true`), post nothing, wake nothing. Persist the key on the message row
   (nullable column, additive migration; no rewrite of applied migrations). TTL: dedupe window
   ≥24h is sufficient (reuse the existing 30d row TTL sweep; no separate sweeper).
2. **Clients (fleet scripts in baker-master):** `scripts/bus_post.sh` + `scripts/bus_post.py`
   generate one key per logical send (uuidgen at entry, NOT per attempt) and send it on every
   retry of that send. Keyless posts keep working byte-identical (back-compat — desks update lazily).
3. **Retry loop:** where the client already retries on 503/timeout, keep it — now safe. Do NOT
   add new retry loops in this brief.

## Constraints

- Additive only: keyless clients and old messages unaffected; no wake/ack behavior change for
  non-duplicate posts.
- No `Date.now`-style nonce reuse pitfalls: key is per-logical-message, generated once.
- Test isolation: wake-cluster suite has ~25 pre-existing failures (BRISEN_LAB_TEST_ISOLATION_WAKE_CLUSTER_1)
  — isolated run + full-suite-minus-file, as on PR #110.

## Files Modified

- brisen-lab: `bus.py` (dedupe lookup), `app.py` (param plumb), `db.py` (additive column + index),
  `tests/test_bus_idempotency.py` (new).
- baker-master: `scripts/bus_post.sh`, `scripts/bus_post.py` (key generation + resend).

## Verification

TDD: failing test first — same key twice → one row, second response carries original id +
`deduped:true`, zero second wake. Then: different keys → two rows; keyless → two rows (legacy).
Live AC after deploy: post twice with one key via curl against prod, verify single message +
single wake_event.

## Acceptance criteria

- AC1: duplicate-key POST returns original message_id, `deduped:true`, no new row, no wake.
- AC2: keyless behavior byte-identical (legacy clients unaffected).
- AC3: bus_post.sh/py retries reuse one key per logical send (shown in test or trace).
- AC4: additive migration only; applied migrations untouched.
- AC5: live prod AC per Verification, posted as POST_DEPLOY_AC_VERDICT v1.

## Done rubric + gate plan

Gate: codex bus review, reasoning_effort=medium, on the PR (brisen-lab) + the client PR
(baker-master) — one review covering both. Ship report answers AC1-AC5. Production-facing →
POST_DEPLOY_AC_VERDICT v1 on topic `fleet/bus-idempotency`.
