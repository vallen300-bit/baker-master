# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1
**Task posted:** 2026-04-22 (post-diagnostic)
**Status:** OPEN — STEP4_HOT_MD_PARSER_FIX_1

---

## Context

Your own diagnostic (`briefs/_reports/B1_step5_opus_scope_gate_diagnostic_20260422.md`) found the root cause of Gate 2 blockage: Step 4's hot.md parser fails to match the live section header + can't parse multi-slug bullets. Rule 1 (Layer 2 gate) fires for every non-null primary_matter → all 56 signals land in skip_inbox stubs. Zero Opus calls have happened on any in-scope signal.

Ship the fix per the direction you recommended in your own report.

## Substrate (YOURS — read first)

`briefs/_reports/B1_step5_opus_scope_gate_diagnostic_20260422.md` §6 (fix-direction recommendation).

## Scope — ship the fix

1. **Section-regex loosen** — `kbl/steps/step4_classify.py:66-69`. Make the `^##\s+Actively\s+pressing` match tolerate the live parenthetical suffix `(elevate — deadline/decision this week)` and any future suffixes on that section header.
2. **Multi-slug bullet parser** — the `\*\*(?P<slug>[A-Za-z0-9_\-]+)\*\*` pattern must parse hot.md line 13's documented multi-slug format (e.g. `**lilienmatt + annaberg + aukera**:`), splitting on `+` and trimming. Hot.md line 13 comment notes this as intentional format.
3. **5 regression tests** covering:
   - Exact live section header (with parenthetical)
   - Prior-format section header (no parenthetical) — backward compat
   - Single-slug bullet — backward compat
   - Multi-slug bullet (e.g. 3 slugs joined with `+`)
   - Mixed single + multi-slug across the hot.md body
4. **No schema / bridge / pipeline_tick / step 1-3 / step 5-7 changes.**
5. **No-ship-by-inspection rule: full `pytest` output in ship report.**

## Recovery (AI Head handles post-merge)

Separate Tier B auth. Director's call on which of the 56 skip_inbox rows to re-run — recommendation is in-scope matters only (Hagenauer, Lilienmatt, Annaberg). Surface the recovery SQL in your ship report §recovery.

## Deliverable

- PR on baker-master, branch `step4-hot-md-parser-fix-1`, reviewer B3.
- Ship report at `briefs/_reports/B1_step4_hot_md_parser_fix_20260422.md`.
- Report sections:
  - Before/after regex + parser logic
  - Regression test matrix (the 5 tests above)
  - Full `pytest` output (suite + full-repo)
  - Recovery SQL for the 56 skip_inbox rows, filtered by in-scope matters (for AI Head to run post-merge with Director auth)

## Constraints

- **Effort: S (~45-60 min) per your own estimate.**
- Migration-vs-bootstrap DDL rule: N/A (no columns).
- Follow `feedback_no_ship_by_inspection.md`.
- No scope creep — fix the parser, ship tests, done.
- **Timebox: 90 min.**

## Working dir

`~/bm-b1`. `git checkout main && git pull -q` before starting.

— AI Head
