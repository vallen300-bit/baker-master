# B3 ship report — CLERK_ON_BUS_1 (repo-work rows)

**Date:** 2026-06-04
**Owner:** b3 (implementation only)
**Brief:** baker-vault `_ops/briefs/BRIEF_CLERK_ON_BUS_1.md` (f9e0573, codex G0 v3 PASS #1850)
**Dispatch:** lead bus #1854 (ACKed)

## Scope delivered (the 2 repo PRs of the 14-row SOP)
AH1 owns Row 1 picker (done) + Tier-B rows (zshrc, Terminal profile, 1P key, Render env, forge redeploy, wake rebuild + listener reload + deployed-copy patch) + AC12 smoke. B3 delivered the repo-work rows only.

### baker-master PR — #295 (`b3/clerk-on-bus-1`, commit 34a0f63)
- **Row 5** `scripts/bus_post.sh`: `clerk` added to recipient whitelist + `clerk|CLERK) SENDER=clerk` to BAKER_ROLE sender case + both error-message valid-lists.
- **Row 7** `tests/fixtures/session-start-bus-drain.sh`: `clerk` added to BAKER_ROLE→SLUG case (Clerk is a Claude picker with a SessionStart drain hook).
- **Row 10** `scripts/forge_snapshot_push.sh`: `TERMINALS += clerk:/Users/dimitry/baker-vault` (no code clone → baker-vault repo-path per Row 12) + Case T regression in `tests/test_forge_snapshot_push.sh`.

### brisen-lab PR — #61 (`b3/clerk-on-bus-1`)
- **Row 8** `static/index.html` shared-specialist card in `.row-shared`; `static/app.js` `clerk` in TERMINALS + TERMINAL_LABELS ("Clerk") + CARD_TYPE ("shared-specialist").
- **Row 9** `bus.py` KNOWN_CARD_SLUGS tuple + `_build_terminals_response` for-loop tuple; `app.py` TERMINALS; 2 regression tests in `tests/test_a3_a8_a9_bus.py`.
- **Row 13** `tools/wake-handler/wake-handler.applescript`: `cwdForAlias clerk → ~/bm-clerk` + `fnMap {"clerk","clerk"}`. Confirmed Claude submit path (codex bare-CR branch guarded `if aliasName is "codex"` — N/A to clerk).
- **Row 14** `tools/wake-listener/wake-listener.py`: `ALLOWED_ALIASES += "clerk"`.

## Done rubric — literal answer
- **Both PRs open with literal-green ship-gate tests:** ✅ (merge = AH1, not B3).
- **`bash tests/test_forge_snapshot_push.sh` (baker-master):** `All 20 cases PASS.` — Case T (clerk) green.
- **`pytest tests/test_a3_a8_a9_bus.py -v` (brisen-lab):** `38 passed, 3 warnings in 302.84s` — `test_bus_badge_change_emitted_for_clerk` + `test_v2_terminals_response_includes_clerk` green.
- **Pre-flight `grep -nE '"lead".*"deputy".*"b1"' bus.py app.py` = 3 known sites:** ✅ confirmed before edit (app.py:40, bus.py:1189 KNOWN_CARD_SLUGS, bus.py:1346 for-loop).
- **AC0 re-check:** `clerk` slug-free across all target files in both repos before edit. ✅

## Test isolation note
brisen-lab pytest run on an isolated throwaway Neon DB (`b3_clerk_test`, created off the direct/non-pooler endpoint, dropped after) to avoid TRUNCATE contention with the shared B-code test DB (per known scar: concurrent TRUNCATE corrupts row-count tests).

## Gates remaining (not B3)
Per PR: G1 lead literal pytest → G2 /security-review → G3 codex → AH1 merge. After both merge → AH1 runs Tier-B + AC12 end-to-end smoke.

## Notes for lead
- Sequencing per SOP: baker-master (#295) → brisen-lab (#61). baker-vault already holds the agent brief.
- One canonical slug `clerk` everywhere; no variants introduced.
- Cleared an unrelated abandoned interactive rebase on `b3/attachment-two-write-parity-1` at session start (accidental side effect of the picker alias's `pull --rebase`); zero data loss (branch intact on origin at f13f300). Reset to clean main before this work.
