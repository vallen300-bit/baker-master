# CODE_4_PENDING — active dispatch mailbox for b4

---
status: ACTIVE
brief_id: ARM_CADENCE_LAUNCHD_JOB_1
to: b4
from: lead (bus dispatch #10331)
dispatched_by: lead
dispatched_at: 2026-07-13
reply_target: lead (ship report + gate verdict to lead)
task_class: fleet infra — KeepAlive launchd watchdog (host-side, read-only poller)
gate_plan: build -> PR to main -> codex review -> lead merge -> install (host-side) + POST_DEPLOY_AC (drift-check + launchctl list)
harness_v2: applies
recommended_effort: medium
charter_spec: ~/baker-vault/_ops/build/baker-os-v2/05_outputs/domain-agent-program/DRAFT_SPEC_ARM_BUS_CUSTODIAN_AMENDMENT_V1.md (RATIFIED v1.1 @c435b18) — D2 + §4
---

# ACTIVE: ARM_CADENCE_LAUNCHD_JOB_1 — dispatch to b4 (bus #10331)

ARM custodian machine-cadence watchdog. Director-ratified charter D2 + §4.

- KeepAlive-hardened launchd job (forge-snapshot-pusher pattern), deploy to
  `~/Library/Application Support/` — NOT `~/Desktop` (TCC lesson).
- Polls `GET /api/bus_health` (+ `arm_sql` telemetry as P1–P4 tables land) every
  30 min. curl/SQL only, ZERO LLM per poll.
- Writes a snapshot that ARM's report synthesis reads at wake.
- Include install script + drift check.
- Gate: codex review, then lead merge. Effort: medium.

**Prior seat state (reconciled 2026-07-13):** BUS_CONSOLE_LIVE_PAGE_1 CLOSED
(PR #525 merged, POST_DEPLOY_AC PASS #9124). CASE_ONE_E23_SESSION_STATE_PERSISTENCE_1
CLOSED (PR #551 merged @f609697e, 3 codex blockers #10226 fixed). Stale
BUS_CONSOLE autostub checkpoint deleted.
