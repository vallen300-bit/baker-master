---
status: PENDING
brief_id: FLEET_CONTEXT_TRIM_1
to: b1
from: lead
dispatched_by: lead
dispatched_at: 2026-06-10
reply_target: lead (bus)
task_class: maintenance / cross-agent state-file hygiene (docs-only)
gate_plan: G1 self-check (AC table + zero-loss spot-check) -> lead gates PRs -> merge. No G2/G3 (no production code).
Harness-V2: N/A — docs/state-file trim, no production code, no deploy surface
---

# FLEET_CONTEXT_TRIM_1 — propagate AH1's session-start context trim to the rest of the fleet

## Problem

AH1-lead's session-start context load dropped 52% → 8% on 2026-06-10 via a 4-part trim
(Director-ratified, GO'd fleet-wide same day). Every other Director-facing agent still
carries its untrimmed startup files, burning ~30-40k tokens per session each.

## Prior art (Context Contract)

- b4's audit: repo `~/bm-b4`, branch `b4/context-trim-audit-1` @ 37e2581 (pushed). READ FIRST.
- AH1's executed trim (the recipe, proven):
  1. PINNED prune — full file archived to `_ops/agents/aihead1/handover-archive/2026-06/PINNED-archive-2026-06-10-prune.md`, live PINNED rewritten to pointer-style pins ≤15 lines each (176KB → 3KB).
  2. MEMORY.md index trim — stale entries moved to `MEMORY_ARCHIVE.md` in same dir (19.8KB → 7.9KB).
  3. Duplicate Tier-0 read drop — where a SessionStart hook already injects a file, the orientation/CLAUDE.md mandatory read of the same file is deleted (baker-master 4bdb2b5 is the pattern).
  4. Skills archive + sync exclusion — ALREADY DONE fleet-wide (vault PR #129); do NOT redo.

## Scope — target agents (in this order)

aihead2, cowork-ah1, researcher, aid, ben, hag-desk, ao-desk, baden-baden-desk,
brisen-desk, movie-desk, origination-desk, architect.

Per agent, apply recipe steps 1-3 where the surface exists:
- PINNED: `~/baker-vault/_ops/agents/<role>/PINNED.md` (skip if absent or already ≤5KB).
- Auto-memory index: `~/.claude/projects/<role-picker-slug>/memory/MEMORY.md` (skip if absent or already ≤8KB).
- Duplicate reads: diff the role's SessionStart hook injection list vs its orientation.md / picker CLAUDE.md mandatory-read list; delete only EXACT duplicates (same file both injected AND ordered read).

## Hard constraints

- ARCHIVE BEFORE PRUNE — full verbatim copy committed to the role's handover-archive (or `MEMORY_ARCHIVE.md`) in the SAME commit as the prune. Zero content loss.
- Structural trim only — never rewrite, summarize away, or merge another agent's live pin sections; pointer-style condensation only, detail moves to archive.
- Vault writes: ~/baker-vault checkout is on a stale branch with uncommitted state — do NOT commit there. Work in a fresh clone (`/tmp/`), PR to vault main, one PR for the whole pass.
- baker-master-side edits (picker CLAUDE.md duplicate reads): branch + PR, do not push main directly.
- Do not touch b1-b5 / clerk / codex lanes (not Director-facing, no PINNED/laconic load) and do not touch aihead1 (done).

## Acceptance criteria

- AC1: per-agent table — surface, before-KB, after-KB, est. tokens saved/session; agents skipped listed with reason.
- AC2: every prune has its archive copy path in the table; spot-check diff proves zero net content loss (archive + live ⊇ original).
- AC3: vault PR + baker-master PR (if any duplicate-read edits) open and linked in ship report.
- AC4: no edits outside the listed surfaces; `git status` clean in both working clones at ship.

## Done rubric

Done = both PRs open + AC table posted to lead on bus + zero content-loss spot-check shown.
NOT done at "files edited". Ship report via bus to lead; plain technical prose, no laconic register tokens.
