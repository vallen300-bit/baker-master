---
status: PENDING
brief_id: BAKER_OS_V2_B4_AO_DATA_PREFLIGHT_1
to: b1
from: lead
dispatched_by: lead
dispatched_at: 2026-07-07
reply_target: lead (bus topic baker-os-v2/b4-ao-data-preflight)
task_class: diagnostic/verification (read-only data checks)
gate_plan: findings report -> lead review (no code merge expected; fix PRs = separate briefs)
arc: Baker OS V2 Wave 2 — AO flight onboarding
harness_v2: applies (see brief)
---

# ACTIVE: BAKER_OS_V2_B4_AO_DATA_PREFLIGHT_1 — dispatch to B1

Full brief (main @7646753): `briefs/_tasks/BAKER_OS_V2_B4_AO_DATA_PREFLIGHT_1.md` — READ IT, source of truth.

**Participant list is ALREADY RATIFIED** (Director 2026-07-07 via ao-desk Triaga): manifest at
`wiki/matters/oskolkov/02_inventory/2026-07-07-ao-flight-participant-manifest-ratified.md`
(ao-desk bus #6229 to b1). 3 name-triggers (Andrey Oskolkov, Lana, Ania) + 9 coverage-keys +
exclusion families (MO-VIE/Baden-Baden crossroad routes OUT). Use it as the confirmed list for
check 1 — no "pending Director confirm" rows, no delta re-run needed.

## Queued behind (do NOT start until B4 report accepted by lead)

TURNAROUND_AGENT_REFRESH_1 (cowork-ah1, dispatched 2026-06-22, gates G0 done) — still wanted but
outranked by AO onboarding. Lead reconciles sequencing with cowork-ah1; b1 ignores it for now.
Prior envelope preserved in git history (this file @76a55e4 and earlier).
