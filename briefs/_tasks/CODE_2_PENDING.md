# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (fresh terminal tab)
**Task posted:** 2026-04-20 (midday, post-SOT Phase A dispatch)
**Status:** QUEUED — waiting on B1 to ship Phase A PR

---

## Task: Review SOT_OBSIDIAN_UNIFICATION_1 Phase A PR (when it lands)

B1 is executing Phase A of SOT_OBSIDIAN_UNIFICATION_1 against `baker-vault` repo (not baker-master). Brief at `briefs/BRIEF_SOT_OBSIDIAN_UNIFICATION_1.md` in baker-master at commit `4596383` — read the whole brief end-to-end before reviewing, especially §Fix/Feature 1 (Phase A).

### When the PR lands

B1 will open a PR against `vallen300-bit/baker-vault` main (branch `sot-obsidian-1-phase-a`). You review. One-time setup on your side:

```bash
cd ~
[ -d bv-b2 ] || git clone https://github.com/vallen300-bit/baker-vault.git bv-b2
cd bv-b2
git fetch origin sot-obsidian-1-phase-a
git checkout sot-obsidian-1-phase-a
```

### Verdict focus

**Scaffold completeness (brief §Fix/Feature 1):**
- `_ops/` tree has exactly 4 subdirs: `skills/`, `briefs/`, `agents/`, `processes/`.
- `_install/` exists with `sync_skills.sh` (executable, skeleton only).
- 6 markdown files landed: `_ops/INDEX.md`, `_ops/skills/INDEX.md`, `_ops/briefs/INDEX.md`, `_ops/briefs/TEMPLATE.md`, `_ops/agents/INDEX.md`, `_ops/processes/INDEX.md`, `_ops/processes/writer-contract.md` (7 files total — count INDEXes).
- All markdown files have frontmatter `type: ops` + `ignore_by_pipeline: true`.
- `writer-contract.md` text matches brief §1.7 verbatim (or equivalently clear — small wording variations OK as long as semantics preserved).
- `TEMPLATE.md` contains the `/write-brief` protocol text (8000+ LOC from `~/.claude/skills/write-brief/SKILL.md`) + frontmatter block.

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

Report to `~/bv-b2/_reports/B2_sot_phase_a_review_<YYYYMMDD>.md` (or the equivalent location B1 chooses — may need to create `_reports/` in baker-vault or stick with pattern from baker-master). APPROVE / REDIRECT / REQUEST_CHANGES.

If APPROVE, AI Head auto-merges per Tier A protocol.

Expected time: 15-20 min.
