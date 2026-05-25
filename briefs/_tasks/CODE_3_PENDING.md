---
status: COMPLETE
completed_at: 2026-05-25T15:15:00Z
pr_baker_vault: 114
merge_squash: pending-fill-by-lead
gate5_authority: lead bus #1089 (gate-5 merge done) + #1091 (Director baseline rerun clean — 15/15 PASS exit 0)
ship_bus: deputy #1083 (ship) + lead #1084 (CC) + deputy #1086 (fix-ship after gate-4 request_changes #1085)
baseline_result: 15/15 PASS on starter corpus (5 hot skills × 3 cases); 60 catalog skills uncovered → v2 backlog
hot_fix_landed: dcfecc8 — missing-slug false-OK scorecard bug + 3 README fast-follows
dispatched_at: 2026-05-25T13:10:00Z
dispatched_by: deputy
target: b3
brief: briefs/BRIEF_SKILLS_EVAL_HARNESS_1.md
brief_id: SKILLS_EVAL_HARNESS_1
reply_target: deputy (AH2) — cc lead
expected_time: ~4-6h
complexity: Medium
director_ratified: 2026-05-25 (chat — Q3=A static trigger-keyword eval v1 only; full LLM behavioral eval deferred to v2)
depends_on: SOPS_TO_SKILLS_MIGRATION_1 (now COMPLETE end-to-end; skill corpus this harness measures is live)
companion_to: SOPS_TO_SKILLS_MIGRATION_1
pre_dispatch_gates:
  architect: feature-dev:code-architect (prior session) — issues addressed in-file before authoring
  code_reviewer: feature-dev:code-reviewer (prior session) — issues addressed in-file before authoring
  lead_second_pair: AH1 bus #1029 — APPROVE both briefs with 3 polish items (all incorporated in baker-vault commit ae2e8ca BEFORE this dispatch)
target_repo: baker-vault (Python + YAML + markdown only — stdlib Python; no baker-master changes)
gate_chain_expected:
  gate_1_architecture: deputy — verify harness reads SKILL.md frontmatter correctly + corpus YAML/JSON format is sane
  gate_2_security: deputy — light pass (read-only static analysis; no shell-out, no network, no LLM call)
  gate_3_picker_architect: SKIP per brief (no install/picker change)
  gate_4_code_reviewer: deputy — verify per-skill PASS/FAIL match logic + report format clear + corpus coverage
  gate_5_merge: lead — merges baker-vault commit + runs first baseline report, observes pass/fail rates across the 5 hot skills × 2-3 cases starter corpus
notes_to_b3:
  - Companion to the migration brief just completed. Skill corpus to test against is now live (20 new entries + ~35 pre-existing in `~/baker-vault/_ops/skills/`).
  - Scope: STATIC trigger-keyword match only for v1. No LLM call, no token cost, runs in seconds. Director-ratified Q3=A in chat 2026-05-25.
  - Starter corpus: 5 hot skills × 2-3 cases each. Hot-skill selection lives in the brief — read the brief before authoring corpus.
  - Stdlib Python only — no dependencies. Reads SKILL.md MANDATORY TRIGGERS keywords + matches against YAML/JSON test corpus + reports per-skill PASS/FAIL.
  - Anchor philosophy: thevccorner.com Substack "Prompts Are Dead. Skills Are the New Moat" (Dec 2025): "Evals are the new gross margin." v1 cheapest-possible.
---

# Dispatch: SKILLS_EVAL_HARNESS_1 → b3

B3 — pick up briefs/BRIEF_SKILLS_EVAL_HARNESS_1.md (canonical mirror at ~/baker-vault/_ops/briefs/BRIEF_SKILLS_EVAL_HARNESS_1.md, committed earlier today).

Build the v1 static trigger-keyword eval harness for the Baker skill catalog. Stdlib Python only. Reads each _ops/skills/<slug>/SKILL.md frontmatter MANDATORY TRIGGERS keywords + matches against YAML/JSON corpus of test prompts + emits per-skill PASS/FAIL report. Starter corpus: 5 hot skills × 2-3 cases.

Companion to the migration brief that completed end-to-end this session — the 55+ skill corpus this harness measures is now live across the picker.

After ship, bus-post ship/skills-eval-harness-1 to deputy (AH2) with PR # + sample baseline-report output + per-skill PASS/FAIL counts on the starter corpus. Deputy runs gates 1+2+4 then hands to lead for Gate-5 merge + first baseline-report run. CC lead on the ship report.

Anchor: deputy bus #1063 (b3 close-out of companion brief, mailbox cleared, standing by for this dispatch).
