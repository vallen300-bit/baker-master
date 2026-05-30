---
dispatch: BRIEF_RESEARCHER_FANOUT_SKILL_1
to: b3
from: deputy
dispatched_by: deputy
status: COMPLETE
completed_at: 2026-05-30T15:10:00Z
ship_commit: 7efcded
ship_branch: main
claimed_at: 2026-05-30T14:55:00Z
claimed_by: b3
dispatched_at: 2026-05-30T12:15:00Z
authored: 2026-05-30
target_repo: baker-vault (markdown + skill spec, no DB, no migrations, no API)
workdir: ~/baker-vault
estimated_time: ~60-90 min
complexity: Low (markdown-only — same shape as BRIEF_HARNESS_SETUP_SKILL_1 you've seen b4 ship)
reply_to: deputy
priority: tier-a
brief_canonical: ~/baker-vault/_ops/briefs/BRIEF_RESEARCHER_FANOUT_SKILL_1.md
brief_anchor_commit: aca31a0 (v2 — codex bus #1394 amends folded + Director Q1/Q2 closures)
brief_v1_anchor: 8209207 (superseded by v2 — read v2 only)
codex_pre_review: PASS-WITH-NOTES bus #1394 — all 4 findings folded into v2 (M1 router rewritten using actual research-types.md type names; L1 menu renamed external-only; L2 failure-mode caveats verbatim; L3 Mnilax verbatim+expanded both required)
director_ratifications:
  - bus #1365 — design (3 default / 5 escalation channels / router)
  - bus #1369 — Opus 4.7 ONLY synthesizer (drop Gemma + drop Sonnet tier switch)
  - bus #1374 — YouTube channel = transcript fetch only, Gemma out of fan-out path
  - AH2 chat 2026-05-30 ~12:05Z — Q1 yes (companion checklist.md), Q2 slug `research-fan-out`
  - AH2 chat 2026-05-30 ~12:15Z — drop prior SKILLS_EVAL_HARNESS_1 mailbox, dispatch fan-out
authorship_override: Director-ratified AH2-authored brief (lead busy on PR #271 scheduler thread + cowork-ah1 on dossier dispatch). Same precedent as BRIEF_HARNESS_SETUP_SKILL_1 (2026-05-29).
gate_chain_expected:
  gate_1_static_review: deputy (AH2) — verify SKILL.md frontmatter shape + body sections + INDEX row + sync_skills.sh dry-run output
  gate_2_security: SKIP (markdown-only — no shell-out, no network call, no LLM call inside the skill body; runtime skill invocation will use existing audited surfaces only)
  gate_3_picker_architect: deputy (AH2) — verify the skill is reachable from `~/bm-researcher/.claude/skills/` after sync_skills.sh + that researcher's method.md §10 pointer resolves
  gate_4_code_reviewer: deputy (AH2) — verify checklist.md walks the 12 steps in order + router heuristic is coherent + Mnilax quote landed verbatim
  gate_5_merge: lead OR cowork-ah1 — merges baker-vault commits + bus-posts close-out
prior_dispatch_dropped: CODE_3_DROPPED_SKILLS_EVAL_HARNESS_1_20260525.md (5 days stale, Director-ratified drop 2026-05-30; re-dispatch later if Director picks back up)
---

# Dispatch: BRIEF_RESEARCHER_FANOUT_SKILL_1 → b3

B3 — pick up the canonical brief at `~/baker-vault/_ops/briefs/BRIEF_RESEARCHER_FANOUT_SKILL_1.md` (commit **aca31a0** on `main` — v2 with codex amends folded; do NOT use v1 `8209207`).

## TL;DR (full spec is in the brief — this is just the pickup pointer)

Convert Researcher's sequential 4-tier method (Gemma → GitHub → Web → Grok Heavy per `_ops/agents/researcher/method.md` §4) into a parallel fan-out skill. 3-of-N channel router default / 5 on escalation. Opus 4.7 synthesizer ONLY (Director-ratified bus #1369 — NO Gemma in synthesizer seat, NO Sonnet tier switch). Mnilax "Surface conflicts, don't average them" verbatim quote in synthesizer prompt + operational expansion. researcher-verify-citations runs Step 6.5. Failure modes 3/3 → 0/3 explicit.

## What to ship (4 fixes)

1. **NEW** `~/baker-vault/_ops/skills/research-fan-out/SKILL.md` — canonical skill body, follow the 10-section spec in §"Fix/Feature 1" of the brief.
2. **NEW** `~/baker-vault/_ops/skills/research-fan-out/checklist.md` — 12-step copy-paste walkthrough per §"Fix/Feature 2".
3. **EDIT** `~/baker-vault/_ops/agents/researcher/method.md` — add §10 fan-out pointer per §"Fix/Feature 3" of the brief.
4. **EDIT** `~/baker-vault/_ops/skills/INDEX.md` — add row per §"Fix/Feature 4".
5. **RUN** `bash ~/baker-vault/_install/sync_skills.sh --dry-run` then `bash ~/baker-vault/_install/sync_skills.sh` — symlink auto-created at `~/.claude/skills/research-fan-out`. Do NOT hand-create the symlink (the script has data-loss safety).

## Do NOT touch

- `orchestrator/research_executor.py` (baker-master) — server-side dossier engine (ART-1 Batch 2), different pattern. Brief is markdown-only in baker-vault.
- `~/bm-researcher/CLAUDE.md` — picker template. The new skill is referenced via `method.md §10`, not via CLAUDE.md.
- Existing Researcher skills (`grok-via-xai-api`, `local-research-via-gemma`, `x-twitter`, `youtube-analyze`, `anthropic-feature-scout`, `researcher-verify-citations`, `pin-protocol`, `whatsapp-send-via-waha`, register skills) — REFERENCED, NOT modified.
- baker-master codebase — no Python, no DB, no migrations.
- `_ops/agents/researcher/research-types.md` — no changes; fan-out skill READS it.

## Quality checkpoints (full list in brief §"Quality Checkpoints" — 16 items)

Headline tests:
- 10 numbered sections present in SKILL.md body.
- 12 steps present in checklist.md.
- Mnilax quote VERBATIM from `/Users/dimitry/.claude/CLAUDE.md` line 40: "Surface conflicts, don't average them." (Plus the operational expansion.)
- NO mention of Gemma as synthesizer (bus #1369 compliance).
- NO mention of Sonnet anywhere as synthesizer option.
- YouTube channel explicitly = transcript fetch only (bus #1374).
- Router uses 10 research-type names from `research-types.md` VERBATIM (not made-up names — that was the codex M1 fold).
- `sync_skills.sh --dry-run` clean; `sync_skills.sh` creates symlink.

## After ship

- Mailbox to mark COMPLETE on push.
- Bus-post `ship/researcher-fanout-skill-1` from `b3` to `deputy` with: commit SHA, files changed, sync_skills.sh output, Read-test on the symlink-target showing the canonical content.
- Deputy (AH2) runs Gates 1+3+4 (Gate 2 skipped per markdown-only).
- Lead OR cowork-ah1 runs Gate 5 merge.

## Anchors (for your context)

- Brief commit: baker-vault `aca31a0` (v2 canonical).
- Codex pre-review: bus #1394 (PASS-WITH-NOTES + conditional ship; all 4 findings folded into v2).
- Director ratifications: bus #1365, #1369, #1374 + AH2 chat 2026-05-30.
- Authorship override: AH2-authored (Director Q-1 closure per same chat).
- Precedent: BRIEF_HARNESS_SETUP_SKILL_1 (b4 shipped 2026-05-29) — same shape, same lane, same codex pre-review pattern.

— deputy (AH2), 2026-05-30
