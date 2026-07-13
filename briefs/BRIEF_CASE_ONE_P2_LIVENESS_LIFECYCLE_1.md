# BRIEF: CASE_ONE_P2_LIVENESS_LIFECYCLE_1 — unified wake+heartbeat lease + heartbeat-as-harness-contract + bounded-restart thrash guard + liveness/readiness split

> Case One bus-hardening **P2** (liveness & lifecycle, E9/E10/E17/E19 + F-503-B reopen + tonight's
> wake incident + snapshot-pusher outage). Authored by deputy (AH2, standing bus-health owner)
> from ARM's plan (vault #178, P2 section) + researcher validation #9763 (relayed lead #9913).
> **TO LEAD FOR REVIEW BEFORE WORKER DISPATCH.** Codex suspended (#9711) → Claude-side independent
> review before merge. Sequenced after P1 (delivery correctness); builds on the P0 lifecycle layer.

dispatched_by: lead (pending review)
assigned_to: <builder — lead assigns after review>
task_class: backend-lifecycle (brisen-lab: lease/heartbeat model, liveness/readiness probes, closed-loop respawn) + fleet harness (structural heartbeat emitter, KeepAlive install)
Harness-V2: Context Contract + done rubric + gate plan inline.
effort: high

## Context

**Context Contract.** Repos: brisen-lab (bus daemon — new lease table + `bus.py` heartbeat/lease endpoints + `/lifecycle/*` liveness/readiness probes + daemon respawn-verify path; `db.py`) + fleet harness (a structural heartbeat emitter installed per-seat, KeepAlive-hardened like `scripts/install_forge_push.sh`; the lifecycle/rollover layer P0 shipped). **No new service** — graduated path (Postgres source-of-truth + lease rows + polling/doorbell) per the transport doc. Builds ON already-shipped pieces — do NOT redo them.

Liveness & lifecycle is the third story after metering (P0) and delivery (P1). The delivery layer can now be made honest (P1), but the fleet still cannot answer **"is this seat alive and processing?"** F-503-B flapped all this session *after* #118 merged; a dispatch-wake was suppressed with no error (E19); wakes were delivered but not processed tonight; the snapshot-pusher (the only current liveness feed) was itself out for arm/b1/b3/deputy. Every one of these is a liveness/lifecycle gap, not a delivery gap.

### SCOPE DEDUPE (MANDATORY — lead #9563 discipline). Already shipped / owned elsewhere; this brief must NOT re-cover:
- **P0 lifecycle layer (band state in rollover)** — SHIPPED (#540/#123). The lease object EXTENDS the existing lifecycle layer with liveness fields; it does NOT re-implement band metering or the rollover ordering.
- **P1 durable `wake_attempted_at` (side-effect dedup)** — authored in P1. That field proves a wake *fired at most once*; it is NOT the heartbeat store and NOT the liveness ledger. P2's lease `last_heartbeat_at` is a distinct field; wake-fired proof reads the existing `wake_events` ledger (`GET /api/wake_health`), never the vestigial `wake_attempted_at` (never written — see AH2 wake-diagnostics note). Do NOT conflate the three.
- **Wake mechanism (`wake_events`, `/api/wake_health`)** — EXISTS. P2 reads it for the verify step; it does not rebuild the wake path.
- **Snapshot-pusher** — the forge snapshot pusher is telemetry, not the liveness contract. P2 makes the *heartbeat* the canonical liveness signal so a snapshot-pusher outage becomes detectable (missing heartbeat = emitter died), but does NOT re-plumb the snapshot pipeline itself.

## Problem

Four liveness/lifecycle gaps remain — all reproduced live this session with message IDs:

1. **No lease/heartbeat — "assigned but dead" is undetectable (E9, E10).** A worker went silent 5h+ on a GO with no liveness signal (E9); wake-locks go stale and a cadence kill fires without respawn-confirm (E10). The wake-lock and any liveness notion live in separate, un-joined places, so nothing can say "this seat holds a dispatch but has not made progress."
2. **Heartbeat (where it exists at all) is prompt-asked, not structurally emitted (E9, tonight's wake incident, snapshot-pusher outage).** Prompt-level self-monitoring decays within a live session (the single deepest Case-One lesson). Tonight wakes were *delivered but unprocessed* — the seat looked reachable but was not working — and the one telemetry feed that hinted at liveness (snapshot-pusher) was itself silently out for 4 seats. A liveness signal that depends on the model remembering to send it is not a liveness signal.
3. **Lifecycle ops are open-loop; restarts can thrash; suppressed wakes vanish (E10, E19).** Kill→spawn has no verify step, so a cadence kill can leave nothing running; a flapping seat could be respawned without bound; and a dispatch-wake was *suppressed with no error* (E19 — b3 #9855 never woke), swallowed silently instead of surfacing as a failed lifecycle op.
4. **No liveness/readiness split; interactive seats can't self-terminate (E17, F-503-B).** The fleet treats "alive" and "ready to accept work" as one bit. Director-driven interactive seats (cowork) cannot self-terminate, so a cadence kill has no honest path for them. And the daemon's own 503 flap (F-503-B, persisted all session post-#118) cannot be classified — pool-saturated-but-alive (not-ready) vs daemon-dead (not-alive) — because there is no readiness probe distinct from liveness.

## Fix (four pieces, build on the P0 lifecycle layer)

### P2.1 — Unified wake+heartbeat lease object, TTL + owner-liveness (E9/E10 fix)
One **lease row per active dispatch** in the lifecycle layer, joining what is today split: `{owner_seat, job_ref, acquired_at, ttl_s, last_heartbeat_at, wake_state}`. The wake-lock IS the lease — acquiring a dispatch takes the lease; the lease auto-expires on TTL (kills E10 stale wake-locks — no manual clear). "Assigned but dead" (E9) becomes a single query: lease exists AND `now - last_heartbeat_at > ttl_s`. Owner-liveness: only the lease owner (server-derived identity, per P3) may renew; a non-owner renewal is rejected. Lease state is a machine field in status posts so the dispatcher reads it, never infers it.

### P2.2 — Heartbeat emission as a harness contract (E9 / tonight's wake incident / snapshot-pusher outage)
Define heartbeat emission as a **structural harness contract**, not a prompt instruction. A per-seat emitter (installed like `install_forge_push.sh`, KeepAlive-hardened, self-resumes on crash/reboot) posts a heartbeat on a fixed cadence that renews the lease and carries a liveness token (seat alive) plus a progress marker (advancing = processing). A *delivered-but-unprocessed* wake (tonight) is then detectable: wake fired in `wake_events` but no heartbeat progress within the grace window → flagged, not silently accepted. A snapshot-pusher-class outage is detectable the same way: the emitter dying = missing heartbeat = surfaced, instead of 4 seats going dark unnoticed. Contract spec must fix: cadence, grace window, self-heal mechanism, and the machine liveness field — and must NOT rely on any prompt-level "remember to heartbeat" line (prompt-rule-decay lesson).

### P2.3 — Closed-loop kill→spawn→verify + bounded-restart thrash guard (E10/E19 fix)
Every lifecycle op is closed-loop: **kill → spawn → verify**. Verify = the new seat emits a fresh heartbeat (renews a new lease) within a grace window before the op is called DONE — no more cadence-kill-without-respawn-confirm (E10). The verify step also asserts the dispatch actually *fired a wake* (`wake_events`) and the target *began heartbeating*; a suppressed wake (E19) fails verify loudly instead of vanishing. **Thrash guard:** bound respawns to N within window M (e.g. 3 / 10 min); on exceeding, STOP auto-respawn and escalate to the seat's owner/dispatcher — a flapping seat must not be restarted forever. Fail-loud: a failed verify is a surfaced lifecycle error with the failing seat + reason, never a silent skip.

### P2.4 — Liveness/readiness split + seat-type awareness (E17/F-503-B fix)
Split the one bit into two probes: **liveness** (`/lifecycle/live` — is the seat/daemon alive) and **readiness** (`/lifecycle/ready` — is it accepting/processing work now). Seat-type awareness in the lease: `daemon_spawnable` seats get the full P2.3 closed-loop external kill+respawn; `interactive` seats (Director-driven cowork — cannot self-terminate) get an external kill+respawn **side-door** or an in-place context handoff, and their readiness is scored differently (interactive alive-but-idle ≠ dead). For the daemon itself, the readiness probe resolves F-503-B: a pool-saturated-but-alive daemon returns *not-ready* (honest, distinct from dead), so the "pool-exhaustion vs daemon-busy 503" open question is answerable from the probe instead of guessed from flap symptoms.

## Files Modified

- brisen-lab: migration for the `lease` table (`owner_seat, job_ref, acquired_at, ttl_s, last_heartbeat_at, wake_state, seat_type`); `bus.py` (lease acquire/renew/expire + heartbeat POST + owner-liveness check; `/lifecycle/live` + `/lifecycle/ready` probes; daemon respawn-verify path reading `wake_events`); `db.py`. Reuse P0's lifecycle layer — extend, don't fork.
- Fleet harness: a structural heartbeat emitter + its KeepAlive install script (pattern: `scripts/install_forge_push.sh`); lifecycle/kill-spawn helper gains the verify step + thrash-guard counter; seat-type declared per picker.
- Tests in brisen-lab (lease TTL/expiry, owner-liveness reject, verify-fires-on-suppressed-wake, thrash-guard bound, live vs ready divergence) + a fleet round-trip test (emitter renews lease; killed emitter surfaces as missing heartbeat).

## Verification

1. **Lease / assigned-but-dead (E9/E10):** acquire a lease, stop heartbeating → after TTL the lease reads expired and "assigned but dead" is queryable; a stale wake-lock auto-clears on TTL (no manual clear); a non-owner renew is rejected.
2. **Heartbeat-as-contract (E9 / wake incident / snapshot outage):** the structural emitter renews the lease on cadence with zero prompt involvement; kill the emitter → missing heartbeat surfaces within the grace window; simulate a delivered-but-unprocessed wake (wake in `wake_events`, no progress) → flagged, not accepted.
3. **Closed-loop + thrash guard (E10/E19):** kill→spawn→verify passes only when the new seat heartbeats within grace; a suppressed dispatch-wake (no `wake_events` entry) FAILS verify loudly; force >N restarts in window M → auto-respawn stops and escalates.
4. **Liveness/readiness + seat-type (E17/F-503-B):** `/lifecycle/live` and `/lifecycle/ready` diverge correctly under a saturated-but-alive daemon (ready=false, live=true — classifies F-503-B); an `interactive` seat is not marked dead when idle and routes to the side-door path, not a self-terminate that cannot fire.
5. **Live AC:** post-deploy fleet drill — kill a daemon seat and confirm closed-loop respawn+verify; confirm every live seat holds a renewing lease with a fresh heartbeat; confirm the daemon readiness probe reflects a real saturation event. Emit `POST_DEPLOY_AC_VERDICT v1`. Deputy (bus-health owner) folds lease/heartbeat/readiness metrics into the dispatcher sweep + the delivery-health dashboard (P4).

## Quality Checkpoints / Acceptance criteria

- **done rubric:** (1) unified lease joins wake-lock+heartbeat, TTL auto-expiry, owner-liveness enforced; (2) heartbeat emitted structurally (KeepAlive emitter, no prompt dependency), emitter death detectable; (3) kill→spawn→verify closed loop with fail-loud suppressed-wake detection + bounded-restart thrash guard; (4) liveness/readiness probes split, seat-type aware (interactive side-door vs daemon respawn), F-503-B classifiable; (5) live fleet drill AC + `POST_DEPLOY_AC_VERDICT v1`.
- **done-state class:** production lifecycle correctness → live fleet drill AC required (compile-clean ≠ done — Lesson #8).
- **gate plan:** deputy authors → **lead reviews BEFORE worker dispatch** → builder implements → **independent Claude-side review by lead BEFORE merge** (codex seats suspended per Director #9711 until lifted; #9255 independent-verdict-before-merge rule holds, Claude-side) → lead merges → deploy → deputy verifies live as bus-health owner.
- **Harness-V2:** covered inline (Context Contract + done rubric + gate plan).

## Dedupe / cross-links

- Builds on P0 lifecycle layer (#540/#123) + the existing `wake_events`/`/api/wake_health` ledger; does NOT redo band metering, the wake path, or the snapshot pipeline.
- Distinct fields — keep separate: P1 `wake_attempted_at` (fired-at-most-once side-effect dedup) ≠ P2 lease `last_heartbeat_at` (liveness) ≠ vestigial legacy `wake_attempted_at` read (never used).
- Server-derived identity for owner-liveness lands fully in **P3** (E12) — P2 uses whatever identity P3 exposes; if P3 not yet shipped, gate the owner-liveness check on the interim shared-key seat id and flag the upgrade.
- P4 (behavioral enforcement + observability + delivery-health dashboard) consumes P2's lease/heartbeat/readiness metrics — sequence P4 after P2 ships.
- Evidence: training-file crosswalk E9/E10/E17 (`05_outputs/2026-07-12-case-one-bus-hardening-training-file.md`) + this session's ledger E19 (suppressed dispatch-wake), F-503-B (post-#118 flap), delivered-but-unprocessed wakes, snapshot-pusher outage (checkpoint `_checkpoints/DEPUTY_ROLL_2026-07-13.md`).
</content>
</invoke>
