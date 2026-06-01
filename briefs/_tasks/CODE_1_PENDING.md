---
dispatch: EXECUTIVE_MEMO_AUTHORING_SKILL_TREE_1
to: b1
from: lead
dispatched_by: lead
dispatched_at: 2026-06-01
status: COMPLETE
merged_anchor: baker-vault main 382ee0e (G1 PASS — evals 59/59 exit0, 8 skills resolve, single-source clean, all 8 ACs)
repo: baker-vault (NOT baker-master) — work in ~/baker-vault, push to baker-vault main
canonical_brief: ~/baker-vault/_ops/briefs/BRIEF_EXECUTIVE_MEMO_AUTHORING_SKILL_TREE_1.md (commit b73c384)
codex_status: PASS-WITH-NITS (v3.1) — dispatch-ready
gate_owner: lead (G1 = sync_skills.sh dry-run clean + trigger evals green)
ship_target: bus topic ship/executive-memo-authoring-skill-tree-1 -> lead
---

# DISPATCH — build the executive-memo-authoring skill tree (b1)

**This is a baker-VAULT build, not baker-master.** All paths are under `~/baker-vault/_ops/`.
Do your work there; commit + push to baker-vault `main` (writer-contract allows B-codes to push `_ops/`).

## Read first
The full, Codex-passed brief is canonical — build exactly to it:
`~/baker-vault/_ops/briefs/BRIEF_EXECUTIVE_MEMO_AUTHORING_SKILL_TREE_1.md` (commit `b73c384`).

Also read its source spec + handoff (referenced in the brief frontmatter). **Do NOT re-derive the design — it is Director-ratified.** You are codifying a fixed design.

## Scope (summary — brief is the source of truth)
1. Build orchestrator `executive-memo-authoring` + 6 net-new step-skills (Fixes 1–2).
2. Wire 3 template gaps (Fix 3); install the already-drafted `memo-body-loops` AS-IS (Fix 4).
3. Promote the SOP overview from the Dropbox-inbox path (Fix 5; fallback = reconstruct from spec).
4. Register via `_ops/skills/INDEX.md` rows + `_install/sync_skills.sh` — **NOT** manual symlinks / manifest (Fix 6).
5. Add trigger eval cases to `_ops/evals/skills/test-cases.yml`.

## Hard constraints
- **Single-source rule:** reference sub-skills BY NAME; never paste a callee's body. The brief's Verification §3b asserts this — it must pass.
- Run the brief's Verification block verbatim; it is fail-loud (`set -euo pipefail`). All checks green before ship.
- Each new SKILL.md needs a `MANDATORY TRIGGERS:` line.
- Do NOT touch any existing sub-skill SKILL.md, the step-1 triaga template, the `memo-body-loops` draft body, or `tasks/lessons.md`.

## Done = (per brief Harness V2 block)
`Authored → Registered (INDEX.md) → Synced (sync_skills.sh clean) → Evals-green → all 8 ACs met`.
Ship is NOT done at "files written." Run the verification block; paste its `ALL VERIFY CHECKS PASSED` line in your ship report.

## Ship
Bus-post to `lead`, topic `ship/executive-memo-authoring-skill-tree-1`, with: commit SHA, verification output, and any nit. Lead gates G1.
