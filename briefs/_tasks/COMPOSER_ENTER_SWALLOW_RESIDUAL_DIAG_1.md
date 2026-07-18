# COMPOSER_ENTER_SWALLOW_RESIDUAL_DIAG_1

**Dispatcher:** lead · **Date:** 2026-07-18 · **Priority:** P2
**Type:** Diagnose-first — reproduce before proposing any fix. No fix commit in this brief.

Harness-V2: N/A — diagnostic-only brief, no production implementation; findings
feed a follow-up implementation brief which will carry the full V2 blocks.

## Context

Fleet seats are Claude Code sessions in tmux, reached by four injection/typing
paths (below). The composer bug family: text lands in the input box, Enter is
swallowed, message parks unsubmitted. One path was fixed today
(WAKE_COMPOSER_SUBMIT_FIX_1 @3ff85b17); today's Director incident happened after
that fix went live, so a residual path exists.

**Context Contract:** worker needs: this brief; `scripts/cockpit_controller.py`
send_wake (fixed reference); `scripts/cockpit_bridge_agent.py` +
`brisen-lab/cockpit_bridge.py` WS relay (path-3 suspect); Wake.app main.scpt
decompile for path 2. Token for path-3 probe: ask lead on bus (never commit it).

## Problem

The stuck-composer bug (typed/injected text parks in a Claude seat's input box;
Enter does not submit) still has at least one live path AFTER
WAKE_COMPOSER_SUBMIT_FIX_1 (baker-master @3ff85b17, live 09:30 local) fixed the
cockpit-controller wake path.

New incident: a Director-typed question into the lead seat sat unsubmitted 35+
minutes today (~11:35–12:10 local), redelivered manually by cowork-ah1. Timing is
AFTER the controller fix went live — so a different path swallowed the Enter.

## Known paths and their state

1. Cockpit controller wake injection (tmux send-keys) — FIXED @3ff85b17 (settle +
   submit-Return), live-probed on b3.
2. Wake.app `do script` nudge (Terminal tabs) — has the ratified submit-Return
   (BUS_AUTOWAKE_SUBMIT_GENERALIZE_1); tabs are mostly gone post-cutover.
3. **NEW, untested: cockpit-in-Lab bridge terminal** (live since ~10:14 local,
   Director used it right before the incident): browser xterm → Lab WS
   `/cockpit/term/<slug>/ws` → bridge mux → laptop ttyd → tmux. CR/LF handling
   across that chain has never been exercised for submission semantics.
4. Direct local typing into a tmux/ttyd pane — no known incidents.

## Prime suspect

Path 3. The Director confirmed the cloud cockpit worked (~12:10 local sent from
it), and the stuck message window overlaps his first cloud-cockpit session.
Possible mechanism: xterm.js sends `\r`; verify nothing in cockpit_mux /
bridge agent / ttyd re-frames or drops the CR when it arrives in the same WS
frame as preceding text, or when the composer shows a banner.

## Deliverables

1. Reproduction matrix — for each path 1-4: inject "probe text" + Enter, record
   submitted / parked. Path 3 via a headless WS client against
   `wss://brisen-lab.onrender.com/cockpit/term/b3/ws` (token in 1P; ask lead) AND
   via a real browser session.
2. If path 3 reproduces: minimal causal trace (which hop eats/splits the CR) +
   fix proposal as a follow-up brief draft. DO NOT fix in this brief.
3. If nothing reproduces: falsification writeup + instrumentation proposal (what
   logging would catch the next occurrence attributably).

## Constraints

- Probe seats: b3/b4 only (ephemeral). NEVER probe Director-facing desks mid-day.
- No production deploys; read-only against the Lab.
- Report to `briefs/_reports/` + bus topic `gates/composer-residual-diag-1`.

## Files Modified (expected)

- NEW `briefs/_reports/COMPOSER_RESIDUAL_DIAG_<date>.md` (matrix + verdicts).
- NEW probe script under `.smoke/` or `scripts/` marked probe-only. No production
  file changes in this brief.

## Verification

Every matrix cell backed by a pane capture or WS transcript pasted/pathed in the
report. A cell without evidence is UNTESTED, not PASS (fail-loud).

## Acceptance criteria

1. AC1: all 4 paths probed with evidence (pane captures / WS transcripts).
2. AC2: verdict per path: SUBMITS / PARKS / NOT-REPRODUCIBLE, with timestamps.
3. AC3: if reproduced — causal hop identified; if not — instrumentation plan.
