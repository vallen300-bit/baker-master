# SEAT_STALL_WATCHDOG_1 — stalled-seat detection + alarm (+ gated auto-relaunch)

- **Status:** AUTHORED 2026-07-16 (Director GO in lead chat, same evening); dispatch after cockpit POST_DEPLOY_AC_VERDICT lands.
- **Anchor incident:** deputy-codex died of Codex context-window exhaustion mid-arc 2026-07-16 ~22:10Z; lead order #12127 sat unacked 41 min on a card still showing working; only Director's manual relaunch resumed the arc. Machine-checkable signal existed the whole time.
- **Dispatcher:** lead. **Builder:** deputy (ARM lane owner). **Gate:** codex cross-vendor PR review → lead merge.
- **Repo:** baker-master (ARM cadence job + scripts).

## Context

ARM's 30-min cadence LaunchAgent already polls bus health with an authenticated key (PR #576 arc, PASS 5/5 #11993). Lab already exposes per-seat `unacked_count`, `oldest_unacked_age_sec`, `unacked_topics`, `is_working` on public `GET /api/v2/terminals`. A stalled-but-alive-looking seat is therefore detectable without new telemetry: an execute-obligation dispatch left unacked beyond threshold. Relaunch mechanics arrive with the cockpit substrate (`fleet_terminals.sh`, controller `POST /api/sessions/{slug}/start`, merged @09833a5f) — but auto-relaunch stays OFF until fleet cutover.

**Context Contract (Harness V2):** builder reads ONLY: `scripts/arm_cadence_poll.sh` + its installer/plist, the ARM alarm ladder scripts (existing semantic/cadence alarm paths), Lab `GET /api/v2/terminals` payload (live), cockpit controller start-route contract (briefs/_tasks/LAB_COCKPIT_CONTROLLER_1.md §Deliverables 1). No vault, no matter context.
**Task class:** ops watchdog extension (local LaunchAgent lane; production-alarm adjacent).
**Done rubric / done-state:** merged + reinstalled LaunchAgent + one real drill (synthetic stalled dispatch → alarm fires end-to-end) + POST_DEPLOY_AC_VERDICT.
**Gate plan:** G1 self-test → codex cross-vendor PR review → lead merge → reinstall + live drill.

## Problem (1-liner)

A seat that dies silently (Codex context exhaustion, hung CLI) stalls its whole arc until a human notices; detection and first response must be automatic.

## Files Modified (expected)

- `scripts/arm_cadence_poll.sh` (or a sibling check it invokes) — stall detector.
- ARM alarm path — new alarm class `seat:stalled` (reuses existing recipient-split + folder rule).
- NEW small config: thresholds + per-seat opt-out (GENERATED/simple env, no hand-kept slug lists — HAGENAUER).
- Tests for the detector logic (fixture payloads: fresh ack, aged unacked, down seat).

## Deliverables

1. **Detector (M0, ships ON):** each 30-min cadence tick, read Lab `GET /api/v2/terminals`; flag any seat with `unacked_count > 0` AND `oldest_unacked_age_sec > 900` (15 min). Down-vs-working does not matter — an aged unacked dispatch IS the stall signal. Emit one `seat:stalled` ARM alarm per seat per incident (dedupe like existing alarm classes; recovery note when it clears).
2. **Bus nudge (M0):** on first detection, post a nudge to the stalled seat + a copy to lead (`stall/<slug>` topic) before/alongside the alarm.
3. **Auto-relaunch (M1, ships OFF behind env flag):** for seats marked migrated in the cockpit ledger only, invoke controller `POST /api/sessions/{slug}/start` (idempotent; brings seat up if down). NEVER kill anything — start-only. Flag stays OFF until fleet cutover + explicit lead GO (double-gated like ARM ENFORCE).
4. **Threshold config:** default 900s; per-class override via env; no hardcoded slug lists.

## Verification

Live drill (Lesson #8): plant a synthetic unacked execute-obligation dispatch on a drill seat (isolated env like the #11990 semantic drill), age it past threshold, run one cadence tick → alarm lands in ARM Alarms folder + nudge posts + dedupe holds on second tick. Fixture tests for payload parsing. M1 path: dry-run proof only (flag off), start-route call asserted-not-executed.

## Quality Checkpoints / Acceptance criteria (live)

- AC-1: aged unacked dispatch → `seat:stalled` alarm e2e (folder landing confirmed), within one cadence tick.
- AC-2: nudge posted to seat + lead copy; message names seat, dispatch id, age.
- AC-3: dedupe — no repeat alarm on next tick for same incident; recovery note on clear.
- AC-4: fresh-ack and down-idle seats produce nothing (no false positives on quiet seats with zero unacked).
- AC-5: M1 flag OFF by default; with flag ON in drill env, start-only call proven idempotent; no kill verbs anywhere.

## Out of scope

Codex-seat context-rollover/self-compaction discipline (separate design — `project_agent_self_compaction_design_needed.md`). Fleet cutover. Any kill/stop verbs. Lab-side schema changes. TokenPressure changes.

## Report

Ship report to `briefs/_reports/`, bus post to lead with PR ref; POST_DEPLOY_AC_VERDICT after merge + live drill.
