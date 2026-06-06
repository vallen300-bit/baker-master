---
brief_id: CLERK_QWEN3_BUS_AGENT
title: Make Qwen3 Clerk the first-class bus agent on slug clerk
to: deputy-codex
from: lead
dispatched_by: lead
task_class: baker-master implementation
harness_v2: applies
slug: clerk
display_name: Clerk
base_branch: main
branch: clerk-qwen3-bus-agent
depends_on:
  - ~/baker-vault/_ops/briefs/BRIEF_CLERK_ON_BUS_1.md
  - briefs/BRIEF_CLERK_WORKBENCH_2.md
  - briefs/BRIEF_CLERK_WORKBENCH_3.md
---

# BRIEF: CLERK_QWEN3_BUS_AGENT

## Context

Replace the Haiku/Claude terminal picker as Clerk's primary runtime with the
existing headless Qwen3 Clerk. Clerk remains on the existing `clerk` slug, sends
and receives Brisen Lab bus messages, keeps the existing dashboard card honest,
and leaves the old terminal picker available as a manual fallback.

Existing shipped surfaces:

- `CLERK_ON_BUS_1` installed the `clerk` slug, card, bus key, picker, wake path,
  and snapshot pusher wiring.
- `CLERK_WORKBENCH_2` shipped the Qwen3 Clerk runtime and `clerk_sessions`.
- `CLERK_WORKBENCH_3` shipped the browser launcher/edit surface.

## Problem

The shipped Clerk card can receive bus messages, but the primary Clerk runtime is
still a terminal picker. Qwen3 Clerk is headless, so it cannot "receive bus" by
waiting for a human-opened terminal session. It needs a server-side worker that
drains `clerk` bus messages, runs the existing `run_clerk_task()` path, replies
on the bus, and updates the existing card while a job is active.

## Context Contract

- **Task class:** production implementation, baker-master only.
- **Surface contract:** no new Director-facing page; no brisen-lab code delta.
- **Authority contract:** worker disabled by default; Tier-B flips
  `CLERK_BUS_WORKER_ENABLED=true` only after merge and env setup.
- **Data contract:** reuse `clerk_sessions`; no new migration/table.
- **Bus contract:** sender is derived from Clerk's terminal key; inbound is ACKed
  only after a successful reply to the original `from_terminal`.

## G0 Design Decisions

- **Host:** baker-master `triggers/embedded_scheduler.py`, not a new Render service.
  The live scheduler already owns production periodic work, and `run_clerk_task`,
  `clerk_sessions`, and `/api/clerk/run` already live in baker-master.
- **Feature flag:** `CLERK_BUS_WORKER_ENABLED=false` by default. Tier-B flips it
  after merge with the required Render env.
- **Worker contract:** poll `GET /msg/clerk?limit=<bounded>` with the Clerk
  terminal key, run `orchestrator.clerk_runtime.run_clerk_task()`, reply to the
  inbound `from_terminal`, and ACK only after the reply succeeds.
- **Idempotency:** deterministic `clerk_sessions.session_id = bus-<msg_id>`.
  The bus ACK is the durable dedup boundary: once a reply POST succeeds, ACK is
  attempted even if the best-effort `result_json.bus_reply_message_id` write
  fails. A retry before reply reuses the stored Clerk result.
- **Heartbeat/card:** no brisen-lab code delta. The worker calls `/api/register`
  for the bus session and emits job-scoped `/api/event` heartbeats only while a
  Clerk bus job is active. This refreshes `forge_sessions.last_seen_at` without
  a persistent ticker or timeline spam.
- **Autonomy:** existing Clerk denylist remains authoritative. `pending_approval`,
  `blocked`, `timeout`, and `error` statuses are returned on the bus; the worker
  does not execute payment, email-send, destructive, deploy, or Director-approval
  actions.

## Files Modified

- `briefs/BRIEF_CLERK_QWEN3_BUS_AGENT.md` — this brief and 14-row SOP map.
- `orchestrator/clerk_bus_worker.py` — new headless Clerk bus worker.
- `triggers/embedded_scheduler.py` — registers `clerk_bus_poll` in the live scheduler.
- `tests/test_clerk_bus_worker.py` — focused mocked bus/store coverage.

## 14-Row SOP Map

Rows below cite `~/baker-vault/_ops/briefs/BRIEF_CLERK_ON_BUS_1.md`, which
already installed the `clerk` slug/card/picker/wake path. This brief does not
silently omit any row from `~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md`.

- **AC0 Existing-workspace pre-flight: DONE by CLERK_ON_BUS_1.** Slug `clerk`,
  display `Clerk`, picker path `/Users/dimitry/bm-clerk`.
- **AC1 Picker folder: DONE by CLERK_ON_BUS_1.** Haiku/Claude picker remains as
  manual fallback; this brief adds server-side primary runtime.
- **AC2 Shell alias: DONE by CLERK_ON_BUS_1.** No change.
- **AC3 Terminal.app profile: DONE by CLERK_ON_BUS_1.** No change.
- **AC4 bus_post.sh recipient whitelist: DONE by CLERK_ON_BUS_1.** `clerk` is a
  valid recipient.
- **AC5 bus_post.sh sender whitelist: DONE by CLERK_ON_BUS_1.** `BAKER_ROLE=clerk`
  maps to sender `clerk`.
- **AC6 SessionStart drain hook: DONE by CLERK_ON_BUS_1.** Manual fallback
  terminal can still drain.
- **AC7 1Password terminal key: DONE for brisen-lab by CLERK_ON_BUS_1; DELTA for
  baker-master Render env.** Tier-B must expose the Clerk terminal key to
  baker-master as `BRISEN_LAB_TERMINAL_KEY_clerk` or `BRISEN_LAB_TERMINAL_KEY_CLERK`.
- **AC8 Brisen Lab Render env: DONE for brisen-lab by CLERK_ON_BUS_1; DELTA for
  baker-master.** Tier-B adds `CLERK_BUS_WORKER_ENABLED`, the Clerk bus key,
  `FORGE_KEY`, `LAB_URL`/`BRISEN_LAB_URL`, and confirms existing `CLERK_QWEN_*`.
- **AC9 Brisen Lab front-end card: DONE by CLERK_ON_BUS_1.** No brisen-lab PR.
- **AC10 Brisen Lab server slug lists: DONE by CLERK_ON_BUS_1.** No brisen-lab PR.
- **AC11 Snapshot pusher: DONE by CLERK_ON_BUS_1.** The worker adds job-scoped
  `/api/register` + `/api/event` telemetry for active work; snapshot pusher remains
  unchanged.
- **AC12 End-to-end smoke: DELTA.** After merge and Tier-B env, lead sends a bus
  dispatch to `clerk`; worker processes with Qwen3; sender receives a bus reply;
  inbound is ACKed; `/api/v2/terminals` shows `clerk` working during the job.
- **AC13 Wake-handler maps: DONE by CLERK_ON_BUS_1.** Wake opens manual fallback
  terminal, not the headless worker.
- **AC14 Wake-listener allowlist: DONE by CLERK_ON_BUS_1.** No change.

## Quality Checkpoints / Acceptance Criteria

- Worker remains inert when `CLERK_BUS_WORKER_ENABLED` is false.
- Polling is bounded by `CLERK_BUS_POLL_LIMIT` and `CLERK_BUS_BATCH_CAP`.
- `clerk_sessions.session_id` is deterministic (`bus-<msg_id>`) and idempotent.
- Reply is posted before ACK; reply failure leaves inbound unacked for retry.
- Reply-posted implies ACK attempted; `result_json.bus_reply_message_id` is a
  best-effort secondary marker and cannot block ACK.
- Existing Clerk denylist statuses are returned on the bus as blockers/approval.
- Scheduler liveness registers `clerk_bus_poll`.
- Direct DB access uses the hardened direct-connection path.

## Verification

- `python3 -m py_compile orchestrator/clerk_bus_worker.py triggers/embedded_scheduler.py`
- `/opt/homebrew/bin/python3.12 -m pytest -q tests/test_clerk_bus_worker.py tests/test_clerk_runtime.py tests/test_clerk_workbench_endpoints.py`

## Gate Plan

G1 lead literal pytest -> G2 security review -> G3 codex -> merge -> Tier-B env
and redeploy -> AC smoke (`clerk` bus dispatch -> Qwen3 run -> bus reply -> ACK
-> card working signal during job).

## Done Rubric / Done-State Class

Done-state class: merge-ready implementation, disabled by default. The feature
is operationally done only after Tier-B enables the worker and the AC smoke proves
the full bus round trip.

## Post-Merge Tier-B

Lead owns Tier-B after G1/G2/G3:

- Add baker-master Render env: `BRISEN_LAB_TERMINAL_KEY_clerk` or
  `BRISEN_LAB_TERMINAL_KEY_CLERK`, `FORGE_KEY`, `LAB_URL`/`BRISEN_LAB_URL`,
  `CLERK_BUS_WORKER_ENABLED=true`, and existing Qwen3 config.
- Redeploy baker-master.
- Smoke: bus message to `clerk` -> Qwen3 run -> reply to sender -> ACK inbound ->
  Clerk card working signal visible during job.

## Do Not

- Do not delete the Clerk terminal picker.
- Do not add a new slug.
- Do not add a brisen-lab PR for heartbeat.
- Do not bypass the Clerk denylist or approval posture.
