# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3
**Task posted:** 2026-04-22 (post-B2 ship of PR #40)
**Status:** CLOSED — PR #40 APPROVE, Tier A auto-merge greenlit, YAML-scalar-coercion class (54% of 48h WARN) structurally cleared

---

## B3 dispatch back (2026-04-22)

**APPROVE PR #40** — all 9 focus items green, zero gating nits. Full-suite regression delta reproduced locally with cmp-confirmed identical 16-failure set. Fix unblocks 54% of 48h Step 6 WARN class (65/121 failures: deadline + source_id YAML-scalar coercion).

Report: `briefs/_reports/B3_pr40_step6_validation_hotfix_review_20260422.md`.

### Regression delta (focus 6) — reproduced locally

```
main baseline:       16 failed / 799 passed / 21 skipped / 19 warnings  (12.18s)
pr40 head 0546ab1:   16 failed / 805 passed / 21 skipped / 19 warnings  (67.06s)
Delta:               +6 passed, 0 regressions, 0 new errors
```

`+6 passed` = exactly the 6 new tests added. cmp-confirmed identical 16-failure SET. Absolute counts match B2's ship-report claim exactly.

### Per focus verdict

1. ✅ **`_deadline_coerce_to_str`.** `mode='before'`; branch table: `None`/`str` pass-through, `datetime` → `.date().isoformat()`, `date` → `.isoformat()`, else `raise TypeError`. **Critical ordering correct** — `datetime` isinstance checked BEFORE `date` (since `datetime` is a subclass of `date`, reverse order would emit `"2026-05-01T12:00:00+00:00"` and break YYYY-MM-DD regex). Chain runs before existing `_deadline_iso_date` (mode='after' default).

2. ✅ **`_source_id_coerce_to_str`.** `None`/`str` pass-through; else `str(v)`. `None` correctly fails downstream required-str check cleanly rather than masking with `NoneType not iterable`. `str(9_999_999_999)` = `"9999999999"` (exact; no scientific notation — Python int stringification is lossless).

3. ✅ **Imports.** `date` + `Any` added; both have live call sites; no circulars.

4. ✅ **`_deadline_iso_date` unchanged.** Appears only as unchanged context line after new validator block. YYYY-MM-DD regex assertion still fires on coerced string.

5. ✅ **6 tests, all exact-string equality.** Zero `isinstance` or presence-only asserts. Test #3 (`datetime(...) → "2026-05-01"`) is the highest-signal: it locks the `.date().isoformat()` path and would catch the isinstance-ordering bug.

6. ✅ **Regression delta.** +6 passed, 0 regressions, identical failure set.

7. ✅ **Scope.** 3 files (2 code + ship report). `_body_length` untouched (only pre-existing refs at line 295/322). No schema, no env vars, no Step 5/6 logic change.

8. ✅ **Part B diagnostic sound.** SQL JOIN + filter chain correct; `GROUP BY sq.id` deduplicates R3-retry WARNs (PG-specific functional-dependency shortcut — works here because `sq.id` is PK). Diagnosis holds: 13/19 full_synthesis rows have `LENGTH(opus_draft_markdown) = 0` — Step 5 empty-output problem, not body-floor issue. Recommendation ("scan `kbl_log component='step5_opus'` for those 13 signal_ids") is exactly the right next scope. 3 enumerated hypotheses cover the plausible failure modes. Secondary anomaly (1 skip_inbox row at 863 chars tripping stub-shape invariant) correctly flagged as sidebar.

9. ✅ **No ship-by-inspection.** Ship report §Full pytest carries literal counts (16/805/21) + FAILED row enumeration; phrase "by inspection" absent.

### N-nits parked (non-blocking)

- **N1:** No explicit `pytest.raises(TypeError)` negative test for `_deadline_coerce_to_str` unknown-type branch. Cheap tidy-up add.
- **N2:** Part B `GROUP BY sq.id` relies on PG functional-dependency extension (non-aggregated SELECT columns allowed with PK grouping). Works in this schema; cosmetic.
- **N3:** Ship report landed on PR branch, not pre-committed to main. Dispatch flagged; squash merge carries it. Informational.

Tier A auto-merge proceeds. Post-deploy: go-forward rows clear Step 6 R3 on deadline + source_id. 9 existing `finalize_failed` rows remain terminal (separate backfill).

**Recommended follow-up brief for AI Head:** Step 5 empty-output investigation for the 13 signal_ids from Part B. Three-branch bisect at `kbl_log component='step5_opus'`: (1) Opus API transient error, (2) 200 OK empty content, (3) Step 5 capture drops the text.

Tab quitting per §Decision.

— B3

---

## Scope

Review **PR #40** on `step6-validation-hotfix-1` @ `0546ab1`.

- URL: https://github.com/vallen300-bit/baker-master/pull/40
- Diff: 3 files, +350 / −2 (`kbl/schemas/silver.py`, `tests/test_silver_schema.py`, `briefs/_reports/B2_step6_validation_hotfix_1_20260422.md`)
- Commits: `db78ced` (fix), `0546ab1` (ship report). Both on PR branch — ship report is NOT on main (unlike PR #39's pre-open pattern).
- Brief: original `briefs/_tasks/CODE_2_PENDING.md` @ `3b772e6`

## Why this is Cortex-launch-critical

Pipeline is blocking here. Every reclaimed row from PR #39 hits Step 6 Pydantic, exhausts R3, lands at `finalize_failed`. AI Head audited `kbl_log` WARN: 54% of 121 failures are YAML-scalar-coerced `deadline` (42) + `source_id` (23). This PR fixes the deadline half fully and adds defense-in-depth for source_id.

## What to verify

1. **`_deadline_coerce_to_str` correctness** — `mode='before'` validator in `kbl/schemas/silver.py`. Accepts `str`, `None`, `date`, `datetime`; raises `TypeError` on anything else. Runs BEFORE the existing `_deadline_iso_date` str-level validator — confirm the chain order: coerce to str → assert YYYY-MM-DD. A `datetime` should produce `.date().isoformat()` (drop time component), not `.isoformat()` (would include `T00:00:00`).

2. **`_source_id_coerce_to_str` correctness** — same file, same pattern. Force-stringifies non-string input. Should also handle `None` gracefully if the field spec permits (check field default + `Optional`).

3. **Imports** — `date` from `datetime`, `Any` from `typing`. Confirm not already imported, and no circular/unused imports.

4. **Existing validator not touched** — `_deadline_iso_date` (line 179-ish) unchanged. The YYYY-MM-DD shape assertion still fires on the coerced string.

5. **6 new tests** in `tests/test_silver_schema.py`:
   - deadline: str / date / datetime inputs → all pass with proper string normalization
   - source_id: str / int / large int → all coerce to str
   - Confirm assertions are on EXACT string output, not just type (e.g., `date(2026,5,1)` → `"2026-05-01"` not just `isinstance(str)`).

6. **Regression delta** — reproduce locally if practical. B2 ship reports `16 failed, 805 passed, 21 skipped`. 16 failures must be byte-identical to the main-branch baseline (same set as PR #37/#38/#39). `+6 passed` matches 6 new tests. Confirm with `cmp -s` or equivalent (same rigor as your PR #39 review).

7. **Scope** — 2 code files + 1 report. NO schema migration, NO new env vars, NO changes to Step 5/Step 6 logic, NO changes to `_body_length`.

8. **Part B diagnostic quality** — this is the key lead for AI Head's NEXT brief. Sanity-check B2's interpretation:
   - 13/19 `full_synthesis` rows have `LENGTH(opus_draft_markdown) = 0` — is the SQL / JOIN correct?
   - Recommendation ("scan `kbl_log component='step5_opus'` for those 13 signal_ids") — is that the right next scope?
   - You don't need to execute the follow-up; just confirm the diagnosis holds.

9. **Ship-report pytest log is FULL, not "by inspection"** — head+tail captured, literal counts quoted. REQUEST_CHANGES if any variant of "pass by inspection" appears.

## Decision

- **APPROVE** → reply `APPROVE PR #40` in your review report; AI Head will Tier-A auto-merge (`gh pr merge 40 --squash`).
- **REQUEST_CHANGES** → name the line/logic; B2 loops.

## Report path

`briefs/_reports/B3_pr40_step6_validation_hotfix_review_20260422.md` — commit + push after review. Close this task file with a `## B3 dispatch back` section.

## Charter notes

- Ship report lives on PR branch (not pre-committed to main, unlike PR #39). Not a blocker; just confirm the file is present in the squashed merge.
- Part B is REPORT-ONLY — no code should change for the body-short class. If you see silver.py touching `_body_length`, REQUEST_CHANGES.

---

**Dispatch timestamp:** 2026-04-22 ~10:50 UTC (post-B2 ship)
