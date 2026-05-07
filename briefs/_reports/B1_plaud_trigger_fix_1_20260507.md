# B1 ship report — BRIEF_PLAUD_TRIGGER_FIX_1

**Date:** 2026-05-07
**Builder:** B1 (App)
**Branch:** `b1/plaud-trigger-fix-1`
**Commit:** `4cf2651`
**PR:** https://github.com/vallen300-bit/baker-master/pull/168
**Brief:** `briefs/BRIEF_PLAUD_TRIGGER_FIX_1.md`
**Mailbox:** `briefs/_tasks/CODE_1_PENDING.md` → COMPLETE

---

## What shipped

5-patch fix for header-only Plaud transcript shells in `triggers/plaud_trigger.py` + new test file `tests/test_plaud_trigger.py`.

| # | Patch | Location | Status |
|---|-------|----------|--------|
| 1 | `backfill_plaud()` — `is_trans` filter (PRIMARY) | line 574 | ✅ |
| 2 | `check_new_plaud_recordings()` — stale-refresh lane | line 353-360 | ✅ |
| 3 | New helper `_has_empty_db_row(source_id, threshold=200)` | line 195-221 | ✅ |
| 4 | Empty-body sentinel `report_failure("plaud", ...)` | both incremental ~line 400 + backfill ~line 605 | ✅ |
| 5 | `_extract_transcript_text` — WARNING logging (url-tail strips signing) | lines 131, 136 | ✅ |
| 6 | `tests/test_plaud_trigger.py` — 5 tests, one per patch | new file | ✅ |

LOC: `2 files changed, 318 insertions(+), 2 deletions(-)`.

---

## Quality checkpoints

### 1. Literal pytest GREEN on `tests/test_plaud_trigger.py`

```
$ python3.12 -m pytest tests/test_plaud_trigger.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b1
plugins: langsmith-0.7.38, anyio-4.12.1
collecting ... collected 5 items

tests/test_plaud_trigger.py::test_backfill_skips_un_transcribed PASSED   [ 20%]
tests/test_plaud_trigger.py::test_stale_refresh_re_ingests_empty_db_row PASSED [ 40%]
tests/test_plaud_trigger.py::test_has_empty_db_row_lt_threshold PASSED   [ 60%]
tests/test_plaud_trigger.py::test_empty_body_sentinel_fires PASSED       [ 80%]
tests/test_plaud_trigger.py::test_extract_transcript_text_logs_warnings PASSED [100%]

========================= 5 passed, 1 warning in 1.56s =========================
```

NOT by-inspection (Lesson #52). Literal `python3.12 -m pytest` invocation; local `python3` is 3.9.6 (lacks PEP 604 `dict | None` union syntax used in `triggers/plaud_trigger.py:40`); Python 3.11+ is repo target per CLAUDE.md "## Stack".

### 2. Full pytest suite — no regression

| Run | Failed | Passed | Skipped | Errors |
|-----|--------|--------|---------|--------|
| main HEAD `4920648` | 67 | 1680 | 69 | 30 |
| `b1/plaud-trigger-fix-1` | 67 | **1685** | 69 | 30 |

Exact same failure / error counts. **+5 passes** (the new plaud trigger tests). Pre-existing 67 failures + 30 errors are local-env dep issues (`ModuleNotFoundError: fastapi` / `google.genai`); not regressions, not introduced by this PR. 6 collection-error files (`test_scan_endpoint.py`, `test_cortex_*.py`, `test_dashboard_kbl_endpoints.py`) excluded via `--ignore` on both runs (also missing-fastapi).

### 3. `grep -n is_trans triggers/plaud_trigger.py` — 2 functional `is_trans` checks

```
329:            if not rec.get("is_trans"):       # incremental (was already there, unchanged)
574:            if not rec.get("is_trans"):       # backfill (NEW — Fix 1, PRIMARY)
406:                if _dur_ms > 300_000 and len(_body) < 200 and rec.get("is_trans"):   # incremental sentinel (Fix 4)
612:                if _dur_ms > 300_000 and len(_body) < 200 and rec.get("is_trans"):   # backfill sentinel (Fix 4)
```

Plus 5 doc/comment occurrences. Brief checkpoint #3 satisfied.

### 4. Stale-refresh test — `store_meeting_transcript` called with full body for re-ingested source_id

`test_stale_refresh_re_ingests_empty_db_row` asserts:
- `_has_empty_db_row` was probed (stale-refresh path entered)
- `fetch_plaud_detail("stale1")` was called (got past `is_processed` short-circuit)
- `store_meeting_transcript` was called with `transcript_id="plaud_stale1"` and `len(full_transcript) > 200`

### 5. Empty-body sentinel test — `report_failure` invoked exactly once

`test_empty_body_sentinel_fires` asserts:
- `report_failure` was called exactly once with topic `"plaud"`
- Message contains `"empty-body-after-transcription"` and `"plaud_empty1"`

### 6. No PLAUD_TOKEN / S3 URL / response body in logs

`test_extract_transcript_text_logs_warnings` asserts:
- `X-Amz-Signature` NOT in any WARNING message (signing material not leaked)
- `X-Amz-Credential` NOT in any WARNING message
- url-tail uses `url.split('?')[0][-40:]` — strips query string entirely before truncating to 40-char path-tail (Gate-4 nit, brief §Fix 5)

`grep -nE "(PLAUD_TOKEN|Authorization|Bearer)" triggers/plaud_trigger.py` shows no leak in new warning calls (existing log lines untouched).

---

## Gates folded

| Gate | Status | Notes |
|------|--------|-------|
| Brief Gate-4 PASS-WITH-NITS (url-tail) | ✅ folded | `url.split('?')[0][-40:]` in `_extract_transcript_text` line 136; query-string signing material stripped |

5-gate review chain (per SKILL.md §Code-reviewer 2nd-pass Protocol — PR touches external API auth surface, Plaud token):
- [ ] `feature-dev:code-reviewer` — logic + edge cases on stale-refresh upsert path
- [ ] `/security-review` — Plaud token handling
- [ ] picker-architect review
- [ ] 2nd-pass `feature-dev:code-reviewer` per SKILL.md
- B1 self-review — clean (this report)

Reviewers: AH1 dispatches per SKILL.md.

---

## Files modified

- `triggers/plaud_trigger.py` — 5 surgical edits (+67 LOC, −2 LOC)
- `tests/test_plaud_trigger.py` — NEW (251 LOC, 5 tests)

## Files NOT touched (per brief §Do NOT Touch)

- `memory/store_back.py:1229+` — `store_meeting_transcript` ON CONFLICT path preserved as-is
- `format_plaud_transcript` — filter is upstream of formatting; unchanged
- `triggers/sentinel_health.py` — `report_failure("plaud", ...)` reuses existing infra; no new sentinel definitions
- 4 broken recordings — Director-side recovery on web.plaud.ai (credits/pairing/language), separate from this preventive ship

---

## Status

PR #168 OPEN. Awaiting AH1 dispatch of 5-gate review chain. No further B1 action until review feedback or merge.

---

```
PL ship-report
==============
PR: #168  https://github.com/vallen300-bit/baker-master/pull/168
Branch: b1/plaud-trigger-fix-1
Commit: 4cf2651
Brief: BRIEF_PLAUD_TRIGGER_FIX_1
Status: OPEN — awaiting 5-gate review chain dispatch (external API auth surface)

Tests:
  tests/test_plaud_trigger.py  → 5/5 PASSED (python3.12 -m pytest, literal)
  full pytest                   → +5 passes vs main baseline; 0 regressions
                                  (67 failed / 30 errors identical pre-existing
                                   local-env dep gaps on main HEAD 4920648)

Patches landed (triggers/plaud_trigger.py):
  1. backfill_plaud is_trans filter      [PRIMARY BUG FIX]
  2. check_new_plaud_recordings stale-refresh lane
  3. _has_empty_db_row helper
  4. Empty-body sentinel report_failure  [both paths]
  5. _extract_transcript_text WARNING + url-tail strips X-Amz-* (Gate-4 nit)

Gates required (SKILL.md §Code-reviewer 2nd-pass Protocol — external API auth):
  [ ] feature-dev:code-reviewer  (logic / stale-refresh upsert)
  [ ] /security-review           (Plaud token handling)
  [ ] picker-architect           (5-gate)
  [ ] 2nd-pass feature-dev:code-reviewer

Note: 4 broken recordings still Plaud-side blocked (Director recovery
needed on web.plaud.ai). This PR is preventive — once Plaud is healthy,
recordings auto-recover via stale-refresh lane.

Mailbox: CODE_1_PENDING.md → COMPLETE
Ship report: briefs/_reports/B1_plaud_trigger_fix_1_20260507.md
```
