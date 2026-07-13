# CODE_4_PENDING — active dispatch mailbox for b4

---
status: ACTIVE
brief_id: ARM_OUT_OF_BAND_ALARM_1
to: b4
from: deputy-codex (bus dispatch #10404); endorsed as b4's new lane by lead #10416
dispatched_by: deputy-codex
dispatched_at: 2026-07-13
reply_target: lead (ship report + gate verdict to lead; ack/start to deputy-codex)
task_class: fleet infra — out-of-band (non-bus) alarm launchd watchdog
gate_plan: build -> PR to main -> codex review -> lead merge -> install (host-side) + POST_DEPLOY_AC (drift-check + launchctl list)
harness_v2: applies
recommended_effort: medium
charter_spec: ~/baker-vault/_ops/build/baker-os-v2/05_outputs/domain-agent-program/DRAFT_SPEC_ARM_BUS_CUSTODIAN_AMENDMENT_V1.md (RATIFIED v1.1 @c435b18) — D3 canary + §3 report-miss
---

# ACTIVE: ARM_OUT_OF_BAND_ALARM_1 — dispatch to b4 (bus #10404, deputy-codex)

Out-of-band alarm path (Plan v3). Non-bus alarm for canary failure + report-miss.

- Host-side KeepAlive launchd job, deploy to `~/Library/Application Support/` (TCC).
- Reads local freshness markers only (never the bus); emails out-of-band via
  Outlook.app (Director ruling this session) + macOS notification.
- Define owner, trigger, ≤5m alarm SLO, dedupe; keep separate from bus controls.
- Include install script + drift check + test evidence.
- Gate: codex review, then lead merge. Effort: medium.

**Prior brief CLOSED (2026-07-13):** ARM_CADENCE_LAUNCHD_JOB_1 shipped + merged
(PR #553 @cb51bf1b, codex G2 PASS #10360, installed by lead, POST_DEPLOY_AC PASS
#10363 per lead #10416). Its stale autostub checkpoint is deleted.

**Earlier seat state:** BUS_CONSOLE_LIVE_PAGE_1 CLOSED (PR #525). CASE_ONE_E23_
SESSION_STATE_PERSISTENCE_1 CLOSED (PR #551 @f609697e).
