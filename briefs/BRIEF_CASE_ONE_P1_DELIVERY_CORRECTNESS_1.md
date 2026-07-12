# BRIEF: CASE_ONE_P1_DELIVERY_CORRECTNESS_1 — ack read-back + idempotency-key/side-effect dedup + explicit backpressure

> Case One bus-hardening **P1** (delivery correctness, F-503/E1/E2/E8). Authored by deputy (AH2,
> standing bus-health owner) from ARM's plan (vault #178). **TO LEAD FOR REVIEW BEFORE WORKER
> DISPATCH.** Codex gate this phase. Standing rule #9255. Sequenced after P0 (fleet-blocking metering).

dispatched_by: lead (pending review)
assigned_to: <builder — lead assigns after review>
task_class: backend-correctness (brisen-lab bus daemon: ack, write dedup, backpressure) + fleet client scripts
Harness-V2: Context Contract + done rubric + gate plan inline.
effort: medium-high

## Context

**Context Contract.** Repo: brisen-lab (`bus.py` ack + post paths, `db.py`) + fleet client scripts (`bus_post.sh`, ack helpers). No new service — the graduated path (Postgres source-of-truth + transactional dedup + explicit busy signal) per the transport doc. Builds ON already-shipped pieces — do NOT redo them.

Delivery correctness is the second story after metering: F-503 (503 flap), E1 (ack no-op), E2/E8 (duplicate post; dedup skipped side-effects). All reproduced live with message IDs. Deputy hit E1 and F-503 live this very session (an ack 503'd then succeeded; sustained 503 saturation blocked a lead post for ~12 min).

### SCOPE DEDUPE (MANDATORY — lead #9563). Already shipped; this brief must NOT re-cover:
- **F-503 bounded-acquire** — SHIPPED as brisen-lab #118 (bounded `getconn` retry, ~300ms jittered, maxconn stays 10). The server now absorbs *transient* pool spikes. **Build ON it** — P1's backpressure item is the NEXT layer (explicit busy signal so clients stop blind-retrying), NOT a redo of the acquire loop.
- **E2 row-level idempotent post** — SHIPPED (`023d95f`, `deduped:true` on replay). P1 EXTENDS it to a client-supplied idempotency key on ALL writes + **side-effect** dedup, which the row-level fix does not cover.
- **E1 root cause** — a diagnosis-first brief (`BRIEF_BRISEN_LAB_E1_ACK_NO_OP_DIAGNOSE_1`) is already authored + delivered. P1's ack item is the **fix phase**, gated on that diagnosis's confirmed root cause — do NOT re-diagnose.

## Problem

Three delivery-correctness gaps remain:

1. **Ack is not transactional with a read-back guarantee (E1).** `POST /msg/<id>/ack` can return `{ok:true}` while `acknowledged_at` stays NULL (repro #9288 3 attempts, #9398 re-surfaced). An `{ok:true}` that does not change readable state is a correctness lie the whole claim/ack + rollover model rests on.
2. **Writes lack a general idempotency key + side-effect dedup (E2/E8).** The row-level dedup exists, but (a) not all write paths carry a client idempotency key, and (b) dedup is not transactional over **side-effects** — a deduped/retried post can still re-fire a wake (`wake_attempted_at` not durable), costing a wake + ack + reader attention fleet-wide.
3. **No explicit busy signal — clients still blind-retry `bus_busy_retry` (F-503 residual).** #118 absorbs transient spikes, but genuine saturation still returns a bare 503 the caller papers over with blind-retry — which manufactures the E2 duplicates. Delivery needs an explicit, honest busy signal (retry-after / queue position), so retry is bounded and informed, not blind.

## Fix (three pieces, build on shipped work)

### P1.1 — Transactional ack with read-back guarantee (E1 fix phase)
Per the E1 diagnosis's confirmed root cause (likely read/write endpoint split or unchecked `rowcount`): make ack transactional + idempotent so `{ok:true}` **implies** `acknowledged_at` is non-NULL and visible to the next fleet read. Minimum: assert `cur.rowcount == 1` on the "ok" branch (else return a distinct `retry`/non-ok, never a false ok); guarantee the ack write and the fleet read are read-your-writes consistent (same endpoint / read-after-write routing). Idempotent re-ack stays `{ok:true, already:true}`.

### P1.2 — Client idempotency key on all writes + side-effect dedup (E2/E8)
Generalize the client-supplied idempotency key to every write path (`bus_post.sh` + helpers supply a dedup token). Server dedup is transactional over the row **and** its side-effects: a deduped post must NOT re-fire the wake — persist `wake_attempted_at` durably and gate the wake on it inside the same transaction as the dedup check.

### P1.3 — Explicit backpressure signal (F-503 residual, build on #118)
When the pool is genuinely saturated past #118's bounded-acquire budget, return an explicit busy signal: a `Retry-After` header (and/or a structured `{busy:true, retry_after_ms}` body) instead of a bare 503 the caller blind-retries. Client scripts honor `Retry-After` with bounded, jittered backoff and STOP blind-retrying. (Full transactional-outbox + LISTEN/NOTIFY doorbell is P2+; P1 delivers the honest busy contract on top of #118.)

## Files Modified

- brisen-lab: `bus.py` (`ack_msg` read-back + rowcount; post-path idempotency-key + side-effect dedup + `wake_attempted_at` durability; explicit `Retry-After` on saturation), `db.py` (read-after-write routing if the E1 diagnosis names endpoint split), migration for durable `wake_attempted_at` if needed.
- Fleet clients: `bus_post.sh` / ack helpers (supply idempotency key; honor `Retry-After`; bounded backoff).
- Tests in brisen-lab + a client-script round-trip test.

## Verification

1. **Ack read-back (E1):** repro harness from the E1 diagnosis brief — ack then immediately read via the fleet path → `acked=true` 100% over N iterations incl. concurrency. `{ok:true}` never leaves `acknowledged_at` NULL.
2. **Idempotency + side-effect (E2/E8):** same idempotency key posted twice → one row, `deduped:true`, and the wake fires **exactly once** (`wake_attempted_at` proves no double-wake).
3. **Explicit backpressure (F-503):** force saturation past the #118 budget → response carries `Retry-After`/`busy:true` (not a bare masked 503); client honors it with bounded backoff and does not blind-spam. Assert no duplicate posts result from a saturation event.
4. **Live AC:** run the b1 queue-soak drill post-deploy — ack persistence 100%, zero duplicate posts under retry, 503s carry an explicit retry signal. Emit `POST_DEPLOY_AC_VERDICT v1`. Deputy (bus-health owner) folds delivery metrics into the dispatcher sweep.

## Quality Checkpoints / Acceptance criteria

- **done rubric:** (1) ack read-back 100% incl. concurrency; (2) idempotent re-ack preserved; (3) idempotency key on all writes + wake fires exactly once on dedup; (4) explicit busy signal replaces bare 503, clients honor it, no retry-born duplicates; (5) live soak AC + `POST_DEPLOY_AC_VERDICT v1`.
- **done-state class:** production correctness → live soak AC required.
- **gate plan:** deputy authors → **lead reviews BEFORE worker dispatch** → (P1.1 gated on E1 diagnosis outcome) → builder implements → independent codex verify BEFORE merge (#9255) → lead merges → deploy → deputy verifies live as bus-health owner.
- **Harness-V2:** covered inline.

## Dedupe / cross-links

- Builds on #118 (bounded-acquire) + `023d95f` (row dedup); does NOT redo them.
- P1.1 depends on `BRIEF_BRISEN_LAB_E1_ACK_NO_OP_DIAGNOSE_1` (diagnosis-first) — sequence the diagnosis, then this fix.
- P2 (lease/heartbeat/lifecycle closed-loop) + P3 (typed schema/identity) + P4 (enforcement/observability + the delivery-health dashboard) queued after P1 ships, per Director's incremental ruling.
- Evidence: training-file crosswalk F-503/E1/E2/E8 (`05_outputs/2026-07-12-case-one-bus-hardening-training-file.md`).
