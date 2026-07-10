# BRIEF: BRISEN_DESK_ON_BUS_1 — install brisen-desk (AG-306) onto Brisen Lab with full bus wiring

status: PENDING
dispatched_by: lead
assignee: b3
Harness-V2: task_class=install (registry-driven, 3-repo) · gate plan: b3 build → codex G3 → lead merge → lead Tier-B post-merge (keys/env/profile/wake) → lead AC12 smoke + POST_DEPLOY_AC_VERDICT

## Context

Director queue: Brisen Desk flight is the next install after Hagenauer (ruling 2026-07-10; Staininger ticket EH-AT.FID1147 is checked-in VALID under lead custody until this desk is live). Flight prep (BRI-GRP-001) is running in parallel — store sweep dispatched to CM-1 (#8618). The flight's desk lanes (step plan, T1 loop, check-ins) need brisen-desk ON THE BUS. Registry: AG-306, `slug: brisen-desk`, currently `status: seeded / bus_enabled: false / runtime: vault-seeded`.

Canonical SOP: `~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md` (14-row map — this brief enumerates every row per the fourth-pass rule). Install is REGISTRY-DRIVEN (librarian AG-209 precedent, 3 PRs SHA-parity, merged 2026-07-08): flip the registry row, regenerate identity artifacts, wire the hardcoded lists.

## Context Contract
- Inputs: this brief; the SOP above; registry `_ops/registries/agent_registry.yml` AG-306; librarian install precedent (vault PR #144 / master PR #492 / lab PR #107); AC0 findings inlined below.
- NOT in context / do not assume: any prior brisen-desk bus wiring (there is none); Director availability (lanes run without him).
- Repos: baker-vault (registry + agent files) → baker-master (identity artifacts, bus_post whitelists, pusher, drain fixture) → brisen-lab (front-end, server, wake maps, tests). Merge in that order (SOP §Three-repo PR sequencing).

## Done rubric (done-state class: gate-verified 3-repo merge + lead post-deploy smoke)
1. All 14 rows addressed in-PR or explicitly `N/A — reason` / `lead post-merge` in the ship report.
2. Registry row flipped: `status: active`, `bus_enabled: true`, `runtime: terminal-claude`; identity artifacts regenerated with NO stderr slug warning.
3. codex G3 PASS on all three PRs; regression tests green (`tests/test_a3_a8_a9_bus.py` brisen-lab, `tests/test_forge_snapshot_push.sh` baker-master) — literal output in PR, no pass-by-inspection.
4. Slug-case drift resolved (AC0 finding): one canonical `brisen-desk` everywhere.
NOT done at: "PRs open" / "wired except wake rows" / smoke not run (smoke is lead's post-merge lane but PRs must make it passable).

## AC0 pre-flight findings (already run by lead — DO NOT re-derive, DO resolve)
- **Existing workspace EXISTS**: `~/Vallen Dropbox/Dimitry vallen/bm-brisen-desk` (Dropbox-synced picker, substantive content expected — verify CLAUDE.md present) + vault `_ops/agents/brisen-desk/`.
- **Existing zshrc fn `brisendesk()`** (line ~109) cd's to the Dropbox path, sets `BAKER_ROLE=BRISEN_DESK` + `FORGE_TERMINAL=brisen_desk`, launches claude with role system-prompt.
- **Ruling (lead, per SOP fifth-pass default)**: wire the slug to the EXISTING Dropbox workspace — do NOT create `~/bm-brisen-desk`. `picker_path: /Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-brisen-desk`.
- **Slug-case drift MUST be fixed**: `BAKER_ROLE=BRISEN_DESK` and `FORGE_TERMINAL=brisen_desk` do not match canonical `brisen-desk`. Update the zshrc fn to `BAKER_ROLE=brisen-desk FORGE_TERMINAL=brisen-desk` (one canonical slug rule) — verify the identity map + drain hook resolve it after the change.

## The 14 rows (every row addressed; SOP row numbers)
- **Row 1 (picker dir)**: N/A — exists (AC0). Add/refresh `CLAUDE.md` bus block (canonical `~/bm-b1/scripts/bus_post.sh` path — NEVER Desktop/baker-code) + register snapshot path for `brisen-desk` in `_snapshot_path_for()` in `scripts/generate_agent_identity_artifacts.py` pointing at the Dropbox picker path; run `python3 scripts/generate_agent_identity_artifacts.py --write`; commit regenerated `agent_identity_generated.sh` + `agent_identity_data.py`. Generator stderr warning = Row-1 gate.
- **Row 2 (zshrc fn)**: exists — patch slug-case drift only (see AC0). Ensure `git pull --rebase --autostash` line present per SOP foot-gun 8 (Dropbox picker: only if it's a git repo; else N/A — note which).
- **Row 3 (Terminal profile)**: LEAD post-merge (Tier-B) via `.terminal` + `open` import; profile name "Brisen Desk" = dashboard card alias exactly. Brief notes it; b3 does NOT touch the plist.
- **Row 4 (picker CLAUDE.md)**: refresh in-place at the Dropbox picker — Tier-0 reads, confirmation phrase, dispatch protocol, canonical bus_post path.
- **Rows 5+6 (bus_post.sh recipient + sender whitelists)**: registry-driven — verify the generated identity map covers `brisen-desk` for BOTH directions after Row-1 regen; if bus_post.sh still carries hardcoded cases, add both.
- **Row 7 (SessionStart drain hook)**: add `brisen-desk` to BAKER_ROLE case in canonical fixture `tests/fixtures/session-start-bus-drain.sh` (baker-master); lead deploys the `cp` to `~/.claude/hooks/` post-merge.
- **Row 8 (1Password key)**: LEAD post-merge — `--category="API Credential"` + `credential` field (Lesson #78). b3: N/A.
- **Row 9 (Render env `BRISEN_LAB_TERMINAL_KEYS`)**: LEAD post-merge + explicit POST /deploys. b3: N/A.
- **Row 10 (front-end)**: brisen-lab PR — card `<article class="card card-desk" data-alias="brisen-desk">` in `.row-desks`, `app.js` TERMINALS array + LABELS ("Brisen Desk").
- **Row 11 (server, FOUR places)**: `bus.py KNOWN_CARD_SLUGS` + `_build_terminals_response()` loop + `app.py TERMINALS` + regression tests in `tests/test_a3_a8_a9_bus.py`. Pre-flight grep per SOP (expect the 3 code matches before edit).
- **Row 12 (snapshot pusher)**: add `brisen-desk:<repo-path>` to `forge_snapshot_push.sh` TERMINALS + test case. Repo-path RULE: if the Dropbox picker has no `.git`, use `~/baker-vault` (hard rule, RESEARCHER_ON_BUS_1 hot-fix 7fb9072) — check and state which you used.
- **Row 13 (wake-handler, BOTH maps)**: 13a `fnMap` add `{"brisen-desk", "brisendesk"}`; 13b `cwdForAlias` add the EXACT Dropbox picker path (quote the space in "Vallen Dropbox" correctly — test the AppleScript string). Lead rebuilds handler post-merge.
- **Row 14 (wake-listener allowlist)**: add `"brisen-desk"` to `ALLOWED_ALIASES` in canonical `tools/wake-listener/wake-listener.py`. Lead diffs + deploys the live copy + kickstarts post-merge.
- **Plus**: `agent-bus-posting-contract` SKILL.md desk list — add brisen-desk as a posting peer.

## Do NOT Touch
- Registry rows other than AG-306.
- The desk's role system-prompt content in the zshrc fn (only the two env var values change).
- `~/.claude/hooks/session-start-bus-drain.sh` deployed copy (lead deploys; you edit the fixture only).

## Quality Checkpoints
1. Ship report enumerates all 14 rows with disposition each.
2. Literal test output for both regression suites in PR descriptions.
3. Slug greps clean: no remaining `BRISEN_DESK`/`brisen_desk` variants in touched files.
4. 3-repo SHA-parity note (librarian pattern) in ship report.

## Verification (lead post-merge, listed so b3 knows the target)
Lead: 1P key → Render env + deploy → pusher redeploy both hosts → Terminal profile import → wake-handler rebuild + listener deploy/kickstart → AC12 smoke (bus msg + SSE badge + /api/v2/terminals + visual card) → POST_DEPLOY_AC_VERDICT on bus.
