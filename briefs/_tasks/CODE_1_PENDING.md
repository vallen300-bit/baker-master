---
status: CLOSED (arc completed 2026-07-10 — commit 4e73aa6a: F5 render check PASS #8360, pilot LIVE hag-desk; mailbox flag never flipped, corrected 2026-07-12 during BUS_FLEET_COMMS_AUDIT_1 dispatch)
brief_id: AGENT_WORK_QUEUE_V1
to: b1
from: lead
dispatched_by: lead
dispatched_at: 2026-07-09
reply_target: lead (bus topic fleet/agent-work-queue)
task_class: feature-build (production service change, brisen-lab — NOT baker-master)
gate_plan: build -> brisen-lab PR -> codex bus G3 (reasoning_effort=medium) -> lead merge -> Render deploy flag-off 24h soak -> POST_DEPLOY_AC_VERDICT v1 (seeded-failure drill = the AC) -> lead flips agent_queue_enabled for hag pilot
arc: agent work-queue V1 (sacca #7987 -> lead ratification #8004 -> G0 PASS-WITH-NITS #8099, nits folded rev3)
harness_v2: applies (see brief)
recommended_effort: high (Medium-High, ~9h, production substrate)
---

# ACTIVE: AGENT_WORK_QUEUE_V1 — dispatch to B1

Full brief (main): `briefs/BRIEF_AGENT_WORK_QUEUE_V1.md` @da652c8c — READ IT, source of truth.

Dispatch gate satisfied: b1/b4 wave closed 2026-07-09 (your ARM verdict #8122 accepted #8128;
b4 lane closed #8126). This dispatch = the lead wave-close confirmation the brief's
Prerequisites require.

Key rails (from the brief — locked decisions table §Locked, do NOT relitigate in build):
- Target repo = **brisen-lab**, schema via inline `db.py` bootstrap (NO migrations/ dir).
- Re-verify every referenced signature against brisen-lab origin/main at build time — draft
  written against @15fb160-era; repo moves fast. Your local ~/bm-b1/brisen-lab checkout is
  stale scratch (your own #8122 note) — fresh pull first.
- TDD first test: two concurrent claims on one job -> exactly one winner (live-PG pytest).
- Done-state class = deployed-flag-off-soak-verified. Merged != done; checkpoint-8 drill required.
- Pilot = hag-desk only, enforcement flag default OFF; rollback = flag off.

Context hygiene: you just closed the ARM arc — if your context is >=50%, checkpoint + respawn
a fresh seat BEFORE starting (worker 50% refresh rule). State your % in first status post.

## Queued behind (unchanged, do NOT start)

TURNAROUND_AGENT_REFRESH_1 (cowork-ah1, dispatched 2026-06-22) — still queued, outranked.
Prior envelopes preserved in git history (this file @480a54f6 and earlier).
