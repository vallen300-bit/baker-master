# B3 Review — PR #40 STEP6_VALIDATION_HOTFIX_1

**Reviewer:** Code Brisen #3
**Date:** 2026-04-22
**PR:** https://github.com/vallen300-bit/baker-master/pull/40
**Branch:** `step6-validation-hotfix-1`
**Head SHA:** `0546ab1`
**Author:** B2
**Ship report:** `briefs/_reports/B2_step6_validation_hotfix_1_20260422.md` (on PR branch)

---

## §verdict

**APPROVE PR #40.** All 9 focus items green. Full-suite regression delta reproduced locally with cmp-confirmed identical 16-failure set. Fixes the YAML 1.1 auto-scalar-coercion bug class that accounted for 54% (65/121) of Step 6 finalize WARNs over the last 48h. Part B diagnostic is sound and the right handoff to AI Head. Tier A auto-merge greenlit.

---

## §focus-verdict

1. ✅ **`_deadline_coerce_to_str` correctness.**
2. ✅ **`_source_id_coerce_to_str` correctness.**
3. ✅ **Imports clean.**
4. ✅ **`_deadline_iso_date` unchanged.**
5. ✅ **6 new tests — exact string equality, not type-only.**
6. ✅ **Regression delta reproduced.**
7. ✅ **Scope — 2 code files + 1 ship report; no `_body_length` touch.**
8. ✅ **Part B diagnostic holds.**
9. ✅ **Ship report carries full pytest output with literal counts.**

---

## §1 `_deadline_coerce_to_str` correctness

`kbl/schemas/silver.py:194-212`. Walked the branch table:

| Input | Branch taken | Output |
|---|---|---|
| `None` | `v is None or isinstance(v, str)` | `None` (pass-through) |
| `"2026-05-01"` | `isinstance(v, str)` | `"2026-05-01"` (pass-through) |
| `datetime(2026,5,1,12,...)` | `isinstance(v, datetime)` | `.date().isoformat()` → `"2026-05-01"` |
| `date(2026,5,1)` | `isinstance(v, date)` | `.isoformat()` → `"2026-05-01"` |
| `int`/`float`/anything else | none of the above | `raise TypeError(...)` with type name |

**Critical ordering:** `isinstance(v, datetime)` is checked BEFORE `isinstance(v, date)`. Because `datetime` is a subclass of `date`, reversing the order would cause a `datetime` to match `isinstance(date)` first and call `.isoformat()` which for `datetime` yields `"2026-05-01T12:00:00+00:00"` — breaking the downstream `_deadline_iso_date` YYYY-MM-DD regex. **B2 got this right.** ✓

`mode='before'` runs this validator BEFORE Pydantic's field-type coercion and BEFORE the existing `_deadline_iso_date` (default `mode='after'`). So the chain is: raw input → `_deadline_coerce_to_str` (produces str or None) → Pydantic type check (str OK) → `_deadline_iso_date` (asserts YYYY-MM-DD shape on the coerced string). ✓

Error-vs-junk tradeoff: raising `TypeError` on unknown types (rather than `str(v)` which would yield `"<object ... at 0x...>"`) matches Pydantic v2's fail-loud philosophy and surfaces producer bugs visibly. ✓

## §2 `_source_id_coerce_to_str` correctness

`kbl/schemas/silver.py:180-192`. Walked the branch table:

| Input | Branch | Output |
|---|---|---|
| `None` | `v is None or isinstance(v, str)` | `None` (pass-through) |
| `"68"` | `isinstance(v, str)` | `"68"` (pass-through) |
| `68` | else | `str(v)` → `"68"` |
| `9_999_999_999` | else | `str(v)` → `"9999999999"` (no scientific notation — Python int stringification is exact) |

`None` pass-through rationale documented in the docstring: if the field is required and absent, the downstream required-field error stays clear rather than being masked by `'NoneType' object is not iterable` from a blanket `str(v)`. Defensible design.

**Field-spec check:** I looked at the field declaration to confirm `None` behavior. `SilverFrontmatter.source_id` is typed as a required `str` (not `Optional[str]`), so `None` will correctly fail the post-coerce Pydantic type check with a clear "required" error. ✓

`str(v)` is safe for all primitives (int, float, bool, Decimal, etc.) and produces deterministic output. No injection surface — the value is consumed as an opaque string identifier downstream. ✓

## §3 Imports

Diff:
```diff
-from datetime import datetime, timezone
-from typing import Annotated, List, Literal, Optional
+from datetime import date, datetime, timezone
+from typing import Annotated, Any, List, Literal, Optional
```

- `date` — new; used in `isinstance(v, date)` in `_deadline_coerce_to_str`. ✓
- `Any` — new; used in both validator signatures (`v: Any`). ✓
- `datetime`, `timezone`, `Annotated`, `List`, `Literal`, `Optional` — unchanged. ✓
- No circular imports (`silver.py` only imports from stdlib + pydantic — no reverse dependency). ✓
- No unused imports — all four additions have live call sites. ✓

## §4 Existing `_deadline_iso_date` validator unchanged

Diff context shows `_deadline_iso_date` appears only as the NEXT validator after the new `_deadline_coerce_to_str` block — no modification lines on its own code. The YYYY-MM-DD shape assertion continues to fire on the coerced string (`mode='after'` runs by default, so it lands on the str that `_deadline_coerce_to_str` produced). Existing R13 tests (`test_r13_deadline_valid_iso_date_accepted`, `test_r13_deadline_malformed_rejected`) still in place and passing on PR head. ✓

## §5 6 new tests — exact string equality

`tests/test_silver_schema.py:234-287`. Read each body:

| # | Test | Input | Assertion | Non-trivial? |
|---|------|-------|-----------|--------------|
| 1 | `test_deadline_accepts_str_yyyy_mm_dd` | `"2026-05-01"` | `fm.deadline == "2026-05-01"` | ✅ exact str |
| 2 | `test_deadline_accepts_date_object` | `date(2026,5,1)` | `fm.deadline == "2026-05-01"` | ✅ pins coercion output |
| 3 | `test_deadline_accepts_datetime_object` | `datetime(2026,5,1,12,0,0,tzinfo=utc)` | `fm.deadline == "2026-05-01"` | ✅ pins `.date().isoformat()` path — NOT just type — verifies time is dropped |
| 4 | `test_source_id_accepts_str` | `"68"` | `fm.source_id == "68"` | ✅ exact str |
| 5 | `test_source_id_coerces_int` | `68` | `fm.source_id == "68"` | ✅ pins int→str |
| 6 | `test_source_id_coerces_large_int` | `9_999_999_999` | `fm.source_id == "9999999999"` | ✅ pins exact digits — no scientific notation, no truncation |

Zero `isinstance` checks. Zero `assert x is not None` presence-only asserts. All six pin EXACT string output. ✓

**Notable:** test #3 (datetime with time component) is the highest-signal test — it would catch the `datetime → .isoformat()` bug (would produce `"2026-05-01T12:00:00+00:00"` and fail the `== "2026-05-01"` assertion). Locks the ordering invariant I called out in §1. ✓

No explicit negative test for the `TypeError` branch of `_deadline_coerce_to_str` (e.g., `deadline=42` should raise). Minor gap — the existing malformed-str rejection test covers the overall "bad input rejected" invariant at the field level, but not the specific TypeError path. Non-gating N-nit.

## §6 Regression delta

Reproduced locally in `/tmp/b3-venv` (Python 3.12):

```
main baseline:       16 failed / 799 passed / 21 skipped / 19 warnings  (12.18s)
pr40 head (0546ab1): 16 failed / 805 passed / 21 skipped / 19 warnings  (67.06s)
Delta:               +6 passed, 0 regressions, 0 new errors, 0 new skips
```

**Failure-set identity check:** `cmp -s /tmp/b3-main4-failures.txt /tmp/b3-pr40-failures.txt` → exit 0 (IDENTICAL). The 16 pre-existing failures are the same test-name set on both runs.

`+6 passed` matches exactly the 6 new tests added in `tests/test_silver_schema.py`. Zero tests moved from passing to failing.

B2's ship-report claim (16 failed / 805 passed / 21 skipped) matches my PR-head run EXACTLY — absolute counts align. ✓

## §7 Scope discipline

- **3 files:** `kbl/schemas/silver.py` (+38/-2), `tests/test_silver_schema.py` (+56/-0), `briefs/_reports/B2_step6_validation_hotfix_1_20260422.md` (+258/-0). `git diff $(merge-base)..pr40 --name-only` confirms. ✓
- **No `_body_length` touches:** `grep -n "_body_length" kbl/schemas/silver.py` — only the pre-existing definition at line 295 and a doc reference at line 322. Not in the diff. Part B is report-only as expected. ✓
- **No Step 5 / Step 6 logic change:** `grep "step5_opus\|step6_finalize"` in diff returns only doc references to `_deadline_iso_date`. ✓
- **No schema migration:** zero DDL. Pydantic-validator-level fix only. `memory/feedback_migration_bootstrap_drift.md` N/A — no column additions/changes. ✓
- **No env vars, no deps:** no `requirements.txt` change, no `os.environ` / `os.getenv` additions. ✓

**Ship report in PR branch, not pre-committed to main:** confirmed — file exists on `pr40` branch at `briefs/_reports/B2_step6_validation_hotfix_1_20260422.md`. Squash merge will carry it into main. Per charter note, not a blocker. ✓

## §8 Part B diagnostic sanity check

Ship report §Part B. Reviewed the SQL + diagnosis:

**SQL correctness:**
```sql
SELECT sq.id, sq.step_5_decision, sq.primary_matter, sq.finalize_retry_count,
       LENGTH(COALESCE(sq.opus_draft_markdown, '')) AS draft_len,
       LEFT(sq.opus_draft_markdown, 400) AS draft_head
  FROM signal_queue sq
  JOIN kbl_log kl ON kl.signal_id = sq.id
 WHERE kl.component='finalize' AND kl.level='WARN'
   AND kl.message LIKE 'body: Value error, body too short%'
   AND kl.ts > NOW() - INTERVAL '48 hours'
 GROUP BY sq.id
 ORDER BY sq.id DESC
 LIMIT 20;
```

- JOIN on `kl.signal_id = sq.id` — correct linkage (standard kbl_log pattern).
- Filter chain (component='finalize' AND level='WARN' AND message LIKE 'body: Value error...') — matches Pydantic v2's error prefix for a body `ValueError` from `_body_length`. ✓
- `GROUP BY sq.id` deduplicates signals that have multiple WARN rows across R3 retries. PostgreSQL-specific: non-aggregated SELECT columns are allowed because `sq.id` is the PRIMARY KEY (functional dependency). Works correctly here; slightly fragile SQL but produces the intended result set.
- 48h window + LIMIT 20 — tight and appropriate for class-of-bug diagnosis.

**Diagnostic interpretation:**

> "13 of 19 `full_synthesis` rows (68%) have `LENGTH(opus_draft_markdown) = 0` — Opus wrote nothing. This is not a body-floor-too-high issue; it is an upstream Step 5 output-capture problem."

Holds. If 68% of failing full_synthesis rows have a literal empty draft, the `_body_length` floor is correctly firing on vacancy — it is the reporter, not the root cause. B2 correctly decouples the symptom (Step 6 reject) from the cause (Step 5 empty output). ✓

**Recommendation:**

> "Narrow kbl_log scan at `component='step5_opus'` for the 13 empty-draft signal_ids will say whether: (1) Opus API errored, (2) returned 200 OK with empty content, (3) Step 5 capture code drops the text."

This is exactly the right next scope. Three enumerated hypotheses cover the plausible failure modes; scan will bisect to one. ✓ AI Head can brief from this directly.

**Secondary anomaly surfaced:** 1 `skip_inbox` row with `draft_len=863` triggering `_body_length` too-short. As B2 notes, the stub shape invariant `_stub_status_matches_shape` caps stub bodies at 600 — an 863-char stub body is unusual and worth its own look. B2 correctly flagged this as a sidebar, not the headline. Good diagnostic depth. ✓

## §9 Ship report — no "by inspection"

Ship report §Full pytest section carries a LITERAL pytest run:

```
$ python -m pytest tests/
...
=========== 16 failed, 805 passed, 21 skipped, 19 warnings in 11.89s ===========
```

16 FAILED rows enumerated verbatim above the summary. Counts quoted explicitly (16/805/21). No variant of "pass by inspection" appears in the report — scanned with `grep -i "by inspection"` mentally; the phrase is absent. `memory/feedback_no_ship_by_inspection.md` honored. ✓

---

## §non-gating

- **N1 — no explicit `TypeError` negative test for `_deadline_coerce_to_str`.** The `raise TypeError(...)` branch for unknown types (e.g., `deadline=42`, `deadline=["list"]`) isn't directly covered by a test with `pytest.raises(TypeError)`. The existing malformed-str rejection test `test_r13_deadline_malformed_rejected` covers the aggregate "bad-input rejected" field-level behavior, but not the specific TypeError code path. Cheap add in a future tidy-up. Not gating.

- **N2 — Part B SQL `GROUP BY` fragility.** The query relies on PostgreSQL's functional-dependency SQL extension (non-aggregated SELECT columns allowed when grouping by PK). Moving this SQL to a different DB engine would require listing all columns in GROUP BY or wrapping in `DISTINCT ON`. Not a production concern; works in this schema. Cosmetic.

- **N3 — ship report on PR branch, not pre-committed to main.** Dispatch flagged this; confirmed it will land via squash merge. Different from PR #39 pattern but within charter. Informational only.

---

## §regression-delta

```
$ wc -l /tmp/b3-main4-failures.txt /tmp/b3-pr40-failures.txt
      16 /tmp/b3-main4-failures.txt
      16 /tmp/b3-pr40-failures.txt

$ cmp -s /tmp/b3-main4-failures.txt /tmp/b3-pr40-failures.txt && echo IDENTICAL
IDENTICAL
```

Raw logs at `/tmp/b3-main4-pytest-full.log` and `/tmp/b3-pr40-pytest-full.log` (local).

---

## §post-merge

- Tier A auto-merge (squash) proceeds.
- Render redeploys. On next tick, go-forward rows that hit `deadline` as `date`/`datetime` or `source_id` as `int` in YAML will clear Step 6 Pydantic cleanly. 54% of the observed WARN class unblocks immediately.
- 9 existing `finalize_failed` rows stay terminal — separate backfill ask (B2 already scoped).
- Part B handoff to AI Head: scan `kbl_log component='step5_opus'` for the 13 empty-draft signal IDs identified in §Part B to bisect the Step 5 empty-output bug. This is the logical next brief for the body-short class.

**APPROVE PR #40.**

— B3
