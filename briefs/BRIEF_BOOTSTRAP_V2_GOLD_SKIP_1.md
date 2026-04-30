# BRIEF — BOOTSTRAP_V2_GOLD_SKIP_1

**Owner:** B-code (assigned: B4)
**Author:** AI Head A (App)
**Drafted:** 2026-04-30
**Priority:** HIGH
**ETA:** 2026-05-02
**Roadmap item:** `bootstrap-v2-gold-skip` (V4 queued)

## Problem

`scripts/bootstrap_matter.py` (you shipped CORTEX_BOOTSTRAP_MATTER_1, PR #96) emits `gold.md` on every new matter creation. This caused 4 manual `gold.md` removal drops today across `capital-call`, `aukera`, `uk-homes`, and the 12-matter batch.

The CHANDA #4 `author:director` guard (`hooks/author_director_guard.sh`) blocks any agent-authored `gold.md` commit anyway — emission is wasted work that the guard then forces a manual revert on.

## Goal

`bootstrap_matter.py` auto-skips `gold.md` emission. Matter directory still bootstraps cleanly without `gold.md`.

## Scope (~30 min)

1. Locate the `gold.md` emission in `scripts/bootstrap_matter.py` (likely a fixture write or `Path.write_text` call near the per-matter file fan-out).
2. Remove or guard the `gold.md` write. Recommended: remove entirely — Director writes `gold.md` manually when ratifying.
3. Verify the rest of the matter directory structure still emits correctly (e.g., `hot.md` symlink, `_priorities.yml` row, `proposed-gold.md`, etc. — confirm by reading PR #96 spec or running the script locally on a synthetic test matter).
4. Update any test fixtures in `tests/scripts/test_bootstrap_matter.py` (or equivalent) that asserted `gold.md` presence; flip them to assert absence.

## Test plan

1. Bootstrap a synthetic test matter:
   ```
   cd ~/Desktop/baker-code && python3 scripts/bootstrap_matter.py --slug test-gold-skip --dry-run
   ```
   Confirm `gold.md` is NOT in the output file list.
2. Run pytest on bootstrap tests: `pytest tests/scripts/test_bootstrap_matter.py -v`. Pre-pytest re-checkout ritual applies.
3. Sanity check: bootstrap an actual matter dir on a feature branch (NOT main), confirm directory structure looks correct, then revert.

## Done definition

- PR opened with diff + test-plan output.
- pytest green.
- AI Head A reviews + merges.

## Trigger-class consideration

Touches CHANDA author:director guard surface (Director-override scope). **B1 second-pair-of-eyes review BEFORE AI Head A merge** per B1 situational review trigger 2026-04-24.

Dispatch sequence:
1. B4 builds + opens PR.
2. AI Head A pings B1 for review.
3. B1 PASS → AI Head A merges. B1 REQUEST_CHANGES → B4 patches → re-loop.
