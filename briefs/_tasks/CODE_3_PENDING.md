---
status: PENDING
brief: briefs/BRIEF_TERMINAL_AUTO_ONBOARD_1.md
trigger_class: LOW
dispatched_at: 2026-05-02T12:00:00Z
dispatched_by: ai-head-a
claimed_at: 2026-05-02T12:05:00Z
claimed_by: b3
last_heartbeat: 2026-05-02T12:05:00Z
blocker_question: null
ship_report: briefs/_reports/B3_terminal_auto_onboard_1_20260502.md
pr: pending
autopoll_eligible: false
---

# CODE_3 — DISPATCH (BRIEF_TERMINAL_AUTO_ONBOARD_1)

**Status:** OPEN — 2026-05-02T12:00Z by AI Head A (overwrites prior CODE_3 closure on VAULT_WRITE_FOLLOWUP_NITS_1 / PR #142 merged 2026-05-01)
**Brief:** `briefs/BRIEF_TERMINAL_AUTO_ONBOARD_1.md` (LOW, ~1-2h, Tier B)
**Builder:** B3
**Branch (cut from latest main):** `b3/terminal-auto-onboard-1`
**Tier:** **Tier B** — autonomous merge on green per `_ops/processes/ai-head-autonomy-charter.md` §3
**autopoll_eligible:** false — paste-block dispatch; cold-start required

## Why this exists

Today, when Director (or any human) opens a new Claude Code session in a
terminal, the model has no idea whether it is AH1 / AH2 / B1-B5. Director
manually pastes "You are AH2..." as the first message every cold start.
This brief eliminates the paste step by wiring a SessionStart hook that
reads `$BAKER_ROLE` and emits the per-role context block via the JSON
envelope contract Claude Code expects.

Companion / next-step brief: `BRIEF_BRISEN_LAB_MSGBUS_1` (pending Director
ratification) — removes Director from the relay path entirely once
auto-onboarding lands here.

## Task summary

9 in-repo files: 1 SessionStart hook + 7 role-context texts + 1
`settings.local.json.example`. Vault-side process doc body lives in PR
description (separate baker-vault PR is Director-side, low priority).

**Files touched:** 9 added.

**Critical: do NOT touch:**
- Existing `.claude/hooks/block-secrets.sh`, `.claude/hooks/syntax-check.sh`.
- `.claude/settings.json` — only `.example` is new + checked-in.
- `~/.claude/bin/baker-statusline.sh` — leave alone; example wraps it.
- No SessionEnd hook — `/handover` slash command (shipped 2026-05-02) covers session-end.

## Dispatch steps

```bash
cd ~/bm-b3
git fetch origin
git checkout main && git pull --ff-only origin main
gh pr list --state open --limit 20    # Lesson #54 precheck
git checkout -b b3/terminal-auto-onboard-1
git config core.hooksPath .githooks

# Read brief in full
cat briefs/BRIEF_TERMINAL_AUTO_ONBOARD_1.md

# Implement Scope per brief — 9 in-repo files exactly.
# Vault doc body goes in PR description, NOT committed to baker-vault from here.

# Quality checkpoints (4 manual unit tests + smoke test) — see brief §Quality checkpoints.

git push -u origin b3/terminal-auto-onboard-1
gh pr create --title "feat(claude-code): SessionStart role auto-onboard via BAKER_ROLE env (BRIEF_TERMINAL_AUTO_ONBOARD_1)" \
  --body "$(see brief §Quality checkpoints for full body template)"
```

## Acceptance criteria

- 9 files added (`.claude/hooks/session-start-role.sh` + 7 role-context md
  files + `.claude/settings.local.json.example`).
- Hook is executable (`100755`); confirm via `git ls-files --stage`.
- All 4 manual unit tests produce a valid JSON envelope on stdout with
  `hookSpecificOutput.hookEventName == "SessionStart"`.
- Hook exits 0 in every branch (set / unset / unknown / missing-file).
- Smoke test in fresh Claude session with `BAKER_ROLE=B3` → role greeting
  appears in turn 1.
- PR opened with brief link in body + vault doc body inline.
- Tier B autonomous-merge on green.
- Ship report at `briefs/_reports/B3_terminal_auto_onboard_1_20260502.md`.

## On completion

1. Open PR.
2. Update this mailbox to `status: COMPLETE` with PR link + ship-report path.
3. AI Head A reviews + merges on green (autonomous Tier B per charter §3).
4. Director copies vault doc body into baker-vault when convenient (separate PR, low priority).

## Out of scope (per brief §Out of scope)

- COWORK role (web Claude.ai — separate brief MSGBUS_1).
- `.claude/settings.local.json` itself (gitignored; `.example` only).
- SessionEnd hook (covered by `/handover` slash command).
- Auto-loading handover *contents* — only a pointer.
