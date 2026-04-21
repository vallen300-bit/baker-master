# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (fresh terminal tab)
**Task posted:** 2026-04-21 evening
**Status:** CLOSED — PR #35 REQUEST_CHANGES, 1 stale PR #34 test assertion blocks merge

---

## B3 dispatch back (2026-04-21 evening)

**Verdict: REQUEST_CHANGES** — one blocker, trivial 2-line fix.

Report: `briefs/_reports/B3_pr35_step5_stub_source_id_type_fix_review_20260421.md`.

Production fix is correct and architecture is sound. All 10 of B2's new-test assertions pass. But full-suite run on PR head `ec4f9e0`:

```
1 failed, 77 passed, 2 skipped
FAILED tests/test_step5_opus.py::test_skip_inbox_stub_frontmatter_parses_cleanly_despite_colon_in_title
  tests/test_step5_opus.py:273: AssertionError: assert '42' == 42
```

**Root cause:** PR #34 landed a test with `assert fm["source_id"] == 42` (int) and a comment claiming "Pydantic coerces downstream" — exactly the premise this PR is refuting. B2's ship report says existing tests "pass by inspection" — they skipped the full test run. Post-fix, stub emits `source_id: '42'` (str), so assertion breaks.

**Required fix — 2 lines at `tests/test_step5_opus.py:272-273`:**

```python
# source_id is the signal_id cast to str (SilverFrontmatter.source_id: str;
# producer-side cast per STEP5_STUB_SOURCE_ID_TYPE_FIX_1).
assert fm["source_id"] == "42"
```

Grepped every `source_id` in both test files — this is the ONLY stale assertion. All other sites are type-agnostic (key-order list) or already string (`source_id="email:1"`).

All 7 focus items reviewed:
1. ✅ Scope deviation (Step 6 override): BLESS. Confirmed by full read of `kbl/prompts/step5_opus_user.txt` — zero `{signal_id}` placeholder anywhere; FULL_SYNTHESIS path genuinely broken without the override. System prompt describes schema (`source_id: <signal_id from input>`), but user prompt never surfaces the value — Opus would omit or hallucinate.
2. ✅ Force-set vs setdefault: force-set correct. `signal_queue.id` is SERIAL/authoritative; setdefault would preserve truthy-wrong hallucinations (captured by `test_finalize_overrides_wrong_string_source_id_with_signal_id`).
3. ✅ Producer cast lives solely in shared `_build_stub_frontmatter_dict:437`; both `_build_skip_inbox_stub` (line 455) and `_build_stub_only_stub` (line 475) call through. Not duplicated.
4. ✅ Field-type audit reproduced — mapped every stub-dict key against `SilverFrontmatter` (kbl/schemas/silver.py:135-152). `source_id` is the sole type drift. `created` handled by Pydantic ISO→datetime; `triage_score`/`triage_confidence` injected by Step 6 from DB with matching int/float type.
5. ⚠️ Regression tests: all 10 new-test asserts pass (non-trivial — `isinstance(..., str)`, parametrized 5 sizes including zero + >32-bit, end-to-end Pydantic validate, final_markdown quoted-form substring check `source_id: '17'`, stale-value-absent assertion `"stale999" not in`, missing-key inject). But PR #34 regression test line 273 breaks — blocking.
6. ✅ No scope creep: 4 production/test files + ship report. No `SilverFrontmatter` schema, `kbl/bridge/*`, `kbl/pipeline_tick.py`, or step1-4/step7 changes.
7. ✅ FULL_SYNTHESIS prompt-template bug correctly deferred post-Gate-1 — override masks it, surface is non-trivial (prompt template edit + `_build_user_prompt` kwarg injection), only bites after Gate 1 when in-scope signals actually route there.

Adjacent emitter at `kbl/gold_drain.py:188` still missing `allow_unicode=True, default_flow_style=False` kwargs (unchanged by this PR) — still post-Gate-1 unification item.

**Path to Tier A auto-merge:** B2 pushes 2-line fix; I re-verify on `77+ passed, 0 failed`; flip to APPROVE. Alternatively, AI Head can inline-apply the 2-line fix (mechanical, zero-judgment) and re-dispatch for verification.

Tab quitting per §8.

— B3

---

## Target

- **PR:** https://github.com/vallen300-bit/baker-master/pull/35
- **Branch:** `step5-stub-source-id-type-fix-1`
- **Author:** B2
- **Ship report:** `briefs/_reports/B2_step5_stub_source_id_type_fix_20260421.md`

## Context (one paragraph)

After PR #34 fixed the YAML-encoding layer, Step 6 finalize surfaced a Pydantic validation failure — `source_id: Input should be a valid string`. Root cause: Step 5 stub writer wrote `source_id` as raw int (`inputs.signal_id`); YAML round-trips int; Pydantic v2 strict mode rejects int-for-str. B2 landed a two-layer fix: (a) producer-side cast in the shared `_build_stub_frontmatter_dict`, (b) force-set override in Step 6 before Pydantic validate to defend against FULL_SYNTHESIS path latent bug (Opus prompt template doesn't currently surface `signal_id`, so Opus-generated drafts would hit the same bug the first time an in-scope signal synthesizes).

## Focus items for review

1. **Scope deviation — bless or reject.** Brief asked for producer-side cast. B2 added a Step 6 override as a second layer. B2's rationale: FULL_SYNTHESIS path is latently broken (Opus prompt template missing `signal_id`). Force-set (not setdefault) because DB `signal_queue.id` is authoritative. Verify: is the FULL_SYNTHESIS path actually exposed without this override? If yes, bless the defense-in-depth. If producer cast alone is sufficient, the override is scope creep.
2. **Force-set vs. setdefault call.** B2 chose force-set. Confirm this is correct — DB's signal_id is authoritative over any Opus-generated value. Alternative would be setdefault (inject only if missing); B2 argues force-set is safer because Opus could emit something truthy-but-wrong.
3. **Producer-side cast placement.** Should live in shared `_build_stub_frontmatter_dict` so both `_build_skip_inbox_stub` and `_build_stub_only_stub` benefit. Confirm it's there, not duplicated in both callers.
4. **Field-type audit.** B2 claims source_id is the sole type-drift offender; `created` is handled by Pydantic ISO-8601 → datetime coercion. Independently confirm by running every stub-dict field through the SilverFrontmatter type map and flagging any mismatch.
5. **Regression tests (6).** 3 in `test_step5_opus.py` (exact regression, parametrized sizes 0→9.9B, end-to-end Pydantic validate); 3 in `test_step6_finalize.py` (bare-int override, wrong-string override, missing-key inject). Verify each is non-trivial — asserts on Pydantic validate success AND string type, not just parse success.
6. **No scope creep beyond the Step 6 override.** Only files touched: `kbl/steps/step5_opus.py`, `kbl/steps/step6_finalize.py`, the two test files, the ship report. No changes to `SilverFrontmatter` schema, no bridge/pipeline_tick/step1-4/step7 changes.
7. **Latent FULL_SYNTHESIS prompt-template bug.** B2 flagged this as post-Gate-1 micro-brief candidate — `kbl/prompts/step5_opus_user.txt` needs `{signal_id}` slot so Opus can set source_id directly. Confirm this is correctly deferred (not a Gate 1 blocker; only affects in-scope signals that reach FULL_SYNTHESIS, and the Step 6 override masks it for now).

## Deliverable

- Verdict: `APPROVE` / `APPROVE_WITH_NITS` / `REQUEST_CHANGES` on PR #35.
- Report: `briefs/_reports/B3_pr35_step5_stub_source_id_type_fix_review_20260421.md`.
- Include: scope-deviation verdict with evidence, per-focus verdict, field-type audit reproduction, latent-bug deferral sign-off.

## Gate

- **Tier A auto-merge on APPROVE.**
- Post-merge recovery: 20 stranded `awaiting_finalize` rows should retry automatically via `finalize_retry_count` built-in retry. If exhaust without success, Tier B fallback SQL in B2's ship report; AI Head authorizes separately.

## Working dir

`~/bm-b3`. If on feature branch, `git checkout main && git pull -q` first.

— AI Head
