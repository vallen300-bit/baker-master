# BRIEF_BEN_ON_BUS_1

**Goal:** Put BEN (Brisen finance/commercial specialist agent) on the brisen-lab bus as a full participant — slug `ben`, like every other agent. Director-requested 2026-07-04.

**Worker:** b2 (hottest context — just shipped BRISEN_LAB_BUS_WIRING_FIX_1, which touched exactly this registry/agent-identity machinery).
**Dispatcher:** lead (AH1). **Recommended effort:** high (3-repo install, registry-driven regeneration + hand-edits + tests).
**SOP:** `~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md` (14-row map; **eleventh-pass: install is registry-driven** — edit `agent_registry.yml` + regenerate, never hand-edit `agent_identity_generated.*`).

## AC0 — pre-flight (DONE by lead)
- Existing workspace: `~/bm-ben` is a **symlink** → `/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-ben` (one canonical picker, Dropbox-synced, has CLAUDE.md + `.claude/`). NOT the AID two-dir trap — it's a single symlinked workspace. **Picker path = `/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-ben`** (use this exact path for cwdForAlias + launcher).
- No `ben()` launcher in `~/.zshrc` yet. `ben` not in registry yet (clean add).
- **Host:** Dropbox-synced picker ⇒ BEN is **Cowork-App-hosted** (like `cowork-ah1`). Consequences: auto-wake is **N/A** (Director opens the Cowork session; it drains the bus itself — eighth-pass), and it needs **FORGE_KEY+LAB_URL injected via `settings.local.json`** for card telemetry (tenth-pass).

## Locked identity (lead's engineering decision — do not re-derive)
- slug `ben` · display `BEN` · agent_id `AG-208` · scope `shared-specialist` · runtime `app-claude` · reports_to `lead` · aliases `()` · bus_enabled `true` · authority level **0** ("NONE — BEN escalates to lead/director; never decides"). Mirror the `russo-ai`/`aid` shared-specialist shape.

## Tasks (b2 — 3-repo PRs, SOP sequence baker-vault → baker-master → brisen-lab)

### Registry source of truth (baker-vault PR)
- Add the `ben` agent record to `_ops/registries/agent_registry.yml` with the locked identity above (including the WORKER_AUTHORITY_SEED level-0 row).
- Regenerate artifacts: `python3 scripts/generate_agent_identity_artifacts.py --write` — commit the regenerated `agent_identity_generated.*` in **each of the 3 repos** (baker-vault if present, baker-master, brisen-lab, + `static/agent_identity_generated.js` + `tools/wake-listener/agent_identity_generated.py`). Gold check: the SHA256 embedded in every regenerated artifact must equal `sha256(agent_registry.yml)` and be identical across repos.

### 14-row map — enumerate every row (N/A rows justified, never silently omitted)
- **Row 1 (picker folder):** N/A — exists at `~/bm-ben` (symlinked Dropbox workspace). Verify `.claude/skills/` present; add a `ben` SKILL.md only if BEN lacks one.
- **Row 2 (zshrc launcher):** AH1 Tier-B (below). For a Cowork agent a launcher is optional, but add a `ben()` fn (cd picker, `BAKER_ROLE=ben`, `FORGE_TERMINAL=ben`, `BRISEN_LAB_TERMINAL_KEY="$(_bkey ben)"`, `git pull --rebase --autostash`, launch) so a Terminal session is possible. **Row-2 foot-gun: MUST inject `BRISEN_LAB_TERMINAL_KEY` (eleventh-pass) or the session 403s on read.**
- **Row 3 (Terminal.app profile):** AH1 Tier-B — `.terminal` import method (no relaunch); profile name `BEN` must equal dashboard card alias.
- **Row 4 (picker CLAUDE.md):** verify dispatch/bus_post path is canonical `~/bm-b1/scripts/bus_post.sh`; add first-message confirmation phrase if missing.
- **Rows 5,6,7 (bus_post recipient+sender whitelist, drain-hook resolve):** GENERATED from registry — covered by regeneration. Verify post-regen.
- **Row 8 (1Password key):** AH1 Tier-B — `op item create --category="API Credential"` title `BRISEN_LAB_TERMINAL_KEY_ben`, field `credential` (Lesson #78).
- **Row 9 (Render env):** AH1 Tier-B — add `"ben":"<key>"` to `BRISEN_LAB_TERMINAL_KEYS` JSON on brisen-lab service, then POST /deploys.
- **Row 10 (front-end):** **hand-edit** `static/index.html` — add `<article class="card card-desk" data-alias="ben">` in the shared-specialist row; `app.js` TERMINALS/LABELS are generated (verify).
- **Row 11 (server, FOUR places):** GENERATED (KNOWN_CARD_SLUGS, `_build_terminals_response`, `app.py TERMINALS`) — covered by regeneration. **Add/extend regression in `tests/test_a3_a8_a9_bus.py`** asserting `ben` in `/api/v2/terminals` + badge SSE.
- **Row 12 (forge snapshot pusher):** AH1 Tier-B — add `ben:~/baker-vault` (no code clone) to `scripts/forge_snapshot_push.sh` SNAPSHOT_TERMINALS (or confirm generated); repo-path `~/baker-vault` (hard rule — picker has no `.git`).
- **Row 13 (wake-handler applescript, BOTH maps):** **hand-edit** — 13a `fnMap` `{"ben","ben"}`; 13b `cwdForAlias` `if a is "ben" then return "/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-ben"`. NOTE: BEN is Cowork-hosted ⇒ auto-wake N/A; still wire both for parity + future Terminal use, but do NOT gate an AC on Director-click auto-wake.
- **Row 14 (wake-listener allowlist):** GENERATED (WAKEABLE) — covered by regeneration; AH1 Tier-B deploys `~/.brisen-lab/wake-listener.py` + kickstart.

## Constraints
- Registry-driven: edit YAML + regenerate; **never hand-edit** `agent_identity_generated.*`. Gold-SHA check before merge.
- Additive; each PR runs the gate chain (AH2/architecture + `/security-review`); Tier-A merge on green.
- Tests-first on the Row-11 regression. NO pass-by-inspection.

## Acceptance criteria
1. `agent_registry.yml` has `ben` (AG-208, shared-specialist, level 0); all regenerated artifacts carry the matching SHA256.
2. `POST /msg/ben` with a valid key + valid recipient succeeds; `ben` is now an accepted recipient (canonicalizer admits it — closes the earlier "ben rejected as ghost" gap).
3. `GET /api/v2/terminals` includes `ben`; card renders on brisen-lab (visual check, not just API).
4. `tests/test_a3_a8_a9_bus.py` green incl. new `ben` assertions; forge-snapshot test green.
5. Ship report + `POST_DEPLOY_AC_VERDICT` after AH1 Tier-B (key/env/redeploy/telemetry) — incl. `has_telemetry:true` for ben after its first Cowork session (tenth-pass verify).

## Split
- **b2:** all repo/registry/code/test work + 3 PRs.
- **AH1 Tier-B post-merge (lead):** 1P key, Render env+deploy, forge pusher redeploy, wake-listener deploy, drain-hook deploy, `~/bm-ben/.claude/settings.local.json` FORGE_KEY+LAB_URL inject, zshrc launcher, Terminal profile, smoke.
