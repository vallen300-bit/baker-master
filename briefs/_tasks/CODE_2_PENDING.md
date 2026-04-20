# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (fresh terminal tab)
**Task posted:** 2026-04-20 (midday, amended with B2 self-improvement scope)
**Status:** OPEN — TWO tasks (one active, one queued)

---

## Task 1 (NOW, while B1 ships Phase A): `baker-review` template + lessons-grep helper

Director-authorized 2026-04-20 based on your own self-analysis ("start with a briefs/_templates/B2_verdict_template.md + a 'before APPROVE, re-read lessons #34-42' line in my standing instructions... If drift or missed regressions surface in the next 5-10 reviews, promote to a proper baker-review skill"). AI Head agreed with one addition: include a shell helper for automated lessons-grep, which is the highest-leverage piece of the proposed skill and the only piece where manual scanning is lossy.

**Scope:**

### 1.1 — `briefs/_templates/B2_verdict_template.md`

Create the verdict-report scaffold you've been typing by hand each cycle. Include:

- Frontmatter block (date, PR #, head SHA, reviewer, verdict, references)
- Scope-verification table (brief section ↔ actual diff match)
- Landmine-sweep checklist — the six patterns you mentioned (column-name drift, unbounded queries, missing rollback, fixture-only tests, LLM signature three-way match, wrong env var)
- CHANDA Q1 (Loop Test) + Q2 (Wish Test) block with prompts
- Nits section
- Dispatch-back block (to AI Head via mailbox)

Write it so each cycle = filling cells, not re-drafting the structure. Reference `tasks/lessons.md` at the top.

### 1.2 — `briefs/_templates/lessons-grep-helper.sh` (15-line shell helper)

Standalone bash script. Input: PR number or branch name. Behavior:

1. Resolve the list of changed files + added/modified hunks (`gh pr diff <N>` or `git diff main...<branch>`).
2. Read each "Mistake:" paragraph block from `tasks/lessons.md`.
3. For each lesson, score overlap against the diff hunks (keyword presence is enough — no ML, no clever NLP).
4. Return top 3-5 lessons ranked by relevance, with lesson number + one-line summary + file it most likely applies to.

Output shape:

```
[lessons-grep] Top 5 lessons for PR #24 (head 9600168):

  #17 — Brief code snippets must be verified against actual function signatures
        → likely applies to: memory/store_back.py
  #38 — ((ts::date)) is VOLATILE in modern Postgres
        → likely applies to: (none flagged — good)
  ...
```

Keep it < 50 lines total. No external deps beyond `gh`, `git`, `grep`. Idiomatic bash, fail-on-error.

### 1.3 — Standing-instruction amendment

Append one line to whichever file holds your standing instructions (likely `~/.claude/agent-memory/code-brisen-2/` or similar — if unclear, flag in PR description and AI Head will decide):

```
Before APPROVE on any PR review: (a) fill briefs/_templates/B2_verdict_template.md, (b) run briefs/_templates/lessons-grep-helper.sh <pr_number> and address any flagged lesson, (c) apply CHANDA Q1/Q2 block.
```

### 1.4 — Ship

Target PR: `baker-master` repo. Branch: `baker-review-template-v1`. Commit message references this dispatch. Reviewer: B1 (or AI Head if B1 is still on Phase A).

**Migration note for PR description:** this lands in `briefs/_templates/` today because SOT_OBSIDIAN_UNIFICATION_1 hasn't canonicalized process docs yet. When Phase B of that brief ships, this template + helper migrate to `~/baker-vault/_ops/processes/baker-review/` (or equivalent). Flag the migration path in the PR body so it doesn't get forgotten.

**Expected time: 25-35 min** (10 min template + 15 min helper + 5 min commit/push/PR).

### Explicit non-goals (do NOT do these yet)

- Do NOT create a full `baker-review` skill at `~/.claude/skills/baker-review/SKILL.md`. Skill promotion is parked until SOT_OBSIDIAN_UNIFICATION_1 Phase B gives us a canonical skill location + 5-10 reviews of template drift data.
- Do NOT modify `tasks/lessons.md` in this PR. Template references it; changes to lessons belong in their own PRs.
- Do NOT automate the entire review (no "auto-APPROVE"). The helper flags candidates; you still make the verdict call.

---

## Task 2 (QUEUED, after Task 1 ships): Review SOT_OBSIDIAN_UNIFICATION_1 Phase A PR

B1 is executing Phase A of SOT_OBSIDIAN_UNIFICATION_1 against the `baker-vault` repo (not baker-master). Brief at `briefs/BRIEF_SOT_OBSIDIAN_UNIFICATION_1.md` at commit `4596383` in baker-master. Read the whole brief end-to-end before reviewing, especially §Fix/Feature 1 (Phase A).

### When B1's PR lands

B1 will open a PR against `vallen300-bit/baker-vault` main (branch `sot-obsidian-1-phase-a`). You review. One-time setup on your side:

```bash
cd ~
[ -d bv-b2 ] || git clone https://github.com/vallen300-bit/baker-vault.git bv-b2
cd bv-b2
git fetch origin sot-obsidian-1-phase-a
git checkout sot-obsidian-1-phase-a
```

**Use your new template + helper from Task 1** for this review. That's the whole point of building them while waiting.

### Verdict focus

**Scaffold completeness (brief §Fix/Feature 1):**
- `_ops/` tree has exactly 4 subdirs: `skills/`, `briefs/`, `agents/`, `processes/`.
- `_install/` exists with `sync_skills.sh` (executable, skeleton only).
- 7 markdown files landed: `_ops/INDEX.md`, `_ops/skills/INDEX.md`, `_ops/briefs/INDEX.md`, `_ops/briefs/TEMPLATE.md`, `_ops/agents/INDEX.md`, `_ops/processes/INDEX.md`, `_ops/processes/writer-contract.md`.
- All markdown files have frontmatter `type: ops` + `ignore_by_pipeline: true`.
- `writer-contract.md` text matches brief §1.7 verbatim (or equivalently clear — small wording variations OK as long as semantics preserved).
- `TEMPLATE.md` contains the `/write-brief` protocol text (~8,000 LOC from `~/.claude/skills/write-brief/SKILL.md`) + frontmatter block.

**Guardrails respected:**
- `wiki/` UNTOUCHED (confirm via `git diff origin/main HEAD -- wiki/` → empty output).
- `CHANDA.md` UNTOUCHED.
- `slugs.yml`, `config/`, `schema/`, `raw/` all UNTOUCHED.
- No migration of real content — this phase is additive only.
- `_install/sync_skills.sh` is Phase A skeleton (just echoes "Phase A skeleton", exits 0 — does NOT touch `~/.claude/skills/`).

**Safety check on sync script skeleton:**
- No `rm`, no `ln`, no file writes in `sync_skills.sh`. Literally just echoes + `exit 0`.
- If you see any actual filesystem mutation in the Phase A sync script, REQUEST_CHANGES — that belongs in Phase B.

**Commit message quality:**
- References "SOT_OBSIDIAN_UNIFICATION_1 Phase A" in the subject.
- Cites Director authorization 2026-04-20.
- Co-Authored-By line present.

### Output

Report to `~/bv-b2/_reports/B2_sot_phase_a_review_<YYYYMMDD>.md` (or the equivalent location — baker-vault may need `_reports/` created). APPROVE / REDIRECT / REQUEST_CHANGES.

If APPROVE, AI Head auto-merges per Tier A protocol.

Expected time: 15-20 min using your new template.
