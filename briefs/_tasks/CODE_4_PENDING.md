# CODE_4_PENDING — active dispatch mailbox for b4

---
status: COMPLETE  # ratified #8206, PR #510 merged @9046e2f0; AO_MATERIALITY_HOOK_1 also closed (G3 R4 PASS #8437); marked 2026-07-11 per b4 #8850
brief_id: MOVIE_FLIGHT_GATE2_ACTIVATION_1
to: b4
from: lead
dispatched_by: lead
dispatched_at: 2026-07-09
reply_target: lead (bus topic baker-os-v2/movie-flight-gate2)
task_class: feature-gap activation (config/registry expected; code only if justified)
gate_plan: diagnose findings -> lead scope-confirm -> build -> PR -> codex G3 (medium) -> lead merge -> live probes -> POST_DEPLOY_AC_VERDICT
arc: MO-VIE-001 launch (Director GO 2026-07-09 ~16:55Z) — Gate-2 keyword + routing activation
harness_v2: applies (see brief)
recommended_effort: medium (mirror of shipped AO precedent, ~3h)
---

# ACTIVE: MOVIE_FLIGHT_GATE2_ACTIVATION_1 — dispatch to B4

Full brief (main): `briefs/_tasks/MOVIE_FLIGHT_GATE2_ACTIVATION_1.md` — READ IT, source of truth.

Two hard sequence points, do not skip:
1. Diagnose findings post FIRST (registry rows, live keyword env, KNOWN-sender widening) —
   wait for lead scope-confirm.
2. Keyword list = lead sign-off on bus BEFORE any env flip. NEVER bare `movie`; `rg7`
   collides with hagenauer-rg7.

Context hygiene: state your context % in first status post; >=50% = checkpoint + respawn first.

**SUPERSEDED / DO NOT REDO:**
- BB_AUK_001_AUDIT_ROUND2_DASHBOARD_UPDATE_1 stage 2 — folded into BB-AUK dashboard arc,
  closed (dashboard v24 live per baden-baden-desk pin 2026-07-09).
- BOX5_OUTBOUND_CORRELATION_FIX_1 — SHIPPED, PR #448 MERGED 2026-07-01 (bus #5548).
