---
status: PENDING
brief: briefs/BRIEF_DEADLINE_ASSIGNED_TO_BACKFILL_1.md
trigger_class: TIER_B_AUDIT_TRIGGERED_BACKFILL_AND_NITS
dispatched_at: 2026-05-13
dispatched_by: ai-head-1 (AH1)
target: b3
director_ratification: |
  Director 2026-05-13 "follow your recomends" — covering both Scope A
  (backfill brief per Brief 3 Q5 trigger: P=2.9% << 50% threshold) and
  Scope B (4 nits from PR #197 2nd-pass — MED1 + MED2 + LOW3 + LOW4).
  This brief is scheduled-tasks v1.5; closes the v1 cycle by enabling
  meaningful scanner enablement (post backfill + Director-ratified apply).
priority: P2
phase: 1 of 1
expected_pr_count: 1 (baker-master)
expected_branch: b3/deadline-backfill-and-nits-1
expected_complexity: medium (~3h B-code; 1 new utility script + 4 quality fixes + 3 new tests + 1 vault doc append)
mandatory_2nd_pass: FALSE
mandatory_2nd_pass_reason: |
  Bundled fixes are <50 LOC of executable changes to already-2nd-pass-cleared
  code (PR #197 PASS-WITH-NITS). New backfill script is local-runtime utility
  with no external surface, dry-run-default with three safety rails (explicit
  --apply flag + ratified-mapping-file requirement + 24h staleness guard +
  BAKER_BACKFILL_DRY_RUN_ONLY=1 kill-switch env). No new public endpoint,
  no external network call.
security_review: |
  Not required per §Security Review Protocol known-scope exceptions
  (no external surface, no new endpoint, parameterized SQL throughout).
hard_ship_gate: |
  1. Literal `pytest tests/test_vault_scanner.py -v` GREEN — 19/19 PASS
     (16 existing + T17/T18/T19 from Part B5). Output in PR description.
  2. `scripts/check_singletons.sh` PASS.
  3. `python3 scripts/backfill_assigned_to.py` (no args, dry-run) runs
     cleanly + emits proposal file path. Literal output (or first 100
     rows + "+N more" tail) pasted in ship report.
  4. Bucket counts M / A / U from dry-run included in ship report.
  5. If Part B4 doc-comment was reverted (migration applied to prod
     already), note in ship report.
scope: |
  baker-master: triggers/vault_scanner.py (MED1+MED2+LOW3 = ≤15 LOC),
  migrations/20260513_scanner_run_log.sql (LOW4 comment ONLY if not yet
  applied — verify first via applied_migrations.lock), tests/test_vault_scanner.py
  (+3 tests T17-T19), scripts/backfill_assigned_to.py (NEW ~150 LOC).
  baker-vault: _ops/processes/deadline-system-contract-v1.md (append
  v1.5 backfill execution log section with bucket counts).
  NO touching: embedded_scheduler.py, scheduler_lease.py, other migrations,
  existing scanner tests T1-T16, Render env.
coordination: |
  Independent. b1/b2/b4 not blocked. Director-ratification gate sits
  between b3's dry-run output and the bulk UPDATE apply (AH1 drives apply).
  Render flip back to VAULT_SCANNER_ENABLED=true is AH1's step AFTER
  ratified apply lands.
ship_report_to: |
  Bus-post to `lead` on completion with topic `ship/DEADLINE_ASSIGNED_TO_BACKFILL_1`.
---

# Dispatch notice

Read `briefs/BRIEF_DEADLINE_ASSIGNED_TO_BACKFILL_1.md` end-to-end before starting.

Pre-flight:
1. `cd ~/bm-b3 && git pull --ff-only origin main` (lesson: 2026-05-03 local checkout drift).
2. Verify `triggers/vault_scanner.py` line numbers in the brief still resolve (B-code may need to re-grep post-merge if intermediate work shifted them; brief is post-v0.1-fold).
3. **Migration applied check** (CRITICAL — Part B4): before editing `migrations/20260513_scanner_run_log.sql`, check `applied_migrations.lock` + `git log` to confirm migration NOT YET APPLIED to prod. The Render scanner is currently disabled via env-var kill-switch (set by AH1 2026-05-13); the migration likely IS applied because Render auto-deployed `705de3f` before the kill-switch. If applied → revert Part B4 to "no DDL change," capture as v2 doc-only.
4. Verify `baker-vault/_ops/agents/_desk-matter-map.yml` exists. If not, surface to AH1 before drafting the backfill script — the brief assumes this map is canonical.

Safety rails on the backfill script (Part A1) are mandatory:
- Default = DRY RUN.
- `--apply` requires explicit flag + ratified-mapping-file path + file <24h old.
- `BAKER_BACKFILL_DRY_RUN_ONLY=1` blocks apply entirely.
- Do NOT run `--apply` yourself — AH1 drives that step after Director ratifies.

End-of-work: bus-post to `lead` with the literal pytest output + dry-run path + bucket counts.
