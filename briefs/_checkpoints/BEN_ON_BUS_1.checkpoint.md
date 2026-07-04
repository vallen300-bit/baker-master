# CHECKPOINT — BRIEF_BEN_ON_BUS_1

attempt: 1
owner: b2 · dispatched_by: lead (#5235) · date: 2026-07-04
brief: baker-master main briefs/_tasks/BRIEF_BEN_ON_BUS_1.md
repos: baker-vault + baker-master + brisen-lab (3-repo registry-driven install)

## STATUS: b2 scope DONE — 3 PRs OPEN, ship posted #5236, awaiting merge + AH1 Tier-B
- baker-vault PR #140 (b2/ben-on-bus-registry) — ben AG-208 registry record.
- baker-master PR #455 (b2/ben-on-bus-baker-master) — regenerated identity artifacts.
- brisen-lab PR #94 (b2/ben-on-bus) — regen + Row10 index.html card + Row13 wake-handler (both maps) + Row11 test.
- Gold SHA parity: 458f6d88253d9a0aaacd4a2b42d2b007e24e156baafa0eacf708e2688ffda46a across registry + ALL artifacts (both repos).
- Tests: 34 passed (new ben tests + movie regression + identity), Neon. AC1-AC4 PASS.
- Ship report: briefs/_reports/B2_BEN_ON_BUS_1_SHIP_20260704.md.

## What's LEFT
1. Lead merges 3 PRs in SOP order (#140 → #455 → #94), gate chain each, Tier-A on green.
2. AH1 Tier-B post-merge: 1P key BRISEN_LAB_TERMINAL_KEY_ben, Render env BRISEN_LAB_TERMINAL_KEYS+=ben
   + POST /deploys, forge pusher redeploy, wake-listener deploy, drain-hook deploy,
   ~/bm-ben/.claude/settings.local.json FORGE_KEY+LAB_URL, zshrc ben() launcher, Terminal profile BEN, smoke.
3. AC5: after Tier-B + redeploy, verify POST /msg/ben live 200 + ben card renders + has_telemetry:true
   after ben's first Cowork session → emit POST_DEPLOY_AC_VERDICT v1 to lead. (b2 emits if asked; else lead/AH1.)

## Notes
- ben is Cowork-hosted (like cowork-ah1): auto-wake N/A, needs settings.local.json telemetry env.
- Row-12 SNAPSHOT_TERMINALS = ben:/Users/dimitry/baker-vault (picker has no .git — hard rule).
- Registry-driven: authority level 0 + note auto-derive from slug/display_name in the generator (no explicit field).
