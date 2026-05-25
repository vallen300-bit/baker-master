---
status: PENDING
dispatched_at: 2026-05-25T11:10:00Z
dispatched_by: deputy
target: b3
brief: briefs/BRIEF_SOPS_TO_SKILLS_MIGRATION_1.md
brief_id: SOPS_TO_SKILLS_MIGRATION_1
reply_target: deputy (AH2) — cc lead
expected_time: ~2-3h
complexity: Low
companion_brief: BRIEF_SKILLS_EVAL_HARNESS_1 (separate dispatch after this ship; brief already authored + committed to baker-vault @ ae2e8ca)
director_ratified: 2026-05-25 (chat — Q1=A inline/pointer split at 200 LOC, Q2=B sop|contract|runbook|coordination|template scope, Q3=A static trigger-keyword eval v1)
pre_dispatch_gates:
  architect: feature-dev:code-architect — 4 issues found + addressed in-file (glob loop replaces $(ls | grep); readlink-validate existing symlinks; mv+ln rollback trap on uplift; awk frontmatter-strip on diff verification)
  code_reviewer: feature-dev:code-reviewer — same set, all addressed
  lead_second_pair: AH1 bus #1029 — APPROVE both briefs with 3 polish items (all incorporated in baker-vault commit ae2e8ca BEFORE this dispatch)
target_repos: baker-vault (markdown only) + ~/.claude/skills/ (symlinks)
no_baker_master_changes: this brief does NOT modify baker-master code; b3 commits to baker-vault for the SKILL.md files + scripts, and to ~/.claude/skills/ for the symlinks (symlink wiring is filesystem-only, not git-tracked)
gate_chain_expected:
  gate_1_architecture: deputy — verify the 13 + 7 slug list matches the audit
  gate_2_security: deputy — light pass (markdown + symlinks; scripts must not run as root, must not touch outside the two named directories)
  gate_3_picker_architect: SKIP per brief (no install/picker/harness CHANGE)
  gate_4_code_reviewer: deputy — verify INLINE byte-faithfulness + POINTER no-duplication + symlink targets absolute
  gate_5_merge: lead — merges baker-vault commit + runs the 2 one-shot scripts once each, observes `created=N skipped=M` audit line
notes_to_b3:
  - This brief touches baker-vault + ~/.claude/skills/ ONLY. No baker-master code changes; the b3 PR opens against baker-vault, NOT baker-master.
  - All 6 architect/reviewer findings + 3 lead-flagged polish items already addressed in-file. Brief content is dispatch-ready as-is.
  - Lead's polish recap (still useful for b3 awareness during implementation, not respin):
      (a) Brief Fix 5 INDEX.md update — auto-detects bullet vs table vs categorized; fail loud if structure is ambiguous (do not guess).
      (b) Brief Fix 2 trigger regex strip chars include `*"` — handles `**MANDATORY TRIGGERS:**` bold markdown + `"quoted phrase"` keywords cleanly. Spot-check AC6 explicitly covers plain + bold + quoted patterns.
  - Re-run the Fix 1 audit at brief start — entries may have shifted between brief authoring (2026-05-25 ~10:30Z) and your dispatch pickup. Expected baseline: 13 MISSING + 1 EXISTS. Surface to deputy if delta > ±2.
  - For the 7-slug uplift in Fix 4: re-run the `comm -13` audit at start. If list differs by more than ±2, surface to deputy before proceeding.
---

# Dispatch: SOPS_TO_SKILLS_MIGRATION_1 → b3

B3 — pick up `briefs/BRIEF_SOPS_TO_SKILLS_MIGRATION_1.md` (canonical mirror at `~/baker-vault/_ops/briefs/BRIEF_SOPS_TO_SKILLS_MIGRATION_1.md`, committed @ ae2e8ca).

Mirror 13 `_ops/processes/*-{sop,contract,runbook,coordination,template}.md` docs into `_ops/skills/<slug>/SKILL.md` (8 INLINE inline-body + 5 POINTER body) + uplift 7 home-only skills (`~/.claude/skills/<slug>/`) into vault canonical + symlink home back to vault.

After ship, bus-post `ship/sops-to-skills-migration-1` to **deputy (AH2)** with PR # + audit-script output + 3 spot-check trigger fires + before/after counts. Deputy runs gates 1+2+4 then hands to lead for Gate-5 merge + script execution. CC lead on the ship report.

Anchor: lead bus #1040 GO signal post-PR-#258-merge; deputy bus follow next.
