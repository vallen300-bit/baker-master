# RESEARCHER_CHANNEL_RECONCILE_YOUTUBE_1

dispatched_by: lead
assigned_to: b1
date: 2026-07-12
task_class: standard
Harness-V2: Context Contract + done rubric + gate plan below. Gates Claude-side only (codex suspended, Director order #9711).

## Context

Context Contract: researcher = Opus research agent, cage ENFORCE live (exact-prefix vetted-script allowance, rd-2 fix). Channel landscape doc = `~/baker-vault/_ops/agents/researcher/method.md` §2. Canonical skills live in `_ops/skills/`; researcher picker symlinks at `~/bm-researcher/.claude/skills/`. Director approved YouTube channel add 2026-07-12; doc/live drift surfaced same day (researcher self-report = 6 channels vs 16 documented).

## Problem

Two defects in the researcher's channel capability, surfaced 2026-07-12:

1. **Doc/live drift.** `~/baker-vault/_ops/agents/researcher/method.md` §2 lists 16 channels (incl. GitHub via `gh`, LinkedIn, Gemma/AI Studio, `auth_source_fetch.sh`, trade press). The live researcher seat self-reports only 6 reachable channels and says `gh`/`curl` are cage-blocked. Either the cage over-blocks vetted paths, method.md is stale, or the seat under-reports. Director saw the contradiction directly.
2. **Missing channel.** YouTube is absent from §2. Director approved adding it 2026-07-12. Canonical skill exists: `_ops/skills/youtube-analyze/` (transcript fetch via `youtube-transcript-api`, Gemma synthesis, zero API cost).

## Constraints

- Researcher cage rules are NOT to be weakened. Exact-prefix vetted-script allowance pattern (rd-2 fix, PR #518/vault#153 era) is the only mechanism for re-enabling a blocked path. Any cage change = separate PR + live probe on researcher seat.
- method.md lives in baker-vault `_ops/` — vault PR from an ISOLATED WORKTREE only (Lesson: shared-checkout races; `_ops/processes/vault-writer-worktree-isolation.md`).
- Skill install = symlink into `~/bm-researcher/.claude/skills/youtube-analyze` → canonical `_ops/skills/youtube-analyze/`, matching existing symlink pattern in that picker.
- youtube-transcript-api + Ollama/gemma4 are Mac-local. Verify both respond on the researcher host before declaring channel live; if Gemma is down, the transcript path alone still counts as the channel (note it).

## Files Modified

- `baker-vault: _ops/agents/researcher/method.md` (§2 channel table — vault PR, isolated worktree)
- `baker-vault: _ops/agents/researcher/cage/*` ONLY IF AC4(a) path chosen (separate PR)
- `~/bm-researcher/.claude/skills/youtube-analyze` (new symlink → canonical skill; not a repo file — document in ship report)
- `briefs/_reports/B1_researcher_channel_reconcile_youtube_1_<date>.md` (ship report)

## Verification

- Per-channel probe evidence from the researcher seat (command + output excerpt) in the audit table — no "by inspection".
- Live YouTube probe: real URL → structured note returned on researcher seat; paste evidence in ship report.
- If cage PR raised: cage test suite green + live probe post-merge.

## Acceptance criteria

- AC1: Audit table produced — every method.md §2 channel vs live-seat reachability (works / cage-blocked / broken / stale), with evidence per row (actual probe from researcher seat or cage-config read; no "by inspection").
- AC2: method.md §2 updated to match verified reality + YouTube row added (tool = `youtube-analyze` skill; notes = transcript-first, visual-heavy caveat). Vault PR from isolated worktree.
- AC3: youtube-analyze skill symlinked into researcher picker; live probe: researcher seat analyzes one real YouTube URL end-to-end and returns a structured note.
- AC4: Any channel found cage-blocked that method.md promises (e.g. `gh`, `auth_source_fetch.sh`) → either (a) re-enable via exact-prefix vetted-script allowance PR + probe, or (b) document as intentionally blocked in method.md with routing alternative. No silent gaps.
- AC5: Ship report answers the done rubric; bus-post to lead with PR links + probe evidence.

## Done rubric

1. Director can ask researcher "what are your channels" and the answer matches method.md 1:1.
2. YouTube URL → structured note works live on researcher seat.
3. No cage weakening; all cage changes gated + probed.

## Gate plan

- Design pass: none needed (mechanical reconcile + install).
- Build gate: independent Claude-side review (deputy or non-author B-code) on both PRs.
- Live probes on researcher seat = merge precondition for the skill-install AC3.
- Lead merges.
