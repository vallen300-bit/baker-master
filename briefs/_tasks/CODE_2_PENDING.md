# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2
**Task posted:** 2026-04-22 (post PR #39 merge)
**Status:** OPEN — `STEP6_VALIDATION_HOTFIX_1` (Cortex-launch-blocking; Director explicit "proceed autonomously, launch Cortex")

---

## Brief-route note (charter §6A)

Freehand hot-fix dispatch. Director skipped the `/write-brief` 6-step and said "proceed as you think fit — launch Cortex." The queue is blocked: every reclaimed row from PR #39 is exhausting Step 6 R3 on the same Pydantic field and landing at `finalize_failed`. This is a production-incident fix, not a feature.

---

## Context — what AI Head already audited

Full `kbl_log` WARN scan for `component='finalize'`, last 48h, **121 validation failures across 58 signals**:

| Pattern | Count | % |
|---|---|---|
| `deadline: Input should be a valid string` | 42 | 35% |
| `body: Value error, body too short (… chars; min 300)` | 52 | 43% |
| `source_id: Input should be a valid string` | 23 | 19% |
| `primary_matter=null with non-empty related_matters` | 2 | 2% |
| `vedana: Input should be 'threat', 'opportunity' or 'routine'` | 2 | 2% |

**Root cause of `deadline`/`source_id` class (54%):** YAML 1.1 auto-coerces unquoted scalars — `2026-05-01` parses as `datetime.date`, bare digits parse as `int`. `SilverFrontmatter` types both as `str`. Pydantic rejects before the existing str-level validators fire. Step 6's existing `fm_dict["source_id"] = str(row.signal_id)` override (step6_finalize.py:614) fixes source_id going forward, but `deadline` has no such guard.

**Root cause of `body too short` class (43%):** unclear — needs a diagnostic query. May be a Step 5 prompt issue (Opus producing thin synthesis on ambiguous matter-routing) or a floor-too-aggressive issue. Out of scope for this brief — investigate only.

## Scope (2 parts — do BOTH)

### Part A — SHIP: `deadline` coercion fix in `kbl/schemas/silver.py`

Add a `mode='before'` validator that stringifies non-string scalars into `YYYY-MM-DD` form, then the existing `_deadline_iso_date` validator runs as today.

**Exact location:** `kbl/schemas/silver.py`, between the `deadline: Optional[str] = None` field declaration (line 148) and the existing `_deadline_iso_date` validator (line 179).

**Shape (exemplar — you tune the signature):**

```python
@field_validator("deadline", mode="before")
@classmethod
def _deadline_coerce_to_str(cls, v: Any) -> Optional[str]:
    """YAML 1.1 auto-parses unquoted ``2026-05-01`` as ``datetime.date``
    before Pydantic sees it. Coerce back to ISO-8601 string so the
    downstream ``_deadline_iso_date`` str-level validator applies.
    Accept ``date`` and ``datetime`` inputs; leave strings and None
    untouched; any other type raises."""
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    raise TypeError(f"deadline: expected str/date/datetime, got {type(v).__name__}")
```

`Any` needs `from typing import Any` (check imports). `date` needs `from datetime import date` (already imports `datetime` — add `date` or verify).

**Don't touch** the existing `_deadline_iso_date` validator. The new one runs first (`mode='before'` runs before typed field validation), produces a string, the existing one then asserts `YYYY-MM-DD`.

**Also add the same pattern for `source_id`** — even though step6_finalize.py:614 overwrites it, the defense-in-depth principle is the whole reason that override exists. Mirror the same `mode='before'` coercion in `SilverFrontmatter` on `source_id`:

```python
@field_validator("source_id", mode="before")
@classmethod
def _source_id_coerce_to_str(cls, v: Any) -> str:
    """YAML may auto-parse numeric source_id as int. Force-string."""
    if isinstance(v, str):
        return v
    return str(v)
```

### Part B — REPORT only: `body too short` diagnostic

Run this query (do not modify body floor logic):

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

Include the result in your ship report. Answer in plain English:

- Is the too-short class correlated with `step_5_decision='skip_inbox'` (expected — stub bodies are intentionally short) vs `'full_synthesis'` (real problem)?
- Median `draft_len` for the too-short class?
- Any smoking gun in the first 400 chars of the drafts (e.g., Opus truncating, producing only frontmatter, empty body, etc.)?

No code changes for Part B. One paragraph of diagnosis, data-backed. AI Head decides next brief based on your findings.

## Tests

### Regression tests in `tests/schemas/test_silver.py` (or nearest existing schema test file)

Add 6 new tests (3 per coerced field):

1. `test_deadline_accepts_str_yyyy_mm_dd` — `"2026-05-01"` → passes.
2. `test_deadline_accepts_date_object` — `date(2026,5,1)` → coerced to `"2026-05-01"`, passes.
3. `test_deadline_accepts_datetime_object` — `datetime(2026,5,1,tzinfo=UTC)` → coerced to `"2026-05-01"`, passes.
4. `test_source_id_accepts_str` — `"68"` → passes.
5. `test_source_id_coerces_int` — `68` → coerced to `"68"`, passes.
6. `test_source_id_coerces_large_int` — `9_999_999_999` → coerced to `"9999999999"`, passes.

Plus regression: the existing `_deadline_iso_date` test file (if any) still passes — don't regress the YYYY-MM-DD format assertion.

### Full pytest (no-ship-by-inspection gate)

Run the full suite. Report `X passed, Y failed, Z skipped`. Expected baseline (per PR #37/#38/#39): `16 failed, 799+N passed, 21 skipped` where N = new tests added. Any NEW failure → REQUEST_CHANGES on yourself; don't ship.

## Out of scope (explicit)

- **Body length floor.** Do NOT modify `_body_length` validator. That's the diagnostic output's job to frame.
- **Step 5 prompt.** Cortex Design §4 #11 — Director territory.
- **vedana / primary_matter edge cases.** 4 rows total; fix-after-cortex-launch.
- **opus_draft_markdown re-generation for already-failed rows.** Those stay terminal — not this brief.

## Ship shape

- PR title: `STEP6_VALIDATION_HOTFIX_1: coerce deadline/source_id YAML scalars to str`
- Branch: `step6-validation-hotfix-1`
- Files changed: `kbl/schemas/silver.py` + new/existing test file. 2 files total.
- Commit style: match PR #38/#39 (one clean commit).
- Ship report path: `briefs/_reports/B2_step6_validation_hotfix_1_<YYYYMMDD>.md`. Include:
  - §before/after for `kbl/schemas/silver.py` (line numbers + diff excerpt)
  - Full pytest log head+tail (no "by inspection")
  - Part B diagnostic paragraph
  - Open-PR link for AI Head routing to B3

**Timebox:** 90 min. If Part A tests fail unexpectedly, ship partial with diagnosis; do NOT chase the body-short issue with code.

**On approve:** Tier A auto-merge. The 9 existing `finalize_failed` rows stay terminal (handled by a separate future brief or manual UPDATE). Go-forward rows clear Step 6 R3 on deadline.

---

**Dispatch timestamp:** 2026-04-22 ~10:20 UTC (AI Head autonomous, post-PR-39 drain observed)
**Working dir:** `~/bm-b2`
