# BRISEN_LAB_WAKE_CLASSIFIED_SET_DRIFT_FIX_1

**Repo:** `brisen-lab` (base `main` @f974731) · **Worker:** b3 · **Dispatcher:** lead (AH1)
**Recommended effort:** low (4-slug set addition + test rerun; runtime behavior unchanged)
**Origin:** lead audit 2026-07-04 — pre-existing test drift found during telemetry-brief anchor pass; queued behind #96, now unblocked.

## Problem

`bus.py:212` `_WAKE_VISIBLE_SLUGS` / `:216` `_WAKE_STEALTH_SLUGS` have drifted behind the generated registry. `tests/test_wake_background_nonintrusive.py::test_classified_sets_cover_wakeable_except_noops` asserts classified ∪ {cowork-ah1} covers `WAKEABLE_TERMINALS`; four slugs are now unclassified:

- `baden-baden-desk`, `movie-desk` — desk seats (added post-classification)
- `ben` — finance specialist (added #94)
- `deep55` — added post-classification

Runtime is SAFE today (unclassified → VISIBLE by design, STEALTH-complement predicate) — this is documented-set + test drift, not a live bug. Test only fires with `TEST_DATABASE_URL` set (skips locally), so CI/live-PG runs are where it bites.

## Task (single)

Add the 4 slugs to `_WAKE_VISIBLE_SLUGS` in `bus.py` — all four are Director-facing/desk seats, matching the existing pattern (`hag-desk`, `ao-desk`, `aid` are VISIBLE). If registry metadata for `deep55` says worker-class instead, put it in STEALTH and say so in the ship report. Update the block comment's exclusion note if wording needs it. No logic changes.

## Constraints

- `bus.py` classified-set literals + comment ONLY. Do NOT touch the predicate, hooks, or `agent_identity_generated.py`.
- Runtime behavior must be byte-identical for VISIBLE placements (unclassified already renders VISIBLE).

## Acceptance criteria

1. `TEST_DATABASE_URL=... pytest tests/test_wake_background_nonintrusive.py -q` — all pass, 0 skipped-by-drift.
2. Full suite green.
3. Ship report states classification rationale per slug (one line each).
4. Post-deploy AC: N/A (no behavior change) — state explicitly per `post-deploy-ac-bus-gate`.

## Notes for worker

- Branch: `b3/wake-classified-set-drift-fix-1`. PR to `main`, ship report + gate to lead on bus.
- Gate: codex, effort=low (set-literal diff).
