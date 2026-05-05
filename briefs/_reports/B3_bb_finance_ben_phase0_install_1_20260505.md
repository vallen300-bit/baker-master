---
brief: BRIEF_BB_FINANCE_BEN_PHASE0_INSTALL_1
brief_revision: V0.1 + V0.2 + V0.3
brief_commits:
  v0_1: 8b8690a
  v0_2: b2fe75a
  v0_3: 92696aa
shipped_by: b3
shipped_at: 2026-05-06T00:30:00Z
trigger_class: VAULT_SCAFFOLD
prs:
  baker_vault: 84
  baker_master: n/a (vault-only — no baker-master changes in Phase 0)
mailbox_state: COMPLETE
---

# B3 Ship Report — BRIEF_BB_FINANCE_BEN_PHASE0_INSTALL_1

**TO:** AH1
**WHAT:** BEN (Baden-Baden AI Finance Director) Phase 0 install — vault scaffold + skill + 3 companions + 4 v1 stubs + 9 people + 1 entity + V0.3 amendments (Tier A/B/C authority + learning-log + 90-day clock + 3 kill criteria + Rheinstrasse sub-ledger + AO/MOVIE deferral) + baden-baden-desk SKILL cleanup.

**Total:** 29 NEW (28 vault + 1 Cowork SKILL) + 1 EDIT (Cowork baden-baden-desk SKILL).

## Links

- **baker-vault PR:** https://github.com/vallen300-bit/baker-vault/pull/84
- **Branch:** `b3/bb-finance-ben-phase0-install-1` on baker-vault
- **HEAD commit:** `f599eec`
- **Director ratification anchors:**
  - V0.1 brief commit `8b8690a` (initial)
  - V0.2 amendment commit `b2fe75a` (researcher + Anthropic financial-services templates fold)
  - V0.3 amendment commit `92696aa` (Brisen Desk synthesis fold)
  - slugs.yml v20 commit `51c3f48` (separate Director-side baker-vault PR — `bb-finance` slug + 4 aliases)
- **Anthropic plugins (Director-side):** `financial-analysis@claude-for-financial-services` + `fund-admin@claude-for-financial-services` installed; verified pre-build via `claude plugin list`.

## Cowork-side writes (separate filesystem, not in baker-vault PR)

1. **NEW:** `~/.claude/skills/bb-finance/SKILL.md` — full §1-§11 with V0.2 §D inserts (§4.1 P1/P2/P3 catalog with learning-log as P1 #5 per V0.3 §B, §6.4 Applied skills, §6.5 Gaps + v1 stubs, §6.6 Steuerberater workflow norms, §11 provenance) + V0.3 references (90-day clock at §1 step 8, kill-criteria at §1 step 9, learning-log + 90-day clock + kill-criteria in §4.2, AO/MOVIE deferral + sub-ledger discipline + kill criteria in §5, V0.3 amendment block in §11).

2. **EDIT:** `~/.claude/skills/baden-baden-desk/SKILL.md` — applied 10 V0.1 Feature 4 diffs + additional sweep of 10 non-diff KPMG mentions per Director Triaga 2 ratification "kill KPMG references everywhere".

## Verification (literal)

```
=== File-existence (29 NEW + 1 EDIT) ===
~/.claude/skills/bb-finance/SKILL.md: OK
3 vault companions: OK
9 lens folder/subfolder files: OK
4 _stubs files: OK
2 V0.3 additions (learning-log.md, rheinstrasse-pm-mandate.md): OK
10 people + entity files: OK

=== V0.3 Authority table ===
Numbered rows: 20 (Tier A 13 + Tier B 7) — supersedes V0.2 §G grep expect=17
Tier sections (A/B/C): 3
Phase commitments + Kill criteria + Out-of-authority sections: present
Status: draft v0 — awaiting Director ratification

=== BEN SKILL.md V0.2 sections present ===
§6.4 Applied skills:               1
§6.5 Gaps + v1 stubs:              1
§6.6 Steuerberater workflow norms: 1

=== V0.2 _stubs frontmatter ===
cap-table-modeler.md:    type: gap-stub-v1 ✓
covenant-tracker.md:     type: gap-stub-v1 ✓
waterfall-modeler.md:    type: gap-stub-v1 ✓
mabv-tracker.md:         type: gap-stub-v1 ✓

=== baden-baden-desk SKILL grep gates ===
Weipert (single-p):     0 ✓ (V0.2 §G expect 0)
Weippert:               19 ✓ (V0.2 §G expect ≥7)
Brandner total:         8 ✓ (V0.2 §G expect ≥2)
Brandner in TRIGGERS:   0 ✓ (V0.2 §G expect 0)
bb-finance handoff:     2 ✓ (V0.2 §G expect ≥2)
NOT YET CLOSED:         1 ✓ (V0.2 §G expect 1)
BEN sibling-Desks line: 1 ✓
KPMG lines:             3 ⚠ (V0.2 §G expect ≤1; see annotations)

=== sync_skills.sh dry-run ===
No bb-finance interactions (BEN is direct-write to ~/.claude/skills/, not vault-symlinked) ✓
Quality checkpoint #1 satisfied.
```

## Annotations / spec gaps surfaced

1. **Authority table V0.2 spec stale.** V0.2 §G grep `expect 17` was for the flat 17-row authority table. V0.3 §A explicitly restructured to Tier A (13 rows) / Tier B (7 rows) / Tier C list, totaling 20 numbered rows. V0.3 supersedes V0.2 — current table reflects V0.3. Reviewer should treat the V0.2 §G `expect 17` line as stale.

2. **V0.2 §G KPMG grep spec internally inconsistent with V0.1 diff content.** V0.2 §G says `expect 1 hit max (the "never retained" negation)`. But V0.1 Feature 4 Diffs 4 + 6 + 8 each contain mandated text with "KPMG never retained" or "KPMG German exit-tax" framing — producing 3 KPMG lines after applying the diffs verbatim. Cleaned all 10 non-diff KPMG mentions per Director Triaga 2 ratification ("kill KPMG references everywhere"). Final KPMG count = 3 (all negation/historical-reference, all diff-mandated). Reviewer can choose to consolidate to 1 negation if desired; B3 preserved diff-mandated content per Tier-A "execute briefs as written".

3. **Pre-existing untracked research files** at `wiki/research/2026-05-03-claude-code-token-audit.md` and `wiki/research/2026-05-05-ben-aicfo-skillset-brisen-desk-design.md` were observed in baker-vault working tree at branch creation (not B3-authored). Left untouched per scope discipline.

4. **Rheinstrasse contracting entity TBC.** V0.3 §E specifies entity attribution "MRCI | Lilienmatt (TBC pending Siegfried email)" — captured as placeholder in `projects/rheinstrasse-pm-mandate.md` frontmatter. To be resolved post-Siegfried confirmation in a separate vault PR.

5. **V0.3 §C Phase 2 forcing function active on merge.** Phase 0 ship date = baker-vault PR #84 merge date. Phase 2 (data-feed automation) brief due within 90 days. Encoded in `authority-boundary-table.md` "Phase commitments" + BEN SKILL.md §1 step 8 + OPERATING.md "Phase 2 clock". AH1 should track for Phase 2 dispatch.

## Cost / clock

- **Clock time:** ~75 min (read brief + V0.3 amendment fold + 28 vault writes + 1 SKILL write + 10 SKILL edits + verification + commit + push + PR)
- **Token usage:** estimate ~250-300K input / ~30K output (3 KPMG-cleanup edits + V0.3 fold required additional context loads)

## Next (handoff to AH1)

1. AH1 reviews PR #84 per RA-24 trigger class assessment.
2. AH1 merges baker-vault PR.
3. Director invokes BEN trigger ("BEN" or "Baden-Baden Finance") in fresh Cowork session.
4. First substantive BEN session: walk Tier A/B/C authority-table v0 row-by-row for ratification (≈10 min Director time).
5. BEN populates initial cash position from Conrad's most recent weekly Excel.
6. **Phase 2 forcing function:** AH1 drafts Phase 2 (data-feed automation) brief or surfaces Director-side extension request within 90 days of PR #84 merge.
7. **Month-6 review:** AH1 drafts BEN month-6 review brief drawing on `learning-log.md` BB-specific vs portfolio-generalisable entries; Director decides AO/MOVIE finance-lens clone scope (V0.3 §F).

**B3 idle.** Mailbox flipped COMPLETE. Next dispatcher: §2 busy-check before overwriting.
