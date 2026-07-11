# VAULT_WRITER_WORKTREE_ISOLATION_1

**Dispatched_by:** lead (AH1) · 2026-07-11
**Repo:** baker-vault (rule doc + hook) — PR to vault main
**Task class:** small guard/process · **Harness-V2:** Context Contract below; gate = codex G3 medium
**Priority:** high — 5th shared-checkout race would hit Director-ratified content again

## Context
Shared `~/baker-vault` is one physical checkout used by many concurrent agents (desks, b-codes, lead). Context Contract: this brief is self-contained; only inputs are the incident anchors below + the two files to touch. Task class: guard/process (non-app code). Done-state: hook live on shared checkout + rule doc merged.

## Problem (evidence)
Shared `~/baker-vault` checkout gets branch-switched mid-work by concurrent agents. 4 collisions in one week; latest (2026-07-11, deputy #8925): two BRI-GRP-001 commits incl. Director-ratified roster ratifications (d8d14a0, b5736fc) stranded on b2's `arm-cage-scripts` branch — would have evaporated at post-merge branch cleanup. Lead rescued to main @89d7013 via isolated worktree. Prior incidents: 2026-07-10 §A "4 shared-vault index races in one day" incl. 1 ungated-code leak reverted @fbfa20e; 2026-07-09 stash incident (ARM spec swept into stash@{0}).

## Rule to codify (already lead practice, now fleet-wide)
Any agent writing to baker-vault MUST either (a) work in an isolated `git worktree` / clone (never the shared `~/baker-vault` checkout), or (b) hand lead the patch. Never switch branches on the shared checkout.

## Deliverables
1. `_ops/processes/vault-writer-worktree-isolation.md` — rule + rescue procedure (worktree add from origin/main → cherry-pick/apply → push → remove+prune) + foot-guns section anchored to the 3 incidents above.
2. Enforcement hook: baker-vault repo pre-commit (`.githooks/`) that REJECTS a commit when `git rev-parse --show-toplevel` == `/Users/dimitry/baker-vault` AND `BAKER_ROLE` != `lead` — error message points at the rule doc. Lead exemption temporary until lead lanes migrate too (lead already worktree-only by memory rule; exemption avoids blocking rescue ops).
3. Propagation: one-paragraph pointer added to `_ops/processes/INDEX.md`; bus broadcast to all vault-writing agents after merge.

## Files to touch
- `_ops/processes/vault-writer-worktree-isolation.md` (new, vault repo)
- `_ops/processes/INDEX.md` (pointer line)
- `.githooks/pre-commit` (vault repo — add guard; create dir if absent)

## Verification
Live exercise on this machine (not "by inspection"): run AC1-AC3 shell probes below and paste outputs in the ship report.

## Quality Checkpoints / Acceptance criteria
- AC1: hook blocks a test commit in shared checkout under `BAKER_ROLE=b2` (exercise live, capture output).
- AC2: hook permits commit in a fresh worktree under any role.
- AC3: hook permits `BAKER_ROLE=lead` in shared checkout (logs a warning).
- AC4: rule doc exists, INDEX.md pointer added, foot-guns cite the 3 anchors.
- AC5: `git config core.hooksPath .githooks` documented as the activation step per checkout; verify it is set on the shared checkout.

## Done rubric
Real defect exercised (AC1 live output pasted in ship report), not "by inspection". Ship report to `briefs/_reports/`, bus-post verdict chain: author → codex G3 (medium) → lead merge → broadcast.
