---
status: COMPLETE
completed_at: 2026-05-12T23:39:50Z
merge_commit: 31158996a820d0c1e412160fd8ed3cc4e524d6fd
pr: 198
ship_report: briefs/_reports/B4_hard_deadline_audit_v1_20260513.md
vault_audit_doc: _ops/processes/deadline-system-contract-v1.md @ 32e42ec (baker-vault main)
db_row: deadlines.id = 1524 (residence-fee deferral 31.12.2026; movie-desk / mo-vie-am)
hard_ship_gate: PASS (4/4 — see ship report)
v1_5_trigger: FIRED — P=2.9% << 50% → triggered CODE_3_PENDING (DEADLINE_ASSIGNED_TO_BACKFILL_1, shipped PR #199)
brief: briefs/BRIEF_HARD_DEADLINE_AUDIT_V1.md
trigger_class: TIER_B_AUDIT_PLUS_DB_WRITE
dispatched_at: 2026-05-13
dispatched_by: ai-head-1 (AH1)
target: b4
update_at: 2026-05-13
update_reason: |
  Post AH1 architecture-review (Director-ratified same session, verdict
  "accept-with-changes"). One amendment folded as
  "## UPDATE — 2026-05-13" section in brief end. Adds ~15 min effort.
  Closes 1 HIGH concern (assigned_to population gap -> scanner silent
  under-reporting). Q5 now requires quantitative output (% population
  rate) + v1.5 backfill trigger if P < 50%.
  READ the UPDATE section FIRST.
director_ratification: |
  Director 2026-05-13 "go" — post AH1 engineering eval of MOVIE Desk
  scheduled-tasks architecture review. Three-tier frame ratified.
  This brief is 3 of 3 in v1 dispatch.
  Director "ratified" 2026-05-13 same session — architecture-review
  amendment (above) folded in pre-build.
priority: P2
phase: 1 of 1
expected_pr_count: 0 (audit doc commits to baker-vault directly; DB write is runtime via MCP)
expected_branch: none (vault direct-push; no baker-master PR)
expected_complexity: low (~2.25h B-code; grep + write doc + 1 MCP call + 1 SQL UPDATE + 1 quantitative Q5 query + conditional v1.5 trigger)
mandatory_2nd_pass: FALSE
hard_ship_gate: |
  1. `_ops/processes/deadline-system-contract-v1.md` committed to
     baker-vault main, covering all 7 questions in brief Part 1 with
     file:line citations.
  2. Literal SELECT verification output pasted in ship report:
     SELECT id, description, due_date, priority, severity, status,
            assigned_to, matter_slug
     FROM deadlines
     WHERE description LIKE '%residence fee%';
     Must return exactly one row, all fields populated.
  3. AH1 spot-check: 3 random file:line citations from the audit doc
     resolve to the actual claimed content.
  4. Q5 quantitative output: literal SQL + literal row output pasted in
     the audit doc (assigned_to + matter_slug population percentages).
     If P < 50%, the v1.5 follow-up section is appended to the audit
     doc per brief UPDATE.
scope: |
  baker-vault: ONE new doc at _ops/processes/deadline-system-contract-v1.md.
  Baker DB: insert + update ONE row in `deadlines` table (residence-fee
  deferral 31.12.2026).
  NO baker-master code changes. NO MCP signature extension. NO new nudge
  stages (audit only — gaps surfaced as v2 follow-up list, not implemented).
coordination: |
  Independent of Brief 1 (b2) + Brief 2 (b3). Brief 2's scanner will pick
  up the registered deadline whenever it next runs. If Brief 2 lands first
  with VAULT_SCANNER_ENABLED=false, no deadline-row drift.
audit_quality_gate: |
  Per Lesson #7 (brief file:line citation verification — anchor: AH#2
  MOVIE AM 2026-04-23 :385 cite on 154-line file). Every cite in the
  audit doc MUST be verified by opening the actual file at the actual
  line. AH1 will spot-check 3 random cites.
ship_report_to: |
  Bus-post to `lead` on completion with topic `ship/HARD_DEADLINE_AUDIT_V1`.
---

# Dispatch notice

Read `briefs/BRIEF_HARD_DEADLINE_AUDIT_V1.md` end-to-end before starting.

Pre-flight:
1. `git pull --ff-only origin main` in `~/bm-b4` (baker-master clone — for reading models/deadlines.py + grep).
2. `cd ~/baker-vault && git pull --ff-only origin main` for the audit-doc commit target.

Audit discipline:
- Open every cited file at the cited line BEFORE writing the cite. AH1 spot-checks 3 at random.
- If a feature is not found (e.g., no nudge state machine exists despite columns existing), say so explicitly + surface as v2 follow-up.
- Part 2 idempotency: if a row matching the description already exists, UPDATE its fields rather than INSERT a duplicate.

End-of-work: bus-post to `lead` with the literal SELECT output + commit SHA of the audit doc.
