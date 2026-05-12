---
status: PENDING
brief: briefs/BRIEF_VAULT_TASKS_SCHEMA_V1.md
trigger_class: TIER_B_VAULT_SCHEMA_INFRA
dispatched_at: 2026-05-13
dispatched_by: ai-head-1 (AH1)
target: b2
director_ratification: |
  Director 2026-05-13 "go" — post AH1 engineering eval of MOVIE Desk
  scheduled-tasks architecture review (architecture doc at
  https://brisen-docs.onrender.com/architecture/scheduled-tasks-architecture.html).
  Three-tier frame ratified (vault soft tasks / Baker hard deadlines /
  APScheduler recurring). This brief is 1 of 3 in v1 dispatch.
priority: P2
phase: 1 of 1
expected_pr_count: 1 (baker-vault — vault-only brief)
expected_branch: b2/vault-tasks-schema-1
expected_complexity: low (~2h B-code; markdown + 1 Python lint script)
mandatory_2nd_pass: FALSE
hard_ship_gate: |
  Literal output of `python3 scripts/validate_vault_tasks.py` exit 0
  against the MOHG-debrief seed file MUST be pasted in ship report.
  No "by inspection."
scope: |
  Pure markdown + 1 Python lint script in baker-vault repo.
  Creates _ops/agents/movie-desk/tasks/active/ directory + first task
  (MOHG-debrief migration) + closure protocol docs + slugs.yml validator
  + empty schedule-registry.yml placeholder.
  NO baker-master touches. NO Render env changes. NO DB writes.
coordination: |
  Independent of Brief 2 (b3, APSCHEDULER_VAULT_SCANNER_V1) + Brief 3
  (b4, HARD_DEADLINE_AUDIT_V1). However Brief 2's scanner cannot run
  successfully until this brief merges (no tasks/active/ to scan).
  Recommended merge order: this brief FIRST.
ship_report_to: |
  Bus-post to `lead` on completion with topic `ship/VAULT_TASKS_SCHEMA_V1`.
  Bus-posting contract: _ops/processes/agent-bus-posting-contract.md.
---

# Dispatch notice

Read `briefs/BRIEF_VAULT_TASKS_SCHEMA_V1.md` end-to-end before starting.

Vault checkout at `~/baker-vault` — confirm `git status` clean + `git pull --ff-only origin main` before first edit (lesson: 2026-05-03 local checkout drift).

Single atomic commit covering all 6 created files + 1 lint script. Push to `baker-vault` `main` (no PR — vault is direct-push by convention; Mac Mini single-writer pattern applies).

End-of-work: bus-post to `lead` with the literal `validate_vault_tasks.py` output.
