# BRIEF: CASE_ONE_E23_SESSION_STATE_PERSISTENCE_1 — enforced close-pin (SessionEnd/Stop checkpoint gate) + session-open orientation contract (state sources, not bus-only)

> Case One reliability layer — **E23** (rollover state loss) + the close-pin half of **E14**/E17. Authored by
> deputy (AH2, standing bus-health owner) from lead dispatch #10178 (scope-add to the E14 threshold-hook lane)
> + ledger E23 @9caab9d + E22/E17/E14 context. **TO LEAD FOR REVIEW BEFORE WORKER DISPATCH.** Same review
> path: deputy authors → lead reviews → worker builds. Codex reinstated → independent gate before merge.

dispatched_by: lead (pending review)
assigned_to: <builder — lead assigns after review>
task_class: fleet harness (SessionEnd/Stop close-pin enforcement hook + session-open orientation-contract check, per-seat, structural) — NOT a service; hooks + settings wiring on the existing picker fleet
Harness-V2: Context Contract + done rubric + gate plan inline.
effort: medium-high

## Context

**Context Contract.** Repo: baker-master `.claude/hooks/` (a new SessionEnd/Stop close-pin gate + a session-start orientation-contract check) + the per-seat picker `settings.local.json` wiring (reuse the P0 `rollover_fleet.py` installer/enumeration — do NOT build a second wiring mechanism) + the `pin-protocol` skill as the checkpoint content contract. No new service. Builds ON already-shipped pieces — do NOT redo them.

Rollover state persistence is the discipline that keeps the Director from becoming the fleet's memory. E23 today: bb-desk's fresh session had NO memory of two live signing-blocker risks (Weippert re-review + Oskolkova waiver, Merz emails that morning) discussed the prior session — the Director restored state by pasting the transcript. Two structural causes: (a) the prior session closed WITHOUT writing a handover/pin (voluntary, so skipped); (b) session-open orientation checked only the bus — genuinely 0-unacked, but the risks lived in email + the brief, so "bus clear" was true and blind. This is the third instance today (with E14 bands-not-self-enforced, E17 interactive-seats-can't-self-terminate) of one meta-pattern: **every persistence/liveness discipline that is voluntary eventually silently fails, and the Director becomes the backstop.**

### SCOPE DEDUPE (MANDATORY — lead #9563 discipline). Already shipped / owned elsewhere; this brief must NOT re-cover:
- **E14 context-band threshold hook — SHIPPED in P0 (#540/#123, meter #537).** The measured meter, the config-driven 70/85 soft/hard hook (block-at-most-once over hard), the machine band field in status posts, the `rollover_fleet.py audit|install` seat installer, and the lifecycle per-seat band query ALL shipped. **This brief does NOT touch context-band enforcement.** The only open E14 remnant is the deploy **sweep** to the 14-of-21 pickers `rollover_fleet.py audit` still reports unwired — that is an **ops deploy step (flagged to lead in the P0 report), not a brief.** SCOPE CORRECTION vs my #10183 ack: I initially framed "generalize 70/85 to all seats" as brief work — it is already P0-shipped; the real new content is only the two E23 gaps below.
- **P2 kill→spawn→verify lifecycle + seat-type awareness (#126/#547)** — SHIPPED. The close-pin gate fires on SessionEnd/Stop of the CURRENT seat (persist-before-exit); it does NOT re-implement the respawn/verify loop. For interactive seats (E17) that can't self-terminate, the gate is a persist-or-warn on the Stop/close event, not a spawn action.
- **`pin-protocol` skill (LIGHT/HEAVY modes)** — EXISTS. The close-pin gate ENFORCES its floor (LIGHT = 3 mandatory artifacts: PINNED §A update + activity-log + audit-log for Tier-B); it does NOT redefine pin modes. Reuse the skill as the content contract.
- **P5 delivery confirmation (in build)** — separate lane (message delivery). E22 (ack-then-idle) is P5's; this brief is session-state persistence, not dispatch delivery. Do NOT conflate.

## Problem

Two structural gaps let a session lose live matter state across a rollover (E23):

1. **Close-pin is voluntary, so it is skipped (E23a / E17).** Only lead has hook-enforced checkpoint discipline (context-threshold + pin-size). Every other seat — desks, AH2, workers, App/interactive seats — can exit (or the human can close the window, E17) with live matter state un-persisted. bb-desk's prior session closed with its auto-memory handover still dated 2026-05-12; the morning's two signing-blocker risks never reached durable storage. A voluntary "please pin before you go" line decays exactly like the other prompt-rules (E3).
2. **Session-open orientation reads only the bus, which is a message channel, not the state store (E23b).** A fresh session that checks the bus and sees 0-unacked concludes "clear" — but pending work lives in the brief, OPERATING.md, armed deadlines, email, and the last handover. "Bus clean" proves nothing about pending matter state. There is no structural session-open contract that forces a seat to read its own state sources.

## Fix (two pieces, build on P0 wiring + pin-protocol)

### P-E23.1 — Enforced close-pin: SessionEnd/Stop checkpoint gate (E23a / E17 fix)
A SessionEnd/Stop hook (sibling to `context-threshold-check.sh`, same per-seat wiring) that, for any seat **holding live matter state**, blocks-or-loudly-warns on **close-without-checkpoint** — lead-style, generalized fleet-wide. Mechanics:
- **Trigger predicate:** fire when the seat has live state to lose — a heuristic that does NOT depend on a prompt rule: e.g. session touched a matter slug / wrote a draft / holds an unresolved PINNED §A OPEN item / has an armed deadline, AND the newest handover/checkpoint is older than this session's start. Config-driven, fail-open-safe (a false fire is a harmless extra warn; a false miss loses state — so bias toward firing).
- **Action:** on a real close-without-checkpoint, either (a) block-once (interactive seat: loud warning + the exact `pin-protocol` LIGHT floor to write, since a model cannot force-terminate an interactive window, E17), or (b) auto-write the LIGHT pin floor if the seat is non-interactive and the content is mechanically derivable. Enforce the `pin-protocol` LIGHT floor as the minimum (PINNED §A + activity-log + audit-log for Tier-B) — never a silent pass.
- **Fail-loud:** a seat that cannot checkpoint (missing PINNED path, no write access) surfaces the gap by name; never silently skips. Respect the Stop-hook exit-0 contract + the settings-hook nesting rule (`hooks.<Event>`, not top-level — the mis-nest lesson).

### P-E23.2 — Session-open orientation contract: read state sources, not the bus alone (E23b fix)
A session-start check (sibling to the bus-drain hook) that makes orientation read the seat's **own state sources** and surface pending work, so "bus clear" can never read as "nothing pending." Minimum sources per seat: **brief tail** (active dispatch mailbox / `_tasks`), **OPERATING.md** (or the seat's operating/wait-state file), **armed deadlines** (the seat's deadline store), and the **latest handover/PINNED §A** — in addition to the bus drain, not instead of it. Deliverable: a structural session-start hook that emits an orientation summary listing any pending item from those sources (or an explicit "checked N sources, none pending" — the fail-loud inverse of a silent empty). Per-seat source list is config (desks read matter brief + deadlines; AH2 reads PINNED + operating; workers read their mailbox). Do NOT rely on a prompt line "remember to read your brief" — it must be structural (prompt-rule-decay lesson).

## Files Modified

- baker-master: `.claude/hooks/close-pin-check.sh` (new SessionEnd/Stop gate; reuse the band-hook's per-seat config pattern), `.claude/hooks/session-open-orientation.sh` (new SessionStart check; sibling to `session-start-bus-drain.sh`, composes with it), a shared "live-state predicate" helper (so both hooks + any audit share one definition, no drift).
- Per-seat wiring: extend the P0 `scripts/rollover_fleet.py` installer/enumeration to register the two new hooks in each picker's `settings.local.json` (reuse the 21-seat enumeration + fail-loud audit; do NOT fork a second installer). The actual fleet **sweep** is the same ops-deploy step class as P0's — flag it, do not auto-run from the build.
- `pin-protocol` skill referenced as the checkpoint content contract (no skill change unless the LIGHT floor needs a machine-checkable form).
- Tests: close-pin gate fires on close-with-live-state-no-checkpoint and passes on checkpoint-present; interactive-seat path warns + emits the LIGHT floor (no forced-terminate); orientation hook surfaces a pending brief/deadline/handover item and emits the explicit "N sources checked, none pending" on a truly-clean seat; both respect exit-0 + `hooks.<Event>` nesting; live-state predicate biases to fire (false-miss = 0 in the test matrix).

## Verification

1. **Close-pin enforcement (E23a):** simulate bb-desk — a session touches a matter + holds an unresolved OPEN item, then hits Stop with no fresh checkpoint → the gate fires (block-once/loud-warn) with the exact LIGHT-floor artifacts to write; a session that DID checkpoint closes clean. An interactive seat gets a loud warn (not a false "done"), never a silent pass. A seat that cannot write its pin surfaces the failure by name.
2. **Orientation contract (E23b):** a fresh session with a 0-unacked bus BUT a pending brief item + an armed deadline + an off-bus handover → the session-open check surfaces all three (reproduces bb-desk: the two signing-blocker risks would have surfaced from brief/deadline sources despite a clean bus). A genuinely-clean seat emits "checked N sources, none pending," never a silent empty.
3. **No drift / no re-cover:** confirm the two hooks reuse the P0 band-hook config pattern + the `rollover_fleet.py` installer (no second wiring mechanism); confirm this brief adds NO context-band enforcement (that is P0-shipped).
4. **Live AC:** post-deploy — wire the two hooks to a real pilot seat (e.g. bb-desk + AH2), force a close-with-live-state and a clean-bus-with-pending-brief → both surface without a human. Emit `POST_DEPLOY_AC_VERDICT v1`. Deputy (bus-health owner) folds close-pin/orientation coverage into the dispatcher sweep. NOTE the fleet-wide sweep to all 21 pickers is an ops-deploy step (like P0's 14-picker gap) — call it out explicitly, do not silently bound coverage.

## Quality Checkpoints / Acceptance criteria

- **done rubric:** (1) SessionEnd/Stop close-pin gate blocks-or-loud-warns on close-without-checkpoint for live-state seats, enforces the `pin-protocol` LIGHT floor, interactive-seat aware (E17), fail-loud on can't-checkpoint; (2) session-open orientation hook reads brief-tail + OPERATING.md + armed deadlines + handover (not bus-only) and surfaces pending work or an explicit none-pending; (3) both reuse P0 wiring + a shared live-state predicate, NO context-band re-cover, correct `hooks.<Event>` nesting + exit-0; (4) live pilot AC + `POST_DEPLOY_AC_VERDICT v1`, sweep-to-21 flagged as an ops step not silently skipped.
- **done-state class:** production fleet-harness → live pilot AC required (a persistence gate that false-passes is the exact failure it exists to catch — bias the predicate to fire).
- **gate plan:** deputy authors → **lead reviews BEFORE worker dispatch** → builder implements → **independent verdict BEFORE merge** (codex reinstated — cross-vendor gate available, or a Claude-side B-code line-review; #9255 holds) → lead merges → deploy → deputy verifies live + owns the fleet sweep.
- **Harness-V2:** covered inline.

## Dedupe / cross-links

- Builds on P0 (context-band hook + `rollover_fleet.py` installer + 21-seat enumeration — REUSE, do not fork), `pin-protocol` skill (LIGHT/HEAVY floor = the checkpoint content contract), the bus-drain SessionStart hook (orientation composes with it). Extends E14 (bands, P0-shipped) + E17 (interactive seats can't self-terminate).
- **The one-line P0/this-brief boundary:** P0 = enforce the context BAND (when to roll); this brief = enforce STATE PERSISTENCE across the roll (don't lose matter state when you do). Different disciplines; this brief adds zero band logic.
- Evidence: live-defect log E23 (rollover state loss; no close-pin + clean-bus blindness), E17 (interactive seats), E14 (bands not self-enforced) — `wiki/matters/flight-academy/Inter-Agent Communication Design for LLM Agent Fleets/2026-07-12-live-defect-evidence-log.md` @HEAD.
- Motivating case: bb-desk lost two live signing-blocker risks at rollover today; the Director restored them by hand. This brief retires the Director-as-memory role structurally.

## LEAD REVIEW RIDERS (lead, 2026-07-13 — PASS with 3 riders, binding)

- **R1 — hook-event capability check first.** SessionEnd hooks cannot block in the harness; only Stop hooks can. Builder verifies which event actually fires on (a) model-driven stop, (b) human window-close, per seat type, and wires the gate to the event that can act — warn-only is acceptable where block is impossible (E17), but the brief's "block-once" must not be claimed on an event that can't block. Fail-loud in the ship report which paths are warn-only.
- **R2 — orientation output is BUDGETED.** Session-start summary ≤30 lines, pending-items-only, pointer-style (path + one-line hook, no content dumps) — the Director's standing slim-session-start directive wins; an orientation hook that bloats every open trades one failure for another. "Checked N sources, none pending" = 1 line.
- **R3 — no auto-written pins that look hand-written.** The non-interactive auto-write path may emit only a clearly-marked `UNVERIFIED-AUTO STUB` checkpoint (wait-state pointers, no synthesized narrative) + loud warn. A fabricated-looking full pin false-reassures the successor — worse than a missing one.
