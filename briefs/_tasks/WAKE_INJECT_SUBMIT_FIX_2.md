# WAKE_INJECT_SUBMIT_FIX_2 — wake nudges must SUBMIT, not park

**Priority:** P1 · **Worker:** b4 · **Dispatched:** 2026-07-18 (lead)
**Report topic:** `gates/wake-inject-submit-fix-2`

## Problem

Wake nudges ("check bus #id ...") injected into seats can PARK unsent in the
Claude Code composer — the seat never acts, and the Director hand-carries bus
messages into seats (his words today: "I wake you up all the time manually...
this is me manually copy pasting"). Live specimens today: b3 held a parked
`check bus #12652 fleet/wake-probe` ~13min (released by lead's manual Enter);
lead's own seat required Director copy-paste all afternoon while wakes counted
as "fired" (wake_health fired_1h=11 for lead).

## Context

Root cause is DIAGNOSED — do not re-diagnose. Read first:
- `briefs/_reports/COMPOSER_RESIDUAL_DIAG_20260718.md` (b2, PR #598): a newline
  INSIDE a bracketed paste (ESC[200~..ESC[201~) is literal; ONLY a bare CR as
  its own PTY write submits. Coalesced text+CR parks when the terminal path
  wraps it in bracketed paste; a separate bare Enter always submits.
- WAKE_COMPOSER_SUBMIT_FIX_1 (baker-master @3ff8b17) already added settle
  delays + one best-effort submit-Return — b3's park today proves a residual
  remains on at least one injection path.
- Approved direction (lead #12795): single `seat_inject.sh` chokepoint +
  visible `[source]` origin prefix + durable log; NEVER auto-submit
  human-composed pastes — auto-submit applies ONLY to machine-injected wake
  nudge lines.

### Surface contract: N/A — no user-clickable surface; PTY injection path + logging only.

## Deliverables

**D1:** every machine wake-injection path (wake-listener delivery on this host —
`brisen-lab/tools/wake-listener/`, plus any tmux `send-keys` wake caller found
in the path-5 inventory of the diag report) sends the nudge as: settle → text
write → separate bare CR write (never a newline inside a paste) → verify.

**D2:** post-inject verification: after ≤2s, force redraw (`C-l` — stale-render
caveat from the diag report) and capture the pane; if the nudge text still sits
at the composer prompt, send ONE bare Enter recovery; if still parked, log +
post a fail-loud bus flag to lead (topic `fleet/wake-inject-park`). Never more
than one recovery Enter (double-submit guard from FIX_1 stands).

**D3:** origin tag: machine-injected nudges carry a visible `[wake]` prefix in
the injected line + one durable log line (who/what/when) at the chokepoint.
Human pastes are untouched — no tagging, no auto-submit.

**D4:** regression test: PTY-level test proving bracketed-paste-with-newline
parks and D1's write pattern submits (reuse/extend b2's probe
`scripts/composer_residual_probe.py`).

## Files Modified

- brisen-lab: `tools/wake-listener/wake-listener.py` (delivery write pattern),
  new/updated tests.
- baker-master: `scripts/` wake/injection helpers touched by FIX_1 (@3ff8b17)
  if the residual path lives there; `scripts/composer_residual_probe.py`
  (extend as test); no cockpit files.

## Harness V2

- **Context Contract:** diag report + FIX_1 commit + this brief; path-5
  inventory section of the report lists every injector. No vault reads.
- **Task class:** production fix, fleet substrate (Tier-A merge path).
- **Done rubric / done-state class:** post-deploy AC bus verdict on the report
  topic, AC1-AC4 PASS/FAIL with pane transcripts.
- **Gate plan:** codex bus-seat gate on tips → lead merge → live AC on this
  host → 24h park-free observation note.

## Verification

Literal flow, not compile-clean: fire a real wake at an idle probe seat (b3),
observe submit within 5s with `[wake]` prefix visible in scrollback; repeat with
seat mid-output (busy) — nudge must not interleave into a human-composed line
(respect FIX_1 settle logic).

## Quality Checkpoints / Acceptance criteria

- AC1: machine wake nudge submits ≤5s on an idle seat (live probe transcript).
- AC2: parked-nudge recovery path fires exactly once; unrecoverable park raises
  the bus flag (test + forced simulation).
- AC3: human-typed composer text is never auto-submitted or tagged (test).
- AC4: D4 regression test red on old write pattern, green on new.

## Gate

Codex gate pre-merge; lead merges; b2 (diag author) gets FYI on the report
topic for spec-conformance eyeball.
