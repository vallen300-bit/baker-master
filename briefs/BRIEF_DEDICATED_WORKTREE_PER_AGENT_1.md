# BRIEF: DEDICATED_WORKTREE_PER_AGENT_1 — eliminate baker-vault shared-FS race via per-agent worktrees

**Owner:** AI Head A (Director-ratified 2026-05-01 09:42Z)
**Author:** AI Head A
**Drafted:** 2026-05-01
**Priority:** HIGH (chronic productivity drag — 4 incidents in 2 days, escalating)
**Roadmap item:** `dedicated-worktree-per-agent` (V4 queued, NEW)

## Context

Cortex tonight (Session 8) shipped Heavy 8/8 + Light 13/13 matter knowledge + Briefs 3+4. Five Wave dispatches ran 2-4 agents in parallel against `~/baker-vault`. Result: **4 shared-filesystem race incidents in 48 hours** (memory file `feedback_baker_vault_shared_fs_race_2nd_incident.md`). Atomic single-shell-command stopgap works at 1-2 concurrent agents, breaks at 3+ when HEAD bounces between interleaved checkouts. Cost is now ~30-60 min/day pure recovery overhead and growing with parallelism. Structural fix required.

## Estimated time: ~30 minutes
## Complexity: Low (shell + markdown only; no production code; no DB writes)
## Prerequisites:
- Director's machine has `git` 2.5+ (worktree command)
- `~/baker-vault` clone exists with origin pointing at `github.com/vallen300-bit/baker-vault`
- All in-flight feature branches on `~/baker-vault` are pushed before migration begins (verify with `cd ~/baker-vault && git status` — no uncommitted work)

## Step 1 EXPLORE results (already done by AI Head A)

- Verified `~/bm-vault-*` paths do NOT exist (`ls ~/bm-vault-* → no matches found`).
- `~/baker-vault` worktree currently checked out on `b1/wave5-lilienmatt-aukera-20260501` — confirms the race is happening live (AI Head A's lane contaminated by B1's branch).
- `~/Desktop/baker-code/00_WORKTREES.md` exists and documents baker-code worktree map (B1/B2/B3/B4 at `~/bm-b1`, etc.) — no baker-vault map yet. This brief extends that doc.
- `~/Desktop/baker-code/scripts/` exists with 20+ Python scripts (canonical script location). New shell script fits convention.
- `~/baker-vault/scripts/` does NOT exist; not the canonical location.
- Lessons.md grep: no prior worktree-related lesson; precedent for `/write-brief` mandatory rule (Lesson on AMEX_RECURRING_DEADLINE inline-drafting) — this brief follows SOP.

## Background

Multi-agent commits to `~/baker-vault` (single shared working tree) cause file-set collisions when 2+ agents work concurrently. **4 incidents in 48 hours:**

| # | Date | Agents involved | Recovery cost |
|---|---|---|---|
| 1 | 2026-04-29 | AI Head A vs B2 | Branch extraction |
| 2 | 2026-04-30 | AI Head 2 App vs B2 | Reflog recovery (b2-recovery branch + PR #34) |
| 3 | 2026-04-30 | AI Head 2 App vs B3 (using B1 lane name) | Cherry-pick + reset |
| 4 | 2026-05-01 | B3 vs B2 | Force-push to remote ref |

Atomic single-shell-command pattern (`git checkout -b X && git add <specific> && git commit && git push`) was the documented stopgap (`memory/feedback_baker_vault_shared_fs_race_2nd_incident.md`). It works at 1-2 concurrent agents but breaks at 3+ — HEAD bouncing during interleaved checkouts is the failure mode, even with atomic invocation.

**Real cost per incident:** ~5-15 min recovery + cognitive overhead surfacing the race + memory/protocol updates. At 2/day cadence: ~30-60 min/day pure overhead. Will grow with more parallel agents (Wave 5 was 4 lanes; future waves likely 5-6).

## Goal

Eliminate shared-FS race structurally. Each agent owns a dedicated git worktree of `baker-vault`; HEAD changes in one worktree do not affect others. Same `.git` directory backs all worktrees → fetch/push coordinate cleanly via remote.

## Specification

### Worktree map (canonical)

| Agent | Worktree path | Default branch | Purpose |
|---|---|---|---|
| AI Head A | `~/baker-vault` | main | orchestration / merges / canonical reads |
| AI Head 2 App | `~/bm-vault-aihead2` | scratch-aihead2 | curation + alignment dispatches |
| B1 | `~/bm-vault-b1` | scratch-b1 | curation + reviews |
| B2 | `~/bm-vault-b2` | scratch-b2 | curation + reviews |
| B3 | `~/bm-vault-b3` | scratch-b3 | curation + reviews |
| B4 | `~/bm-vault-b4` | scratch-b4 | infra builds + curation |

Pattern parallels existing `~/bm-<agent>` worktrees of baker-code (per `Desktop/baker-code/00_WORKTREES.md`).

### Scratch-branch convention

Each agent's "default branch" (e.g. `scratch-aihead2`) is a permanent branch existing only to back the worktree. Agents NEVER push from this branch. Workflow:

1. Sync from main: `git fetch origin main`
2. Checkout work branch FROM main: `git checkout -b <agent>/<task>-<date> origin/main` (clean base, NOT the scratch branch)
3. Write + commit + push the work branch
4. Return to scratch branch when done: `git checkout scratch-<agent>` (idle state; doesn't affect other worktrees)

The scratch branch is the parking place between dispatches; it's never the working branch. This avoids accidental scratch-branch pollution.

### Lockdown rule

Each agent's dispatch paste-block MUST start with `cd ~/bm-vault-<agent>` — never `cd ~/baker-vault`. AI Head A's `~/baker-vault` lane is reserved for orchestration writes (OPERATING.md, ARCHIVE.md, V4 YAML, atomic close commits) — never agent dispatches.

### Migration plan

- One-shot setup script `scripts/setup_agent_worktrees.sh` (provided in this brief; runs once on Director's machine):
  ```bash
  #!/bin/bash
  set -euo pipefail
  cd ~/baker-vault
  git fetch origin main
  for agent in aihead2 b1 b2 b3 b4; do
    branch="scratch-$agent"
    path="$HOME/bm-vault-$agent"
    if [ -d "$path" ]; then
      echo "skip: $path exists"
      continue
    fi
    git branch "$branch" origin/main 2>/dev/null || true
    git worktree add "$path" "$branch"
    echo "added: $path on $branch"
  done
  git worktree list
  ```
- Dispatch paste-block templates in OPERATING.md updated to use `~/bm-vault-<agent>` path.
- Existing in-flight feature branches (none at brief time — Wave 5 lanes 2/3 are still open but on b1/b2 branches not affected by worktree path) continue normally.

## Implementation steps (B-code lane)

1. **Create script** `scripts/setup_agent_worktrees.sh` per spec above. `chmod +x`.
2. **Run script** locally on Director's machine — creates 5 dedicated worktrees + 5 scratch branches. Verify with `git worktree list`.
3. **Update `Desktop/baker-code/00_WORKTREES.md`** — add baker-vault worktree map alongside existing baker-code map. Single source of truth for both repos.
4. **Update OPERATING.md** at `~/baker-vault/_ops/agents/ai-head/OPERATING.md` — add "Worktree discipline" section under Standing rules, referencing `~/bm-vault-<agent>` per-agent paths.
5. **Update curation pattern brief** at `briefs/BRIEF_MATTER_KNOWLEDGE_CURATION_PATTERN_1.md` — replace atomic-shell-pattern reference with new `cd ~/bm-vault-<agent>` pattern.
6. **Communicate to agents** — AI Head A surfaces a one-time paste-block to each B-code: "next dispatch onward, your lane is `~/bm-vault-<agent>`; do NOT cd to `~/baker-vault`."

## Verification

- `git worktree list` shows 6 worktrees (1 main + 5 agent).
- Each agent's working tree has correct scratch branch checked out.
- After 1 wave of agent dispatches in new worktrees: zero shared-FS race incidents (vs 4-incident baseline).
- 2-day window post-deploy with at-least-1-multi-agent-wave: race-free verified, brief closes.

## Done definition

- Setup script written, run, verified
- 5 dedicated worktrees live
- OPERATING.md + 00_WORKTREES.md + curation brief updated to reflect new paths
- One-shot communication paste-blocks sent to each B-code
- 1 multi-agent wave run successfully without incident
- Memory file `feedback_baker_vault_shared_fs_race_2nd_incident.md` annotated with closure note (incidents stopped at #4; structural fix landed)

## Out of scope (parked for follow-up)

- Same pattern for `~/Desktop/baker-code` (baker-master worktree) — that one already has dedicated worktrees per `Desktop/baker-code/00_WORKTREES.md`; this brief only addresses baker-vault.
- Automated worktree pruning / sync hygiene (manual verification sufficient at 5 worktrees).
- CI enforcement of "no `cd ~/baker-vault` in B-code paste-blocks" — manual discipline + AI Head A reviews suffice for V1.

## Files Modified

- `~/Desktop/baker-code/scripts/setup_agent_worktrees.sh` — NEW shell script per spec above
- `~/Desktop/baker-code/00_WORKTREES.md` — ADD baker-vault worktree map under existing baker-code map (single source of truth for both repos)
- `~/baker-vault/_ops/agents/ai-head/OPERATING.md` — ADD "Worktree discipline" section under Standing rules; reference per-agent paths
- `~/Desktop/baker-code/briefs/BRIEF_MATTER_KNOWLEDGE_CURATION_PATTERN_1.md` — UPDATE atomic-shell pattern reference to new `cd ~/bm-vault-<agent>` workflow

## Do NOT Touch

- `~/baker-vault/.git/` — shared backing repo; worktree command manages this. No manual `.git/` edits.
- Existing `~/bm-b{1,2,3,4}` baker-code worktrees — unrelated repo (baker-master); already working with their own worktree system.
- `~/Desktop/baker-code/scripts/` Python files — none touched.
- Any in-flight branches on `~/baker-vault` (B1 lane: `b1/wave5-lilienmatt-aukera-20260501` is live; let it land cleanly before migration).
- Render env vars / production deployment — this is local-only dev infra.
- `wiki/matters/<slug>/curated/*.md` content — curation work continues normally; only the dispatch path changes.

## Quality Checkpoints

1. **Worktrees listed:** `cd ~/baker-vault && git worktree list` shows 6 entries (1 main + 5 agent paths).
2. **Each agent path navigable:** `cd ~/bm-vault-aihead2 && git status` reports clean working tree on `scratch-aihead2`. Repeat for b1/b2/b3/b4.
3. **Shared `.git`:** `git config --get core.worktree` empty in main repo; worktree paths use `.git` link file (verify `ls -la ~/bm-vault-aihead2/.git` shows file, not dir).
4. **Branch isolation works:** in `~/bm-vault-b1`, `git checkout -b test-branch origin/main && echo "x" > /tmp/x && git status` shows `test-branch` checked out — concurrently in `~/bm-vault-b2`, `git status` still shows `scratch-b2` (no HEAD bleed).
5. **OPERATING.md updated:** `grep -n "bm-vault" ~/baker-vault/_ops/agents/ai-head/OPERATING.md` returns the new "Worktree discipline" section.
6. **00_WORKTREES.md updated:** `grep -n "bm-vault" ~/Desktop/baker-code/00_WORKTREES.md` returns the baker-vault map.
7. **Curation brief updated:** `grep -n "bm-vault-<agent>" ~/Desktop/baker-code/briefs/BRIEF_MATTER_KNOWLEDGE_CURATION_PATTERN_1.md` returns the new dispatch path.
8. **No race in next wave:** first multi-agent wave run after deploy has zero shared-FS race incidents (vs 4-incident baseline). Verified via memory file annotation.

## Verification (no SQL needed — bash verification)

```bash
# 1. Worktree count
[ "$(cd ~/baker-vault && git worktree list | wc -l)" -eq 6 ] && echo "PASS: 6 worktrees" || echo "FAIL"

# 2. Each agent path exists + on correct scratch branch
for a in aihead2 b1 b2 b3 b4; do
  branch=$(cd ~/bm-vault-$a 2>/dev/null && git branch --show-current)
  [ "$branch" = "scratch-$a" ] && echo "PASS: $a on scratch-$a" || echo "FAIL: $a got '$branch'"
done

# 3. Shared .git verified (worktree path .git is a file, not dir)
[ -f ~/bm-vault-aihead2/.git ] && echo "PASS: .git is link file" || echo "FAIL"

# 4. Documentation sweep
grep -q "bm-vault" ~/Desktop/baker-code/00_WORKTREES.md && echo "PASS: 00_WORKTREES.md updated"
grep -q "bm-vault" ~/baker-vault/_ops/agents/ai-head/OPERATING.md && echo "PASS: OPERATING.md updated"
grep -q "bm-vault-<agent>" ~/Desktop/baker-code/briefs/BRIEF_MATTER_KNOWLEDGE_CURATION_PATTERN_1.md && echo "PASS: curation brief updated"
```

## Trigger class for review

NOT trigger-class for code-review purposes (no production code paths; no DB writes; pure local dev-environment infra). AI Head A spot-reviews script content + OPERATING.md update; no second-pair-of-eyes required.

## Estimated effort breakdown

~30 minutes total: script write (~5 min) + run + verify (~3 min) + 00_WORKTREES.md edit (~5 min) + OPERATING.md edit (~5 min) + curation brief update (~5 min) + agent communication paste-blocks (~5 min) + verification checkpoints (~3 min).

Single B-code lane; B4 natural assignee (currently bench post-Brief-3 ship). Could also be AI Head A direct execution (Tier A autonomous, dev-infra change) given trivial complexity.
