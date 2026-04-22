# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3
**Task posted:** 2026-04-22
**Status:** CLOSED — PR #36 APPROVE, Tier A auto-merge greenlit, full Step 5 stub drift class structurally killed

---

## B3 dispatch back (2026-04-22)

**Verdict: APPROVE** — all 8 focus items green, zero gating nits. Full-repo regression delta reproduced exactly.

Report: `briefs/_reports/B3_pr36_step5_stub_schema_conformance_audit_review_20260422.md`.

### Regression delta (focus 5) — reproduced locally

```
Baseline b73fb49:  22 failed / 719 passed / 21 skipped / 12 errors
PR head  9703745:  22 failed / 748 passed / 21 skipped / 12 errors
Delta:             +29 passed, 0 regressions, 0 new errors
```

Pre-existing failure SET identical (`cmp -s` confirms).

### Per focus verdict

1. ✅ **Axis 1/2 helper correctness.** All 4 helpers (`_normalize_stub_inputs`, `_normalize_stub_title`, `_pad_stub_body`, `_cap_stub_body`) read end-to-end. Enforcement order correct (slug filter → §4.2 → dedupe; §4.2 can cascade from slug-demotion). Idempotent, deterministic (order-preserving list comprehensions, not dict-dependent). Full validator coverage map vs `kbl/schemas/silver.py` — every `@field_validator` / `@model_validator` / slug registry check structurally covered by the helpers or N/A (stub doesn't emit money/deadline/thread_continues).

2. ✅ **Axis 3 fresh-conn pattern.** Release-clean via `with get_conn() as fresh_conn:` + inner try/except/rollback. Outer envelope catches even `get_conn()` itself failing and logs to stderr without masking the caller's re-raise. Retry-bump semantically correct (one bump per failed finalize — the counter IS the budget); double-bump in a single invocation is not possible. Signature change applied uniformly at all 4 call sites.

3. ✅ **Axis 4 test coverage.** 29 leaf tests (23 named + 8 parametrized), all with non-trivial asserts pinning specific values, not presence-only. Known-bad shapes from error logs covered (null-primary + non-empty related; empty body). 14 of 23 named tests run end-to-end through `_yaml_roundtrip_then_validate` (Step 5 stub → YAML → Step 6 telemetry inject → `SilverDocument.model_validate`). Local run: 107 passed / 2 skipped in trifecta.

4. ✅ **Axis 5 prompt edits.** `signal_id: {signal_id}` at TOP of user prompt's "Signal triage output" section, column-aligned. System prompt's new `### Frontmatter cross-field invariants` section names §4.2 explicitly + "wrap source_id in quotes — Pydantic rejects unquoted integers". Imperative phrasing, unambiguous, unmissable. Wiring verified at `_build_user_prompt:785`; test #19 locks against accidental removal.

5. ✅ **Full-repo regression delta.** Reproduced exactly — above.

6. ✅ **No ship-by-inspection.** Ship report §10.1 (blast-radius), §10.2 (full-repo), §10.3 (py_compile) all carry raw pytest output. `feedback_no_ship_by_inspection.md` honored.

7. ✅ **Scope discipline.** 9 touched files, all in allowed set. Zero changes to `kbl/schemas/silver.py`, bridge, pipeline_tick, step1-4, step7, `claim_one_signal`.

8. ✅ **Post-merge recovery SQL.** Pre-flight SELECT + precise WHERE (`status = 'finalize_running' AND final_markdown IS NULL`) + `started_at = NULL` reset for retry pickup. `stage` column confirmed via `memory/store_back.py:6217`. Correctly Tier B (deviates from standing `opus_failed/finalize_failed` pattern). Not gating per §8.

### N-nits parked (non-blocking, both pre-existing)

- **N1:** `error_count` parameter of `_route_validation_failure` unreferenced in body (also unused pre-fix). Preserved for call-site signature compatibility. Clean-up candidate.
- **N2:** `needed = _STUB_BODY_MIN_CHARS - len(body)` in `_pad_stub_body` is computed then immediately `del`'d — leftover. Cosmetic.

Tier A auto-merge proceeds. Post-Gate-1 Cortex-3T track unblocks.

Tab quitting per §8.

— B3

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
