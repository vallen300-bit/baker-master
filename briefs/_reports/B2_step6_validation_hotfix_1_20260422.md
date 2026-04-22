---
role: B2
kind: ship
brief: step6_validation_hotfix_1
pr: https://github.com/vallen300-bit/baker-master/pull/40
branch: step6-validation-hotfix-1
base: main
verdict: SHIPPED_READY_FOR_REVIEW
date: 2026-04-22
tags: [step6, silver-schema, pydantic, yaml-coercion, cortex-t3-gate1, launch-blocker]
---

# B2 — `STEP6_VALIDATION_HOTFIX_1` ship report

**Scope:** 2-validator hotfix in `kbl/schemas/silver.py` + 6 regression tests. Unblocks 54% of in-flight Step 6 finalize failures (65 of 121 48h WARNs — the `deadline` and `source_id` classes).

**Part B diagnostic (body-too-short class) included below — no code changes in that scope.**

---

## Root cause

YAML 1.1 auto-coerces unquoted scalars **before** Pydantic v2 sees them:

| YAML on disk | Python type after `yaml.safe_load` | `SilverFrontmatter` field | Pydantic v2 verdict |
|---|---|---|---|
| `deadline: 2026-05-01` | `datetime.date` | `deadline: Optional[str]` | REJECT — `Input should be a valid string` |
| `source_id: 68` | `int` | `source_id: str` | REJECT — `Input should be a valid string` |
| `source_id: "68"` | `str` | `source_id: str` | pass |
| `deadline: "2026-05-01"` | `str` | `deadline: Optional[str]` | pass (existing `_deadline_iso_date`) |

Pydantic v2 **does not** coerce date/int → str even in non-strict mode (tightened from v1). The str-level validators (`_deadline_iso_date`) never run on non-str input because field-type validation fails first.

The PR #35 producer-side `str(row.signal_id)` override at `step6_finalize.py:614` already handles `source_id` on the write path, but (a) it only runs for rows Step 6 assembles directly and (b) any YAML doc re-read downstream (recovery flows, CLI eval) bypasses it. `deadline` has no equivalent override. Defense-in-depth belongs in the schema.

## Fix

`kbl/schemas/silver.py` — 2 new `mode='before'` validators inserted between the field declarations and the existing `_deadline_iso_date` validator. Also added `date` and `Any` to imports.

### Diff excerpt

```diff
-from datetime import datetime, timezone
-from typing import Annotated, List, Literal, Optional
+from datetime import date, datetime, timezone
+from typing import Annotated, Any, List, Literal, Optional
```

```diff
+    @field_validator("source_id", mode="before")
+    @classmethod
+    def _source_id_coerce_to_str(cls, v: Any) -> Any:
+        """YAML 1.1 auto-parses bare-digit scalars (``source_id: 68``) as
+        ``int`` before Pydantic v2 sees them; Pydantic v2 does NOT coerce
+        int→str even in non-strict mode. Stringify non-string inputs here
+        so the typed field accepts them. ``None`` passes through so
+        required-field absence raises its own clear error rather than the
+        opaque ``'NoneType' object is not iterable``-class mutation."""
+        if v is None or isinstance(v, str):
+            return v
+        return str(v)
+
+    @field_validator("deadline", mode="before")
+    @classmethod
+    def _deadline_coerce_to_str(cls, v: Any) -> Optional[str]:
+        """YAML 1.1 auto-parses unquoted ISO-date scalars (``deadline:
+        2026-05-01``) as ``datetime.date`` before Pydantic v2 sees them.
+        Coerce ``date`` / ``datetime`` back to ISO-8601 ``YYYY-MM-DD``
+        strings so the downstream str-level :meth:`_deadline_iso_date`
+        validator applies uniformly. Strings and ``None`` pass through;
+        any other type raises ``TypeError`` (rather than silently
+        stringifying, which would produce junk like
+        ``"<object ... at 0x...>"``)."""
+        if v is None or isinstance(v, str):
+            return v
+        if isinstance(v, datetime):
+            return v.date().isoformat()
+        if isinstance(v, date):
+            return v.isoformat()
+        raise TypeError(
+            f"deadline: expected str/date/datetime/None, got {type(v).__name__}"
+        )
+
     @field_validator("deadline")
     @classmethod
     def _deadline_iso_date(cls, v: Optional[str]) -> Optional[str]:
```

### Before / after line map

| File | Before (main `b1f204c`) | After (branch HEAD `db78ced`) |
|---|---|---|
| `kbl/schemas/silver.py:33-34` | `from datetime import datetime, timezone` / `from typing import Annotated, List, Literal, Optional` | `from datetime import date, datetime, timezone` / `from typing import Annotated, Any, List, Literal, Optional` |
| `kbl/schemas/silver.py:~179` | `_deadline_iso_date` first validator on deadline | Preceded by new `_source_id_coerce_to_str` (before) + `_deadline_coerce_to_str` (before) |

`isinstance(v, datetime)` is checked before `isinstance(v, date)` because `datetime` is a subclass of `date` (`datetime.date` returns the date portion — the intent is to keep datetime → YYYY-MM-DD rather than the bare-date path with a default constructor).

### Why the existing `_deadline_iso_date` stays unchanged

The brief called this out: the new `mode='before'` validator produces a string (or `None`), then the existing `_deadline_iso_date` runs as-is against the str and asserts `YYYY-MM-DD`. No behavior change for string input.

---

## Tests — 6 new

Added under `tests/test_silver_schema.py` R13 block:

| Test | Input | Expectation |
|---|---|---|
| `test_deadline_accepts_str_yyyy_mm_dd` | `"2026-05-01"` | pass, `fm.deadline == "2026-05-01"` |
| `test_deadline_accepts_date_object` | `date(2026,5,1)` | pass, coerced to `"2026-05-01"` |
| `test_deadline_accepts_datetime_object` | `datetime(2026,5,1,12,tzinfo=UTC)` | pass, coerced to date-only `"2026-05-01"` |
| `test_source_id_accepts_str` | `"68"` | pass, `fm.source_id == "68"` |
| `test_source_id_coerces_int` | `68` | pass, `fm.source_id == "68"` |
| `test_source_id_coerces_large_int` | `9_999_999_999` | pass, `fm.source_id == "9999999999"` |

Existing R13 tests (`test_r13_deadline_valid_iso_date_accepted`, `test_r13_deadline_malformed_rejected`) unchanged and still pass — no regression in the YYYY-MM-DD assertion.

### Focused run

```
$ python -m pytest tests/test_silver_schema.py
============================== 47 passed in 0.08s ==============================
```

---

## Full pytest (no "by inspection")

```
$ python -m pytest tests/
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b2
plugins: langsmith-0.7.33, anyio-4.13.0
collected 842 items

tests/test_1m_storeback_verify.py FFFF                                   [  0%]
tests/test_anthropic_client.py .....................s                    [  3%]
tests/test_bridge_alerts_to_signal.py ..................................[  7%]
...
=========================== short test summary info ============================
FAILED tests/test_1m_storeback_verify.py::test_1_dry_run - FileNotFoundError:...
FAILED tests/test_1m_storeback_verify.py::test_2_mock_analysis - ModuleNotFou...
FAILED tests/test_1m_storeback_verify.py::test_3_chunking - ModuleNotFoundErr...
FAILED tests/test_1m_storeback_verify.py::test_4_failure_resilience - ModuleN...
FAILED tests/test_clickup_client.py::TestWriteSafety::test_add_tag_wrong_space_raises
FAILED tests/test_clickup_client.py::TestWriteSafety::test_create_task_wrong_space_raises
FAILED tests/test_clickup_client.py::TestWriteSafety::test_post_comment_wrong_space_raises
FAILED tests/test_clickup_client.py::TestWriteSafety::test_remove_tag_wrong_space_raises
FAILED tests/test_clickup_client.py::TestWriteSafety::test_update_task_wrong_space_raises
FAILED tests/test_clickup_integration.py::test_tasks_in_database - voyageai.e...
FAILED tests/test_clickup_integration.py::test_qdrant_clickup_collection - vo...
FAILED tests/test_clickup_integration.py::test_watermark_persistence - voyage...
FAILED tests/test_scan_endpoint.py::test_scan_returns_sse_stream - assert 401...
FAILED tests/test_scan_endpoint.py::test_scan_rejects_empty_question - assert...
FAILED tests/test_scan_endpoint.py::test_scan_accepts_history - assert 401 ==...
FAILED tests/test_scan_prompt.py::test_prompt_is_conversational_no_json_requirement
=========== 16 failed, 805 passed, 21 skipped, 19 warnings in 11.89s ===========
```

**Counts:** 16 failed, 805 passed, 21 skipped. Matches brief baseline (`799+N` passed with `N=6` → 805). **Zero new failures.** The 16 failures are byte-identical to the main-branch baseline and trace to external state this local venv doesn't have:

- `test_1m_storeback_verify.py` (4) — FileNotFoundError / ModuleNotFoundError in harness discovery
- `test_clickup_client.py::TestWriteSafety` (5) — ClickUp write-guard tests
- `test_clickup_integration.py` (3) — `voyageai.error` (Voyage API key missing in local env)
- `test_scan_endpoint.py` (3) — `assert 401 == …` (scan endpoint auth returns 401 without live creds)
- `test_scan_prompt.py` (1) — prompt-content assertion

None touch `kbl/schemas/*`, `kbl/steps/step5_opus.py`, or `kbl/steps/step6_finalize.py`.

---

## Part B — `body too short` diagnostic (report-only, no code)

### Query executed

```sql
SELECT sq.id, sq.step_5_decision, sq.primary_matter, sq.finalize_retry_count,
       LENGTH(COALESCE(sq.opus_draft_markdown, '')) AS draft_len,
       LEFT(sq.opus_draft_markdown, 400) AS draft_head
  FROM signal_queue sq
  JOIN kbl_log kl ON kl.signal_id = sq.id
 WHERE kl.component='finalize'
   AND kl.level='WARN'
   AND kl.message LIKE 'body: Value error, body too short%'
   AND kl.ts > NOW() - INTERVAL '48 hours'
 GROUP BY sq.id
 ORDER BY sq.id DESC
 LIMIT 20;
```

### Result — 20 rows

| Bucket | Count | `draft_len` range |
|---|---|---|
| `skip_inbox` (stub, expected short) | 1 | 863 |
| `full_synthesis` — empty draft | 13 | 0 |
| `full_synthesis` — populated draft | 6 | 1876 – 2750 |

**Median `draft_len` across all 20 rows: 0.** Among the 19 `full_synthesis` rows, median is also 0 (13 of 19 are zero).

Matter distribution (from `sq.primary_matter`, routed by Step 1 triage): `hagenauer-rg7` 13, `annaberg` 5, `lilienmatt` 1, null 1 — matches prod traffic shape, not a matter-specific bug.

Populated drafts (head extract):

- id=55 `full_synthesis`, 1969 chars: `title: Forbes Self Made 250 event invitation — Hagenauer attendance angle` — real content, passes frontmatter, body likely borderline
- id=50 `full_synthesis`, 2434 chars: `title: Corinthia two-pager for Marcus Pisani / IHI board`
- id=46 `full_synthesis`, 2750 chars (lilienmatt): `title: Aukera Annaberg €15M financing — viability doubts raised by Balazs`

### Plain-English diagnosis

**Smoking gun: 13 of 19 `full_synthesis` rows (68%) have `LENGTH(opus_draft_markdown) = 0` — Opus wrote nothing.** This is not a body-floor-too-high issue; it is an upstream Step 5 output-capture problem. Either Opus is returning an empty content block (rate-limit / content-filter / thinking-only response with no text block) or the Step 5 capture path writes `''` on some exception branch instead of raising. The body-length floor is firing correctly on empty bodies — it is the reporter, not the root cause.

The 6 rows with real drafts (1876 – 2750 chars total) suggest a secondary class: frontmatter consumes ~1300–1500 chars on complex frontmatters (10+ required keys, related_matters array, money_mentioned structured list), leaving ~500–1500 chars of post-frontmatter body. Most clear the 300-char floor; a handful may legitimately fall under. That's a tail problem, not the headline.

Correlation with `step_5_decision`:
- **No correlation with stub shape** — only 1 of 20 rows is `skip_inbox` (and its 863-char draft still exceeds the 600-char stub cap logic — worth its own look; the stub shape invariant `_stub_status_matches_shape` is for bodies > 600, so that row is tripping `_body_length` on too-short, which is odd if the stub writer is producing the expected ≤600-char body).
- **Problem sits inside `full_synthesis` Opus path** — 19 of 20 rows.

### Recommended next step (for AI Head to brief or not)

A narrow kbl_log scan at `component='step5_opus'` for the 13 empty-draft signal_ids will say whether:
1. Opus API errored (retryable transient) — then Step 5 should raise, not persist empty
2. Opus returned 200 OK with empty `content[0].text` (content-filter, thinking-only block) — then Step 5 should detect empty and mark Step 5 failed, not let a blank draft flow to Step 6
3. Step 5 capture code drops the text on some branch — then direct code bug

Either way: **not a `SilverDocument._body_length` change.** Body floor correctly rejects empty draft; Step 5 should never have produced an empty draft in the first place.

---

## Files changed

```
 kbl/schemas/silver.py       | 38 ++++++++++++++++++++++++++++--
 tests/test_silver_schema.py | 56 +++++++++++++++++++++++++++++++++++++++++++++
 2 files changed, 92 insertions(+), 2 deletions(-)
```

## PR

[#40](https://github.com/vallen300-bit/baker-master/pull/40) — reviewer B3.

## Rule alignment

- **`feedback_no_ship_by_inspection.md`:** full pytest run quoted above with literal counts (805 / 16 / 21). Not "by inspection."
- **`feedback_migration_bootstrap_drift.md`:** N/A — no DB column changes. Schema-level Pydantic validators only; no `store_back.py` touch, no DDL.
- **`feedback_code_working_dirs.md`:** worked in `~/bm-b2` throughout.
- **Timebox:** inside the 90 min cap.

## Post-merge

Per brief:
- Go-forward rows clear Step 6 R3 on `deadline` + `source_id`.
- 9 existing `finalize_failed` rows stay terminal — separate future brief or manual UPDATE handles backfill.
- Part B body-short class → AI Head brief (Step 5 empty-draft investigation) — not this PR.

— B2
