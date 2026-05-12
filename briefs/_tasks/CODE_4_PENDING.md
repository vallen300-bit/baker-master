---
status: REQUEST_CHANGES
brief: briefs/BRIEF_HARNESS_SUBAGENT_MIGRATION_1.md
trigger_class: TIER_B_HARNESS_OPTIMIZATION
dispatched_at: 2026-05-12
dispatched_by: aihead1
estimated_effort: 2-3h
supersedes: TIER_B_MODEL_DEPRECATION_SWEEP (COMPLETE, PR #192 merged 31454dc)
update_at: 2026-05-12
update_reason: PR #194 gate chain returned 1 CRITICAL + 2 HIGH + 1 MEDIUM (see PR comment 4435153131 + UPDATE block below)
---

## UPDATE — 2026-05-12 — REQUEST_CHANGES on PR #194

Picker-architect (1 issue @ ≥80) + `feature-dev:code-reviewer` 2nd-pass converged. Fast-follow commit on `b4/harness-subagent-migration` required. **Do NOT open a new PR.**

### CRITICAL — Acceptance #9 not satisfied pre-merge

Brief's hard ship gate: invoke `Agent(subagent_type="feature-dev:code-reviewer")` from **all 6 pickers** post-step-6, BEFORE declaring ship. PR description verifies only `bm-b4` and defers the remaining 5 to post-merge — direct breach of the pre-mortem mitigation criterion.

**Fix:** invoke `feature-dev:code-reviewer` from each of `bm-aihead1`, `bm-aihead2`, `bm-b1`, `bm-b2`, `bm-b3`. Paste explicit per-picker pass/fail into PR description. If ANY fails → revert step 6 (restore picker `.claude/agents/` directories) BEFORE re-requesting review.

### HIGH — `.githooks/pre-commit` header/behavior mismatch (picker-architect 85-score confirmed)

L1-11 header says "enforce migration immutability" + documents two bypass paths (`Migration-edit-authorized:` trailer, `BAKER_MIGRATION_EDIT_AUTHORIZED=1`). New `.claude/agents/*.md` check at L18-26 has no bypass and runs BEFORE `exec "$CHECK"`. Developer reading header assumes bypasses apply, gets blocked, falls back to `--no-verify` — bypasses both.

**Fix:** Add subheader before L18: `# Part 2: subagent location enforcement (NO BYPASS — add to ~/.claude/agents/, not picker)`. Add explicit line in file header stating existing migration-edit bypasses do NOT cover this check.

### HIGH — `--diff-filter=A` misses renames

`git mv some-file.md .claude/agents/foo.md` uses filter `R`, slipping past. Combined with `.gitignore` removal or `git add -f`, rename evades.

**Fix:** Change to `--diff-filter=ACRD` or drop the filter and grep the diff output for the path pattern.

### MEDIUM — `CLAUDE.md` L293 stale pointer

Current `- **Specialized agents:** .claude/agents/` references a deleted directory.

**Fix:** Update to `- **Specialized agents:** ~/.claude/agents/ (user-global — not in repo per HARNESS_SUBAGENT_MIGRATION_1)`.

### NEW — Step 9 SCOPE AMENDMENT (Director-ratified 2026-05-13)

Fold a Part 3 into the same `.githooks/pre-commit` hook (no new file): reject staged content containing `claude-opus-4-20250514` or `claude-sonnet-4-20250514`. Exclusions: `briefs/`, `tasks/lessons.md`, `docs-site/`.

**Why ride this PR rather than separate:** the hook surface is already being modified in PR #194, single review cycle covers both, and this hardens what MODEL_DEPRECATION_SWEEP_1 manually fixed yesterday (commit `31454dc`).

**Full spec + implementation pattern:** see brief §"Step 9" + acceptance criterion #13. Brief updated in same commit as this mailbox UPDATE.

**Header convention (matches Step 8 / Part 2 design):** subheader `# Part 3: retired Anthropic model ID enforcement (NO BYPASS — use claude-opus-4-6/4-7 or claude-sonnet-4-5/4-6)`. File header must clarify existing migration-edit bypasses do NOT cover Part 2 OR Part 3.

**Acceptance criterion #13:** test commit with retired ID in `orchestrator/test_retired_id.py` → expect rejection; test commit with same string in `briefs/test.md` → expect success (then revert both).

### Heartbeat

Per AH1 SKILL.md §B-code stall chase: ~30-45 min fast-follow window. Single heartbeat OK; bus-post `heartbeat/HARNESS_SUBAGENT_MIGRATION_1` if you cross the hour mark before pushing.

### Re-trigger gate chain

After fast-follow commit + push, bus-post `ship/HARNESS_SUBAGENT_MIGRATION_1-v0-2` to `lead`. AH1 re-runs:
1. Static review of fast-follow diff
2. `/security-review` inline
3. `feature-dev:code-reviewer` 2nd-pass on new head SHA

Merge gates clear ALL or revert.

### Anchors

- PR comment: https://github.com/vallen300-bit/baker-master/pull/194#issuecomment-4435153131
- Picker-architect comment: https://github.com/vallen300-bit/baker-master/pull/194#issuecomment-4435130106
- Brief: `briefs/BRIEF_HARNESS_SUBAGENT_MIGRATION_1.md` @ `d1a514c`

# CODE_4 — HARNESS_SUBAGENT_MIGRATION_1 — 2026-05-12

## Wake summary

Collapse Brisen subagent definitions to user-global `~/.claude/agents/`. Delete picker `.claude/agents/` directories across all 6 pickers. Add drift-prevention guardrails (gitignore + pre-commit hook).

## Where to read the brief

**Authoritative spec:** `briefs/BRIEF_HARNESS_SUBAGENT_MIGRATION_1.md` on `main` @ `d1a514c`. Read it fully before starting — it's the source of truth for all 8 steps, acceptance criteria, abort gates, and risk-mitigation tests. This mailbox file is the WAKE only; the brief itself is the contract.

## Hard gates before starting

1. Pull latest main in your working clone (`git -C ~/bm-b4 pull --ff-only origin main`)
2. Verify the brief file exists and is the `d1a514c` version (frontmatter says `Status: DRAFT (pending Director ratify)` — that's stale; Director ratified 2026-05-12, you may flip it to RATIFIED in your PR)
3. Confirm orientation: read brief §"Two-pass review trail" so you understand WHY the simplified plan is what it is

## 8 steps (per brief §"Scope")

1. **Backup user-global** (NON-REVERSIBLE without this) — `cp -r ~/.claude/agents ~/.claude/agents.bak-2026-05-12`. Verify before any further step.
2. **Reconcile 12 forked pairs** WITH the wrong-direction abort gate. All 12 diffs captured in PR description.
3. **Fix `baker-pm.md` hardcoded path** at lines 242 + 269. Choose option A (path replace to bm-aihead1) if `~/bm-aihead1/.claude/agent-memory/baker-pm/` exists; option B (strip block) if absent.
4. **Migrate 10 picker-only** to user-global.
5. **Invocation-matrix audit** — `find ~/.claude/projects -name "*.jsonl" -mtime -30 | xargs grep -h '"subagent_type":' | grep -oE '"subagent_type":"[^"]+"' | sort -u`. Confirm every type either lives in `~/.claude/agents/` (after steps 2+4) OR is plugin-namespaced/built-in (out of scope).
6. **Delete `.claude/agents/`** across all 6 pickers — atomic with step 4 in a single git operation per picker.
7. **`.gitignore` `.claude/agents/`** in each picker.
8. **Pre-commit hook** rejecting `.claude/agents/*.md` additions.

## Acceptance criteria (12 — see brief §"Acceptance criteria")

All 12 must PASS. Two are AH1's pre-mortem mitigations and are HARD GATES:

- **#9 (plugin subagent path-resolution):** invoke `Agent(subagent_type="feature-dev:code-reviewer")` from all 6 pickers post-merge. ALL 6 must succeed. If ANY fails → revert step 6 deletion before declaring ship.
- **#11 (wrong-direction overwrite audit):** PR description must show all 12 forked-pair diffs explicitly with overwrite-direction annotation. No silent overwrites.

## Ship gate

Per brief §"Ship gate":
- Literal pytest green output pasted in ship report (if any test touches subagent registry — likely none)
- All 12 acceptance criteria PASS — paste explicit output per criterion
- All 6 fresh-session smoke tests succeed
- Backup directory `~/.claude/agents.bak-2026-05-12/` confirmed present with 12 files
- Commit message: `feat(harness): collapse subagents to user-global (HARNESS_SUBAGENT_MIGRATION_1)`
- PR title: same
- Bus-post `ship/HARNESS_SUBAGENT_MIGRATION_1` to lead on PR open

## Heartbeat cadence

Per AH1 SKILL.md §B-code stall chase: minimum every 12h while building. Brief is 2-3h scope; expect 1-2 heartbeats total. First heartbeat: after step 1 backup confirmation.

## Bus-post on ship

Per `_ops/processes/agent-bus-posting-contract.md` (ratified 2026-05-11): post `ship/HARNESS_SUBAGENT_MIGRATION_1` to `lead` bus topic with PR# + commit anchor when PR is open.

## Anchors

- Director ratified dispatch to B4 2026-05-12
- Brief draft commit: `5b99afb`
- Brief mitigations folded: `d1a514c`
- Prior B4 dispatch (MODEL_DEPRECATION_SWEEP_1) shipped clean — PR #192 merged 31454dc; mailbox flipped COMPLETE 2a9380d
