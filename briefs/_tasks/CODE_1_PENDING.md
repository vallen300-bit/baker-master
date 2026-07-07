---
status: PENDING
brief_id: AO_FLIGHT_PROD_TICKET_ROUTING_1
to: b1
from: lead
dispatched_by: lead
dispatched_at: 2026-07-07
reply_target: lead (bus topic baker-os-v2/ao-flight-ticket-routing)
task_class: feature-gap fix (per-matter ticket routing) + tests
gate_plan: diagnose-confirm -> TDD test first -> fix -> deputy G2 -> codex G3 (gate/ao-ticket-routing-g3, medium) -> lead merge -> post-deploy AC verdict
arc: Baker OS V2 Wave 2 — AO flight onboarding (Director goal 2026-07-07: AO Desk receives its own tickets in production)
harness_v2: applies (see brief)
---

# ACTIVE: AO_FLIGHT_PROD_TICKET_ROUTING_1 — dispatch to B1 (fresh seat)

Full brief (main): `briefs/_tasks/AO_FLIGHT_PROD_TICKET_ROUTING_1.md` — READ IT, source of truth.
Lead pre-explored: bridge is single-flight (`AIRPORT_TICKETING_DESK` global, default baden-baden-desk);
design pre-picked = env JSON desk map + `_desk_for_matter()` helper. Diagnose gate still fires FIRST
(email-lane matter attribution is the open question) — post findings, wait for lead scope-confirm.

You are a FRESH b1 seat. Predecessor rolled over at 91% (#6673) with its queue closed out:
B4 preflight DONE (report merged), AO_FLIGHT_IDENTITY_RECONCILE_1 DONE (report merged),
57-doc re-tag DONE (#6557). Its researcher-cage follow-up commits (vault branch
b1/researcher-harness-retrofit @21a1b88) are PARKED pending codex #6760 closure design —
NOT your task unless lead re-dispatches.

## Queued behind (do NOT start until routing brief accepted by lead)

TURNAROUND_AGENT_REFRESH_1 (cowork-ah1, dispatched 2026-06-22) — still queued, outranked by
AO onboarding. Prior B4 envelope preserved in git history (this file @480a54f6 and earlier).
