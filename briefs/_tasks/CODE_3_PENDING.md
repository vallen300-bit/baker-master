---
status: PENDING
brief: briefs/BRIEF_STATE_RECONCILER_1.md
brief_id: STATE_RECONCILER_1
target_branch: b3/state-reconciler-1
target_repo: baker-vault (NOT baker-master — reconciler code lives in ~/baker-vault/_ops/reconciler/, hooks in ~/baker-vault/.githooks/)
matter_slug: baker-internal
cross_matter_usage: [mrci, aukera, lilienmatt, capital-call, annaberg, mo-vie-am, hagenauer-rg7, oskolkov]
dispatched_at: 2026-05-18T09:55:00Z
dispatched_by: lead
director_auth: 2026-05-18 chat — "go with your recomendations" (post Amendment §0 + §0.8 Path A presentation; ratifies §0 schema + Path A skip-and-log)
trigger_class: HIGH (cross-file state propagation + new git-hook surface + 8-matter migration + nightly cron on Mac Mini; mandatory 4-gate review per SKILL.md §"Code-reviewer 2nd-pass Protocol")
ratified_amendments:
  - amendment_section: "§0 template-schema"
    author: AH1
    commit: 446cacb
    director_ratified: 2026-05-18
  - amendment_section: "§0.8 Path A (accept Tier-3 skips as drift signal)"
    director_ratified: 2026-05-18
prior_brief_complete: |
  GROK_API_HARDENING_1 shipped + merged as PR #217 → 468965a on 2026-05-18.
  Mailbox slot reclaimed for this dispatch.
estimated_time: ~8 builder-days
---

# Dispatch: STATE_RECONCILER_1

B3 — full brief at `briefs/BRIEF_STATE_RECONCILER_1.md` (commit `446cacb`).

**TL;DR:** Phase 1 of the state-architecture rebuild. Build the cortex-config reconciler that auto-regenerates the "recent ratifications" auto-region of 8 matter cortex-configs from `curated/06_decisions_log.md`. Fires on pre-commit + nightly cron. Closes the Aukera-25-day-stale class of drift incidents.

## Working repo

**baker-vault**, NOT baker-master. Code lives in `~/baker-vault/_ops/reconciler/`; hooks in `~/baker-vault/.githooks/`; tests in `~/baker-vault/tests/test_state_reconciler.py`. Use existing clone at `~/bm-b3-baker-vault` if present; otherwise fresh-clone `https://github.com/vallen300-bit/baker-vault` to a worktree.

## Director-ratified amendments to read FIRST

1. **§0 template-schema** (commit `446cacb`) — the authoritative contract for region format, body grammar, frontmatter contract, sort+cap, schema-version rules, hook/cron identity. If §0 and Step 3 code disagree, §0 wins; surface to lead via mailbox UPDATE before opening PR.

2. **§0.5 revised decision parser** — two-tier ID format (`D-NNN` and `DN`); three-tier date extraction (heading paren → body fallback → skip-and-log). The original Step 3 single-regex is retained as reference but SHALL NOT be implemented as-is.

3. **§0.8 Path A ratified** — accept Tier-3 un-parseable skips as drift signal. Do NOT pre-canonicalize decision-log headings. Survey pass in Step 2 still runs (read-only diagnostic for the Director-facing migration paste-block).

## Ship gate (literal)

1. `pytest tests/test_state_reconciler.py -v` shows **28 passed** (was 22; six new `TestDecisionParsing` cases added by §0.5).
2. Dry-run on actual 8 matters returns zero `error_*` statuses (Step §Verification).
3. Step 2 migration diff paste-block surfaced to lead BEFORE B3 stages the migration commit (Director ratifies migration shape).
4. Survey output `/tmp/state_reconciler_survey.md` attached to ship report.
5. Pre-commit hook synthetic verification (Step §Verification "D-999 fold → cortex-config auto-updates") captured in ship report.

## Reporting

- Bus-post **`lead`** (per `dispatched_by:` field) on PR open with topic `pr-open/state-reconciler-1`.
- AH1 fires the full 4-gate chain (cross-lane static + `/security-review` + picker-architect + `feature-dev:code-reviewer` 2nd-pass) per HIGH trigger class.
- LaunchAgent install on Mac Mini is **AH1 Tier-B**, post-merge — not B3's lane.

## Anchors

- 2026-05-17 mapping session (Director + AH1 6-Q ratification).
- 2026-05-18 Director — "go with your recomendations" (ratifies §0 + §0.8 Path A).
- AID delegation withdrawn 2026-05-18 (bus #389) — template-schema authored inline by AH1.
- Engineering audit `_ops/reviews/2026-05-17-ah1-engineering-audit-aid-state-architecture-note.md`.
