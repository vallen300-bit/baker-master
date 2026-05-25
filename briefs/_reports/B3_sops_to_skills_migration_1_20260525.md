---
report_id: B3_sops_to_skills_migration_1_20260525
brief_id: SOPS_TO_SKILLS_MIGRATION_1
target: b3
status: SHIPPED — awaiting deputy gates (1+2+4) + lead Gate-5 (merge + 2 scripts run on Director machine)
shipped_at: 2026-05-25T11:50:00Z
pr_baker_vault: 113
branch_baker_vault: b3/sops-to-skills-migration-1
target_repo: vallen300-bit/baker-vault (markdown + scripts only; NO baker-master changes)
companion_brief_queued: BRIEF_SKILLS_EVAL_HARNESS_1 (separate dispatch after this ship; brief already authored + committed @ ae2e8ca)
bus_posts:
  - deputy #1051 ship/sops-to-skills-migration-1
  - lead #1052 ship-cc/sops-to-skills-migration-1
  - (prior) deputy #1046 blocker/sops-to-skills-migration-1 (resolved by AH2 commit 3c5be9b)
---

# B3 — SOPS_TO_SKILLS_MIGRATION_1 ship report — 2026-05-25

## Bottom line

Baker-vault PR #113 open. 16 files, +1264/-0. 13 SKILL.md mirrors (8 INLINE byte-faithful + 5 POINTER) + `_ops/skills/INDEX.md` extended with 20 new entries + 2 idempotent one-shot scripts in `_ops/scripts/`. Frontmatter validation 13/13. INLINE diff vs source = 0 lines for all 8. POINTER LOC ratio ≤15% (target <25%) for all 5. Surfaced blocker bus #1046 (2 source files untracked) resolved by AH2 commit `3c5be9b`. Gate-3 SKIP per brief; deputy gates 1+2+4 pending; lead Gate-5 merges + runs the 2 scripts on Director's machine.

## Scope shipped

### Fix 2 — 13 SKILL.md mirrors (`~/baker-vault/_ops/skills/<slug>/SKILL.md`)

**8 INLINE (<200 LOC source, body byte-faithful to source process doc):**
- `b-code-dispatch-coordination` (136 LOC source)
- `claude-settings-forge-collision-runbook` (63 LOC)
- `cortex-config-template` (191 LOC)
- `desk-gmail-reach` (116 LOC)
- `important-document` (162 LOC)
- `v2-bridge-cutover-runbook` (156 LOC)
- `worker-execution-of-matter-filing` (125 LOC)
- `writer-contract` (24 LOC)

**5 POINTER (≥200 LOC source, stub pointing back):**
- `capability-extension-template` (313 LOC source)
- `install-agent-to-brisen-lab` (210 LOC)
- `matter-onboarding-runbook` (278 LOC)
- `project-room-build` (204 LOC)
- `specialist-prompt-template` (319 LOC)

All 13 use the canonical frontmatter pattern (`name: <slug>` + `description: |` with embedded `MANDATORY TRIGGERS:` line) from `_ops/skills/agent-bus-posting-contract/SKILL.md`.

### Fix 3 — `_ops/scripts/sop_skills_migration_symlinks.sh`

One-shot idempotent script that creates 13 symlinks from `~/.claude/skills/<slug>` → `/Users/dimitry/baker-vault/_ops/skills/<slug>` (absolute target paths, mirroring existing pattern). Pre-flight writability check on home skills dir before any symlink work. Existing correct symlinks SKIP; conflicts ABORT with manual-reconciliation message. Final line: `Done. created=N skipped=M`. `chmod +x` + `bash -n` syntax-check both clean.

### Fix 4 — `_ops/scripts/sop_skills_migration_uplift.sh`

One-shot script that moves 7 home-only skill directories from `~/.claude/skills/<slug>` → `~/baker-vault/_ops/skills/<slug>` and replaces home with a symlink pointing back to vault. Safety: pre-flight writability on both dirs; **rollback trap** on the most recent `mv` if the subsequent `ln -s` fails (architect-flagged issue). Already-symlinked entries SKIP. `chmod +x` + `bash -n` clean.

The 7 UPLIFT slugs: `aidennis-edge-scout`, `build-pm`, `director-facing-filter-contract-validator`, `director-facing-filter-stakeholder-validator`, `dropbox-file-delivery`, `skill-installation`, `write-brief`.

### Fix 5 — `_ops/skills/INDEX.md`

Extended with 20 new entries (13 mirror + 7 uplift) under a new heading `## Added 2026-05-25 (SOPS_TO_SKILLS_MIGRATION_1)`. Same 5-column markdown table format as the existing registry. Provenance tag (INLINE/POINTER/UPLIFT) embedded in the Version column as `v1 (INLINE)` / `v1 (POINTER)` / `v1 (UPLIFT)`.

## Acceptance criteria — results

| AC | Check | Result |
|---|---|---|
| AC1 | Fix 1 audit on canonical `origin/main` | **13 MISSING + 1 EXISTS, exact match** ✅ |
| AC1 | Fix 4 audit (home-only slugs) | **7 home-only, delta=0** ✅ |
| AC2 | Frontmatter validation (13 SKILL.md) | all OK: `name:` matches slug; `MANDATORY TRIGGERS:` present; opens `---` ✅ |
| AC3 | INLINE byte-faithfulness diff vs source | all 8 INLINE: `diff_lines=0` ✅ |
| AC4 | POINTER no-duplication | all 5 POINTERs ≤15% of source LOC (target <25%) ✅ |
| AC5 | 13 symlinks installed | deferred — Gate-5 (lead runs symlinks script) |
| AC6 | 7 uplift dirs moved cleanly | deferred — Gate-5 (lead runs uplift script) |
| AC7 | INDEX.md updated | 20 entries appended under migration heading ✅ |
| AC8 | Fresh session shows new skills | deferred — requires symlinks first (Gate-5) |
| AC9 | 3 trigger spot-checks | deferred — requires fresh session post-Gate-5 |
| AC10 | git status clean of unrelated | only 16 explicit migration files staged; ~100 unrelated dirty/untracked baker-vault files left untouched ✅ |
| AC11 | cascade-backprop hook clean | not applicable: commit touches `_ops/skills/` + `_ops/scripts/`, not `_ops/agents/` ✅ |
| AC12 | Commit message references brief id + 13+7 slugs | ✅ |

## Blocker surface + resolution (bus #1046)

At brief pickup, Fix 1 audit returned **11 MISSING + 1 EXISTS** vs expected **13 MISSING + 1 EXISTS**. Delta = -2. Root cause: 2 of the 13 source files were UNTRACKED in baker-vault's dirty working tree, never committed to `origin/main`:
- `_ops/processes/claude-settings-forge-collision-runbook.md` (63 LOC)
- `_ops/processes/specialist-prompt-template.md` (319 LOC)

Brief authored against the dirty local checkout; canonical state on `origin/main` lacked both. Delta = -2 was AT the brief's ±2 surface threshold (strictly not over). Per engineering rule "fail loud" + the qualitative finding (source files literally absent from canonical state), b3 surfaced bus **#1046** to deputy with options (a/b/c) and recommendation **(a)**: deputy commits source files first.

Within ~30 min AH2 committed both via `3c5be9b ops(_ops/processes): commit 2 AID-authored process docs to canonical state`. b3 re-pulled main, audit then matched expected baseline exactly (13 MISSING + 1 EXISTS), and the migration proceeded.

## Hard-constraint compliance

- ✅ Did NOT bulk-rewrite any `_ops/processes/<file>.md` source. Skills mirror; canonical body stays in process file.
- ✅ Did NOT inline any of the 5 POINTER files. Pointer skills are stubs that point back.
- ✅ Did NOT add skills outside the 13 migration + 7 uplift list.
- ✅ Did NOT modify trigger keywords in pre-existing skills (`agent-bus-posting-contract` etc.).
- ✅ Did NOT install a recurring sync hook (one-shot migration only).
- ✅ Did NOT bypass git hooks (`--no-verify`).
- ✅ Did NOT touch `~/.claude/CLAUDE.md` or any picker CLAUDE.md for Tier 1 routing changes (skills auto-fire on trigger keywords; no manual routing needed).
- ✅ NO baker-master code changes — PR opened against `vallen300-bit/baker-vault`, not baker-master.
- ✅ Slug naming: `-sop` trailing stripped (e.g. `desk-gmail-reach-sop.md` → slug `desk-gmail-reach`); other suffixes preserved (`-contract`, `-runbook`, `-coordination`, `-template`).
- ✅ Disciplined `git add <explicit paths>` only — none of the ~100 unrelated dirty files in baker-vault's shared checkout were swept into the commit.

## Files changed

```
A  _ops/scripts/sop_skills_migration_symlinks.sh
A  _ops/scripts/sop_skills_migration_uplift.sh
M  _ops/skills/INDEX.md
A  _ops/skills/b-code-dispatch-coordination/SKILL.md
A  _ops/skills/capability-extension-template/SKILL.md
A  _ops/skills/claude-settings-forge-collision-runbook/SKILL.md
A  _ops/skills/cortex-config-template/SKILL.md
A  _ops/skills/desk-gmail-reach/SKILL.md
A  _ops/skills/important-document/SKILL.md
A  _ops/skills/install-agent-to-brisen-lab/SKILL.md
A  _ops/skills/matter-onboarding-runbook/SKILL.md
A  _ops/skills/project-room-build/SKILL.md
A  _ops/skills/specialist-prompt-template/SKILL.md
A  _ops/skills/v2-bridge-cutover-runbook/SKILL.md
A  _ops/skills/worker-execution-of-matter-filing/SKILL.md
A  _ops/skills/writer-contract/SKILL.md
```

16 files, +1264 / -0.

## Bus posts

- Deputy — bus **#1051**, topic `ship/sops-to-skills-migration-1`.
- Lead (CC) — bus **#1052**, topic `ship-cc/sops-to-skills-migration-1`.
- (prior) Deputy — bus **#1046**, topic `blocker/sops-to-skills-migration-1` (resolved by AH2 commit `3c5be9b`).

## Gate chain status

- gate_1 architecture — pending deputy
- gate_2 security (light) — pending deputy
- gate_3 picker-architect — SKIP per brief (no install / picker / harness change)
- gate_4 code-reviewer 2nd-pass — pending deputy
- gate_5 merge — pending lead

Lead Gate-5 steps:
1. Merge baker-vault PR #113.
2. Run `bash _ops/scripts/sop_skills_migration_symlinks.sh` on Director's machine. Expected output: `Done. created=13 skipped=0`.
3. Run `bash _ops/scripts/sop_skills_migration_uplift.sh` on Director's machine. Expected output: `Done. moved=7 skipped=0`.
4. Hand off to Director / lead for Fix 6 fresh-session spot-checks (3 trigger fires per brief §Fix 6 step 3).
5. Dispatch the queued companion brief `BRIEF_SKILLS_EVAL_HARNESS_1`.

## Anchor

- Brief: `briefs/BRIEF_SOPS_TO_SKILLS_MIGRATION_1.md` (canonical at `~/baker-vault/_ops/briefs/`)
- Dispatch envelope: `briefs/_tasks/CODE_3_PENDING.md` (overwritten on mailbox-hygiene flip → COMPLETE post-merge)
- Dispatch bus: deputy #1044 → acked
- Surface bus: deputy #1046 → resolved by AH2 commit `3c5be9b`
- Ship bus: deputy #1051 + lead #1052
- Director ratification: chat 2026-05-25 Q1=A inline/pointer split at 200 LOC, Q2=B sop|contract|runbook|coordination|template scope, Q3=A static trigger-keyword eval v1
- Companion brief queued: `BRIEF_SKILLS_EVAL_HARNESS_1` (authored + committed @ ae2e8ca)
