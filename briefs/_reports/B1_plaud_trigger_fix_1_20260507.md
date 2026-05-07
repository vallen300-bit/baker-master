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

## GATE-1+3 2nd-pass FOLD — 2026-05-07

**Source:** AH1-T mailbox UPDATE on `CODE_1_PENDING.md` (commit `f2d7350`). I1 dedup + I2 advisory-lock + I3 watermark verification + 2 regression tests. Folded onto existing branch on top of `a11122f`.

### Fold patches (`triggers/plaud_trigger.py`)

| # | Patch | Where |
|---|-------|-------|
| I1 | `_maybe_report_empty_body_alarm()` helper — per-source_id-per-UTC-day dedup before `report_failure("plaud", ...)`; coalesces incremental + backfill call sites (cycle-aware via `trigger_state` synthetic key `plaud_empty_alarm_<source_id>_<YYYYMMDD>`) | new helper at `_maybe_report_empty_body_alarm`; replaces inline blocks at incremental + backfill sentinel sites |
| I2 | `_stale_refresh_advisory_lock()` `@contextmanager` wrapping `pg_try_advisory_xact_lock(hashtext(source_id))`; stale-refresh path acquires lock via `__enter__` and releases via `finally` after iteration body (fail-closed if lock not acquired or no DB conn — skip iteration cleanly) | new helper after `_maybe_report_empty_body_alarm`; iteration body in `check_new_plaud_recordings` wrapped in `try`/`finally` to release lock |
| I3 | **Verification only — no patch needed.** `trigger_state.set_watermark("plaud")` is called once **after** the for-loop (post-iteration tail). Iteration body never advances watermark. Stale-refresh re-uses incremental loop's tail-only watermark management. Already-correct. | n/a |

**Why option A for I1 dedup:** trigger_log audit trail (Director-visible / queryable) > in-memory dict (lost on Render restart, no audit). UTC-day key naturally provides ~24h bucketed dedup with O(1) DB check.

**Why xact lock for I2:** matches AH1-T spec literally; auto-released at txn commit/rollback; one extra pooled conn held for stale-refresh iteration only (4 stuck recordings × 15min = rare). PG handles dedup at storage layer via ON CONFLICT, but Qdrant uses fresh `uuid.uuid4()` per point — without serialization, two Render instances issue duplicate Voyage embedding calls + Qdrant duplicates.

### Regression tests (`tests/test_plaud_trigger.py`)

| Test | Asserts |
|------|---------|
| `test_empty_body_sentinel_dedup_per_source_id` | Two consecutive polls of same broken recording (body<200, dur>5min, is_trans=True) → `report_failure("plaud", ...)` called **exactly 1 time** (stateful `is_processed`/`mark_processed` mocks emulate real trigger_log dedup) |
| `test_stale_refresh_advisory_lock_skips_when_held` | `_stale_refresh_advisory_lock` mocked to yield `False` (peer instance owns lock) → `fetch_plaud_detail`, `format_plaud_transcript`, `store_meeting_transcript` **all uncalled**; iteration skipped cleanly |

### Literal pytest (Ship gate)

```
$ .venv-b1/bin/python -m pytest tests/test_plaud_trigger.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
collected 7 items

tests/test_plaud_trigger.py::test_backfill_skips_un_transcribed PASSED   [ 14%]
tests/test_plaud_trigger.py::test_stale_refresh_re_ingests_empty_db_row PASSED [ 28%]
tests/test_plaud_trigger.py::test_has_empty_db_row_lt_threshold PASSED   [ 42%]
tests/test_plaud_trigger.py::test_empty_body_sentinel_fires PASSED       [ 57%]
tests/test_plaud_trigger.py::test_extract_transcript_text_logs_warnings PASSED [ 71%]
tests/test_plaud_trigger.py::test_empty_body_sentinel_dedup_per_source_id PASSED [ 85%]
tests/test_plaud_trigger.py::test_stale_refresh_advisory_lock_skips_when_held PASSED [100%]

========================= 7 passed, 1 warning in 2.25s =========================
```

**7/7 GREEN. Ship gate satisfied (Lesson #52 — no by-inspection).**

### Full-suite regression check

| Run | Failed | Passed | Skipped | Errors |
|-----|--------|--------|---------|--------|
| Pre-fold (HEAD `a11122f`) | 32 | 1765 | 62 | 30 |
| Post-fold | 32 | **1767** | 62 | 30 |

Identical failure / error pattern. **+2 passes** (the I1 + I2 regression tests). Pre-existing 32 fails / 30 errors are local-env / pollution issues (`test_mcp_vault_tools` collection errors, `test_step6_cortex_dispatch` polluted by earlier test state, `test_scan_endpoint` 401/503 against missing local services) — same set as base, no fold-introduced regressions.

### Files modified (fold)

- `triggers/plaud_trigger.py` — +2 helpers (`_maybe_report_empty_body_alarm`, `_stale_refresh_advisory_lock`), inline empty-body sentinel replaced with helper call at both sites, stale-refresh path wrapped in advisory lock with try/finally release
- `tests/test_plaud_trigger.py` — +2 regression tests

### Status

PR #168 fold pushed. Awaiting:
1. Re-fired focused gate chain on fold diff only (gates 1 + 3) — AH1-T
2. AH2 `/security-review` (gate 2) — running in parallel
3. Merge gated on fold gates PASS + AH2 PASS — AH1-T

---

```
PL ship-report
==============
PR: #168  https://github.com/vallen300-bit/baker-master/pull/168
Branch: b1/plaud-trigger-fix-1
HEAD (pre-fold):  a11122f
HEAD (post-fold): <FOLD_SHA>
Brief: BRIEF_PLAUD_TRIGGER_FIX_1 + GATE-1+3 fold UPDATE (CODE_1_PENDING.md @ f2d7350)
Status: OPEN — fold landed; awaiting re-fired gate-1+3 verdicts + AH2 /security-review

Fold patches:
  I1  Per-source_id-per-UTC-day dedup before report_failure("plaud", ...)
      - Helper: _maybe_report_empty_body_alarm()
      - trigger_log synthetic key: "plaud_empty_alarm_<source_id>_<YYYYMMDD>"
      - Coalesces incremental + backfill sentinel sites (cycle-aware via DB)
      - Option A chosen — auditable; 24h-bucketed via UTC date
  I2  pg_try_advisory_xact_lock(hashtext(source_id)) on stale-refresh
      - Helper: _stale_refresh_advisory_lock @contextmanager
      - Lock held across iteration body via try/finally; auto-released at commit
      - Fail-closed: peer instance holds lock → skip cleanly, no detail / store / Qdrant
  I3  Watermark verification — already-correct, no patch
      - set_watermark called once post-loop; iteration body never advances watermark
      - stale-refresh re-uses incremental loop's tail-only watermark management

Tests (Ship gate — literal, not by-inspection):
  tests/test_plaud_trigger.py        → 7/7 PASSED  (.venv-b1/bin/python -m pytest)
                                        (incl. 2 NEW regression tests:
                                         test_empty_body_sentinel_dedup_per_source_id
                                         test_stale_refresh_advisory_lock_skips_when_held)
  full pytest (regression check)      → +2 passes vs pre-fold baseline (a11122f)
                                        (32 fail / 30 err identical to baseline,
                                         all pre-existing pollution / local-env issues)

Files modified (fold):
  triggers/plaud_trigger.py  +2 helpers, 2 inline sentinel call-sites refactored
                             to use dedup helper, stale-refresh wrapped in lock
  tests/test_plaud_trigger.py  +2 regression tests

Gates next:
  [ ] feature-dev:code-reviewer (gate 1 — fold diff)        — AH1-T re-fire
  [ ] code-architecture-reviewer (gate 3 — fold diff)        — AH1-T re-fire
  [ ] AH2 /security-review (gate 2)                          — AH2 in parallel
  Merge: AH1-T after fold gates PASS + AH2 PASS

Mailbox: CODE_1_PENDING.md (already marked COMPLETE in earlier commit a11122f;
         fold per UPDATE block at commit f2d7350 — does not re-flip status)
Ship report: briefs/_reports/B1_plaud_trigger_fix_1_20260507.md (this file)
```
