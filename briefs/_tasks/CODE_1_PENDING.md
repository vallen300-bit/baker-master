---
status: COMPLETE
brief: BRIEF_ANTHROPIC_CACHE_TTL_AUDIT_DIAG (informal — no brief file authored)
trigger_class: AUDIT_DIAGNOSTIC
dispatched_at: 2026-05-03T~earlier
dispatched_by: ai-head-a (prior session)
claimed_at: 2026-05-03T12:44:38Z
claimed_by: b1
completed_at: 2026-05-03T12:44:38Z
merged_at: 2026-05-03T14:04:11Z
verdict: PASS
blocker_question: null
ship_report: briefs/_reports/B1_anthropic_cache_ttl_audit_20260503.md
return: briefs/_tasks/CODE_1_RETURN.md
pr: 154
merge_commit: 3a8051386a63f4aa8d3add2723a675cc38e2ae8d
autopoll_eligible: false
---

B1: Anthropic cache TTL audit — diagnostic-only.

**Verdict (B1's):** upgrade material on inter-cycle reuse (esp. oskolkov), but **hold the 1-hr extended-cache-TTL flip** until post-Step-30 + 1 week observation. Re-audit then.

Findings:
- Default 5-min ephemeral; `cache_control={"type":"ephemeral"}` at 4 hot sites; no `extended-cache-ttl-*` header anywhere.
- Median intra-cycle gap 13.6s (5-min default fits).
- Inter-cycle on oskolkov: 9/16 gaps in 5min-1hr window — exactly where extended cache converts misses to hits. ~$4-5/debug batch potential save.

No code change. Two doc files added on PR branch. PR #154 merged 2026-05-03T14:04:11Z by AI Head A.

**B1 mailbox empty.** Next dispatch overwrites this entry per §3 hygiene.
