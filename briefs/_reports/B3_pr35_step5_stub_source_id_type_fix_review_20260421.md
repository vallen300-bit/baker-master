---
title: "B3 review — PR #35 STEP5_STUB_SOURCE_ID_TYPE_FIX_1"
pr_url: https://github.com/vallen300-bit/baker-master/pull/35
reviewer: Code Brisen #3
reviewed: 2026-04-21 evening
verdict: REQUEST_CHANGES
author: B2
branch: step5-stub-source-id-type-fix-1
head_sha: ec4f9e0
---

# Verdict: REQUEST_CHANGES

One blocker. Production fix is correct, architecture is sound, 10/10 of B2's new-test assertions pass — but **B2 left a stale assertion in a PR #34 test that this PR flips from passing to failing**. B2's ship report says existing tests "pass by inspection" (no full suite run); the failure would not surface until after merge.

Full test run on the PR head (`ec4f9e0`):

```
1 failed, 77 passed, 2 skipped in 0.44s
FAILED tests/test_step5_opus.py::test_skip_inbox_stub_frontmatter_parses_cleanly_despite_colon_in_title
  tests/test_step5_opus.py:273: AssertionError: assert '42' == 42
```

## The stale assertion

`tests/test_step5_opus.py:272-273` (landed in PR #34):

```python
# source_id is the signal_id int (Pydantic coerces downstream).
assert fm["source_id"] == 42
```

The comment's premise is exactly what this PR is refuting — Pydantic v2 default mode does **not** coerce `int → str`, which is the whole reason PR #35 exists. Post-fix, `_build_skip_inbox_stub` emits `str(signal_id)`, `yaml.safe_dump` writes `source_id: '42'`, `yaml.safe_load` returns `"42"`.

### Required fix (2-line change)

```python
# source_id is the signal_id cast to str (SilverFrontmatter.source_id: str;
# producer-side cast per STEP5_STUB_SOURCE_ID_TYPE_FIX_1).
assert fm["source_id"] == "42"
```

No other assertion in the two test files is stale — I grepped every `source_id` occurrence. `tests/test_step5_opus.py:332` is a key-order list that's type-agnostic; all `source_id="email:1"` in `test_step6_finalize.py` are already `str`. Only this one line.

## Per focus item

1. ✅ **Scope deviation (Step 6 override) — BLESS.** FULL_SYNTHESIS path is genuinely broken independent of the stub bug. `kbl/prompts/step5_opus_user.txt` has zero `{signal_id}` placeholder (full read, 38 lines — not present anywhere). The system prompt at line 52 describes the schema (`source_id: <signal_id from input>`) but the user prompt never surfaces the value — Opus would either omit the key or hallucinate. Step 6 force-set is legitimate defense-in-depth, not scope creep. Unblocks in-scope signals the first time one routes to FULL_SYNTHESIS.

2. ✅ **Force-set vs setdefault — CORRECT.** `signal_queue.id` is SERIAL primary key; it's the ground truth. Setdefault would preserve a truthy-but-wrong Opus hallucination like `email:stale999` (regression test `test_finalize_overrides_wrong_string_source_id_with_signal_id` captures this). Force-set is the stronger, correct guarantee. B2's reasoning accepted.

3. ✅ **Producer cast placement.** Lives solely in shared `_build_stub_frontmatter_dict:437` (`"source_id": str(inputs.signal_id),`). Both `_build_skip_inbox_stub` (line 455) and `_build_stub_only_stub` (line 475) call through. Not duplicated.

4. ✅ **Field-type audit — source_id is sole offender.** Independently mapped every stub dict key against `SilverFrontmatter` in `kbl/schemas/silver.py:135-152`:

| Stub key | Stub value | Schema type | Coercion |
|----------|-----------|-------------|----------|
| `title` | `str` | `str` | identity |
| `voice` | `"silver"` | `Literal["silver"]` | identity |
| `author` | `"pipeline"` | `Literal["pipeline"]` | identity |
| `created` | ISO-8601 `str` from `_iso_utc_now()` | `datetime` | Pydantic ISO→datetime ✓ |
| `source_id` | `int` (pre-fix) | `str` | **FAILS** (int→str not coerced) |
| `source_id` | `str(int)` (post-fix) | `str` | identity ✓ |
| `primary_matter` | `None`/slug | `Optional[MatterSlug]` | validator-checked slug |
| `related_matters` | `list[str]` | `List[MatterSlug]` | per-item validator |
| `vedana` | `"routine"`/`"threat"`/`"opportunity"` | `Literal[...]` | identity |
| `status` | `"stub_auto"` | `Optional[StubStatus]` | identity |

   `triage_score` and `triage_confidence` are injected by Step 6 `setdefault` at line 614-617 from DB ints/floats — schema already expects int/float, no coercion gap. B2's audit claim holds.

5. ⚠️ **Regression tests: 10 pass, 1 PRE-EXISTING TEST FAILS.**
   - All 6 of B2's new tests pass with non-trivial asserts: `isinstance(..., str)` check (not just value equality), parametrized over `[1, 0, 17, 2_147_483_647, 9_999_999_999]`, end-to-end Pydantic validate, final_markdown substring check for quoted form (`source_id: '17'`), authoritative-override asserting stale value NOT present (`"stale999" not in final_markdown`), missing-key inject.
   - **The PR #34 regression at line 273 breaks on merge.** Blocking.

6. ✅ **No scope creep beyond Step 6 override.** Only files: `kbl/steps/step5_opus.py`, `kbl/steps/step6_finalize.py`, the two test files, the ship report. No `SilverFrontmatter` schema change, no `kbl/bridge/*`, no `kbl/pipeline_tick.py`, no `step1-4/step7`.

7. ✅ **FULL_SYNTHESIS prompt-template deferral — CORRECT.** Confirmed by reading the full `step5_opus_user.txt` — no `{signal_id}` anywhere. Post-Gate-1 micro-brief is the right framing because (a) the Step 6 override already masks the bug, (b) it requires a prompt-template edit + corresponding `_build_user_prompt` kwarg injection (non-trivial surface), (c) it only bites once FULL_SYNTHESIS actually emits an in-scope signal, which requires Gate 1 complete anyway.

## Adjacent-emitter audit (carried from PR #34 follow-up)

Reconfirmed `kbl/gold_drain.py:188` still missing `allow_unicode=True, default_flow_style=False` kwargs — unchanged by PR #35. Still a post-Gate-1 unification item, non-blocking.

## Path to Tier A auto-merge

B2: replace `tests/test_step5_opus.py:272-273` with the 2-line fix above. After the push, I re-run the suite; on `77+ passed, 0 failed, 2 skipped` I flip to **APPROVE** and Tier A auto-merge proceeds. Stub-type FULL_SYNTHESIS deferral and gold_drain.py:188 stay post-Gate-1.

— B3
