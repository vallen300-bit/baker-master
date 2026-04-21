# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (fresh terminal tab)
**Task posted:** 2026-04-21 (post-B1 ship of STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1)
**Status:** OPEN — review PR #30

---

## Task: Review baker-master PR #30 — STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1

- **PR:** https://github.com/vallen300-bit/baker-master/pull/30
- **Branch:** `step-consumers-signal-content-source-fix-1`
- **Head commit:** `777ca48`
- **Size:** 10 files / +563 / -19
- **B1 ship report:** `briefs/_reports/B1_step_consumers_fix_ship_20260421.md` (on branch)
- **Brief:** `briefs/BRIEF_STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1.md` (on main; same commit on branch)
- **Upstream diagnostic:** `briefs/_reports/B2_pipeline_diagnostic_20260421.md` (commit `1ac8ed0`)
- **Unblocks:** Cortex T3 Gate 1

---

## Context

B2's diagnostic (1ac8ed0) identified the root cause of Steps 2-7 being frozen: Steps 1/2/3/5 `SELECT raw_content` from `signal_queue`, but the bridge writes body into `payload->>'alert_body'`. Every tick raised `UndefinedColumn`; 15 rows stranded at `status='processing'`.

B1's fix redirects the 4 consumer SELECTs to `COALESCE(payload->>'alert_body', summary, '') AS raw_content`. Alias preserves downstream `row['raw_content']` keys so no refactoring cascade. Each call-site carries a comment explicitly flagging COALESCE as a safety net — not a cover-up for future drift.

---

## Focus areas for your review

1. **All 4 step consumers redirect cleanly** — Steps 1, 2, 3, 5. Confirm no residual `SELECT raw_content` in `kbl/steps/` (grep). B1 claims zero.
2. **Alias strategy is clean** — `AS raw_content` preserved so dict/tuple shapes don't shift. Scrutinize `step2_resolve.py` where B1 refactored `_SIGNAL_SELECT_COLUMNS` → `_SIGNAL_SELECT_FIELDS` (pairs of sql_expr + dict_key).
3. **COALESCE ladder is safe** — fallback to `summary` for legacy rows, final `''` empties (NOT NULL) so downstream `.lower()`, concat, len() don't blow up.
4. **New integration test module** `tests/test_bridge_pipeline_integration.py` — 6 live-PG tests gating the exact drift point. Do they assert the right thing? Verify `needs_live_pg` gating works locally (should collect clean, skip without `TEST_DATABASE_URL`).
5. **Shared fixture helper** `tests/fixtures/signal_queue.py::insert_test_signal` — bridge-canonical shape. Reasonable API? Correctly shared?
6. **Fixture drift repairs** in `tests/test_step4_classify.py` + `tests/test_status_check_expand_migration.py` — only 2 files had actual INSERT drift (brief had guessed 5). Confirm the 3 remaining step test modules are MagicMock-shape-stable.
7. **CRITICAL CONSTRAINT:** `kbl/pipeline_tick.py:359-365` emit_log block MUST be unchanged. B1 claims empty `git diff main -- kbl/pipeline_tick.py`. Verify.
8. **Comment quality** — the "safety net not cover-up" comment exists at all 4 sites and reads as durable guidance (not vague).
9. **No schema changes** — brief forbids a `raw_content` generated column. Confirm.
10. **Test count:** B1 claims 299 passed / 8 skipped (live-PG gates) / 0 failed. Run locally if fast; otherwise spot-check the 4 step test files + new integration module.

---

## Brief deviations to evaluate

B1 flagged three in the ship report — judge whether each is reasonable:

- **DEV-1:** Expected 5 affected test modules with fixture drift; found only 2. The other 3 use MagicMock and are shape-stable. → Reasonable if grep of `INSERT INTO signal_queue.*raw_content` in `tests/` returns only the 2 files B1 fixed.
- **DEV-2:** `step2_resolve._SIGNAL_SELECT_COLUMNS` → `_SIGNAL_SELECT_FIELDS` (pairs). Justified to preserve alias + dict-key cleanly. → Judge clarity of the new abstraction.
- **DEV-3:** Step 4 production code untouched; only its live-PG test INSERT was drifted. → Confirm Step 4 doesn't consume `raw_content` in prod.

---

## Deliverable

Write report at `briefs/_reports/B3_pr30_step_consumers_fix_review_20260421.md`:

- Verdict: APPROVE | REQUEST_CHANGES
- Verification of the 10 focus items above (check-box format acceptable)
- Any non-blocking nits (collect for the next bridge-tuning brief, do not gate merge)
- Test-count reproduction (or documented reason for skipping)
- Recommendation on Tier A auto-merge

Commit + push the report. Post a short dispatch-back note to AI Head at the top of the report OR in the commit message.

**If APPROVE:** AI Head auto-merges per Tier A (no further Director auth needed for merge itself). Director authorizes the Tier B recovery UPDATE separately post-merge.

**If REQUEST_CHANGES:** pass back to B1 via `CODE_1_PENDING.md` with specific redlines.

Time expectation: 30-60 min review. PR is small and mechanical; the critical question is whether the COALESCE fallback semantics are right and whether the alias strategy actually keeps downstream code stable.

---

## Working dir

`~/bm-b3` (baker-master) — `git pull -q` before starting.

— AI Head
