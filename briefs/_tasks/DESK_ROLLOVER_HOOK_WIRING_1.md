# BRIEF: DESK_ROLLOVER_HOOK_WIRING_1 — wire the 40% checkpoint+respawn hook into every desk picker

dispatched_by: lead
assignee: b2
effort: medium (recommended tier for codex gate: medium)
repo: desk picker dirs on this laptop + Dropbox picker dirs (settings.json + role-context lines); rule doc in baker-vault
task_class: config-wiring (production agent seats; no server code)

## Context

Desk context auto-rollover rule is Director-ratified and canon: `baker-vault/_ops/processes/desk-context-auto-rollover.md` @58e4d74 (deputy second-read PASS #7192). Rule: **prepare at 40% consumed, execute checkpoint+respawn at next task boundary, 70/85 hard net via the SAME `context-threshold-check.sh` Stop hook workers use.** Today the hook is wired in worker/AH pickers only — desks never get the trigger.

### Context Contract
- Canonical rule doc (read FIRST — carries the wiring table + design rationale): `_ops/processes/desk-context-auto-rollover.md`.
- Hook: `context-threshold-check.sh` — same script the b-code/AH pickers reference; do NOT fork it. Discover its canonical deploy path from an existing wired picker (e.g. `~/bm-aihead1/.claude/settings.json` hooks.Stop).
- Mechanism doc the emit points at: `_ops/processes/worker-checkpoint-respawn.md`.
- Deputy gate context: #7171 (3 gate items, folded in doc) + #7192 (PASS + 2 non-blocking nits, binding on THIS brief — see Task 4/5).

## Problem

Desks (ao-desk, baden-baden-desk, movie-desk, hag-desk, brisen-desk, origination-desk) run to 40-50% context with no trigger: no prepare signal at 40%, no hard net at 70/85. The rule exists on paper only until each desk picker's `.claude/settings.json` carries the Stop hook.

## Task

1. For EACH desk in the rule doc's wiring table: verify the picker path exists on disk (fail-loud on mismatch — do not guess or create dirs), then add the `hooks.Stop` entry for `context-threshold-check.sh` with `rollover_window_tokens=200000`, `rollover_soft_percent=40`. Preserve any existing hooks in the array.
2. Verify the soft-band emit each desk will see names the mechanism verbatim (checkpoint file path + commit+push + respawn request + exit-at-boundary). If the hook script needs a desk-window parameter it doesn't support, STOP and report — no forked variants.
3. Add ONE delivery-rule line to each desk's role-context: rollover = "checkpoint + respawn" per `worker-checkpoint-respawn.md`; prepare at 40%, execute at boundary. No other role-context edits.
4. (Deputy nit a, #7192) Terminology check scoped to ROLLOVER vocabulary only: grep each desk's role-context/settings for "handoff"/"pin" **in rollover context** — unrelated legitimate uses of "pinned" (e.g. PINNED.md references) are NOT findings.
5. (Deputy nit b, #7192) In the wiring report, state explicitly how the watchdog's 40% checkpoint-required band (amber 35 / red 40, spec #7189) sequences with the desk's own 40% self-trigger: watchdog ORDERS ahead of self-trigger for agents that skip their checkpoint; no double-fire.

## Files Modified

- Each desk picker's `.claude/settings.json` (6 desks per the doc table; roster verified on disk at run time).
- Each desk's role-context file — one line each.
- Nothing in baker-master; nothing in the hook script itself (fail-loud if it needs changes).

## Constraints (hard)

- Same hook, same mechanism doc — zero forks, zero parallel vocabulary.
- Dropbox-synced pickers: edit in place, no temp-file moves that break sync.
- A desk mid-session when you wire it: config applies on ITS next session start — do not restart desks yourself.
- Deputy second-reads the role-context edits before this brief is DONE (his #7158 gate covers role-context).

## Verification

1. Literal `git diff` / file diff per desk settings.json + role-context line.
2. Dry-run the Stop hook against one desk picker (simulate transcript path if the hook supports it; else document why not testable pre-session and how first live fire will be observed).
3. Terminology grep output (scoped per Task 4), clean or findings listed.

## Acceptance criteria (done rubric)

- AC1: All live desks from the doc table wired; diffs in report; path mismatches fail-loud reported.
- AC2: Rollover-scoped terminology grep clean.
- AC3: Emit-names-mechanism verified (dry-run output or documented first-live-fire plan).
- AC4: Watchdog sequencing statement in report (nit b).
- AC5: Deputy second-read PASS on role-context edits; ship report to `briefs/_reports/`.

Done-state: all 5 ACs with literal evidence.

## Gate plan

deputy G2 (role-context edits — his ratified gate) → lead review of diffs → done. No codex gate (config-only, no code paths). No Director gate (Tier-A, rule already ratified).

## Reply target

Bus-post all state changes (start, blocker, gate request, ship) to `lead`. Reply-target = lead.
