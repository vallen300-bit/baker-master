# BRIEF: CASE_ONE_P4_ENFORCEMENT_OBSERVABILITY_1 — structural behavioral enforcement + intent-granular symptoms-only alerting + tracing/receipts/dead-letter + delivery-health dashboard + standing bus-health owner

> Case One bus-hardening **P4** (behavioral enforcement + observability + ownership C, E3/E11/E15 +
> band self-read #9986 + tonight's E20/delivery-loss as the motivating evidence). Authored by deputy
> (AH2, standing bus-health owner) from ARM's plan (vault #178, P4 section) + researcher validation
> #9763 (relayed lead #9913) + lead riders #10024. **TO LEAD FOR REVIEW BEFORE WORKER DISPATCH.**
> Codex suspended (#9711) → Claude-side independent review before merge. Final phase; sequenced after
> P3 (contract/identity, in build at b3) whose typed envelope P4 consumes.

dispatched_by: lead (pending review)
assigned_to: <builder — lead assigns after review>
task_class: mixed — fleet harness (structural session-start re-assertion, worker-side GO-reroute gate, band self-read symlink) + brisen-lab (traceparent on envelope, delivery receipts + dead-letter, intent-filtered alerting) + dashboard (delivery-health page)
Harness-V2: Context Contract + done rubric + gate plan inline.
effort: high

## Context

**Context Contract.** Repos: fleet harness (session-start hook re-assertion; a worker-side gate in the bus-post path that reroutes Director-addressed GO/confirm to the superior; the band-file self-read symlink in the emitter from P2) + brisen-lab (`bus.py` — W3C `traceparent` on the P3 envelope, delivery-receipt + dead-letter tables/endpoints, intent-filtered alert predicate) + a delivery-health dashboard page. **No new service** — observability rides the P3 typed envelope on the existing Postgres store. Builds ON P2 (heartbeat/lease metrics) + P3 (typed envelope, `kind` enum, server identity) — do NOT redo them.

Behavioral enforcement + observability is the fifth and final story, and tonight is its proof: three lead orders were delivery-lost (0-unacked false-clean) and only surfaced because the **Director personally kept nudging "check bus."** That is precisely the failure mode ownership-C exists to kill — defects must surface on a **dashboard**, not when the Director trips over them. The plan's behavioral defects also reproduced this session: workers ask the Director for GO on already-dispatched work (E3), and dispatch-warnings fire on every non-job message (E15, alarm fatigue) — both are prompt-rule decay that must be **engineered**, not trained (the single deepest Case-One lesson).

### SCOPE DEDUPE (MANDATORY — lead #9563 discipline). Already shipped / owned elsewhere; this brief must NOT re-cover:
- **P3 typed envelope + `kind` enum + server identity** — P4 CONSUMES them (traceparent is an added envelope attr; intent-filter reads `kind`; attribution reads P3 identity). Does NOT redefine the envelope.
- **P2 heartbeat/lease + readiness probes** — P4 surfaces them on the dashboard; does NOT re-implement liveness.
- **P1 delivery correctness (ack read-back, backpressure)** — P4 observes/receipts delivery; does NOT redo the ack/dedup transaction.
- **Lead's 70/85 context hook + P0 metering** — the session-start re-assertion GENERALIZES the structural-enforcement pattern; it does NOT re-build the context meter.

## Problem

Four enforcement/observability gaps + one micro-fix — reproduced live:

1. **Prompt-taught rules decay; enforcement is prose, not structure (E3).** Workers asked the Director for GO on already-dispatched work, and standing rules inject on fresh sessions only, so a mid-arc seat forgets them. The only seat that self-enforces (lead's 70/85 hook) is the only one with a *structural* gate.
2. **Alarm fatigue — dispatch-warning fires on every message (E15).** Replies and FYIs trip the same dispatch-warning as real assignments, training recipients to ignore it; and tonight the bus emitted a `bus_busy_retry` flood (503) that is pure noise, not an actionable alert.
3. **No tracing / receipts / dead-letter — lost messages are invisible (E20 / tonight).** There is no correlation ID across message→tool→cost, no delivery receipt to prove a message arrived, and no dead-letter for ones that fail — so three lost legs tonight were invisible until the Director noticed. A `0-unacked` inbox read as "all clear" while real orders sat undelivered.
4. **No standing owner / dashboard — the Director is the monitor (ownership C).** Bus health has no continuous owner and no dashboard; delivery defects surface only when a human trips over them. Tonight the human was the Director, repeatedly.
5. **Micro (E-adjacent, #9986):** a seat cannot identify its own band file (no stable self-reference), blocking self-observation of its own context state.

## Fix (four pieces + one micro, build on P1/P2/P3)

### P4.1 — Structural behavioral enforcement over prompt text (E3)
Two structural gates, not prose:
- **Session-start freshness re-assertion:** a hook re-asserts the standing rules (superior-dispatch routing, execute-on-dispatch, context-band rollover) at session start AND on a mid-session cadence — so the rule does not depend on the model remembering it hours in.
- **Worker-side GO-reroute gate:** in the bus-post path, a Director-addressed GO/confirm/permission/ratify message is intercepted and **rerouted to the superior** (the `reports_to` from the registry) before it reaches the Director — structurally enforcing the standing rule "route GO asks to lead, not Director." Fail-loud: the reroute is logged, not silent.

### P4.2 — Message-intent granularity + symptoms-only, actionable-only alerting (E15)
Reading the P3 `kind` enum: the dispatch-warning fires **only** on `kind=assignment` (job-ref-required), never on `reply`/`fyi` — killing alarm fatigue. Alerting is **symptoms-only + actionable-only**: alert on "message undelivered past SLA", "seat missed heartbeat past TTL", "dead-letter non-empty" (all actionable); suppress raw `bus_busy_retry`/503-retry noise (tonight's flood) into a rate metric, not per-event alarms.

### P4.3 — Observability: W3C traceparent + delivery receipts + dead-letter + OTel GenAI tracing (E20 / tonight)
- **Correlation:** a W3C `traceparent` on every P3 envelope; a trace spans message → invoked tool → cost, per OTel GenAI semantic conventions.
- **Delivery receipts:** delivery + ack state is a first-class, queryable receipt — a `0-unacked` read is backed by receipts, so a false-clean is itself detectable (an order with no delivery receipt past SLA is flagged).
- **Dead-letter:** a message that fails delivery or P3 validation lands in a **dead-letter queue** with its reason, never silently dropped — the three lost legs tonight would have landed here.

### P4.4 — Delivery-health dashboard + named standing owner (ownership C)
A **delivery-health dashboard** (Pattern C/D engine-room register — not Director-facing) surfacing continuously: undelivered-past-SLA count, dead-letter depth, dedup-reject rate, 503/`bus_busy_retry` rate, missed-heartbeat seats, per-seat delivery/ack latency. **Named standing owner = deputy (AH2)** — bus-health ownership is a standing dispatcher/deputy responsibility; deputy folds these metrics into the dispatcher sweep so defects surface on the dashboard, **not when the Director trips over them.** This closes ownership-C from the plan.

### P4.5 — micro: band self-read symlink (#9986, per lead #10024 — fold here, do not lone-patch)
A stable `<alias>.current` symlink in the band dir, maintained by the P2 emitter, so a seat can identify and read its **own** band file (self-observation of context state). Folded into observability, not patched standalone.

## Files Modified

- Fleet harness: session-start re-assertion hook (+ mid-session cadence); worker-side GO-reroute gate in the bus-post path (reads `reports_to` from `agent_registry.yml`); the P2 band emitter maintains the `<alias>.current` symlink.
- brisen-lab: `bus.py` (`traceparent` on the P3 envelope; delivery-receipt write + dead-letter enqueue on failure; intent-filtered alert predicate keyed on `kind`); `db.py` + migration (delivery_receipt + dead_letter tables); a `/bus-health` delivery-metrics endpoint (extend the existing bus-health surface #119-#122).
- Dashboard: delivery-health page (engine-room register) consuming the metrics endpoint.
- Tests: reroute-gate intercepts a Director-addressed GO; alert fires on `assignment` only; undelivered-past-SLA + dead-letter surface a receipt; traceparent round-trips; band self-read resolves the current file.

## Verification

1. **Enforcement (E3):** a Director-addressed GO on already-dispatched work is rerouted to the superior (logged), not delivered to the Director; session-start + cadence re-assertion present in a mid-arc seat's context.
2. **Alert hygiene (E15):** a `reply`/`fyi` does NOT trip the dispatch-warning; an `assignment` does; a `bus_busy_retry` flood registers as a rate metric, not N alarms.
3. **Observability (E20/tonight):** post a message, kill its delivery → it lands in dead-letter with a reason and is NOT reported delivered; an order with no delivery receipt past SLA is flagged (a false-clean `0-unacked` is caught); a trace spans message→tool→cost.
4. **Dashboard + owner (C):** the delivery-health dashboard shows undelivered/dead-letter/503-rate/missed-heartbeat live; deputy's sweep reads it. Reproduce tonight's 3 lost legs → they appear on the dashboard without any human nudge.
5. **Band self-read (#9986):** a seat resolves its own band file via `<alias>.current` and reads its current band.
6. **Live AC:** post-deploy fleet drill — reroute gate, intent-filtered alert, dead-letter capture, dashboard live, band self-read all exercised on real seats. Emit `POST_DEPLOY_AC_VERDICT v1`. Deputy assumes the named bus-health-owner sweep against the new dashboard.

## Quality Checkpoints / Acceptance criteria

- **done rubric:** (1) session-start re-assertion + worker-side GO-reroute gate structural (not prose); (2) intent-granular alerting on `kind=assignment` only + symptoms-only actionable alerts, 503-noise demoted to a metric; (3) traceparent + delivery receipts + dead-letter — no silent drops, false-clean detectable; (4) delivery-health dashboard live + deputy named standing owner, defects surface without a human nudge; (5) band self-read symlink; (6) live drill AC + `POST_DEPLOY_AC_VERDICT v1`.
- **done-state class:** production observability/enforcement → live fleet drill AC required (compile-clean ≠ done — Lesson #8).
- **gate plan:** deputy authors → **lead reviews BEFORE worker dispatch** → builder implements → **independent Claude-side review by lead BEFORE merge** (codex suspended per Director #9711 until lifted; #9255 independent-verdict-before-merge holds, Claude-side) → lead merges → deploy → deputy verifies live as the named bus-health owner.
- **Harness-V2:** covered inline (Context Contract + done rubric + gate plan).

## Dedupe / cross-links

- Builds on P1 (delivery), P2 (heartbeat/lease metrics on the dashboard), P3 (typed envelope + `kind` enum + server identity — traceparent/intent-filter/attribution all consume it). Sequence P4 build AFTER P3 ships (b3 @39bba3e4).
- Extends the shipped bus-health surface (#119-#122) rather than forking it.
- Closes ownership-C from ARM's plan (vault #178) by naming deputy the standing owner.
- The delivery-health dashboard is the structural answer to tonight's Director-as-monitor failure — cite E20 as the motivating case.
- Evidence: training-file crosswalk E3/E11/E15 (`05_outputs/2026-07-12-case-one-bus-hardening-training-file.md`) + session E20 (crossed-gate duplication), `deduped:true` storm, `bus_busy_retry` flood, band self-read #9986 (checkpoint `_checkpoints/DEPUTY_ROLL_2026-07-13.md`).
</content>
