---
brief_id: MOVIE_DESK_ON_BUS_1
attempt: 1
claimed_by: b2
claimed_at: 2026-06-27
brief_sha: 92479cd
---

# MOVIE_DESK_ON_BUS_1 — checkpoint

## Key discovery (deviation from brief/SOP — both STALE on the generated migration)
Wiring is now registry-driven. Edit `~/baker-vault/_ops/registries/agent_registry.yml`
(flip AG-304 movie-desk seeded→active) then REGENERATE in each repo. Most "hand-edit"
rows in the brief are now GENERATED:
- baker-master regen (`python3 scripts/generate_agent_identity_artifacts.py --write`):
  scripts/agent_identity_generated.sh (bus_post whitelist + SNAPSHOT_TERMINALS + role-resolve),
  orchestrator/agent_identity_data.py, tests/fixtures/session-start-bus-drain.sh (Row 7).
  forge_snapshot_push.sh READS AGENT_IDENTITY_SNAPSHOT_TERMINALS → Row 12 auto (no hand-edit).
- brisen-lab regen (`python3 scripts/generate_agent_identity_artifacts.py --write`):
  agent_identity_generated.py, static/agent_identity_generated.js,
  tools/wake-listener/agent_identity_generated.py → wires bus.py CARD_SLUGS (Row 11a/b),
  app.py APP_TERMINALS (Row 11c), app.js front-end data (Row 10 dynamic), wake-listener (Row 14).

## Genuinely hand-edited (NOT generated):
- brisen-lab static/index.html: add `<article class="card" data-alias="movie-desk"></article>`
  to `.matter-desk-shelf` (after line 113 origination-desk).
- brisen-lab tools/wake-handler/wake-handler.applescript: cwdForAlias +
  `if a is "movie-desk" then return "/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-movie-desk"`;
  fnMap + `{"movie-desk", "moviedesk"}`.
- Tests: brisen-lab tests/test_a3_a8_a9_bus.py (movie-desk in /api/v2/terminals);
  baker-master tests/test_forge_snapshot_push.sh (movie-desk snapshot terminal present).

## Registry edit (AG-304):
status: active / bus_enabled: true / aliases: [MOVIE_DESK, movie_desk, moviedesk, MOVIE-DESK]
/ runtime: terminal-claude (was vault-seeded). scope stays matter-desk. snapshot path auto = baker-vault.

## SHARED-VAULT HAZARD: ~/baker-vault working tree DIRTY with OTHER agents' uncommitted work
+ 1 behind origin. Branch off, stage ONLY my 1 file (agent_registry.yml), atomic commit. Do NOT stash/clobber.

## PR sequence:
1. baker-vault: agent_registry.yml only (config). Branch b2/movie-desk-registry.
2. baker-master: 3 regenerated artifacts + test_forge_snapshot_push.sh. Branch b2/movie-desk-bus.
3. brisen-lab: 3 regenerated artifacts + index.html + wake-handler.applescript + test. Branch b2/movie-desk-bus.

## Lead Tier-B post-merge: Row3 verify, Row8 1P key, Row9 Render env, zshrc FORGE_TERMINAL movie_desk→movie-desk,
deploy regenerated drain hook to ~/.claude/hooks/, redeploys, AC12 smoke.

## NEXT CONCRETE STEP: edit agent_registry.yml AG-304 block, then regenerate baker-master + verify generated diff.

## STATUS UPDATE (2026-06-27): ALL 3 PRs OPEN — awaiting gate chain
- baker-vault #138 (1/3, registry source) — branch b2/movie-desk-registry @ 41955a7
- baker-master #431 (2/3, regenerated artifacts + forge test) — branch b2/movie-desk-bus @ 590ae1ee
- brisen-lab #85 (3/3, regen + index.html + wake-handler + test) — branch b2/movie-desk-bus @ d365443
- Ship report: briefs/_reports/B2_MOVIE_DESK_ON_BUS_1_SHIP_20260627.md
- NEXT: respond to gate feedback (G2 deputy-codex / G3 deputy AC / G4 lead security-review). Merge order 1/3→2/3→3/3.
