---
brief_id: RESEARCHER_HARNESS_RETROFIT_1
attempt: 1
status: NOT_STARTED — retired at dispatch (predecessor seat context ~70% > 50% threshold, lead #6484 first-instruction)
dispatched_by: lead
reply_to: lead (bus topic baker-os-v2/researcher-harness-retrofit)
priority: P1 — security retrofit, 1-session
created: 2026-07-07
---

# Checkpoint — RESEARCHER_HARNESS_RETROFIT_1 (attempt 1)

Fresh seat: this is a COLD pickup. Nothing started — the predecessor seat retired immediately at dispatch
because it was ~70% context (had just carried the full AO_FLIGHT_IDENTITY_RECONCILE_1 arc). Read the brief
and execute from scratch. Bump `attempt: 2` here on claim (per rollover rule).

## Brief (source of truth — READ IT)
- `baker-vault _ops/build/baker-os-v2/05_outputs/domain-agent-program/BRIEF_RESEARCHER_HARNESS_RETROFIT_1.md` @4673937 (vault main).
- Dispatch bus msg: lead #6484 (topic baker-os-v2/researcher-harness-retrofit).

## Scope (from dispatch #6484 — confirm against brief)
- P1 security retrofit, 1-session.
- PreToolUse write-cage: ENFORCE ON, fail-closed; reuse render_acl_guard shape @da04b8e.
- disallowedTools: trim send/write.
- writer-contract standby.
- §6 rulings locked; §7 binding — esp R1 seeded REJECT on _ops/agents/researcher self-edit.
- Gate: G1 self -> G2 deputy -> G3 codex bus effort=high.

## Next concrete step
1. git pull; read the brief @4673937 + §6/§7 rulings.
2. Bump attempt: 2 here (claim), commit.
3. Execute the retrofit per brief; run G1/G2/G3 gates.
