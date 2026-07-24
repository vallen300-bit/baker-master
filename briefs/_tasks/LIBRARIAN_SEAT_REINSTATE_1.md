# LIBRARIAN_SEAT_REINSTATE_1 — reinstate librarian (AG-209) as full Brisen Lab seat

dispatched_by: lead (2026-07-24, Director GO "go" — reverses LIBRARIAN_CM1_SLUG_ALIAS_1 2026-07-17)
repos: baker-master (bm-b3) + brisen-lab (bm-b3-brisen-lab) · branches: b3/librarian-reinstate-1 (both)
registry already flipped: baker-vault @108e78a (AG-209 active + bus_enabled true; CM-1 librarian alias removed)

## Context

librarian was retired into CM-1 on 2026-07-17, but the retirement never stuck:
zshrc launcher + ~/bm-librarian picker + live Terminal sessions continued under
the librarian identity (one running now, heartbeating as slug librarian). Lab
card cannot open — no tmux/ttyd/manifest wiring. Director ruled: reinstate as
a proper seat. Install SOP = _ops/processes/install-agent-to-brisen-lab-sop.md
(14-row map). This brief enumerates ALL 14 rows; builder scope = rows 5/6
(identity regen), 11, 12, 13, 14 + tests. Lead executes the rest post-merge.

## Context Contract

- IN (baker-master): scripts/generate_agent_identity_artifacts.py output regen
  (agent_identity_generated.sh + agent_identity_data.py — vault registry @108e78a
  is source), scripts/forge_snapshot_push.sh TERMINALS, tests/test_forge_snapshot_push.sh.
- IN (brisen-lab): bus.py (canonicalization + KNOWN_CARD_SLUGS + _build_terminals_response
  loop), app.py TERMINALS, tools/wake-handler/wake-handler.applescript (fnMap +
  cwdForAlias), tools/wake-listener/wake-listener.py ALLOWED_ALIASES,
  tests/test_a3_a8_a9_bus.py, tests/test_wake_handler_no_retired_slugs.py.
- OUT: v2 static shell (roster is runtime-derived), cockpit substrate scripts
  (lead lane), registry (done), CM-1's own seat wiring (stays).

## Problem

Slug librarian routes to CM-1 (bus canonicalization), is excluded from card/
terminal/wake slug-lists server-side, absent from forge pusher TERMINALS, and
absent from both wake maps + listener allowlist. Tests currently ASSERT the
retirement — they must be reversed, not deleted.

## Files Modified

Baker-master: agent_identity_generated.sh + agent_identity_data.py (regen),
forge_snapshot_push.sh (+librarian:~/baker-vault — picker has NO .git, Row-12
hard rule), test_forge_snapshot_push.sh (+case).
Brisen-lab: bus.py (librarian self-canonical again — remove librarian->CM-1
RECIPIENT_CANONICAL mapping; +KNOWN_CARD_SLUGS; +_build_terminals_response loop),
app.py (+TERMINALS), wake-handler.applescript (+fnMap {"librarian","librarian"} +
cwdForAlias -> /Users/dimitry/bm-librarian), wake-listener.py (+ALLOWED_ALIASES),
tests reversed (a3_a8_a9: librarian IN card slugs, canonical_recipient("librarian")
=="librarian", terminals response includes; no_retired_slugs: librarian OUT of
retired list). No other files; extras named in receipt with why.

## 14-row enumeration (SOP-mandatory; N/A rows justified)

1. Picker: N/A — ~/bm-librarian EXISTS (no .git -> Row 12 uses ~/baker-vault).
2. zshrc fn: N/A — librarian() EXISTS.
3. Terminal profile: LEAD post-merge (.terminal import method — profile absent today).
4. Picker CLAUDE.md: N/A — exists; lead re-audits canonical bus_post path post-merge.
5/6. bus_post whitelists: BUILDER — regen identity artifacts from registry @108e78a (generator prints Row-1 WARNING if snapshot path missing — librarian already in _snapshot_path_for or add it).
7. Drain hook: N/A — AG-209 case already present in session-start-bus-drain.sh.
8. 1P key: N/A — exists (_bkey librarian resolves).
9. Render env key: LEAD post-merge — verify librarian entry in BRISEN_LAB_TERMINAL_KEYS; add + explicit POST /deploys if missing.
10. Front-end: N/A for v2 (runtime-derived roster); legacy app.js CONTROL_GROUPS already lists librarian — builder VERIFIES no dead-card regression, no edit expected.
11. Server FOUR places: BUILDER (bus.py x2, app.py TERMINALS, tests).
12. Forge pusher: BUILDER (librarian:~/baker-vault + test case).
13. Wake-handler BOTH maps: BUILDER (13a fnMap + 13b cwdForAlias); lead rebuilds via build.sh post-merge.
14. Wake-listener allowlist: BUILDER canonical file; lead diffs + deploys ~/.brisen-lab copy + kickstart post-merge.

## Verification

1. baker-master: `python3 scripts/generate_agent_identity_artifacts.py --write` clean (no stderr WARNING) + `bash tests/test_forge_snapshot_push.sh` green.
2. brisen-lab: `python3 -m pytest tests/test_a3_a8_a9_bus.py tests/test_wake_handler_no_retired_slugs.py -q` green (reversed assertions).
3. Pre-flight greps per SOP: `grep -nE '\"lead\"|\"deputy\"|\"b1\"' bus.py app.py` — confirm all slug-list sites touched.
4. `git ls-remote` shas for BOTH branches in receipt.

## Done rubric / done-state class

done-state: BUILT-AND-SELF-VERIFIED. Receipt enumerates all 14 rows SHIPPED /
N/A-because / LEAD-lane (no silent skips). Three-signature done-gate applies
(codex gate -> lead merge -> ARM 12-row stamp); registry state pending-arm-stamp
until ARM PASS.

## Gate plan

lead codex-gates BOTH deltas (repo+branch+sha each) -> lead merges (baker-master
then brisen-lab per SOP sequencing; vault already landed) -> Render deploy ->
lead Tier-B local rows (profile, manifest regen + ttyd + tmux, pusher redeploy
both hosts, wake-listener deploy + kickstart, wake-handler rebuild) -> E2E smoke
(bus post to librarian lands librarian inbox NOT CM-1; card opens tmux from Lab;
wake click nudges) -> ARM stamp -> Director eyeball.

## Out of scope

CM-1 seat stays fully wired. No v2 shell edits. No registry edits (done). No
cockpit-controller code changes — manifest regen is config, lead lane. Do not
touch the RUNNING librarian Terminal session.
