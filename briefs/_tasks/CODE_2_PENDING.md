# CODE_2 — PENDING (ROADMAP_DRIFT_CLICKUP_SENTINEL_1)

**Status:** PENDING — dispatched 2026-04-30 by AI Head A (App)
**Brief:** `briefs/BRIEF_ROADMAP_DRIFT_CLICKUP_SENTINEL_1.md`
**Builder:** B2
**Priority:** MEDIUM
**ETA:** 2026-05-03

## Task summary

Daily 06:00 UTC sentinel comparing `cortex-roadmap-current.yml` last-edit vs PR merge cadence on baker-vault + baker-master. If ≥5 PRs merged without YAML update → write comment on recurring ClickUp task `86c9k6kau` (drift sentinel). NO Slack — Director rule 2026-04-30.

## Dispatch

1. Read brief: `briefs/BRIEF_ROADMAP_DRIFT_CLICKUP_SENTINEL_1.md`
2. Branch: `b2/roadmap-drift-clickup-sentinel`
3. Coordinate with B3 on advisory_lock key choice (B3 is renumbering 900300 in parallel — pick a distinct key, e.g. 900900, after re-grepping post-B3 merge).
4. Pre-pytest re-checkout ritual.
5. AI Head A solo review (non-trigger-class).

## Previous task (closed)

PR #81 (CORTEX_SLACK_INTERACTIVITY_1) squash-merged 2026-04-29.
