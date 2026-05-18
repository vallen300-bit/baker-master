---
status: PENDING
brief: briefs/BRIEF_STATE_RECONCILER_2.md
brief_id: STATE_RECONCILER_2
target_repo: baker-vault
matter_slug: baker-internal
cross_matter_usage: [mrci, aukera, lilienmatt, capital-call, annaberg, mo-vie-am, hagenauer-rg7, oskolkov]
dispatched_at: 2026-05-18T14:05:00Z
dispatched_by: lead
director_auth: 2026-05-18 chat — "go" (drafts STATE_RECONCILER_2 follow-up; pre-itemized deferrals from STATE_RECONCILER_1)
trigger_class: LOW (touches shipped reconciler internals; no new external surface, no schema change, no auth/DB; ≤45 LOC delta expected)
gate_chain_required:
  gate_1_ah2_static: REQUIRED
  gate_2_security_review: REQUIRED
  gate_3_picker_architect: NOT_REQUIRED (LOW trigger class)
  gate_4_2nd_pass_code_reviewer: NOT_REQUIRED (LOW trigger class)
predecessor:
  brief: STATE_RECONCILER_1
  pr: https://github.com/vallen300-bit/baker-vault/pull/96
  merge_commit: e289ff4
  followup_pr: https://github.com/vallen300-bit/baker-vault/pull/97
  followup_merge_commit: 6ef117e
items:
  - F1: schema_version regex re-application cleanup (gate-3 M2 from #419)
  - F2: STATE_RECONCILER_SKIP bypass audit trail (gate-3 M5 from #419)
  - F3: reconcile_matter post-write error path (gate-3 re-fire M)
estimated_loc: ~45
estimated_tests_added: ~9
target_test_count_after: ≥54
branch: b3/state-reconciler-2
commit_identity: Code Brisen #3 <b3@brisengroup.com>
---

# Dispatch — STATE_RECONCILER_2 (follow-up cleanup)

Brief: `briefs/BRIEF_STATE_RECONCILER_2.md`. Three items, all pre-itemized as deferrals from STATE_RECONCILER_1 (bus #419 round-1 verdict).

**Scope:** F1 (regex cleanup in `update_frontmatter`) + F2 (bypass audit-trail JSONL log + nightly cron surfacer) + F3 (symmetric post-write error path with `error_io_postwrite` status).

**Trigger class:** LOW. Gate-1 (AH2 static) + Gate-2 (/security-review) required; Gate-3 + Gate-4 NOT required.

**Predecessor still warm:** STATE_RECONCILER_1 PR #96 + follow-up #97 are your work. Same repo, same files, same builder. First nightly cron fires 02:30 UTC tomorrow — land this before drift accumulates on the new bypass-audit surface.

**Standard contract:** branch `b3/state-reconciler-2`, commit identity Code Brisen #3 <b3@brisengroup.com>, no `--no-verify`, bus-post `ship/state-reconciler-2` to `lead` on PR open.

Open the brief + go.
