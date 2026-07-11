# B2 Ship Report — MOVIE_DESK_ON_BUS_1

**Brief:** MOVIE_DESK_ON_BUS_1 (dispatched by lead @ 92479cd, 2026-06-27)
**Builder:** b2 · **Reply target:** lead (bus)
**PRs:** baker-vault #138 (1/3) → baker-master #431 (2/3) → brisen-lab #85 (3/3)

## Headline deviation from brief/SOP (both STALE — surfaced, not blocked)
The wiring has migrated to **registry-driven generated artifacts** since the SOP was last
validated (2026-06-11). Most rows the brief frames as "hand-edit FOUR server places" /
"edit forge_snapshot_push TERMINALS" are now **generated** from `agent_registry.yml`. The
brief's own Delta-1 rule ("edit the yml source + regenerate; do NOT hand-edit generated
artifacts") governs and resolves the conflict — so I edited the registry + regenerated in
each repo, and hand-edited only the genuinely non-generated files (index.html card,
wake-handler.applescript, tests). No architectural tradeoff to escalate; one correct path.

What is now generated (was hand-edit in SOP):
- baker-master: bus_post recipient+sender whitelist, valid-slug list, **SNAPSHOT_TERMINALS
  (Row 12 — forge_snapshot_push.sh reads `AGENT_IDENTITY_SNAPSHOT_TERMINALS`)**, drain-hook block (Row 7).
- brisen-lab: `bus.py KNOWN_CARD_SLUGS` (Row 11a/b), `app.py APP_TERMINALS` (Row 11c),
  `app.js` card data+label (Row 10 data), `wake-listener WAKEABLE_TERMINALS` (Row 14).

## 14-row wiring map (every row enumerated)
- **Row 1 — Picker folder:** N/A — pre-exists at `~/Vallen Dropbox/Dimitry vallen/bm-movie-desk` (AC0 verified; CLAUDE.md + `.claude/skills/movie-desk/` present). Wired to existing Dropbox path per Delta 2; did NOT create `~/bm-movie-desk`.
- **Row 2 — Shell alias (zshrc):** N/A (builder) — `moviedesk()` pre-exists. Lead Tier-B fixes `FORGE_TERMINAL=movie_desk`→`movie-desk` (Delta 2).
- **Row 3 — Terminal.app profile:** N/A (builder) — "MOVIE Desk" profile pre-exists. Lead verifies name parity post-merge.
- **Row 4 — Picker CLAUDE.md:** N/A — pre-exists.
- **Row 5 — bus_post recipient whitelist:** done @ #431 — regenerated `AGENT_IDENTITY_VALID_SLUGS` includes `movie-desk` (no hand-edit per Delta 1).
- **Row 6 — bus_post sender whitelist / role-resolve:** done @ #431 — regenerated `agent_identity_resolve_role` maps `MOVIE_DESK|movie_desk|moviedesk|MOVIE-DESK|AG-304`→`movie-desk`. Verified: `is_valid movie-desk: YES`.
- **Row 7 — SessionStart drain hook:** done @ #431 — generated block in `tests/fixtures/session-start-bus-drain.sh` adds the movie-desk case. Lead deploys to `~/.claude/hooks/session-start-bus-drain.sh` post-merge.
- **Row 8 — 1Password terminal key:** lead Tier-B post-merge (`BRISEN_LAB_TERMINAL_KEY_movie-desk`, API-Credential category per Lesson #78).
- **Row 9 — Render env var:** lead Tier-B post-merge (`BRISEN_LAB_TERMINAL_KEYS` JSON + redeploy).
- **Row 10 — Front-end card:** done @ #85 — `static/index.html` card slot `<article class="card" data-alias="movie-desk">` in `.matter-desk-shelf`; card data+label `AG-304 MOVIE Desk [movie-desk]` via regenerated `static/agent_identity_generated.js` (group=matter-desk → renders in Matter-desks panel).
- **Row 11 — Server (4 places):** done @ #85 — (a) `bus.py KNOWN_CARD_SLUGS` ← `CARD_SLUGS`; (b) `bus.py _build_terminals_response` loops `KNOWN_CARD_SLUGS`; (c) `app.py APP_TERMINALS`; (d) test `tests/test_a3_a8_a9_bus.py`. (a-c) all generated; only (d) hand-written.
- **Row 12 — Snapshot pusher:** done @ #431 — `movie-desk:/Users/dimitry/baker-vault` in generated `AGENT_IDENTITY_SNAPSHOT_TERMINALS`; `scripts/forge_snapshot_push.sh` reads it (no hand-edit). + forge test Case X.
- **Row 13a — Wake-handler fnMap:** done @ #85 — `{"movie-desk", "moviedesk"}`.
- **Row 13b — Wake-handler cwdForAlias:** done @ #85 — `if a is "movie-desk" then return "/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-movie-desk"` (exact Dropbox picker path).
- **Row 14 — Wake-listener allowlist:** done @ #85 — regenerated `tools/wake-listener/agent_identity_generated.py WAKEABLE_TERMINALS` includes movie-desk. Lead deploys `~/.brisen-lab/wake-listener.py` + `launchctl kickstart` post-merge.
- **Plus — Registry source:** done @ baker-vault #138 — AG-304 flipped seeded→active.

## Verification (literal)
baker-master (#431):
```
$ python3 scripts/generate_agent_identity_artifacts.py --check  → CHECK OK (no drift)
$ python3 -c "import py_compile; py_compile.compile('orchestrator/agent_identity_data.py', doraise=True)"  → OK
$ bash tests/test_forge_snapshot_push.sh  → PASS: Case X (movie-desk) … All 24 cases PASS.
$ source scripts/agent_identity_generated.sh  → is_valid movie-desk: YES; MOVIE_DESK/movie_desk/moviedesk → movie-desk
```
brisen-lab (#85):
```
$ python3 scripts/generate_agent_identity_artifacts.py --check  → CHECK OK
$ node --check static/agent_identity_generated.js  → JS OK
$ osacompile -o /tmp/x.scpt tools/wake-handler/wake-handler.applescript  → AppleScript compiles OK
$ python3 -c "from agent_identity_generated import CARD_SLUGS,APP_TERMINALS,WAKEABLE_TERMINALS,IDENTITY_LABELS; assert 'movie-desk' in all; label=='AG-304 MOVIE Desk [movie-desk]'"  → PASS
$ python3 -m pytest tests/test_a3_a8_a9_bus.py -v  → 52 skipped (live-PG; no TEST_DATABASE_URL locally; CI runs green)
```
**Fail-loud note:** the brisen-lab DB-backed suite SKIPS locally (no test DB; op not authenticated
in this shell) — identical to every prior desk install. The new import-only assertions PASS
standalone; the DB-backed badge/terminals test runs in CI's ephemeral Neon branch.

## Gate plan status
G1 pytest (baker-master 24/24 green; brisen-lab CI-pending) → G2 deputy-codex (slug-list
completeness / partial-install) → G3 deputy AC → G4 lead /security-review → merge (order
1/3→2/3→3/3) → lead Tier-B post-merge (Rows 2 zshrc fix, 3, 7 deploy, 8, 9, 14 deploy) → AC12 smoke.

## Shared-vault hygiene
`~/baker-vault` working tree was dirty with OTHER agents' uncommitted work + 1 behind origin.
Branched `b2/movie-desk-registry`, staged ONLY `agent_registry.yml`, atomic commit — did not
touch/stash/clobber others' changes.
