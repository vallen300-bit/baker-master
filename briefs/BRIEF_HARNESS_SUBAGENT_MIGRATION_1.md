# BRIEF — HARNESS_SUBAGENT_MIGRATION_1

**Status:** DRAFT (pending Director ratify)
**Author:** AH1
**Created:** 2026-05-12
**Tier:** B
**Estimated effort:** 2-3h
**Dispatch target:** TBD at ratify time (B-code mailbox state check first)
**Supersedes / replaces:** none

---

## Why this exists

The Brisen harness keeps subagent definitions in two places: each picker's `~/bm-<picker>/.claude/agents/` (22 files, identical across all 6 pickers) and the user-global `~/.claude/agents/` (12 files). The 12 names appearing in BOTH are forked — same name, different content. Pre-2026-05-12 the picker version wins at runtime (Claude Code precedence). User-global versions are stale.

This creates three problems:
1. **Token waste** at session start — every picker auto-loads the full 22-entry registry, ~2-4K tokens of irrelevant content per session.
2. **Drift surface** — forked-not-duplicated state silently diverges. Today picker is "newer" but no enforcement keeps them so.
3. **Inconsistency with skills** — 2026-05-08 V17 moved domain-specific skills to picker-scoped + global ones to user-global. Subagents were never aligned to that pattern.

The fix: collapse all subagents to user-global `~/.claude/agents/`. Delete picker copies. Add drift-prevention guardrails.

## Two-pass review trail (audit anchor)

This brief is the simplified successor to a prior plan (CLAUDE.md split + subagent redistribution) that didn't survive review. Trail:
1. **Initial proposal** by AH1 (2026-05-12) — paste-block to external Architect. Three pre-brief verification asks.
2. **External Architect** returned NEEDS-REWORK on D1 (@-import was unverified — confirmed static-only), D2 (token-savings math was unmeasured — confirmed off 4-6×), D3 (subagent topology was wrong — confirmed user-global is supported), D5 (split, not bundle), D6 (side-find out of scope).
3. **AH1 ran the three pre-brief probes** (2026-05-12). Results folded into simplified plan.
4. **Local `feature-dev:code-architect` review** of simplified plan: PASS-WITH-NITS. Flagged: 12 "duplicates" not byte-identical; `baker-pm.md` stale path; precedence assumption.
5. **Local `code-architecture-reviewer` review** of simplified plan: Request changes. Flagged: all 12 pairs forked (not duplicates); user-global is not in any repo so `git revert` is insufficient — need pre-overwrite backup; invocation matrix must come from conversation transcripts; drift will recur without `.gitignore` + pre-commit hook; 30-min estimate wrong, real is 2-3h.
6. **This brief** (2026-05-12) folds in all of step 5's findings.

## Measured baseline (verified 2026-05-12 by AH1)

**Picker `.claude/agents/`** — identical across all 6 pickers (sha256 `4159951101ee` for concatenated content). 22 files per picker, 132 files total across the fleet.

**User-global `~/.claude/agents/`** — 12 files.

**The 12 forked pairs** (present in BOTH picker and user-global — content diverges):
```
ai-head.md
baker-asset-mgmt.md
baker-communications.md
baker-deal-analyst.md
baker-it.md
baker-legal.md
baker-marketing.md
baker-people-intel.md
baker-pr-branding.md
baker-research.md
baker-sales.md
claims-analysis.md
```

**The 10 picker-only** (need migration to user-global):
```
baker-pm.md
code-architecture-reviewer.md
investment-proposal-analyst.md
russo-ai.md
russo-at.md
russo-ch.md
russo-cy.md
russo-de.md
russo-fr.md
russo-lu.md
```

**Stale path in baker-pm.md** (verified at file:line):
- `~/bm-aihead1/.claude/agents/baker-pm.md:242` — `/Users/dimitry/Desktop/baker-code/.claude/agent-memory/baker-pm/`
- `~/bm-aihead1/.claude/agents/baker-pm.md:269` — same path
- Retired pre-2026-05-08 V17 root. Must be updated or stripped before promotion to user-global.

**Invocation matrix (last 30 days of conversation transcripts):**
```
74  feature-dev:code-reviewer       ← plugin, OUT OF SCOPE
61  general-purpose                 ← built-in, OUT OF SCOPE
56  code-architecture-reviewer      ← picker-only, MUST migrate
22  Explore                         ← built-in, OUT OF SCOPE
17  feature-dev:code-architect      ← plugin, OUT OF SCOPE
16  security-code-reviewer          ← plugin/other, OUT OF SCOPE
 6  baker-deal-analyst              ← in both, picker version wins today
 5  baker-research / baker-pr-branding / baker-legal / ai-head
 4  claude-code-guide               ← plugin, OUT OF SCOPE
 3  baker-marketing
 1  baker-sales / baker-people-intel / baker-it / baker-communications / Plan
 0  russo-* (all 7) / baker-pm / investment-proposal-analyst / claims-analysis
```

Subagents NEVER invoked in 30 days are migrated anyway to preserve optionality; deletion candidates flagged separately, out of scope.

## Scope — 8 steps (atomic single PR)

### Step 1 — Backup user-global (NON-REVERSIBLE WITHOUT THIS)

```bash
cp -r ~/.claude/agents ~/.claude/agents.bak-2026-05-12
```

`~/.claude/agents/` is NOT in any git repo. Without this backup, the overwrite in step 2 is irreversible. Verify backup exists before any further step.

### Step 2 — Reconcile 12 forked pairs (winner = picker version, audited)

For each of the 12 names in the forked-pairs list:

1. Open both files: `~/bm-aihead1/.claude/agents/<name>.md` and `~/.claude/agents/<name>.md`
2. Run `diff -u` to capture divergence
3. **Default decision: picker version wins** (per code-architecture-reviewer finding — picker is the intentional shorter "Triggers: …" style; user-global is older verbose "<example>"-block style)
4. **Wrong-direction abort gate (MANDATORY).** Before overwriting, inspect each diff. ABORT and surface to AH1 — do NOT overwrite — if any of the following apply to a specific pair:
   - User-global file's mtime is more recent than picker file's mtime (`stat -f "%m"` comparison)
   - User-global contains a `description` block, `<example>`, `when_to_use`, or frontmatter field NOT present in picker (suggests user-global has content picker lost)
   - User-global references a tool/skill/integration that picker doesn't (suggests divergent intentional edits)
   - File contents differ in semantically meaningful sections — not just whitespace / formatting / "Triggers" reformulation
   If any pair triggers the abort gate: pause migration, write the diff to a tracking file `briefs/_reports/HARNESS_SUBAGENT_MIGRATION_1_DIFF_AUDIT.md`, surface to AH1 for explicit winner-pick. Do NOT proceed to step 6 deletion until all 12 pairs are explicitly resolved.
5. Copy picker version OVER user-global: `cp ~/bm-aihead1/.claude/agents/<name>.md ~/.claude/agents/<name>.md`
6. Record the diff for every pair in the PR description for audit — even the ones that passed the abort gate. The PR description must show all 12 diffs explicitly. Reviewer's job is to confirm no pair should have aborted.

Exceptions: if any picker file contains a clearly broken/stale element (e.g., `baker-pm.md`-style hardcoded path), flag and pause for AH1 review before overwriting. (`baker-pm.md` itself is handled in step 3.)

### Step 3 — Fix `baker-pm.md` hardcoded path

`baker-pm.md` references `/Users/dimitry/Desktop/baker-code/.claude/agent-memory/baker-pm/` at lines 242 + 269 (verified). That path is the retired pre-2026-05-08 V17 root.

Two options:
- **Option A:** Replace path with `/Users/dimitry/bm-aihead1/.claude/agent-memory/baker-pm/`.
- **Option B:** Strip the persistent-memory block entirely if directory doesn't exist at either path (check first: `ls /Users/dimitry/bm-aihead1/.claude/agent-memory/baker-pm/`).

**B-code call:** pick A if the new path exists with content; pick B if the directory is empty/absent. Document choice in PR.

### Step 4 — Migrate 10 picker-only subagents to user-global

```bash
for name in baker-pm code-architecture-reviewer investment-proposal-analyst \
            russo-ai russo-at russo-ch russo-cy russo-de russo-fr russo-lu; do
  cp ~/bm-aihead1/.claude/agents/${name}.md ~/.claude/agents/${name}.md
done
```

(Use the AH1-fixed `baker-pm.md` from step 3 — do NOT copy the stale one.)

### Step 5 — Invocation-matrix audit (pre-delete gate)

```bash
find ~/.claude/projects -name "*.jsonl" -mtime -30 \
  | xargs grep -h '"subagent_type":' 2>/dev/null \
  | grep -oE '"subagent_type":"[^"]+"' | sort -u
```

For every type listed:
- If type is in `~/.claude/agents/` (after steps 2 + 4): OK
- If type starts with `feature-dev:` / `claude_ai_` / is one of {Explore, Plan, general-purpose, claude-code-guide, security-code-reviewer}: OK (plugin/built-in, not affected by this migration)
- Else: BLOCKER — surface to AH1 before proceeding

### Step 6 — Delete picker `.claude/agents/` across 6 pickers (atomic with steps 2 + 4)

```bash
for picker in bm-aihead1 bm-aihead2 bm-b1 bm-b2 bm-b3 bm-b4; do
  git -C ~/${picker} rm -r .claude/agents/
done
```

Git rm in each picker's clone — these files ARE tracked in the picker repos.

### Step 7 — Add `.claude/agents/` to `.gitignore` in each picker

For each picker repo, append `.claude/agents/` to the picker-clone-specific `.gitignore` (or the project `.gitignore` if picker doesn't have a local one). Prevents re-accumulation.

### Step 8 — Pre-commit hook rejecting `.claude/agents/*.md` additions

Add a hook in `.githooks/` rejecting any commit that introduces `.claude/agents/*.md`. Hook should print clear remediation: "Subagents live at `~/.claude/agents/` (user-global). Add there, not in picker."

Hook installable via `git config core.hooksPath .githooks` (already standard in Brisen repos per CLAUDE.md session-start).

## Acceptance criteria

1. `~/.claude/agents.bak-2026-05-12/` exists and contains 12 files (the original user-global state)
2. `~/.claude/agents/` contains exactly 22 files matching the union of (forked pairs picker-side) + (10 migrated picker-only)
3. `find ~/bm-* -path '*/.claude/agents/*.md'` returns ZERO matches
4. `find ~/bm-* -path '*/.claude/agents/*.md' -not -path '*/.git/*'` ZERO matches (sanity)
5. `grep '.claude/agents/' ~/bm-*/. gitignore` shows the entry in each picker
6. Pre-commit hook blocks: `cd ~/bm-b1 && touch .claude/agents/test.md && git add .claude/agents/test.md && git commit -m test` → rejected with clear message
7. Fresh session open from each of 6 pickers succeeds with the picker's confirmation phrase
8. **Brisen-internal subagent invocation post-delete:** `Agent(subagent_type=baker-legal)` invokes successfully from a B-code picker (test with any trivial prompt)
9. **Plugin subagent invocation post-delete (new — guards against picker-directory existence dependency):** `Agent(subagent_type="feature-dev:code-reviewer")` invokes successfully from each of the 6 pickers (one smoke prompt per picker; "review this empty file" is fine). All 6 must succeed. If ANY fails, the migration is broken — revert step 6 deletion before proceeding to ship.
10. Invocation-matrix audit (step 5) returns no orphaned types
11. **Wrong-direction overwrite audit (new):** PR description contains all 12 forked-pair diffs explicitly. Each diff annotated with "overwrite direction: picker → user-global" + "abort gate: PASS | TRIGGERED-and-resolved". No pair shipped with un-surfaced divergence.
12. PR diff cleanly shows 132 picker file deletions + 10 user-global additions + path-fix in `baker-pm.md` + `.gitignore` entries + pre-commit hook

## Test plan

**Pre-merge:**
1. Run step 5 invocation matrix; confirm coverage
2. After steps 2 + 4, run `ls ~/.claude/agents/ | wc -l` → expect 22
3. After step 6, run `find ~/bm-* -path '*/.claude/agents/*.md' | wc -l` → expect 0
4. Run any existing pytest in baker-master to confirm no subagent-dependent test broke

**Post-merge:**
1. Open fresh AH1 session via picker — confirm orientation phrase
2. Open fresh AH2 session — same
3. Open fresh B1-B4 sessions — same (4 separate verifications)
4. Invoke one Brisen-internal subagent from each picker (smoke test for acceptance #8) — B-code chooses convenient subagent_type per picker context
5. **Invoke `feature-dev:code-reviewer` from each of the 6 pickers** (acceptance #9 — plugin subagent path resolution test). Smoke prompt: "review this empty file" or equivalent. Capture pass/fail per picker in ship report.
6. Try the pre-commit hook block test from criterion 6

## Ship gate

- Backup verified before any destructive step
- All 10 acceptance criteria PASS (literal output pasted in ship report)
- All 6 fresh-session smoke tests succeed
- Commit message: `feat(harness): collapse subagents to user-global (HARNESS_SUBAGENT_MIGRATION_1)`
- PR title: same
- Bus-post `ship/HARNESS_SUBAGENT_MIGRATION_1` to lead on PR open

## Code Brief Standards verification

1. **API version/endpoint:** N/A (no Anthropic API surface change; Claude Code subagent registry is the surface)
2. **Deprecation check date:** 2026-05-12 — no Anthropic-side deprecation involved; Brisen-internal harness change
3. **Fallback note:** N/A — Claude Code falls through to general-purpose if a `subagent_type` is missing entirely (verified by code-architecture-reviewer: hard error, surfaced — acceptable)
4. **Migration-vs-bootstrap DDL:** N/A (no schema)
5. **Singleton pattern `_get_global_instance()`:** N/A
6. **Test plan:** see above
7. **file:line citation verification:** `baker-pm.md:242` + `baker-pm.md:269` verified by AH1 Read tool 2026-05-12; sha256 of all 6 picker `.claude/agents/` content concatenations = `4159951101ee` verified
8. **Post-merge script handoff:** N/A (no script invocation post-merge)
9. **Invocation-path audit (Amendment H):** N/A (not a Pattern-2 capability — no `capability_sets` rows touched)

## Tier classification + gate chain

**Tier B.** Touches harness across all 6 pickers + user-global config. PR triggers:
1. AH1 static review
2. `/security-review` inline or full (judgment call — diff is config/markdown, likely inline)
3. `feature-dev:code-reviewer` 2nd-pass per AH1 SKILL.md §"Code-reviewer 2nd-pass Protocol" trigger 4 (touches MCP tool surfaces / subagent registry, which is harness perimeter)

## Risk + rollback

- **Reversibility:** single `git revert` on the merge restores picker files. User-global overwrite reverses via `rm -rf ~/.claude/agents/ && mv ~/.claude/agents.bak-2026-05-12 ~/.claude/agents/`. Pre-commit hook removable via single commit.
- **Blast radius if step 6 deletes before step 4 lands:** any fresh session in a picker where a still-needed subagent was picker-only would 404 on invoke. Mitigation: steps 4 + 6 ATOMIC in one git operation (single commit per picker).
- **B-code subagent-type runtime behavior on missing registry entry:** verified by code-architecture-reviewer — hard validation error, surfaced (not silent). Blast radius bounded.
- **Plugin subagent path-resolution dependency on picker `.claude/agents/` existing as directory:** UNVERIFIED. Claude Code may use the picker dir for path resolution of plugin-namespaced subagents (`feature-dev:*`, `claude_ai_*`) even though those subagents live elsewhere. AH1 currently averages 100+ plugin-subagent invocations per 30 days (`feature-dev:code-reviewer` × 74, `feature-dev:code-architect` × 17, `security-code-reviewer` × 16). If this dependency exists, the heaviest tools of the agent fleet 404 after step 6. **Mitigation:** acceptance criterion #9 invokes `feature-dev:code-reviewer` from all 6 pickers post-merge as a hard gate. If any picker fails, revert before merge confirmation. Cost: 6 × ~10s = ~1 min added to ship gate.
- **Wrong-direction overwrite for one specific forked pair:** UNVERIFIED. AH1's "picker is always newer" assumption is based on the local code-architecture-reviewer's spot-check, not a complete audit. If user-global is actually the right winner for ONE pair (e.g., recent user-global edit AH1 missed), overwriting regresses that subagent's behavior. **Mitigation:** step 2's wrong-direction abort gate + acceptance criterion #11 require all 12 diffs in PR description with explicit overwrite-direction annotation. Reviewer's job to confirm no pair should have aborted.
- **Cosmetic:** russo-* now visible from B-code pickers. Reviewer flagged this as LOW — accept.

## Out of scope (do NOT touch)

- CLAUDE.md split (dropped 2026-05-12; measured savings too small)
- Plugin-namespaced subagents (`feature-dev:*`, `claude_ai_*`)
- Built-in subagents (Explore, Plan, general-purpose, claude-code-guide, security-code-reviewer)
- Skills under `~/.claude/skills/` or `~/bm-*/.claude/skills/` (separate optimization, already done 2026-05-08 V17)
- Subagents never invoked in 30d (russo-*, baker-pm, investment-proposal-analyst, claims-analysis) — migrate, don't delete. Deletion candidates flagged separately.
- Side-find `~/bm-aihead{1,2}/.claude/role-context/lead.md` missing — separate one-line PR, not bundled here

## Dispatch protocol

When Director ratifies this brief:
1. AH1 verifies B-code mailbox state (per `_ops/processes/b-code-dispatch-coordination.md` §2)
2. AH1 writes `briefs/_tasks/CODE_<N>_PENDING.md` pointing at this BRIEF file
3. AH1 commits + pushes
4. AH1 bus-posts `dispatch/HARNESS_SUBAGENT_MIGRATION_1` to target B-code
5. B-code follows the 8 steps + ships PR
6. AH1 runs gate chain + merges per charter §3

**Recommended dispatch target at ratify time:** B2 (familiar with picker harness from 2026-05-08 V17 skill-scope work) OR B4 (just shipped MODEL_DEPRECATION_SWEEP_1 cleanly, mailbox COMPLETE, fresh context). Both viable; pick at dispatch time based on mailbox state.

## Anchors

- AH1 paste-block to external Architect 2026-05-12 (initial 3-fix proposal)
- External Architect verdict 2026-05-12: NEEDS REWORK (D1-D6)
- AH1 3 pre-brief probes 2026-05-12: confirmed (1) @-import static-only, (2) savings 1.5-2K not 6-10K, (3) user-global subagents supported
- Local `feature-dev:code-architect` verdict 2026-05-12: PASS-WITH-NITS (3 nits folded)
- Local `code-architecture-reviewer` verdict 2026-05-12: Request changes (5 changes folded, including the critical "forked-not-duplicate" finding that reshapes from dedup to migration)
- CLAUDE.md split DROPPED 2026-05-12 — measured savings too small
- Side-find `lead.md` missing — separate one-line PR
