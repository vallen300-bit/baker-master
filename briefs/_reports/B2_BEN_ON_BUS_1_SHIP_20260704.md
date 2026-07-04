# B2 SHIP REPORT — BRIEF_BEN_ON_BUS_1

**Date:** 2026-07-04 · **Worker:** b2 · **Dispatcher:** lead (#5235)
**Brief:** baker-master main `briefs/_tasks/BRIEF_BEN_ON_BUS_1.md`
**Context:** follows directly from BRISEN_LAB_BUS_WIRING_FIX_1 (ben was a surfaced unregistered ghost).

## PRs (SOP order: baker-vault → baker-master → brisen-lab)
- **baker-vault #140** — `b2/ben-on-bus-registry` — registry record (AG-208).
- **baker-master #455** — `b2/ben-on-bus-baker-master` — regenerated identity artifacts.
- **brisen-lab #94** — `b2/ben-on-bus` — regen + Row10 card + Row13 wake-handler + Row11 test.

## Locked identity (per lead, not re-derived)
`ben` · BEN · AG-208 · shared-specialist · app-claude (Cowork) · reports_to lead · aliases () · bus_enabled true · authority **0** (auto-derived: "NONE — BEN escalates to lead/director; never decides").

## Gold-SHA parity
`sha256(agent_registry.yml)` = **458f6d88253d9a0aaacd4a2b42d2b007e24e156baafa0eacf708e2688ffda46a**, identical across every regenerated artifact in both repos (baker-master orchestrator/agent_identity_data.py + scripts/agent_identity_generated.sh + tests/fixtures/session-start-bus-drain.sh; brisen-lab agent_identity_generated.py + static/.js + tools/wake-listener/.py).

## 14-row map (b2 scope)
- **Registry source** ✅ (baker-vault #140).
- **Rows 5/6/7 (bus_post whitelist + drain resolve)** ✅ generated — verified (VALID_BUS_SLUGS/BUS_AGENT_SLUGS/role-resolve carry ben).
- **Row 10 (front-end card)** ✅ hand-edit — ben `<article class="card" data-alias="ben">` in shared-specialist row.
- **Row 11 (server, 4 places + test)** ✅ generated (KNOWN_CARD_SLUGS/_build_terminals_response/APP_TERMINALS) + new tests.
- **Row 12 (forge snapshot pusher)** ✅ generated — SNAPSHOT_TERMINALS has `ben:/Users/dimitry/baker-vault` (Row-12 hard rule: picker has no .git → baker-vault repo-path).
- **Row 13 (wake-handler, both maps)** ✅ hand-edit — cwdForAlias (ben → `/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-ben`) + fnMap `{ben,ben}`. NOTE: Cowork-hosted ⇒ auto-wake N/A; wired for parity/future Terminal.
- **Row 14 (wake-listener allowlist)** ✅ generated (WAKEABLE_TERMINALS has ben).
- **Rows 1/2/3/4/8/9 = AH1 Tier-B post-merge** (picker exists; launcher, Terminal profile, 1P key, Render env, telemetry settings.local.json — lead's split).

## Tests (literal pytest, Neon)
`tests/test_a3_a8_a9_bus.py` + `tests/test_agent_identity_generated.py`: **34 passed, 30 deselected** (248s). New: `test_ben_registered_card_slug` (ben in CARD_SLUGS/APP_TERMINALS/WAKEABLE_TERMINALS + IDENTITY_LABELS) + `test_ben_badge_and_terminals_surface` (dispatch to ben → 200, card in /api/v2/terminals). Movie-desk regression still green.

## Acceptance criteria
- AC1 ✅ ben in registry (AG-208, level 0); all artifacts carry matching SHA256.
- AC2 ✅ POST /msg/ben with valid key + recipient succeeds; ben accepted recipient (test).
- AC3 ✅ GET /api/v2/terminals includes ben (test); card render = visual post-deploy.
- AC4 ✅ test_a3_a8_a9_bus.py green incl. ben; forge-snapshot path generated.
- AC5 ⏳ ship report (this) + POST_DEPLOY_AC_VERDICT after AH1 Tier-B (key/env/redeploy/telemetry); has_telemetry:true after ben's first Cowork session.

## Handoff to AH1 (Tier-B post-merge)
1P key `BRISEN_LAB_TERMINAL_KEY_ben`, Render env `BRISEN_LAB_TERMINAL_KEYS += ben` + POST /deploys, forge pusher redeploy, wake-listener deploy, drain-hook deploy, `~/bm-ben/.claude/settings.local.json` FORGE_KEY+LAB_URL, zshrc `ben()` launcher (inject BRISEN_LAB_TERMINAL_KEY), Terminal profile `BEN`, smoke.
