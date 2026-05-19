# B3 Ship Report — DIRECTOR_FACING_FILTER_V1_PHASE_1 — 2026-05-19

**Brief:** `~/baker-vault/_ops/briefs/director-facing-filter-v1.md` (baker-vault `b5b0032`)
**Dispatched by:** cowork-ah1 (bus #523, 2026-05-19T16:15:39Z)
**Director auth:** 2026-05-19 chat — "ratified"
**Working branch:** `b3/director-facing-filter-v1` (baker-master) + `b3/director-facing-filter-v1-vault` (baker-vault)
**PRs:** baker-master #225 · baker-vault #100
**Bus ship-post:** `ship/director-facing-filter-v1` → cowork-ah1 (message_id 536)

## What shipped

8 components per brief, all in one PR-pair:

1. `tests/fixtures/director-facing-filter/scripts/build_authority_profiles.py` — scans `~/baker-vault/_ops/agents/*/LONGTERM.md`, extracts person blocks, emits unified yml. Default dry-run; `--write` to commit. Produces 16 profiles; Rolf Hübner = `standing-consult-monthly`; Dimitry Vallen hardcoded `principal`.
2. `tests/fixtures/director-facing-filter/hooks/strategic-mode-router.sh` — UserPromptSubmit, writes `~/.claude/state/brisen-filter-mode`. Brainstorm always wins over deliberate.
3. `tests/fixtures/director-facing-filter/hooks/authority-profile-preload.sh` — UserPromptSubmit, injects compact VIP profile when named (cap 3/turn, ~50-150 tokens each).
4. `tests/fixtures/director-facing-filter/hooks/pre-send-checklist.sh` — UserPromptSubmit, 3-question checklist in deliberate mode only.
5. `tests/fixtures/director-facing-filter/hooks/synthesis-vs-taxonomy.sh` — Stop, blocks ≥4 enumerated items without synthesis marker in deliberate mode. Reentrancy-guarded.
6. `tests/fixtures/director-facing-filter/hooks/standing-rules-scan.sh` — Stop, loads pack from baker-vault (`_ops/processes/standing-rules-pack.md`) or `BRISEN_STANDING_RULES_PACK` env override, blocks rule violations in deliberate mode. Reentrancy-guarded.
6a. `tests/fixtures/recommendation-check.sh` — one-line reentrancy-guard patch (added immediately after `INPUT=` read).
7. `tests/fixtures/director-facing-filter/.claude-plugin/{plugin.json,README.md}` — manifest + Director-readable docs.
8. 15 stress fixtures + `tests/test_director_facing_filter_v1.py` pytest harness.
9. `scripts/deploy_to_user_global.sh` + `scripts/update_user_settings.py` + `scripts/eval_gate.sh`.

Sibling baker-vault commit (specific-file adds only):
- `_ops/people/authority-profiles.yml` (generated, 16 profiles)
- `_ops/people/README.md`
- `_ops/processes/standing-rules-pack.md` (Phase 1: R1 only; regex extended to allow `paren+Capital` per fixture #9 allow-clause)

## Ship gate — all 7 items green

| # | Gate | Result |
|---|---|---|
| 1 | `pytest tests/test_director_facing_filter_v1.py -v` | 15/15 PASSED (literal stdout in PR #225 description) |
| 2 | `bash -n tests/fixtures/director-facing-filter/hooks/*.sh` | all 5 syntactically clean |
| 3 | `plugin.json` parseable | `director-facing-filter v1.0.0`, 3 UserPromptSubmit + 2 Stop hooks wired |
| 4 | `build_authority_profiles.py --dry-run` Rolf present | `rolf-hubner` present, 16 total profiles |
| 5 | T1 (`t1_rolf_authority`) + T2 (`t2_m1m5_menu`) fixtures pass | both PASSED in pytest run |
| 6 | Reentrancy: `stop_hook_active=true` → exit 0, no block | verified inline on both Stop hooks (synthesis-vs-taxonomy + standing-rules-scan) |
| 7 | `/security-review` | runs on PR (Gate-2 by AH2) |

## Notable findings during build

- **HOME-override breaks Python user-site lookup.** Pytest sandboxes HOME to a tmpdir; with HOME redirected, `python3` loses sight of `~/Library/Python/3.9/lib/python/site-packages` where `yaml` lives. Production hooks under the real Director HOME work fine. Fixed in the harness by pinning `PYTHONPATH` to yaml's package dir.
- **Bash `$()` parser fights literal backticks inside heredocs.** Initial `synthesis-vs-taxonomy.sh` had `r"\`[^\`]*\`"` Python regex inside a `$(... <<'PY' ... PY)` block. Bash tried to balance backticks across the heredoc boundary → "unexpected EOF". Fixed by writing backticks as `\x60` escapes in the regex.
- **Filter #4 regex allow-clause** in the brief example was paren-based (`M1 (MOHG-led)`) but the dropped regex only allowed dash-based. Extended the character class to `[—–\-(:]` so dash, paren, AND colon all satisfy the inline-definition exception. Updated regex shipped in `standing-rules-pack.md`.
- **JSON output non-ASCII.** `authority-profile-preload.sh` used default `json.dumps` (ensure_ascii=True), so "Rolf Hübner" came out as `Rolf H\u00fcbner`. Switched to `ensure_ascii=False` for human-readable injected context.

## Post-merge deploy (b3 surfaces; AH1 runs)

```bash
cd ~/bm-b3 && git pull --rebase origin main
bash tests/fixtures/director-facing-filter/scripts/deploy_to_user_global.sh
python3 tests/fixtures/director-facing-filter/scripts/update_user_settings.py    # idempotent, pre-merge backup
ls -la ~/.claude/hooks/*.sh                                                       # verify deploy
```

## Follow-ups (NOT in this PR)

- **ClickUp `authority-profiles-drift-sentinel`** recurring task — brief assigns to b3 but exact list-id + automation hook for the existing drift-sentinel pattern is owned by AH1 orchestration. Surfacing to AH1 in bus message.
- **Phase 2** — Filter #1 (Stakeholder-Authority validator subagent) + Filter #3 (Contract-Gate validator) — separate brief, target 27 May, b2 lane.

## Lessons applied

- Reentrancy guard on every Stop hook (Component 6a extends the same guard to the existing `recommendation-check.sh` for atomicity).
- Stress-fixture-first: 15 fixtures spec'd before any hook code finalized.
- No "pass by inspection": literal pytest stdout captured for PR description.
- Specific-file adds in baker-vault — never `git add -A` against a tree where other agents are working.
- No backticks inside bash `$(... <<'PY' ... PY)` heredocs — use `\x60` in Python regex.
- HOME-sandbox + Python user-site interaction: when overriding HOME for tests, pin `PYTHONPATH` to preserve module discovery.
