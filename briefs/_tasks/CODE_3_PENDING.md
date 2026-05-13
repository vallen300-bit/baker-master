---
status: COMPLETE
brief: briefs/BRIEF_DEADLINE_FEEDBACK_LOOP_1.md
brief_id: DEADLINE_FEEDBACK_LOOP_1
trigger_class: TIER_B_DB_MIGRATION_+_DASHBOARD_UI_+_ENDPOINT
dispatched_at: 2026-05-13
dispatched_by: ai-head-1 (AH1)
target: b3
mandatory_2nd_pass: true
security_review_required: true
effort_estimate: ~4h
completed_at: 2026-05-13
pr: 203
pr_state: OPEN (AWAITING_REVIEW — AH1/AH2 own merge)
ship_commit: c6bf0c6
report: briefs/_reports/B3_DEADLINE_FEEDBACK_LOOP_1_20260513.md
bus_msg: 226
predecessor:
  brief: briefs/BRIEF_DEADLINE_SIGNAL_HYGIENE_1.md
  pr: 202
  merge_commit: 6c31b057
  director_apply: 2ed9896 (Scope C 352/352 applied 2026-05-13)
ratified_spec: _ops/ideas/2026-05-13-smart-signal-classification.md
director_ratification: |
  2026-05-13 — "Rest is okay. All ratified." (4-phase sequencing Q1-Q4 + Gemini
  Flash/Pro stack swap on smart-signal-classification spec).
scope_summary:
  part_1: NEW migration 20260513b_deadline_feedback.sql (1 table + 3 indexes)
  part_2: NEW models/deadline_feedback.py + NEW endpoint POST /api/deadlines/{id}/feedback + NEW GET /api/slug-registry + AUGMENT existing /dismiss + /complete to write corpus rows
  part_3: 2 new buttons on deadline-card triage bar + XSS-safe DOM-constructed wrong-matter dropdown
  part_4: NEW tests/test_deadline_feedback.py (≥7 tests, mix of unit + live-PG)
followup_brief: SIGNAL_CLASSIFIER_TIER2_1 (gated on 2+ weeks click corpus from THIS brief)
ship_gate: literal pytest -v output paste + check_singletons PASS + py_compile on both modified .py files
bus_topic: ship/DEADLINE_FEEDBACK_LOOP_1
---

# CODE_3_PENDING — DEADLINE_FEEDBACK_LOOP_1

Read `briefs/BRIEF_DEADLINE_FEEDBACK_LOOP_1.md` for full spec.

## Confirmation phrase
`"B3 oriented. Read: CODE_3_PENDING.md, MEMORY.md."`

## Working dir
`~/bm-b3` — branch off `main` after `git pull --ff-only`. Suggested branch: `b3-deadline-feedback-loop`.

## What ships (single PR, 4 parts)

1. **Migration** — `migrations/20260513b_deadline_feedback.sql` (1 new table, 3 indexes). Verify post-deploy via `information_schema.columns`.
2. **Backend** — `models/deadline_feedback.py` (NEW), `outputs/dashboard.py` (1 new POST + 1 new GET + augment 2 existing POSTs). `Request` already imported at dashboard.py:21 (verified).
3. **Frontend** — `outputs/static/app.js` (2 button additions + 4 new functions, all XSS-safe via DOM construction, NO innerHTML on dynamic content); `outputs/static/index.html` cache bump `?v=112` → `?v=113`.
4. **Tests** — `tests/test_deadline_feedback.py` (NEW). At minimum: invalid-type rejection, unknown-slug normalize-to-None, round-trip insert, endpoint write, 400 on bad verb, backward-compat dismiss/complete corpus capture.

## What does NOT ship (AH1 owns / out of scope)

- Phase 3 Gemini classifier upgrade (`SIGNAL_CLASSIFIER_TIER2_1`) — separate brief, gated on 2+ weeks of click corpus from THIS brief
- Phase 4 multi-dim envelope JSONB column on deadlines / signal_queue — phase 4 brief, after phase 3 proves out
- Touching `_match_matter_slug()` / classifier code in `orchestrator/pipeline.py` — phase 3 territory
- Touching `outputs/static/mobile.html` / `mobile.js` — they don't render deadlines (verified clean grep)
- Touching `models/deadlines.py` table-creation bootstrap — migration owns the new table

## Hard constraints

- **No `innerHTML` on dynamic content.** Build the wrong-matter dropdown via `document.createElement` + `option.value` / `option.textContent` + `appendChild`. Static-ASCII button labels in `_landingTriageBar` can keep the existing string-concat pattern (consistent with surrounding code). See brief §Part 3 §XSS discipline.
- **`insert_feedback` is fault-tolerant.** Failures inside it return `None` + log; they MUST NOT raise to the calling endpoint. Augmented `/dismiss` and `/complete` must continue to flip status even if the feedback write fails (existing user-facing behavior preserved).
- **`conn.rollback()` in every except block** on DB code paths (Python backend rule).
- **`LIMIT` on every SELECT** including `get_recent_feedback` (Python backend rule — capped at 100 default).
- **Ship gate is literal `pytest -v` output.** No "pass by inspection" — REQUEST_CHANGES if claimed.

## 2nd-pass code-reviewer (MANDATORY)

This brief touches DB schema (migration trigger #2 per `/security-review` 2nd-pass protocol). After AH2 static + AH2 `/security-review` + picker-architect verdicts land, AH1 fires `feature-dev:code-reviewer` agent with the 6-line output contract. All 4 gates must clear before merge.

## Bus post on ship

```bash
BAKER_ROLE=b3 ~/Desktop/baker-code/scripts/bus_post.sh lead \
  "PR #<N> OPEN — DEADLINE_FEEDBACK_LOOP_1. Migration 20260513b_deadline_feedback applied via deploy. <K>/<K> tests PASS. check_singletons PASS. New endpoints registered: POST /api/deadlines/{id}/feedback + GET /api/slug-registry. /dismiss + /complete now write 'mute' / 'confirm' corpus rows (backward compat preserved)." \
  ship/DEADLINE_FEEDBACK_LOOP_1
```

## Verification SQL (post-deploy)

Run as part of ship-report — paste output back to lead:

```sql
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'deadline_feedback' ORDER BY ordinal_position;
-- Expect 9 rows.

SELECT feedback_type, COUNT(*) FROM deadline_feedback GROUP BY feedback_type;
-- Probably 0 rows pre-traffic. That's fine — confirms table exists + index works.
```
