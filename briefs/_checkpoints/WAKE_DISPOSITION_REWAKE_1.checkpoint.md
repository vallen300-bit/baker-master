---
brief_id: WAKE_DISPOSITION_REWAKE_1
attempt: 1
dispatched_by: lead (bus #13840, phase-2 release)
report_topic: wake-disposition-rewake-1
repos:
  - brisen-lab b1/wake-disposition-rewake-1 @feb0af5 (off lab main @ceb53e5)
status: PHASE-2 (listener, tasks 4-5) BUILT + pushed; gate requested #13842 (lead CLI lane). Awaiting codex gate -> lead merge -> re-sync ~/.brisen-lab + kickstart -> live AC3 (undelivered WARNING + receipt probe + reconcile-retry). Phase-1 (controller) already merged/live (baker PR #611).
gate: lead CLI codex-verify merged-tree vs current lab main
---

# WAKE_DISPOSITION_REWAKE_1 phase-2 (listener) — checkpoint

Brief: `briefs/_tasks/WAKE_DISPOSITION_REWAKE_1.md` @ baker main. My tasks = 4-5 (listener).
Phase-1 controller (deputy-codex) merged baker PR #611 — do NOT touch cockpit_controller.py.

## Done (@feb0af5)
- Task 4: dispatch_wake consumes disposition — undelivered -> WARNING+reconcile+controller-retry
  (via label-parameterised _handle_ambiguous_wake); skipped/delivered terminal INFO; absent ->
  legacy (result dict unchanged when disposition absent). _post_controller_wake carries
  disposition/reason only when present.
- Task 5: WAKE_RECEIPT_URL derives from COCKPIT_CONTROLLER_URL+/api/wake-receipt when unset
  (env override wins; ""=dormant); also set in the launchd plist template.
- Tests: +6 phase-2; existing 4 classification tests pinned receipt_url="". 27 pass py3.9+3.12.

## Contract (baker PR #611, live)
Response: {ok,sent,disposition:delivered|skipped|undelivered,reason,slug,skipped}. Receipt:
GET /api/wake-receipt/<rid> -> {landed:bool} Basic auth. undelivered reasons: no telemetry /
no unacked message id / no wake obligation message id.

## Next concrete step (owner = lead, then B1 live)
1. Lead: codex gate @feb0af5 -> merge -> re-sync ~/.brisen-lab/wake-listener.py + plist + kickstart.
2. B1 post-deploy: live AC3 — undelivered WARNING+rid, receipt probe GET /api/wake-receipt/<rid>,
   reconcile-retry proven; post verdict on wake-disposition-rewake-1.

## Other open arc
CLERK_SEAT_COLLISION_FIX_1 — still awaiting lead GO on the gated ~/.zshrc fail-loud edit
(report B1_CLERK_SEAT_COLLISION_FIX_1_20260719.md, branch b1/clerk-seat-collision-fix-1, #13135).
