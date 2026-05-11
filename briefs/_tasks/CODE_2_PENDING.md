---
status: COMPLETE
brief: briefs/BRIEF_COCKPIT_SIDEBAR_LEGACY_SLUG_ALIAS_FIX_1.md
trigger_class: TIER_B_USER_FACING_CORRECTNESS_FIX
dispatched_at: 2026-05-11
dispatched_by: ai-head-1 (AH1)
target: b2
pr: https://github.com/vallen300-bit/baker-master/pull/185
pr_head: cca6657bb54094c58dd5d01bf9a3df6ce982947a
merged_at: 2026-05-11T14:21:47Z
merge_commit: 3fc12c4c298b6727ce21b1e6eb8d12e5564d7fd0
gates_cleared:
  - gate_1_pytest: GREEN (17/17 fold + 6/6 dashboard + 60/60 broader, no regressions)
  - gate_2_security_review: NO_FINDINGS (clean scan)
  - gate_3_ah2_cross_lane: PASS_WITH_NITS (1 LOW non-blocking — Tier-1+Tier-2 fold-collision test gap, follow-up nit)
  - gate_4_code_reviewer_2nd_pass: SKIPPED (no trigger class hit per SKILL.md §Code-reviewer 2nd-pass Protocol)
ship_report: briefs/_reports/B2_cockpit_sidebar_legacy_slug_alias_fix_20260511.md
followup_nits:
  - test_tier1_tier2_collision_at_same_canonical — bundle into next b2 window or follow-on slugs.yml PR
followup_recommended:
  - Separate baker-vault PR to ratify `ao_pm` alias on `ao` + 9 dropped free-text labels as canonical slugs (Tier-1 then catches them; no further dashboard.py change needed). NEEDS-DIRECTOR-RATIFICATION.
---

# CODE_2_PENDING — BRIEF_COCKPIT_SIDEBAR_LEGACY_SLUG_ALIAS_FIX_1 — COMPLETE 2026-05-11T14:21Z

Merged at `3fc12c4c`. Render auto-deploy in flight; post-deploy curl verification pending.

Outcome (live):
- mo-vie-am: gets ~136 items (Tier-1 `movie_am` alias hit)
- hagenauer-rg7: gets a few items (Tier-1 `hagenauer` + Tier-2 `Oskolkov-RG7`)
- mo-vie-exit: gets 2 items (Tier-2 `Mandarin Oriental Sales`)
- inbox_count: drops from 299 → ~163 (residual: 28 `_ungrouped` + 100 `ao_pm` + 9 unverified free-text + 17 misc)

Full fix requires the separate-repo follow-on (see frontmatter `followup_recommended`).

Mailbox hygiene applied per `_ops/processes/b-code-dispatch-coordination.md` §3.
