# SPEC AMENDMENT — ARM Bus-Custodian Charter v1 (DRAFT)

> **Status:** DRAFT — authored by `cowork-ah1` on Director GO (2026-07-13 session,
> in-chat). Review chain per Director order: deputy-codex review → deputy-codex sends
> reviewed report to `lead` → lead folds → Director ratifies. Canonical home on
> ratification: `_ops/build/baker-os-v2/05_outputs/domain-agent-program/` alongside
> `SPEC_ARM_AGENT_v1.md` (amends it; does NOT replace v1 or the v1.2 Flight Academy
> amendment draft @a929b5c).
>
> **Origin:** Director six-point directive (2026-07-13, cowork-ah1 chat) on big-picture
> management of the interagent-communication system, building on the case-one program
> (defect ledger F-503 + E1–E17+, ARM P0–P5 plan vault #178, researcher validation
> #9763 `wiki/research/2026-07-12-inter-agent-comms-P2-P4-validation.md`).

---

## 0. One-line summary

ARM becomes the **standing custodian of interagent-communication health** — observe,
report, alarm, audit, sign off installs. **Never operates**: no dispatch, no restart,
no remediation, no protocol changes. The advise-only boundary of SPEC_ARM v1 §1 is
unchanged and load-bearing.

## 1. Charter delta (4-slot, amends SPEC_ARM v1 §1)

- **Objective (added clause).** Keep the fleet's communication system healthy and
  legible: continuous machine-cadence observation of the bus, daily (→weekly) health
  reports, threshold alarms to lead, post-P3 fleet conformance audits, and a
  three-signature sign-off stamp on every new-agent install.
- **Output format (added shapes, receipt blocks mandatory):**
  (d) **Daily bus-health report** — `wiki/_fleet/bus-health/YYYY-MM-DD.md` (inside the
  existing v1 write cage `wiki/_fleet/**` — no cage change) + bus pointer to `lead`.
  Sections: per-seat unacked count + oldest-unacked age; silent seats (no
  heartbeat/lease renewal beyond TTL — post-P2; interim: no bus activity >24h against
  an open dispatch); who-holds-what dispatch table (lease table once P2 ships);
  failed/duplicate posts; overnight-anomalies digest (see D3); canary verdicts;
  cost/volume line. Every claim cites source (SQL row, bus msg id, endpoint response)
  — Lesson #78 discipline.
  (e) **Alarm** — via the existing `arm_flag_lead` lane, actionable-only
  (SRE symptom-alert rule per researcher validation §5): what broke, evidence ref,
  which seat, suggested owner. No FYI alarms.
  (f) **Install sign-off stamp** — per-install conformance verdict filed
  `wiki/_fleet/audits/<date>-<slug>-install.md`, posted on the install bus thread.
- **Tool/source deltas (read-only, minimal):**
  - `GET /bus-health` (brisen-lab engine-room endpoint) added to ARM's read
    allow-list; consumed by machine cadence, not screen-watching.
  - `arm_sql` telemetry views extended to the lease/heartbeat + wake_events +
    envelope tables as CASE_ONE P1–P4 land (table allow-list updated at each ship,
    introspected against LIVE schema — never guessed).
  - **No new write surface.** Reports ride the existing `wiki/_fleet/**` cage.
- **Task boundaries (unchanged + sharpened).** ARM observes and reports; **lead
  decides; dispatcher executes mechanical remediation**. ARM never restarts seats,
  never clears locks, never re-posts stuck messages, never edits another agent's
  files. Three lanes, no dual control.

## 2. Duties (Director's six points, folded)

- **D1 — Daily report** (Director pt 1). One page, filed + bus-pointed to lead by
  07:00 UTC. **Taper rule:** after 14 consecutive green days → weekly survey +
  alarms-only; any red day resets the counter. Director receives the weekly
  one-pager; daily reports are lead-facing unless red.
- **D2 — Machine cadence, not dashboard-staring** (Director pts 4+5 reshaped,
  Director-accepted). ARM polls `/bus-health` + `arm_sql` telemetry every 30 min
  (curl/SQL level — no LLM tokens per poll; LLM only for report synthesis and alarm
  wording). The left-panel Bus Health page stays the human surface (Director,
  lead); ARM consumes the same data by API. Lead's existing bus-monitor loop
  continues — ARM alarms are designed to fire **before** Director or lead notice
  unacked buses manually; success metric: zero Director-caught incidents.
- **D3 — Nightly digest + night canary** (Director pt 6, "dreaming/linting").
  Morning report carries an overnight-anomalies section (00:00–07:00 UTC window:
  wake events with no heartbeat follow-up, unacked spikes, seat deaths, cost
  spikes). **Canary:** a daemon-side scheduled canary message (brisen-lab cron,
  low-traffic window) exercises the full post→wake→ack loop against a canary
  mailbox; ARM **verifies** the canary round-trip each morning and alarms on
  failure. Injection stays daemon-side so ARM remains read-only. (Canary cron =
  one small brisen-lab brief, separate from this charter — flagged for lead.)
- **D4 — Full fleet conformance audit** (Director pt 2). One full audit of every
  currently-working agent, run **after CASE_ONE P3 ships** (typed envelope +
  server-derived identity), so seats are audited against the new contract, not the
  soon-obsolete one. Scorecard shape = SPEC_ARM v1 §1(b), extended with bus-contract
  rows (envelope construction, ack discipline, heartbeat emitter installed,
  reader/ack wrapper correctness). Then **quarterly** cadence.
- **D5 — Install sign-off gate** (Director pt 3). Extends
  `install-agent-to-brisen-lab` (12-row map) + `agent-onboarding-runbook` with a
  **three-signature done-gate**: (1) codex — gate verdict on the install PRs;
  (2) lead — merge + deploy; (3) ARM — post-install conformance stamp §1(f)
  verifying all 12 rows live (the HAGENAUER_DESK partial-install trap is the
  anchor). An install is not DONE until all three signatures sit on the install
  bus thread. SOP text change = one small skill edit, flagged for lead.
- **D6 — Escalation lane** (boundary restated). Findings → `arm_flag_lead`.
  Remediation → lead decides, dispatcher executes. Protected/business findings →
  lead routes to Director per technical-escalation-contract. ARM self-remediates
  nothing.

## 3. SLO targets v0 (initial; ARM proposes tuning after 2 weeks of data)

- Unacked message: >24h = AMBER (report line), >48h = RED (alarm).
- Open dispatch with no heartbeat/progress beyond lease TTL + grace = RED (post-P2;
  interim proxy: >4h silence on an open GO).
- Canary round-trip failure = RED, same morning.
- Daily report delivered by 07:00 UTC; a missed report is itself a RED (fail-loud —
  the watchdog must be watched: lead's monitor loop is the meta-check).
- Duplicate-side-effect or identity-mismatch event (post-P3) = RED.

## 4. Structural enforcement delta

Everything in SPEC_ARM v1 §2 stands. Additions: `/bus-health` GET in the read
allow-list; `arm_sql` allow-list extension per D2; report path
`wiki/_fleet/bus-health/**` (subset of existing cage — hook regex unchanged).
No prompt-level duties: cadence + report generation run from a KeepAlive-hardened
launchd job (forge-snapshot-pusher pattern), not from a "remember to check" prompt
line (prompt-rule-decay lesson; researcher validation REFINE 1 analog).

## 5. Model + cost

Polling = curl/SQL, zero LLM cost. Report synthesis 1×/day + alarms: existing ARM
model per SPEC_ARM v1 §5; estimated well under EUR 1/day at current bus volume
(~10²–10³ msg/day). Quarterly audit = one focused session per quarter.

## 6. Rollout ramp

- **Week 1–2 (shadow):** daily reports + alarms live; lead cross-checks every RED
  against his own monitor loop; false-alarm rate tuned (<1 false RED/week target).
- **After 14 green days:** taper to weekly survey + alarms-only (D1 rule).
- **Post-P3:** D4 full fleet audit fires once, then quarterly.
- **Exit criteria for "managed utility" claim:** 30 days with zero
  Director-caught comms incidents + zero silent losses on the defect ledger.

## 7. Governance + kill switch

- Kill switch: disable the ARM custodian launchd job + cadence (single command,
  documented in the install brief); ARM reverts to v1 scope instantly.
- This amendment does NOT alter ARM's advise-only boundary, write cage, or the
  registry `reports_to`. Protocol/design changes remain the case-one program's lane
  (lead + Director); ARM audits and reports against the shipped contract only.
- Director ratifies this amendment after deputy-codex review + lead fold; ramp per
  §6 with lead as accepting authority on week-2 exit.

## Open items for reviewer (deputy-codex)

1. D3 canary: daemon-side cron vs ARM-side wrapper — draft chose daemon-side to
   keep ARM read-only. Challenge if wrong.
2. Interim silent-seat proxy (>24h no activity / >4h on open GO) before P2 lease
   ships — sane thresholds?
3. D5 three-signature gate: ordering (codex → lead → ARM) and whether ARM's stamp
   should block the board row going live or only flag.
4. Anything in §3 SLO v0 that will alarm-fatigue lead at current defect rates.
