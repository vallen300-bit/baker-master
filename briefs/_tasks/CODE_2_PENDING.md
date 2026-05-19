---
status: PENDING
brief: _ops/briefs/BRIEF_UI_SURFACE_PREBRIEF_V2.md (baker-vault)
brief_id: UI_SURFACE_PREBRIEF_V2
target_repo: baker-vault
working_dir: baker-vault clone of B2's choice (no bm-b2-baker-vault worktree exists yet — B2 may use a /tmp clone or set one up; see Pre-requisites)
matter_slug: baker-internal
cross_matter_usage: [all-matters] (hook gates brief-authoring across all matter work)
dispatched_at: 2026-05-19T13:55:00Z
dispatched_by: lead
director_auth: 2026-05-19 chat — "ratified"
trigger_class: LOW-MEDIUM
gate_chain:
  gate_1_static: REQUIRED (deputy / AH2 cross-lane)
  gate_2_security_review: REQUIRED (hook is security-perimeter component — gates agent tool use)
  gate_3_cross_lane_architecture: NOT required (no auth/DB schema/architecture-affecting changes)
  gate_4_2nd_pass_code_reviewer: NOT required (no auth/DB schema/operation-ordering per SKILL.md trigger list)
estimated_effort: 1-2h
working_branch_suggestion: b2/ui-surface-prebrief-v2-hook
reply_target: lead (bus topic `ship/ui-surface-prebrief-v2`)
---

# CODE_2_PENDING — UI_SURFACE_PREBRIEF_V2 — 2026-05-19

## Brief

`~/baker-vault/_ops/briefs/BRIEF_UI_SURFACE_PREBRIEF_V2.md` (baker-vault repo, commit `c64e46c` 2026-05-19). Read end-to-end before starting — Director Q1+Q2+Q3+Q5 answers baked into the brief; do not re-litigate.

## Target repo + working branch

- **Repo:** baker-vault.
- **Branch:** `b2/ui-surface-prebrief-v2-hook` cut from baker-vault `main` after `git pull --ff-only origin main`.
- **Working dir options (B2 picks):**
  1. Use `~/baker-vault` directly (shared FS — apply branch isolation per 2026-04-30 shared-FS race lesson; avoid concurrent agent edits).
  2. Create `~/bm-b2-baker-vault` worktree: `git worktree add ~/bm-b2-baker-vault b2/ui-surface-prebrief-v2-hook` from `~/baker-vault`. **Recommended** — cleaner isolation.
  3. Fresh `/tmp/bv-b2-uisp/` clone as ephemeral. Acceptable for short brief.

## Pre-requisites

- `jq` on PATH (`command -v jq` — verify before starting; install via `brew install jq` if absent, surface to AH1 if Director-time install needed).
- Read current Claude Code hooks docs at https://code.claude.com/docs/en/hooks — cite URL + fetch date in PR description per Code Brief Standards. Confirm PreToolUse contract + exit-code semantics match brief's behavior contract.

## Scope summary (full detail in brief)

1. **Hook script:** `~/baker-vault/_ops/hooks/ui-surface-prebrief-check.sh`. Bash. Reads PreToolUse JSON from stdin via `jq`. Fires on Write to `briefs/BRIEF_*.md` OR `_ops/briefs/BRIEF_*.md` OR on Edit/MultiEdit adding new `## Acceptance criteria` heading or new `file:line` reference. Greps target content for `### Surface contract` block. Exit 2 if absent (with specific stderr message naming N/A escape valve). Fail-open on malformed JSON.
2. **Test harness:** `~/baker-vault/_ops/hooks/tests/test_ui_surface_prebrief_check.sh`. 8 cases (full list in brief § Test plan). Asserts exit codes + stderr substring. Includes latency assertion <100ms per invocation.
3. **Documentation:** `~/baker-vault/_ops/hooks/README.md` — create if absent. One-line entry for this hook minimum.
4. **Cross-reference:** add `## Hook companion` section to `~/baker-vault/_ops/skills/ui-surface-prebrief/SKILL.md` (~10 lines) linking to the hook script + naming firing conditions.

## Out of scope (DO NOT touch)

- Picker-side install (symlinks into `~/bm-aihead1/.claude/hooks/` + `~/bm-aihead2/.claude/hooks/`, settings.json updates). AH1 does this post-merge as Tier A.
- Propagation to AID-T / Architect / Researcher pickers. Q3 ratification: one-shot, not general policy.
- Generalization to other skills (cascade-back-prop already has a hook; pre-mortem stays advisory).

## Ship gate (literal)

1. `bash ~/baker-vault/_ops/hooks/tests/test_ui_surface_prebrief_check.sh` — full literal output in ship report. All 8 cases pass + latency assertion green. No "pass by inspection."
2. Anthropic docs URL + fetch date cited in PR description.
3. Settings.json snippet for AH1 to install post-merge included in PR description (so AH1 can paste-install without re-deriving).
4. README.md hooks index entry visible.

## Self-check before claiming ship

- [ ] Anthropic hooks docs URL fresh (within 30 days), confirmed PreToolUse JSON shape unchanged.
- [ ] Hook fails OPEN on malformed JSON (gate bugs must never block legitimate tool use).
- [ ] `file:line` regex doesn't false-positive on common prose ("Section 4:1 of the contract" stays safe).
- [ ] All 8 test cases green via literal harness run.
- [ ] Latency <100ms per invocation (each case `time`-wrapped).
- [ ] Settings.json snippet for picker install written out verbatim — AH1 can paste-and-go without thinking.
- [ ] No modifications to AID-T / Architect / Researcher picker paths (one-shot scope).
- [ ] No modifications to existing brisen-lab / baker-master / brisen-docs hooks.

## Reporting

- Open PR with title `UI_SURFACE_PREBRIEF_V2: skill+hook hybrid hardening`.
- Bus-post `ship/ui-surface-prebrief-v2` to `lead` with: PR link, commit SHA, literal test harness output presence, Anthropic docs URL + fetch date, settings.json snippet preview, latency assertion result.
- Heartbeat every 12h while in progress (likely a single-session brief, but follow the rule).

## Surface contract: N/A — pure tooling brief, no user-clickable surface added (the hook gates other agents' tool use; produces no UI artifact)

## Anchors

- Brief: `~/baker-vault/_ops/briefs/BRIEF_UI_SURFACE_PREBRIEF_V2.md`
- Skill being hardened: `~/baker-vault/_ops/skills/ui-surface-prebrief/SKILL.md` (v1.1, commit `6467edd`)
- Researcher market scan: `~/baker-vault/wiki/research/2026-05-19-ui-surface-prebrief-market-scan.md` (Action 1 source)
- Precedent for bash-native hook in Brisen: `~/baker-vault/.githooks/cascade_backprop_check.sh`
- Anchor incident: brisen-lab PR #22 / #23 ship-time discovery 2026-05-19 ~07:35Z
