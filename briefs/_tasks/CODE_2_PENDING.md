---
brief_id: MOVIE_DESK_ON_BUS_1
status: PENDING
to: b2
from: lead
dispatched_by: lead
dispatched_at: 2026-06-27
reply_target: lead (bus)
task_class: infra-install (3-repo)
recommended_effort: high
picker_path: /Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-movie-desk
canonical_slug: movie-desk
Harness-V2: applies — Context Contract + done rubric + gate plan below
gate_plan: G1 pytest -> G2 deputy-codex (slug-list completeness / partial-install) -> G3 deputy AC -> G4 lead /security-review -> merge -> lead Tier-B post-merge -> AC12 smoke
---

# BRIEF_MOVIE_DESK_ON_BUS_1 — put MOVIE Desk on the Brisen Lab bus + dashboard card

## Context Contract
MOVIE Desk (Mandarin Oriental Vienna asset-management + disposal agent) is **half-installed**: it already has a picker folder and a "MOVIE Desk" Terminal profile, but it is **NOT on the bus** (no key, no registry entry, no card, no drain). This brief completes the bus install end-to-end.

**Canonical slug: `movie-desk`** (kebab, matches `ao-desk` / `hag-desk` / `origination-desk` / `baden-baden-desk`). The existing zshrc launcher uses `BAKER_ROLE=MOVIE_DESK` + `FORGE_TERMINAL=movie_desk` — treat those as ALIASES that must resolve to `movie-desk`, not as new slugs.

**Read FIRST:** `~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md` (the 14-row wiring map + foot-guns). Follow it, with the two deltas below.

### AC0 pre-flight — ALREADY RUN by lead (verify, do not re-derive):
- Picker EXISTS: `~/Vallen Dropbox/Dimitry vallen/bm-movie-desk/` (CLAUDE.md + `.claude/skills/movie-desk/` present). **Wire to this existing Dropbox path — do NOT create `~/bm-movie-desk`.** (AID_ON_BUS_1 defect-3 class.)
- Terminal profile "MOVIE Desk" EXISTS in `com.apple.Terminal.plist` (Row 3 substantially done — verify name parity with card alias).
- zshrc `moviedesk()` EXISTS (Dropbox cd, BAKER_ROLE=MOVIE_DESK, FORGE_TERMINAL=movie_desk).
- MISSING: bus key, registry entry, drain-hook mapping, forge-pusher entry, front-end card, server slug-lists, wake-handler/listener entries.

### DELTA 1 — SOP Rows 5/6 are STALE. The bus_post.sh whitelist moved to a central registry.
Slug validation is now generated from `~/baker-vault/_ops/registries/agent_registry.yml` into `scripts/agent_identity_generated.sh` (header: "Do not edit by hand. Regenerate with: python3 scripts/generate_agent_identity_artifacts.py --write").
- **Do NOT hand-edit `agent_identity_generated.sh` or bus_post.sh case statements.**
- Add `movie-desk` to `agent_registry.yml`: bus-agent slug + valid slug + snapshot-terminal (repo-path `/Users/dimitry/baker-vault`, like the other desks) + role-resolve aliases (`MOVIE_DESK`, `movie_desk`, `moviedesk`, `MOVIE-DESK` → `movie-desk`). Assign the next free `AG-3xx` id (ao-desk=AG-303; pick the next unused).
- Regenerate the artifact via the documented script; commit BOTH the yml and the regenerated `agent_identity_generated.sh`. Confirm the SHA256 header matches.
- This replaces SOP Row 5 + Row 6. Row 7 drain-hook in `~/.claude/hooks/session-start-bus-drain.sh` (and its baker-master fixture `tests/fixtures/session-start-bus-drain.sh`): check whether it reads the registry or still has a hardcoded BAKER_ROLE case; if hardcoded, add `MOVIE_DESK`/`movie-desk`.

### DELTA 2 — Snapshot terminal alias parity.
Card `data-alias`, forge-pusher `TERMINALS` entry, FORGE_TERMINAL, and registry snapshot-terminal MUST all be the SAME string = `movie-desk`. The existing zshrc has `FORGE_TERMINAL=movie_desk` (underscore) — **lead will fix the zshrc to `movie-desk` (local AH1 file, Tier-B).** Everything you wire uses `movie-desk`.

## Engineering Craft Gates
- Diagnose: N/A — additive install, not a bug fix.
- Prototype: N/A — wiring pattern is fully specified by the SOP; no design uncertainty.
- TDD/verification: applies — extend `tests/test_a3_a8_a9_bus.py` (brisen-lab) to assert `bus_badge_change` SSE + `/api/v2/terminals` include `movie-desk`; add the `movie-desk` case to `tests/test_forge_snapshot_push.sh` (baker-master). Write the test assertions alongside each repo change, not after.

## Scope — all 14 SOP rows, movie-desk specifics
Enumerate EVERY row in your ship report (`Row X: done @ <ref>` or `Row X: N/A — <reason>`).
- **Builder owns (repo PRs):** registry (Delta 1), Row 7 (if hardcoded fixture), Row 10 (front-end card in `.row-desks` + app.js TERMINALS/LABELS), Row 11 (FOUR server places: bus.py KNOWN_CARD_SLUGS, bus.py _build_terminals_response loop, app.py TERMINALS, tests), Row 12 (forge_snapshot_push.sh `movie-desk:/Users/dimitry/baker-vault`), Row 13a/13b (wake-handler both maps; cwdForAlias → the Dropbox picker path EXACT), Row 14 (wake-listener ALLOWED_ALIASES), plus regression tests.
- **Lead owns post-merge (Tier-B, do NOT attempt):** Row 3 verify, Row 8 (1P key), Row 9 (Render env + redeploy), zshrc fix, drain-hook + wake-listener + forge-pusher redeploys, AC12 smoke.

## Three-repo PR sequencing (per SOP)
1. **baker-vault PR** — agent_registry.yml + regenerated artifact (+ any `_ops/agents/movie-desk/` files if needed). Config; merge first.
2. **baker-master PR** — forge_snapshot_push.sh + drain-hook fixture (if hardcoded) + tests.
3. **brisen-lab PR** — front-end (index.html `.row-desks` card + app.js TERMINALS/LABELS) + server (bus.py x2 + app.py) + wake-handler + wake-listener + tests.
Brisen-lab clone for b2: `~/bm-b2-brisen-lab`.

## Key Constraints / Do NOT touch
- Do NOT create `~/bm-movie-desk` — wire to the existing Dropbox picker.
- Do NOT hand-edit generated artifacts — edit the yml source + regenerate.
- Do NOT touch other desks' slugs/cards/keys.
- Card alias, data-alias, forge TERMINALS, FORGE_TERMINAL, registry snapshot-terminal = the single string `movie-desk`.

## Done rubric (answer each, not "tests pass")
1. `movie-desk` in registry + artifact regenerated, SHA header correct; slug validates (no "unknown slug").
2. Pre-flight grep covers the new slug in all 4 server sites: `grep -nE '"lead".*"deputy".*"b1"' ~/bm-b2-brisen-lab/{bus.py,app.py}`.
3. Card slot present in `static/index.html` `.row-desks` (renders after lead deploys).
4. Wake-handler has BOTH fnMap + cwdForAlias (cwdForAlias → the Dropbox picker path, exact).
5. Wake-listener ALLOWED_ALIASES includes `movie-desk` (canonical repo file).

## Ship gate (literal pytest output in PR description — NO pass-by-inspection)
- `pytest tests/test_a3_a8_a9_bus.py -v` (brisen-lab)
- `bash tests/test_forge_snapshot_push.sh` (baker-master)

## ON RESUME (long-arc rollover)
If `briefs/_checkpoints/MOVIE_DESK_ON_BUS_1.checkpoint.md` exists, resume from its "next concrete step" — do not restart. At ~85% context, checkpoint + push + request respawn.

## Reporting
Bus-post `lead` on: claim, each PR opened, each merge-ready, blockers, scope-ambiguity. Plain technical prose (B-codes are NOT Director-facing register). Enumerate all 14 rows in the final ship report.
