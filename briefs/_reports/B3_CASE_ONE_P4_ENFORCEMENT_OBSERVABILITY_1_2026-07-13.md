# B3 ship report — CASE_ONE_P4_ENFORCEMENT_OBSERVABILITY_1

Date: 2026-07-13
Builder: b3 (fresh successor seat; claimed the pre-build checkpoint attempt:2 @9ddc98ca)
Dispatch: lead bus #10036. Brief @381ebedb. Effort: HIGH. Final Case-One phase.
Gate: G1 self-verify (done) → independent Claude-side review by lead (codex suspended #9711) → lead merges → deploy → deputy live drill.

## PRs (two-repo)
- **baker-master PR #546** @7d957253 — harness: GO-reroute gate, standing-rules re-assertion hook, band self-read symlink.
- **brisen-lab PR #125** @2c1c5f8 — observability spine, recipient-scope /artifact, intent alerting, delivery-health dashboard.

## Done rubric (brief §Quality Checkpoints)

1. **Session-start re-assertion + worker-side GO-reroute gate — STRUCTURAL, not prose.** ✅
   - `.claude/hooks/standing-rules-reassert.sh` re-asserts the 3 standing rules at SessionStart AND on a mid-session UserPromptSubmit cadence (every Nth prompt, per-session counter). Additive wiring in `settings.json`.
   - `scripts/go_reroute_gate.py` (wired in `bus_post.sh`) reroutes a Director-addressed GO/confirm on already-dispatched work to the sender's `reports_to` superior.
2. **Intent-granular alerting on assignment only + symptoms-only + 503-noise demoted.** ✅
   - `_is_assignment(kind, parent_id)` = root dispatch (no parent_id). Dispatch-warning gated on it — a reply/fyi no longer trips it.
   - 503/`bus_busy_retry` + dedup-reject → bounded in-memory rate metrics (not per-event alarms).
3. **traceparent + delivery receipts + dead-letter — no silent drops, false-clean detectable.** ✅
   - W3C traceparent captured on the P3 envelope (column + catalog-guarded ALTER; surfaced on read).
   - `brisen_lab_delivery_receipt` — receipt on drain + ack-stamp; undelivered-past-SLA (row, no receipt) is queryable → the `0-unacked` false-clean is caught.
   - `brisen_lab_dead_letter` — door-rejections captured with reason (unknown-recipient / bad-kind / body / tier-below-classification), never a silent 400-drop.
4. **Delivery-health dashboard live + deputy named owner; defects surface without a human nudge.** ✅
   - `/api/bus_health` extended (undelivered-past-SLA + by-seat, dead-letter depth + recent, missed-heartbeat seats, 503 rate, dedup rate) — extends the shipped surface (#119-#122), no fork.
   - `/delivery-health` engine-room page (Pattern C/D, not Director-facing). Named standing owner: **deputy (AH2)**.
5. **Band self-read symlink.** ✅ `<alias>.current` maintained atomically by the P2 emitter in `context-threshold-check.sh`.
6. **Live drill AC + POST_DEPLOY_AC_VERDICT v1.** ⏳ post-merge, deputy-owned (deputy assumes the bus-health-owner sweep against the new dashboard).

## Two binding riders (#10036)

1. **GO-reroute gate CONSERVATIVE.** ✅ Reroutes ONLY a GO/confirm about referenced already-dispatched work (job/PR/brief token). Protected veto beats every positive signal — `ratify_required` / Tier-B/C / business (money, counterparty, sign, external send) is NEVER rerouted. Env kill switch `BAKER_GO_REROUTE_DISABLED`. Audit line to `~/.brisen-lab/go-reroute.log` on every reroute; reroute target == `lead` for every current seat → cc-lead is inherent. **Mandatory false-positive tests present + passing** (ratify, Tier-B/C, business question, bare-GO, kill switch, non-director, top-level sender — all asserted NOT rerouted).
2. **Recipient-scope GET /artifact/{ref}.** ✅ Tightened from any-authenticated-seat: recipient/sender/Director → 200, non-recipient → **403** (test asserts it), unknown ref → 404 (no existence leak).

## Tests (literal)
- `tests/test_go_reroute_gate.py` — **23 passed** (baker-master).
- `tests/test_context_meter.py` — **15 passed** (baker-master; P4.5 symlink covered).
- `tests/test_case_one_p4_enforcement_observability.py` — **8 passed** (brisen-lab, isolated local pg).
- brisen-lab P3 + bus regression lanes — **120 passed**.
- Full brisen-lab suite — **27 failed / 534 passed / 1 skipped**. The 27 are the pre-existing autowake/identity env-baseline failures (test_bus_autowake*, test_autowake_master_killswitch, test_agent_identity_generated, test_bus_wake_topic_gate, test_agent_queue) — no CI, cross-region latency; 526→534 = my 8 new P4 tests, **no new failures introduced**.

## Notes for lead
- Scope-dedupe honored: consumes P3 typed envelope + `kind`; surfaces P2 heartbeat/lease on the dashboard; observes (not redoes) P1 delivery correctness; the session-start re-assertion generalizes lead's 70/85 structural-gate pattern, does not rebuild the context meter.
- `cc lead` on reroute: implemented as reroute-target == `lead` (true for every current rerouting seat, since all report to lead) + the go-reroute.log audit trail. If a future seat reports to a non-lead superior, an explicit lead cc should be added in `bus_post.sh` (marked in-code).
- **Stray artifact flagged**: a nested `brisen-lab/` clone (its own `.git`, created in a prior P3 session, Jul 12) sits untracked in `~/bm-b3`. NOT committed (I staged only the specific P4 files, never `git add -A`). Recommend cleanup.
