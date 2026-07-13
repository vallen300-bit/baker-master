# B4 ship report — CASE_ONE_E23_SESSION_STATE_PERSISTENCE_1

- PR: #551 (b4/case-one-e23-session-state-persistence → main)
- Commit: 1d5e33b8
- Dispatched by: lead (bus #10191); reply target: lead
- Date: 2026-07-13

## Done rubric

1. **Close-pin gate (P-E23.1)** — `.claude/hooks/close-pin-check.sh`, wired on Stop + SessionEnd.
   Warns/persists on close-without-checkpoint for live-state seats, enforces the pin-protocol
   LIGHT floor, interactive-seat aware (E17), fail-loud on can't-persist. ✅
2. **Orientation contract (P-E23.2)** — `.claude/hooks/session-open-orientation.sh`, SessionStart,
   composes with the bus-drain check. Reads brief-tail + OPERATING.md + armed deadlines +
   handover/PINNED (not bus-only); surfaces pending or explicit "checked N sources, none pending". ✅
3. **Reuse + no re-cover** — one shared live-state predicate (`live_state_predicate.py`) used by both
   hooks + the audit; the P0 `install-rollover-stop-hook.py` / `rollover_fleet.py` extended (no second
   wiring mechanism); NO context-band logic added; correct `hooks.<Event>` nesting + exit-0. ✅
4. **Live pilot AC + POST_DEPLOY_AC_VERDICT v1** — post-merge; deputy owns the fleet sweep. The
   fleet-wide sweep to all 21 pickers is an **ops-deploy step**, flagged not silently skipped. ⏳

## Riders

- **R1 (hook-event capability — verified, code.claude.com/docs/en/hooks 2026-07-13):**
  Stop CAN block + emit `systemMessage`, fires at each turn end (cannot detect "this is the close").
  SessionEnd fires at real termination (window-close → `reason:logout`) but **its output is IGNORED by
  the harness** — it can neither block nor show a message. => A hard block exactly at close is
  IMPOSSIBLE here: the event that detects close can't act; the event that can act can't detect close.
  Design is honest about that:
    - Stop + dirty → loud `systemMessage` warn, **once per session** (marker-gated, no per-turn nag).
      `block-once` is **opt-in** (`close_pin_block_on_stop`, default OFF — blocking a non-final Stop
      would trap mid-arc work, the context-hook self-feed trap) and only claimed on Stop where it works.
    - SessionEnd + dirty → the only thing that works at true close is a side effect: non-interactive
      worker auto-writes an UNVERIFIED-AUTO STUB checkpoint; interactive seat gets a warn-log breadcrumb.
  **Warn-only paths (block impossible):** every interactive-seat close, and all SessionEnd handling.
- **R2 (budgeted orientation):** ≤30 lines, pointer-style (path + one-line hook); 1 line when clean.
- **R3 (no fake pins):** auto-write emits ONLY a clearly-marked `UNVERIFIED-AUTO STUB` (wait-state
  pointers, no synthesized narrative). Interactive seats → warn-log breadcrumb, never a fabricated pin.

## Tests

`python3 -m pytest tests/test_close_pin_and_orientation.py tests/test_rollover_fleet.py tests/test_worker_rollover.py -q`
→ **46 passed**. 16 new (predicate bias-to-fire, close-pin Stop warn/warn-once/silent-clean/
interactive-floor/block-opt-in, SessionEnd auto-stub vs breadcrumb, orientation
brief/deadline/handover + none-pending + autostub-flagged).

Live e2e smoke on this real b4 repo: close-pin Stop warned with the worker LIGHT floor (no block);
orientation surfaced the active brief + latest handover in ≤30 lines.

**Pre-existing / unrelated:** `tests/test_stop_hooks.py` has 2 failures
(`recommendation-check` / `fail-loud` hooks) that fail identically on the base branch — not E23.

## Ops note (do not auto-run from build)

`python3 scripts/rollover_fleet.py audit` reports most pickers `MISSING_HOOK` (expected — only
baker-master clones inherit the new tracked settings.json). The `install` sweep to the non-baker-master
pickers (baker-vault desks, cowork dirs) is an ops-deploy step, same class as P0's 14-picker gap.

## Gate plan status

codex verify (or Claude-side B-code line-review) BEFORE merge → lead merges → deploy → deputy live AC.
