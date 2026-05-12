---
status: PENDING
brief: briefs/BRIEF_HARNESS_SUBAGENT_MIGRATION_1.md
trigger_class: TIER_B_HARNESS_OPTIMIZATION
dispatched_at: 2026-05-12
dispatched_by: aihead1
estimated_effort: 2-3h
supersedes: TIER_B_MODEL_DEPRECATION_SWEEP (COMPLETE, PR #192 merged 31454dc)
---

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
