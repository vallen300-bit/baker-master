# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3
**Task posted:** 2026-04-22
**Status:** OPEN — review PR #36 `STEP5_STUB_SCHEMA_CONFORMANCE_AUDIT_1`

---

## Target

- **PR:** https://github.com/vallen300-bit/baker-master/pull/36
- **Branch:** `step5-stub-schema-conformance-audit-1`
- **Author:** B1
- **Ship report:** `briefs/_reports/B1_step5_stub_schema_conformance_audit_20260422.md`

## Context

Director called "audit" over "patch" after five single-bug PRs (#30-#35) revealed a systemic class of drift bugs in the Step 5 stub → Step 6 Pydantic validate path. B1 did the comprehensive sweep across 5 axes. Gate 1 blocker. This PR should kill the whole class — no more whack-a-mole post-merge.

## What landed (per ship report summary)

- **Axis 1/2 (structural conformance):** new helpers `_normalize_stub_inputs`, `_normalize_stub_title`, `_pad_stub_body`, `_cap_stub_body` enforce every SilverFrontmatter/SilverDocument invariant before the stub leaves Step 5. Covers: §4.2 null-primary ⇒ empty-related, no-primary-in-related dedupe, retired-slug demotion, vedana Literal coercion, title trailing-period strip, 300-char body floor, 600-char body ceiling, R18 forbidden-marker scrub.
- **Axis 3 (error handler):** `_route_validation_failure` opens a fresh `kbl.db.get_conn()` for the retry-bump + terminal-state-flip + commit. Kills the `InterfaceError: connection already closed` cascade stranding rows at `finalize_running`. Fault-tolerant stderr envelope never masks the caller's re-raise.
- **Axis 5:** `{signal_id}` placeholder added to Opus user prompt; system prompt gains cross-field-invariants section naming §4.2.
- **Axis 4:** 29 regression tests in new `test_step5_stub_schema_conformance_audit.py` — matrix table in ship report §6.
- **pytest:** 349 passed / 11 live-PG skipped in blast radius. Full-repo +29 new passing vs baseline, zero regressions (22 pre-existing failures all Python 3.9 `int | None` + unrelated harness drift, confirmed via git stash -u baseline on b73fb49).

## Focus for review

1. **Axis 1/2 — helper correctness.** Read each of the 4 new helpers end-to-end. Confirm: (a) each invariant listed is enforced, (b) invariant enforcement order is correct (e.g., related_matters dedupe happens before §4.2 null-primary check), (c) no dead branches, (d) idempotency under re-invocation, (e) output is deterministic (no dict-iteration-order leaks). Worth grepping SilverFrontmatter for ANY `@model_validator` / `@field_validator` and confirming the helper set covers every one — B1's matrix in §6 should enumerate them.
2. **Axis 3 — fresh-connection pattern.** The fresh `get_conn()` call inside `_route_validation_failure` must be release-clean (commit + close even on inner raise) so no idle connections leak. Verify with `try/finally` or context manager. Also: confirm the retry-bump write is idempotent — if the same signal hits this path twice (unlikely but possible), we don't double-increment.
3. **Axis 4 — test coverage quality.** 29 tests is high. Check each:
   - Does the assert actually pin the invariant, or just that some value exists?
   - Is there at least one per field in the conformance matrix AND at least one per named invariant?
   - Are the known-bad shapes from today's error logs covered (null-primary + non-empty related_matters; bare-int source_id; colon-in-title; empty stub body)?
   - Non-trivial pass checks (not just `assert result is not None`).
4. **Axis 5 — prompt-template edits.** Grep `kbl/prompts/step5_opus_user.txt` + system prompt for `{signal_id}`. Confirm it's surfaced to Opus in a way the model can actually USE (not buried, not ambiguous). System-prompt §4.2 mention should be unambiguous — if Opus misreads it, we re-enter the bug class via FULL_SYNTHESIS path.
5. **Full-repo regression delta.** B1 claims +29 new passing, zero regressions vs. `b73fb49` baseline. Reproduce: `git stash -u`, `git checkout b73fb49`, run full pytest, record count; `git checkout step5-stub-schema-conformance-audit-1`, re-run. Delta must match B1's claim. The 22 pre-existing failures must be identical file/test-name set on both runs.
6. **No ship-by-inspection.** `feedback_no_ship_by_inspection.md` ratified yesterday. Full pytest output must be in ship report §8 or similar. Verify.
7. **Scope discipline.** Changes confined to `kbl/steps/step5_opus.py`, `kbl/steps/step6_finalize.py`, `kbl/prompts/step5_opus_user.txt` (+system prompt), new test file, ship report. NO changes to `SilverFrontmatter` schema, bridge, pipeline_tick, step1-4, step7, or `claim_one_signal`. If any schema-side change landed, REQUEST_CHANGES (Director said no schema edits without surfacing first).
8. **Post-merge recovery SQL.** Ship report §11 carries SQL for currently-stranded `finalize_running` rows. Read and sanity-check it — shape deviates from standing Tier A, AI Head asks Director separately before running. Not gating the APPROVE.

## Deliverable

- Verdict: `APPROVE` / `APPROVE_WITH_NITS` / `REQUEST_CHANGES` on PR #36.
- Report: `briefs/_reports/B3_pr36_step5_stub_schema_conformance_audit_review_20260422.md`.
- Include: per-focus verdict, regression delta reproduction, invariant coverage map, any nits.

## Gate

- **Tier A auto-merge on APPROVE.**
- Post-merge recovery SQL → Tier B, AI Head auths with Director.

## Working dir

`~/bm-b3`. `git fetch -q origin main && git checkout origin/main -- briefs/_tasks/CODE_3_PENDING.md && cat briefs/_tasks/CODE_3_PENDING.md`.

— AI Head
