---
status: PENDING
brief: briefs/BRIEF_BB_FINANCE_BEN_PHASE0_INSTALL_1.md
trigger_class: VAULT_SCAFFOLD
dispatched_at: 2026-05-05T22:00:00Z
dispatched_by: ai-head-a
brief_revision: V0.1 (initial) + V0.2 (researcher + Anthropic templates fold)
brief_commits:
  v0_1: 8b8690a
  v0_2: b2fe75a
working_branch_baker_vault: b3/bb-finance-ben-phase0-install-1
working_branch_baker_master: n/a (vault-only — no baker-master changes in Phase 0)
ratified_by: Director 2026-05-05 (initial brief + V0.2 amendment)
prerequisites_director_side:
  - baker-vault slugs.yml PR for `bb-finance` slug + aliases — MUST merge BEFORE dispatch fires
  - claude plugin install fund-admin@claude-for-financial-services
  - claude plugin install financial-analysis@claude-for-financial-services
  - (anti-pattern banned: claude plugin install month-end-closer / gl-reconciler / valuation-reviewer / etc.)
priority: P2 — Phase 0 foundation for first AI CFO; Phase 1 (data feed) blocked on this
eta: 6-10h
heartbeat_cadence: 12h binding (per SKILL.md `59f23c4` §B-code stall chase)

# CODE_3_PENDING — BRIEF_BB_FINANCE_BEN_PHASE0_INSTALL_1 — 2026-05-05

**Brief:** baker-master `briefs/BRIEF_BB_FINANCE_BEN_PHASE0_INSTALL_1.md` (V0.1 commit `8b8690a` + V0.2 amendment commit `b2fe75a`)
**Working branch (baker-vault):** `b3/bb-finance-ben-phase0-install-1`
**Pre-requisites:** Director-side: (1) baker-vault slugs.yml PR for `bb-finance` slug merged; (2) Anthropic financial-services plugins (`fund-admin` + `financial-analysis`) installed via `claude plugin install`. Both verified by Director or AH1 before B3 begins work.

**Read first (MANDATORY):**
1. `briefs/BRIEF_BB_FINANCE_BEN_PHASE0_INSTALL_1.md` — full spec (V0.1 features 1-5 + V0.2 amendments §A-§I)
2. `~/baker-vault/_ops/agents/b3/orientation.md` — your role
3. `~/.claude/projects/-Users-dimitry-Vallen-Dropbox-Dimitry-vallen-Baker-Project/memory/MEMORY.md` — canonical Baker memory

**First-message confirmation phrase (evidence-bound, exact):**
`"B3 oriented. Read: CODE_3_PENDING.md, MEMORY.md."`

**Path forward (vault-only — no baker-master code changes):**

1. Read brief BRIEF_BB_FINANCE_BEN_PHASE0_INSTALL_1.md cover-to-cover (all 5 V0.1 features + V0.2 amendments §A-§I).
2. Confirm prereqs landed: `cd ~/baker-vault && git pull && grep -A1 "slug: bb-finance" slugs.yml` (expect alias line); `claude plugin list | grep -E "financial-analysis|fund-admin"` (expect 2 plugins).
3. Create branch `b3/bb-finance-ben-phase0-install-1` on baker-vault.
4. **Feature 1 — Vault scaffold:** create `wiki/_finance/baden-baden/` lens-folder + 7 sub-folders + main README + authority-boundary-table.md (17 rows per V0.2 §B) + 7 sub-folder seed READMEs (covenants/README per V0.2 §C; rest per V0.1 §Feature 1).
5. **Feature 2 — BEN's skill:** create `~/.claude/skills/bb-finance/SKILL.md` (full §1-§11 per V0.1 + V0.2 §D.1-§D.5 inserts: §4.1 P1/P2/P3 catalog + §6.4 Applied skills + §6.5 Gaps + §6.6 Steuerberater workflow + §11 V0.2 provenance). Plus 3 vault companion files at `_ops/agents/bb-finance/{OPERATING,LONGTERM,ARCHIVE}.md` (OPERATING + LONGTERM seeds per V0.1 + LONGTERM extension per V0.2 §E).
6. **V0.2 §F — 4 v1 gap-stub files:** create `wiki/_finance/baden-baden/_stubs/{cap-table-modeler,covenant-tracker,waterfall-modeler,mabv-tracker}.md` per V0.2 §6.5 spec (frontmatter + 1-paragraph description + named template).
7. **Feature 3 — Registry:** create 9 wiki/people files (weiss-conrad, brandner-siegfried, schreiner-caroline, morgental-andrea, beniulis-ramunas, krenn-rudiger, weippert-klaus, romme, kopp) + 1 wiki/entities/engel-voelkers.md per V0.1 §Feature 3 verbatim frontmatter.
8. **Feature 4 — baden-baden-desk SKILL cleanup:** apply 10 diffs to `~/.claude/skills/baden-baden-desk/SKILL.md` per V0.1 §Feature 4 (line-by-line OLD/NEW blocks).
9. Run all verification scripts in V0.1 + V0.2 §G (file existence + grep checks). All must pass before opening PR.
10. Open baker-vault PR titled "feat(bb-finance): BEN Phase 0 install — vault scaffold + skill + registry + cleanup".
11. Ship via PL paste-block per SKILL.md §"PL ship-report contract".

**Out of scope (do NOT touch):**
- `baker-vault/slugs.yml` — separate-repo PR (Director or AH1 lane). CLAUDE.md hard rule.
- `baker-vault/_install/sync_skills.sh` — auto-discovers `_ops/skills/*/`; BEN's SKILL is at `~/.claude/skills/`. No edit needed.
- `~/.claude/CLAUDE.md` and `~/.claude/dropbox-tier0.md` — no targets there (verified by AH1 in EXPLORE).
- `wiki/matters/{mrci,annaberg,lilienmatt}/*` — Baden-Baden Desk's lane.
- All non-listed files.

**Gates / quality checkpoints:**
- All 27 NEW files created (1 SKILL + 3 companions + 1 lens-root README + 1 authority-table + 7 sub-READMEs + 4 _stubs + 9 people + 1 entity).
- 1 file edited (baden-baden-desk SKILL with all 10 diffs).
- Verification script: `grep -c "Weipert\b" ~/.claude/skills/baden-baden-desk/SKILL.md` returns 0; `grep -c "Weippert"` returns ≥7.
- Authority-table v0 has 17 rows; status `draft v0 — awaiting Director ratification`.
- BEN SKILL.md §6.4 / §6.5 / §6.6 sections present.
- 4 _stubs/ files present with `type: gap-stub-v1` frontmatter.
- No counterparty-facing artefacts produced (Phase 0 is internal scaffolding only).

**Ship-report contract (per PL paste-block):**
- TO: AH1
- WHAT: 1-line summary + Phase 0 deliverables count + branch + PR link
- LINKS: baker-vault PR; ratification anchor (V0.1 + V0.2 commits)
- COST: token usage + clock time
- NEXT: AH1 reviews + merges + Director invokes BEN trigger for first-session walk-through of authority-table v0

**Critical pre-merge gates (post-WRITE review):**
- All 27 file paths verified present
- baden-baden-desk SKILL cleanup grep checks all green (no Weipert single-p; KPMG only in negation; bb-finance handoff present)
- Authority-table at 17 rows
- No drift from V0.1 + V0.2 verbatim content blocks
