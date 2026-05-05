---
status: COMPLETE
brief: briefs/BRIEF_BB_FINANCE_BEN_PHASE0_INSTALL_1.md
trigger_class: VAULT_SCAFFOLD
dispatched_at: 2026-05-05T22:00:00Z
dispatched_by: ai-head-a
claimed_at: 2026-05-05T23:10:00Z
claimed_by: b3
last_heartbeat: 2026-05-06T00:30:00Z
shipped_at: 2026-05-06T00:30:00Z
brief_revision: V0.1 + V0.2 + V0.3 (Brisen Desk synthesis fold)
brief_commits:
  v0_1: 8b8690a
  v0_2: b2fe75a
  v0_3: 92696aa
working_branch_baker_vault: b3/bb-finance-ben-phase0-install-1
working_branch_baker_master: n/a (vault-only — no baker-master changes in Phase 0)
ratified_by: Director 2026-05-05 (V0.1 + V0.2 + V0.3 amendments)
ship_report: briefs/_reports/B3_bb_finance_ben_phase0_install_1_20260505.md
prs:
  baker_vault: 84  # open, awaiting AH1 review + merge
  baker_master: n/a
autopoll_eligible: false
---

# CODE_3 — COMPLETE (BRIEF_BB_FINANCE_BEN_PHASE0_INSTALL_1 V0.1 + V0.2 + V0.3)

**Shipped:** 2026-05-06T00:30:00Z by B3.

**PRs:**
- baker-vault [#84](https://github.com/vallen300-bit/baker-vault/pull/84) — **open**, awaiting AH1 review + merge.
- baker-master: n/a (vault-only Phase 0; no baker-master changes).

**Ship report:** [briefs/_reports/B3_bb_finance_ben_phase0_install_1_20260505.md](../_reports/B3_bb_finance_ben_phase0_install_1_20260505.md)

**Branch (baker-vault):** `b3/bb-finance-ben-phase0-install-1` @ HEAD `f599eec`.

**Total deliverables:** 29 NEW (28 in baker-vault PR + 1 Cowork-side SKILL at `~/.claude/skills/bb-finance/SKILL.md`) + 1 EDIT (Cowork-side `~/.claude/skills/baden-baden-desk/SKILL.md` cleanup).

**V0.3 fold complete:**
- §A authority-boundary-table.md restructured to Tier A (13 rows) / Tier B (7 rows) / Tier C list ✓
- §B learning-log.md added ✓
- §C 90-day Phase 2 trigger encoded in authority-table + SKILL.md §1 step 8 ✓
- §D 3 kill criteria encoded in authority-table + SKILL.md §5 ✓
- §E Rheinstrasse PM-mandate sub-ledger entry created (entity TBC pending Siegfried) ✓
- §F AO/MOVIE deferral line in authority-table "Out of authority" + SKILL.md §5 ✓

**Verification:** All file-existence + grep gates pass; 2 spec annotations surfaced — see ship report §"Annotations / spec gaps surfaced":
1. V0.2 §G grep `expect 17` (authority-table rows) is stale post-V0.3 §A restructure (now 20 rows: Tier A 13 + Tier B 7).
2. V0.2 §G KPMG `expect ≤1` is internally inconsistent with V0.1 Feature 4 Diffs 4 + 6 + 8 (each contains diff-mandated negation/historical-reference text). Final count = 3 lines, all diff-mandated; 10 non-diff KPMG mentions cleaned per Director Triaga 2 ratification.

**Notes:**
- V0.3 amendment landed mid-build (after authority-table v1 was drafted in flat-list form per V0.2 §B); refactored to Tier A/B/C per V0.3 §A b3 action without re-doing other work.
- Cowork-side writes (~/.claude/skills/bb-finance/SKILL.md NEW + ~/.claude/skills/baden-baden-desk/SKILL.md EDIT) live outside baker-vault PR — separate filesystem, no separate PR.
- 90-day Phase 2 forcing function active on baker-vault PR #84 merge (V0.3 §C).
- Rheinstrasse contracting entity (MRCI vs Lilienmatt) TBC pending Siegfried email — captured as placeholder in `projects/rheinstrasse-pm-mandate.md` frontmatter.

**B3 idle.** Next dispatcher: run §2 busy-check before overwriting.
