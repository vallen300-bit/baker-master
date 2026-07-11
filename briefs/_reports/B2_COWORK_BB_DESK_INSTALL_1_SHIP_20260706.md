# B2 ship report — COWORK_BB_DESK_INSTALL_1

> **REVISION 1 (G3 re-gate fix, codex #5729 H1, lead #5730):** cowork-bb-desk is now
> non-wakeable at the SOURCE. Vault 48f29d9 adds `wakeable: false` to AG-308 (optional
> registry field, documented in the YAML header); the lab generator's `_wakeable()`
> honors the override; all artifacts regenerated in both repos — new gold SHA
> `9b0b3eaa5b8fb087e784cd46b14c425c6748e25f77c4a1f25cfddeba18e2ae75`. cowork-bb-desk
> leaves WAKEABLE_TERMINALS (kills wake_request emission at app.py's WAKE_TERMINALS
> gate + the listener default allowlist) while keeping VALID_BUS_SLUGS + CARD_SLUGS;
> cowork-ah1 membership unchanged. New head commits: vault 48f29d9 / master 2596d193 /
> lab 7c07b10. New tests both pass: `test_cowork_bb_desk_never_fires_wake` (POST →
> zero wake_request) + `test_cowork_bb_desk_is_valid_but_never_wakeable` (server +
> listener generated twins, ast-parsed). Adjacent wake tests re-run green (4 passed).
> Deployed drain hook re-cp'd for SHA parity. Pre-existing main breakage surfaced,
> not fixed (out of scope): `test_non_picker_recipient_does_not_fire_wake` fails on
> clean origin/main (expects 200 posting to unknown slug; strict recipient validation
> 400s it). The handler no-op guard from the original ship stays as defense-in-depth.

> **REVISION 2 (post-merge Tier-B executed, lead #5742):** all 3 PRs merged (codex
> PASS #5739). Tier-B done by b2: forge pusher redeployed from merged main on MacBook
> (launchctl 49763) + Mini (3058), run from a real Terminal per the Cowork
> ~/Library-wipe foot-gun; wake-handler rebuilt on BOTH hosts (Mini staging synced
> from canonical first); wake-listener deployed copies were stale on both hosts
> (pre-allowlist code + registry SHA 2 revs old) — cp'd canonical pair + kickstarted:
> MacBook dispatches all 26 wakeable aliases (cowork-bb-desk absent), Mini
> host-affinity intact (['baden-baden-desk'] only). Live post-deploy smoke: key
> resolves (200, was 401), card in prod HTML, /api/v2/terminals entry live with
> fresh daemon_last_seen; has_telemetry false until Director's first App open.
> Follow-up test fix shipped as brisen-lab PR #103 (fake-desk → clerk; 1 passed).
> REMAINING: Director first App-open → live round-trip + wake-log AC →
> POST_DEPLOY_AC_VERDICT to lead.

**Date:** 2026-07-06 · **Builder:** b2 · **Dispatcher:** lead (bus #5710, acked)
**Brief:** `briefs/_tasks/COWORK_BB_DESK_INSTALL_1.md` @ e055a0d

## PRs (merge in this order)

| # | Repo | PR | Branch | Head commit | Content |
|---|---|---|---|---|---|
| 1 | baker-vault | #142 | `b2/cowork-bb-desk-install-1` | 37dd170 | registry AG-308 + talk-only orientation |
| 2 | baker-master | #471 | `b2/cowork-bb-desk-install-1` | 1dfdfaeb | regenerated identity artifacts (bus_post whitelists, drain-hook fixture, SNAPSHOT_TERMINALS) |
| 3 | brisen-lab | #102 | `b2/cowork-bb-desk-install-1` | d4b4196 | card slot + regenerated artifacts + wake-handler no-op guard |

Gold SHA embedded in all regenerated artifacts: `2a45fdfd96ab24eeb711d413117ff353054d1c25679efdff40b9de82b6e6b501` = sha256 of the PR-142 registry file (identical across both consuming repos — authentic-regeneration proof per SOP eleventh-pass).

## Mandatory investigation result (cowork-ah1 identity mechanism, mirrored 1:1)

cowork-ah1 gets its App-session identity from THREE parts, all replicated:
1. **Separate picker folder** (`~/bm-aihead1-cowork` vs lead's `~/bm-aihead1`) → replicated as `~/bm-cowork-bb-desk` (laptop-local; the Mini seat's Dropbox workspace `~/Vallen Dropbox/Dimitry vallen/bm-baden-baden-desk` is untouched — a shared folder would have synced `settings.local.json` to the Mini and risked identity bleed).
2. **`.claude/settings.local.json` env block** (`BAKER_ROLE` + `FORGE_TERMINAL` + `FORGE_KEY` + `LAB_URL` — the Cowork App does not source zshrc; tenth-pass telemetry gap covered) → written with `BAKER_ROLE=cowork-bb-desk` + fresh terminal key + forge key + git identity.
3. **Orientation load** — for cowork-ah1 this is the repo role hook; the desk pattern (Mini BB seat precedent) uses picker `CLAUDE.md` as orientation. Followed the desk pattern: `~/bm-cowork-bb-desk/CLAUDE.md` is the talk-only orientation loader pointing at the canonical vault orientation.

## Open questions (brief §Context) — answered by investigation, posted pre-build (bus #5711)

1. **Card:** cowork-ah1 HAS its own Lab card → mirrored; cowork-bb-desk gets a card in `.matter-desk-shelf`.
2. **Wake exclusion:** mechanism = early Terminal-side no-op guard in `wake-handler.applescript` (`if aliasName is "cowork-bb-desk" then return`, same class as cowork-ah1/codex-arch) + intentionally ABSENT from `fnMap`, `cwdForAlias`, and the `isDeskSlug` Mac-Mini host-affinity set (PR #100). WAKEABLE_TERMINALS is registry-generated and includes app-claude runtimes (cowork-ah1 precedent) — exclusion lives at the handler layer, mirrored 1:1. No touch to the Mini seat's wiring or §0 rule.

## 12-row wiring map (every row enumerated)

| Row | Component | Status |
|---|---|---|
| 1 | Picker folder | DONE — `~/bm-cowork-bb-desk/` with `CLAUDE.md` (talk-only orientation) + `.claude/settings.local.json` (identity + telemetry env). NOT the shared Dropbox desk folder — see identity-bleed note above. |
| 2 | Shell alias (`~/.zshrc`) | N/A — app-claude seat; the Claude App picker is the launch surface (BEN twelfth-pass). Key cached at `~/.brisen-lab/keys/cowork-bb-desk` (mode 600) for `_bkey` parity anyway. |
| 3 | Terminal.app profile | N/A — app-claude seat, no Terminal session ever (BEN twelfth-pass). |
| 4 | Picker CLAUDE.md | DONE — canonical `~/bm-b1/scripts/bus_post.sh` path used; banned-actions list embedded; evidence-bound confirmation phrase. |
| 5+6 | bus_post.sh recipient+sender whitelists | DONE — generated (`scripts/agent_identity_generated.sh`, baker-master PR #471). |
| 7 | SessionStart drain hook | DONE — generated fixture (PR #471) + deployed copy `~/.claude/hooks/session-start-bus-drain.sh` updated by cp from fixture (backup at `/tmp/session-start-bus-drain.sh.bak-pre-cowork-bb`); `bash -n` clean. |
| 8 | 1Password key | DONE — `BRISEN_LAB_TERMINAL_KEY_cowork-bb-desk`, category verified `API_CREDENTIAL`, `op read …/credential` round-trip verified (Lesson #78 pre-flight). One accidental duplicate item created + deleted in the same turn (id hrk33…, delete confirmed). |
| 9 | Render env | DONE — `BRISEN_LAB_TERMINAL_KEYS` now 32 entries incl. `cowork-bb-desk`; explicit `POST /deploys` fired (dep-d95l7c28qa3s73e5ckt0, **live 07:06:37Z**) — env-PUT-alone foot-gun avoided. |
| 10 | Front-end card | DONE — `static/index.html` card in `.matter-desk-shelf` (brisen-lab PR #102); `app.js` TERMINALS/LABELS are registry-generated since the centralization — covered by the regenerated `static/agent_identity_generated.js`. |
| 11 | Server slug lists (4 places) | DONE — `bus.py` KNOWN_CARD_SLUGS / `_build_terminals_response` / `app.py` TERMINALS all derive from `agent_identity_generated.py` (regenerated, PR #102); tests = existing registry-driven suites (below). |
| 12 | Snapshot pusher | DONE — generated `SNAPSHOT_TERMINALS` entry `cowork-bb-desk:/Users/dimitry/baker-vault` (default real-git-repo path per Row-12 hard rule; PR #471). Pusher redeploy on hosts = lead Tier-B post-merge (install_forge_push.sh on MacBook + Mini). |
| 13 | Wake-handler | DONE — no-op guard added; fnMap + cwdForAlias intentionally ABSENT (talk seat must never spawn). `osacompile` clean. Post-merge rebuild (`bash tools/wake-handler/build.sh`) = lead Tier-B. |
| 14 | Wake-listener allowlist | DONE via generation — `tools/wake-listener/agent_identity_generated.py` regenerated (slug lands in WAKEABLE like cowork-ah1; handler no-ops it). Deployed-copy diff + `launchctl kickstart` = lead Tier-B post-merge. |

Cowork-specific rows (tenth/twelfth-pass): telemetry env injected (Row-12-adjacent) — DONE in settings.local.json. Launch row: **first open is Director-manual** (Claude App folder picker on `~/bm-cowork-bb-desk`) — no CLI/bus path can start an App session; `has_telemetry:true` + card amber are Director-action-blocked until that first open.

## Test evidence (literal runs)

baker-master (vault checkout on the #142 branch at run time):
```
pytest tests/test_agent_identity_registry.py -q → 10 passed
pytest tests/test_agent_identity_registry.py tests/test_bus_post.py -q → 30 passed, 1 failed*
bash tests/test_forge_snapshot_push.sh → All 24 cases PASS
```
*the 1 fail = `test_generated_artifacts_match_vault_registry` with vault on main — drift guard working as designed; passes with the PR-142 registry (10-passed run above).

brisen-lab (Neon test DB `TEST_DATABASE_URL_BRISEN_LAB`):
```
pytest tests/test_a3_a8_a9_bus.py tests/test_bus_recipient_validation.py -q
→ 69 passed, 3 warnings in 1173.39s (0:19:33)
pytest tests/test_agent_identity_generated.py -q → 9 passed, 1 failed*
```
*same drift guard; `generate_agent_identity_artifacts.py --check` rc=0 with the PR-142 registry content at the canonical path (10-second swap, restored byte-identical, cmp-verified — vault checkout was unusable for a branch switch, see Deviations).

No-write grep: none of the three PRs touch signal_queue / DB writes / migrations — wiring + docs + generated artifacts only.

## Pre-merge live smoke

`GET /msg/cowork-bb-desk` with the new key → **401, expected**: deployed `load_terminal_keys()` filters on the deployed `VALID_BUS_SLUGS`, which gains the slug only when PR #102 merges (auto-deploy). Key + env + explicit deploy are already live, so no second Render step is needed post-merge.

## Done rubric — status

1. Seat identifies as cowork-bb-desk on App open → **wired; Director-action-blocked** (first App open is irreducibly manual, BEN twelfth-pass).
2. Bus post to baden-baden-desk + lead, replies via drain → **wired; post-merge AC** (401 gate above).
3. Mini seat identity bleed → **zero by construction** (separate local folder; Mini's Dropbox workspace + zshrc + §0 untouched). Same-day live test on both seats owed post-merge.
4. No wake dispatches → handler no-op + not in host-affinity desk set; **wake-listener log check owed post-merge** after a real desk wake.
5. 12-row map → enumerated above.
6. Live round-trip demo → **owed post-merge**; will post POST_DEPLOY_AC_VERDICT to lead per post-deploy-ac-bus-gate.

## Deviations / observations

- **Shared `~/baker-vault` checkout found mid-arc on detached HEAD (06115e1) with an unresolved conflicted merge** (2 UU lilienmatt files, not mine) — surfaced to lead (bus #5724), untouched by me. Blocked branch-switch verification; worked around via the registry-content swap above.
- brisen-lab commit d4b4196 carries committer `Dimitry <dimitry@MacBook-Pro-2.local>` — the inner lab clone had no local git identity; config now set (`Code Brisen #2`) for future commits. Not amended (published).
- First background test run hung 24 min at 0 CPU (Neon compute cold-start); killed and re-run foreground — final run is the 69-passed evidence above.

## Post-merge lead Tier-B checklist (owed by lead per gate plan)

1. Merge order: vault #142 → baker-master #471 → brisen-lab #102 (lab auto-deploys; key already provisioned).
2. Forge pusher redeploy (MacBook + Mini) for the new SNAPSHOT_TERMINALS entry.
3. Wake-handler rebuild on MacBook (`bash tools/wake-handler/build.sh`) + wake-listener deployed-copy diff/kickstart.
4. Direct Director to open `~/bm-cowork-bb-desk` in the Claude App picker (first launch, Director-manual).
5. b2 then runs the live round-trip + wake-log AC and posts POST_DEPLOY_AC_VERDICT.
