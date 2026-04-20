# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (fresh terminal tab)
**Task posted:** 2026-04-20 (midday, post-Phase-A merge)
**Status:** OPEN — SOT_OBSIDIAN_UNIFICATION_1 Phase B

---

## Task: SOT_OBSIDIAN_UNIFICATION_1 Phase B — migrate AI Dennis + populate registries + wire sync_skills.sh

Phase A merged at 12:15 UTC on baker-vault (squash merge of PR #3). `_ops/` scaffold is live.

Brief: `briefs/BRIEF_SOT_OBSIDIAN_UNIFICATION_1.md` at commit `4596383` in baker-master. Execute **Phase B** per §Fix/Feature 2 — steps 2.1 through 2.10 verbatim.

**Target PR:** against `baker-vault`. Branch: `sot-obsidian-1-phase-b`. Base: `main`. Reviewer: B2.

### Continuing in `~/bv-b1/`

```bash
cd ~/bv-b1
git checkout main && git pull --ff-only origin main
git checkout -b sot-obsidian-1-phase-b
```

### Scope (exact steps from brief §Fix/Feature 2)

Follow brief steps **2.1 through 2.10 verbatim**. Summary:

1. **2.1** — Canonicalize AI Dennis skill (copy Baker-Project source → `_ops/skills/it-manager/SKILL.md`). Verify zero diff against `~/.claude/skills/it-manager/SKILL.md`. Abort + escalate if diff non-zero.
2. **2.2** — Split AI Dennis memory per v3 spec: `OPERATING.md` (<80 lines), `LONGTERM.md` (<200 lines), `ARCHIVE.md` (append-only). Seed content from legacy `AI_DENNIS_MEMORY.md`.
3. **2.3** — Update `_ops/skills/INDEX.md` with the it-manager row.
4. **2.4** — Update `_ops/agents/INDEX.md` with AI Dennis canonical pointers.
5. **2.5** — Replace `_install/sync_skills.sh` Phase A skeleton with real symlink logic per brief. **Safety non-negotiable:** never delete non-symlink non-empty dir; skip + log instead.
6. **2.6** — Create three process docs: `_ops/processes/write-brief.md` (copy body of `~/.claude/skills/write-brief/SKILL.md`), `_ops/processes/bank-model.md` (from `feedback_ai_head_communication.md` in Director's memory), `_ops/processes/git-mailbox.md` (from current `_handovers/AI_HEAD_20260420.md`).
7. **2.7** — Update `_ops/processes/INDEX.md` — all rows now have real file links.
8. **2.8** — Retire 2 duplicate copies: rename `Baker-Project/pm/ai-operations/it-manager/AI_DENNIS_SKILL.md` → `.retired-2026-04-20` (and same for `Dropbox/.skills/skills/it-manager/SKILL.md`). **Do NOT `rm`.**
9. **2.9** — Execute `_install/sync_skills.sh` against `~/.claude/skills/` in dry-run mode first (add `--dry-run` flag if not in brief — implement if missing). Verify expected output. Then run for real. Verify symlink via `readlink ~/.claude/skills/it-manager`.
10. **2.10** — Commit + push per brief.

### Hard constraints

- **Symlink direction:** vault = source, runtime = target. `ln -s /vault/path /runtime/path`. Never the other way. The brief has this explicit — obey.
- **Do NOT `rm` any file.** Rename to `.retired-*` only. Destructive deletion is Director-authorized only after 7+ days of burn-in (brief §Key Constraints).
- **TEMPLATE.md in _ops/briefs/ carries write-brief protocol.** Phase B's new `_ops/processes/write-brief.md` is the CANONICAL version going forward; TEMPLATE.md becomes a pointer to it. Update TEMPLATE.md accordingly — brief doesn't specify this explicitly but it's the clean separation.
- Bank-model doc source: `/Users/dimitry/.claude/projects/-Users-dimitry-Vallen-Dropbox-Dimitry-vallen-Baker-Project/memory/feedback_ai_head_communication.md`. Git-mailbox doc source: the "Workflow patterns" section of `briefs/_handovers/AI_HEAD_20260420.md` in baker-master.

### Acceptance criteria (from brief §Verification)

```bash
diff ~/bv-b1/_ops/skills/it-manager/SKILL.md ~/.claude/skills/it-manager/SKILL.md
# Expected: zero output (identical because one IS the other via symlink)

readlink ~/.claude/skills/it-manager
# Expected: /Users/dimitry/baker-vault/_ops/skills/it-manager

ls ~/bv-b1/_ops/agents/ai-dennis/
# Expected: OPERATING.md LONGTERM.md ARCHIVE.md

wc -l ~/bv-b1/_ops/agents/ai-dennis/OPERATING.md
# Expected: ≤80 lines

wc -l ~/bv-b1/_ops/agents/ai-dennis/LONGTERM.md
# Expected: ≤200 lines

ls ~/bv-b1/_ops/processes/
# Expected: INDEX.md write-brief.md bank-model.md git-mailbox.md writer-contract.md

ls "/Users/dimitry/Vallen Dropbox/Dimitry vallen/Baker-Project/pm/ai-operations/it-manager/"
# Expected: AI_DENNIS_SKILL.md.retired-2026-04-20 (still present under original name? NO — renamed)
```

### Coordination note

B3 is in parallel working on lessons-grep-helper v2 (addressing B2's N1+N2 nits from Phase A review). No conflict — different files, different repo. Both PRs can ship independently.

### Trust marker

**What in production would reveal a bug:** open a fresh Claude App session after symlink-in-place and verify AI Dennis skill still triggers on "start Dennis" / "IT session" prompts. If the symlink breaks skill loading, the AI Dennis invocation will fail — easy to spot within 30 seconds of a fresh session.

Expected time: 2-2.5 hours. Don't rush step 2.2 (memory split) — content seeding matters for AI Dennis's next live invocation. Ping B2 for review when done.
