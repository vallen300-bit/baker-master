---
status: PENDING
brief: briefs/BRIEF_APSCHEDULER_VAULT_SCANNER_V1.md
trigger_class: TIER_B_SCHEDULER_PLUS_EXTERNAL_SURFACE
dispatched_at: 2026-05-13
dispatched_by: ai-head-1 (AH1)
target: b3
director_ratification: |
  Director 2026-05-13 "go" — post AH1 engineering eval of MOVIE Desk
  scheduled-tasks architecture review. Three-tier frame ratified.
  This brief is 2 of 3 in v1 dispatch — the messenger piece.
priority: P2
phase: 1 of 1
expected_pr_count: 1 (baker-master) + 1 small vault commit (schedule-registry.yml)
expected_branch: b3/apscheduler-vault-scanner-1
expected_complexity: medium (~4h B-code; APScheduler job + scan logic + tests + Slack push)
mandatory_2nd_pass: TRUE
mandatory_2nd_pass_reason: |
  PR touches (1) external surface = Slack DM push primitive, (2) scheduler
  ordering = job registration + startup catch-up race. Both fall under
  SKILL.md §Code-reviewer 2nd-pass Protocol fire conditions.
hard_ship_gate: |
  1. Literal `pytest tests/test_vault_scanner.py -v` GREEN output (all 8
     tests pass) MUST be pasted in PR description.
  2. `scripts/check_singletons.sh` pass.
  3. Path-traversal hardening verified: `desk` name must match `^[a-z0-9-]+$`
     and resolve to direct subdirectory (no symlink follow) before any
     file write or path join.
scope: |
  baker-master: triggers/embedded_scheduler.py (register new job + startup
  catch-up), triggers/vault_scanner.py (NEW module), tests/test_vault_scanner.py
  (NEW), requirements.txt (PyYAML if not present).
  baker-vault (small commit): _ops/processes/schedule-registry.yml (add
  vault_scanner_daily entry).
  NO outputs/dashboard.py edits. NO models/deadlines.py edits.
  NO new DB tables.
coordination: |
  Dependency: Brief 1 (b2, VAULT_TASKS_SCHEMA_V1) should merge FIRST so
  the scanner has _ops/agents/<desk>/tasks/active/ to scan. If b3 lands
  first, gate behind VAULT_SCANNER_ENABLED=false Render env until Brief
  1 lands; AH1 sets the env post-merge.
  Independent of Brief 3 (b4, HARD_DEADLINE_AUDIT_V1) — scanner just
  sees zero deadlines if Brief 3 hasn't landed yet.
security_review: |
  /security-review MANDATORY per SKILL.md §Security Review Protocol.
  Touches external surface (Slack DM), scheduler primitives, vault file
  writes, DB read.
ship_report_to: |
  Bus-post to `lead` on completion with topic `ship/APSCHEDULER_VAULT_SCANNER_V1`.
---

# Dispatch notice

Read `briefs/BRIEF_APSCHEDULER_VAULT_SCANNER_V1.md` end-to-end before starting.

Pre-flight:
1. `git pull --ff-only origin main` in `~/bm-b3` (lesson: 2026-05-03 local checkout drift).
2. Verify `triggers/embedded_scheduler.py` line numbers in the brief still resolve (lesson: outputs/dashboard.py:N drift; embedded_scheduler.py is less volatile but verify anyway).
3. Verify PyYAML in `requirements.txt` before adding — likely already there.

Test discipline: literal pytest output required. No "by inspection." 8 specific test scenarios listed in brief §Test plan — all 8 must execute.

End-of-work: bus-post to `lead` with the literal pytest output + /security-review verdict.
