---
status: REQUEST_CHANGES_ROUND_1
prior_round: AWAITING_REVIEW (PR #212 @81cb7be, then 5d5a855)
round_2_dispatched_at: 2026-05-17T11:35:00Z
round_2_dispatched_by: ai-head-1 (AH1)
round_2_findings:
  medium:
    - id: M1
      severity: MEDIUM
      file: triggers/state_drift_audit.py
      function: _discover_matters + _audit_matter + _newest_decision_date
      finding: |
        _is_safe_slug rejects symlinked matter DIRECTORIES via is_symlink() check
        on matter_path. BUT _discover_matters then evaluates
        (matters_dir / name / "cortex-config.md").is_file() — and Path.is_file()
        FOLLOWS symlinks. A symlinked cortex-config.md → /etc/passwd (or any
        host file) passes discovery, then _audit_matter calls read_text() on it.
        Same shape applies to curated/06_decisions_log.md path in
        _newest_decision_date.
      current_blast_radius: |
        NO content exfiltration today — yaml.safe_load on non-frontmatter
        falls through to "missing/malformed frontmatter" note; bytes don't echo
        anywhere. BUT this is the exact shape Director scarred yesterday on
        PR #210 — Lesson #65 was added for this. Future extensions (logging
        frontmatter snippets, quoting a parsed line in the report) make it
        exploit-worthy.
      fix: |
        In _audit_matter (immediately before read_text on cortex_config_path):
          if cortex_config_path.is_symlink():
              result.notes.append("cortex-config.md is a symlink — skipped")
              return result
        Same shape in _newest_decision_date (before read_text on
        decisions_log_path):
          if decisions_log_path.is_symlink():
              return None  # logged at debug; classified as missing_decisions_log
        One-line fix per file + 1 parametrised test covering both
        (symlinked-cortex-config + symlinked-decisions-log).
      anchor: AH2 cross-lane bus #332 + Lesson #65 (ratified 2026-05-16, still warm)
ship_gate_round_2: |
  Literal pytest output, 9/9+ green (8 existing + 1+ new for symlink guard):
    pytest tests/test_state_drift_audit.py -v
  Test must cover both file-level symlinks: cortex-config.md AND
  curated/06_decisions_log.md. Parametrise with the existing tmp_path/synth_vault
  fixture; create os.symlink targets pointing at /etc/passwd or a sibling temp file.
brief: briefs/BRIEF_STATE_FILE_REFRESH_1.md
brief_id: STATE_FILE_REFRESH_1
trigger_class: MEDIUM (new APScheduler job + ClickUp write + vault filesystem scan)
dispatched_at: 2026-05-17T08:30:00Z
dispatched_by: ai-head-1 (AH1)
target: b1
prior_brief_complete: |
  AO_PM_READ_CURATED_WIKI_1 (PR #210 merged 2026-05-16T13:34Z, v2 at b2e6f35).
  Mailbox FREE since 2026-05-16 13:34Z.
context: |
  Three drift scars in two weeks — 2026-05-10 stale tracker labels, 2026-05-15
  Aukera deadline 25-day stale, 2026-05-15 CYCLE_REGISTER 5-day stale →
  b3 duplicate dispatch. All traced to the same class: cortex-config.md
  snapshots drift from authoritative state (curated/06_decisions_log.md).
  No mechanical detection layer below "agent eyeballs it before acting."

  Director-ratified 2026-05-17 state-architecture mapping session (6 Q's:
  Q1 commit-hook + nightly cron, Q2 baker-vault repo, Q3 AID designs / AH1
  architects / B-code builds / Director ratifies output, Q4 start this week
  parallel to ClaimsMax B4, Q5 defer cycle-register-shape question, Q6 ratify
  OPERATING.md split pattern fleet-wide upfront).

  This brief = Option B bridge (audit-only, ~2 builder-days). Covers the 3-4
  week window during BRIEF_STATE_RECONCILER_1 Phase 1 build. Read-only against
  baker-vault. Posts daily summary to existing ClickUp `drift-sentinel` task
  (86c9k6kau, shared with roadmap-drift sentinel; comments prefixed
  `[state-drift]` to disambiguate).

  Inputs to this brief:
   - AID state-architecture research note: wiki/_ai-it/aid-t/library/state-architecture-best-practice-2026-05-16.md
   - AH1 engineering audit of AID: _ops/reviews/2026-05-17-ah1-engineering-audit-aid-state-architecture-note.md
   - 2nd-pair-of-eyes pass (code-reviewer + architect, 2026-05-17): folded
     1 CRITICAL (invented ClickUp helper -> real ClickUpClient pattern) +
     1 MEDIUM (UTC date drift) + 1 cross-brief integration (heartbeat audit
     for Brief 2 reconciler liveness).
review_chain:
  - AH2 cross-lane review (substantive Tier-B; new external surface = ClickUp post)
  - /security-review (vault filesystem scan; slug input from listdir filtered
    via SLUG_RE allow-list per existing vault_scanner.py pattern)
  - feature-dev:code-reviewer 2nd-pass per SKILL.md if AH2 review opens
    architectural questions on the PR diff
  - AH1 final merge sign-off
ship_gate: |
  Literal pytest output, 8/8 green:
    pytest tests/test_state_drift_audit.py -v
  NOT "by inspection." Lesson #8 hard rule.
acceptance:
  - 8 of 8 tests pass on literal pytest run (test names enumerated in brief
    Verification - Local pytest section)
  - Job registered in embedded_scheduler.py at 03:00 UTC daily with the
    log line "Registered: state_drift_audit (daily at 03:00 UTC)"
  - Manual fire (python3 -c "from triggers.state_drift_audit import
    run_state_drift_audit; run_state_drift_audit()") produces a markdown
    report at ~/baker-vault/_ops/reports/state-drift-YYYY-MM-DD.md
  - State file at ~/baker-vault/_ops/agents/_scanner-state/state-drift-last-run.json
    written atomically (temp + os.replace)
  - ClickUp post lands ONLY when there are new drift candidates OR
    layout-class anomalies vs last-run state file
  - Cross-brief hook _check_reconciler_heartbeat function present + wired
    into the post body when Brief 2 reconciler-heartbeat.json exists +
    is >36h stale (returns None silent pre-Phase-1 ship - no false-alarm)
estimated: medium / ~2 builder-days / 1 PR / Tier-B
branch_suggestion: b1/state-file-refresh-1
mandatory_2nd_pass: true
security_review_required: true
director_anchor: |
  Director-ratified 2026-05-17: 6-Q mapping session, then explicit "go ahead"
  on the brief + 2nd-pair-of-eyes folded findings paste-block.
  Standing skepticism rule: AID is not a qualified engineer; his proposals
  require AH1 engineering proof-pass. Applied same skepticism to MY brief
  output via code-reviewer + architect 2nd-pass - folded all CRITICAL +
  HIGH + MEDIUM before dispatch.
---

# CODE_1_PENDING - STATE_FILE_REFRESH_1 (Option B bridge) - 2026-05-17

Brief: `briefs/BRIEF_STATE_FILE_REFRESH_1.md`
Working branch suggestion: `b1/state-file-refresh-1`
Acceptance criteria: see frontmatter `acceptance:` block + brief Verification section.
Ship gate: literal `pytest tests/test_state_drift_audit.py -v` 8/8 green. No "by inspection" (Lesson #8).
Pre-merge: mandatory `/security-review` + AH2 cross-lane review per `review_chain`.

## What to read before claiming

1. The brief itself: `briefs/BRIEF_STATE_FILE_REFRESH_1.md` (full design + code snippets + tests).
2. Reference precedent: `triggers/vault_scanner.py` (the canonical pattern this brief mirrors - path-traversal protection, frontmatter parser, marker-file pattern).
3. ClickUp post pattern: `orchestrator/roadmap_drift_sentinel.py:196-214` (canonical `ClickUpClient._get_global_instance().post_comment(DRIFT_TASK_ID, body)` pattern).
4. APScheduler registration: `triggers/embedded_scheduler.py` (slot the new job after `clickup_poll` block).

## Cross-brief coordination

BRIEF_STATE_RECONCILER_1 (B-code TBD when AID template-schema lands) builds the Layer C reconciler in parallel. This brief `_check_reconciler_heartbeat` function reads the reconciler heartbeat file once Phase 1 ships - pre-Phase-1 it returns None silently (no false alarms while Layer C does not exist yet).

Both briefs commit to baker-vault - but only Brief 2 writes the heartbeat. This brief READS it (read-only across the cross-brief boundary).

## Notes

Director directive 2026-04-30 (drift detection -> ClickUp recurring task, NOT Slack) is HARD - do NOT add Slack DMs to this audit.

The brief includes a "Sunset / repositioning" section explaining how this 2-day audit rescopes to a ~0.5-1 day diff-job audit after Phase 1 reconciler ships. Code is not throwaway; rescope is in-place.

Claim by editing this file frontmatter: status PENDING -> CLAIMED + claimed_at timestamp.
