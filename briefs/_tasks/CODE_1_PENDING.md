---
status: PENDING
brief_id: TURNAROUND_AGENT_REFRESH_1
to: b1
from: cowork-ah1
dispatched_by: cowork-ah1
dispatched_at: 2026-06-22
reply_target: cowork-ah1 (bus)
task_class: fleet-infra / dashboard feature (brisen-lab: db.py + app.py + bus.py + static + generator)
gate_plan: G0 codex-arch APPROVE_WITH_RULINGS #3827 + codex verify PASS-WITH-NITS #3861 (ALL DONE) -> B1 build -> G1 pytest -> G3 codex code gate -> cowork-ah1 merge -> live (additive, NO feature flag)
arc: TURNAROUND (agent refresh; companion to shipped+live STEALTH_FLIGHT)
harness_v2: applies
---

# TURNAROUND_AGENT_REFRESH_1 — dispatch to B1

Full brief (this commit): briefs/BRIEF_TURNAROUND_AGENT_REFRESH_1.md — READ IT, source of truth.

## What
Director-facing "Refresh" controls on Brisen Lab cards to force a fresh-context restart of a tired agent (instead of terminal-by-terminal). Reuses EXISTING lifecycle.trigger_force_fresh_context + session-age badges + is_working. New POST /api/refresh-agent (single + fleet) + card Refresh button. ADDITIVE, Director-click-only, origin-gated — NO feature flag, safe to go live.

## Design status: TRIPLE-CLEARED, all green
- codex-arch G0 APPROVE_WITH_RULINGS (#3827; R1/R2/R3 folded)
- codex (AG-202) verify rounds #3837 (5 findings) + #3852 (2) -> #3861 PASS-WITH-NITS (ALL folded)

## Read the brief in authority order, then build
1. ROLE/Surface contract + CODEX-ARCH G0 RULINGS #3827 (R1 refreshable-set, R2 protected-confirm, R3 busy-queue).
2. CODEX (AG-202) FINDINGS LOCKED: F1 busy queues for ALL modes (only force= bypasses); F2 PROTECTED_SLUGS confirm_protected=true server-side (409 else); F3 REFRESHABLE_SLUGS GENERATED from registry predicate `bus_enabled and runtime.startswith("terminal-")` (no hand-list); F4 refresh_requests DDL in db.py SCHEMA_V2_SQL (NO migrations/ dir) + bounded drain honoring heartbeat contract app.py:345-348 + max-defer ~10min; F5 fleet branch BEFORE alias validation; button preventDefault()+stopPropagation(); shared _refresh_one() guard helper.

## Gates
G1 pytest (endpoint + mode gating + non-refreshable 400 + protected-confirm + busy-pending persists+drains + max-defer expires + no-alias fleet path) -> G3 codex code gate -> cowork-ah1 merge -> live. Additive, no flag flip.

## Reply
Ship report -> bus to cowork-ah1 (dispatched_by: cowork-ah1). Heartbeat if long. Blockers -> cowork-ah1, not Director.
