# B3 ship report — DEADLINE_MATTER_SLUG_BACKFILL_1

**Brief:** `briefs/BRIEF_DEADLINE_MATTER_SLUG_BACKFILL_1.md`
**Branch:** `b3-matter-slug-backfill` (off `main` @ `3091f50`)
**Date:** 2026-05-13
**Predecessor:** PR #199 (merged `7e07516`)

---

## Scope shipped

### Scope A — write-path classifier closure (4 file edits)

| Door | File | Change |
|---|---|---|
| A1 | `models/deadlines.py:265` | `insert_deadline()` accepts `matter_slug: str = None`; INSERT column list extended. |
| A2 | `models/cortex.py:455` | `cortex_create_deadline()` accepts + passes through `matter_slug`. |
| A3 | `baker_mcp/baker_mcp_server.py:1660` | Compute slug via `_match_matter_slug` + `slug_registry.normalize` BEFORE both cortex + legacy branches; flow into row. |
| A4 | `triggers/clickup_trigger.py:548` | Compute slug before direct INSERT; column added to INSERT statement. |

Backward-compat preserved: `matter_slug` defaults to `None`, existing callers (email/fireflies/dropbox/calendar triggers) unchanged.

### Scope B — `scripts/backfill_matter_slug.py` (NEW, ~330 LOC)

- Dry-run-default; `--apply <ratified.md>` for write mode.
- Three safety rails on `--apply`: file-must-exist + <24h-old, every M-row has non-empty proposed_slug, `BAKER_BACKFILL_DRY_RUN_ONLY=1` kill-switch.
- **Per-row SAVEPOINT pattern** — fixes predecessor v2_followup bug where a single mid-batch UPDATE error rolled back all prior successful UPDATEs.
- Idempotent: `WHERE matter_slug IS NULL` so re-runs over partial sets are safe.

### New tests (9 total — 6 PASS + 3 SKIPPED-live-PG)

- `tests/test_deadline_matter_slug_writepath.py` — 4 tests (3 live-PG round-trip + 1 unit on classifier→normalize integration shape).
- `tests/test_backfill_matter_slug.py` — 5 tests (dry-run 0-row + dry-run mixed buckets + apply happy path idempotent + apply with bad row preserves others via SAVEPOINT + env kill-switch).

---

## Ship gate — literal pytest output

```text
$ BAKER_VAULT_PATH=/Users/dimitry/baker-vault python3.12 -m pytest \
    tests/test_deadline_matter_slug_writepath.py tests/test_backfill_matter_slug.py -v

============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0 -- /opt/homebrew/opt/python@3.12/bin/python3.12
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b3
plugins: langsmith-0.7.38, anyio-4.12.1
collecting ... collected 9 items

tests/test_deadline_matter_slug_writepath.py::test_insert_deadline_matter_slug_roundtrip SKIPPED [ 11%]
tests/test_deadline_matter_slug_writepath.py::test_insert_deadline_without_matter_slug_is_null SKIPPED [ 22%]
tests/test_deadline_matter_slug_writepath.py::test_cortex_create_deadline_propagates_matter_slug SKIPPED [ 33%]
tests/test_deadline_matter_slug_writepath.py::test_match_matter_slug_then_normalize_resolves_to_canonical PASSED [ 44%]
tests/test_backfill_matter_slug.py::test_dry_run_zero_rows_empty_proposal PASSED [ 55%]
tests/test_backfill_matter_slug.py::test_dry_run_mixed_buckets_proposal PASSED [ 66%]
tests/test_backfill_matter_slug.py::test_apply_happy_path_then_idempotent_rerun PASSED [ 77%]
tests/test_backfill_matter_slug.py::test_apply_one_bad_row_savepoint_preserves_others PASSED [ 88%]
tests/test_backfill_matter_slug.py::test_apply_blocked_by_dry_run_only_env PASSED [100%]

========================= 6 passed, 3 skipped in 0.19s ===========================
```

- 3 SKIPPED tests are live-PG round-trip tests gated on `TEST_DATABASE_URL` per documented conftest contract (brief §Verification.6 explicitly allows skip-on-missing).
- Local Python 3.9 in PATH; ran on python3.12 because conftest uses `int | None` annotation (Python 3.10+). CI / Render uses 3.11+.

## Quality checkpoints

- `bash scripts/check_singletons.sh` → **OK: No singleton violations found.**
- `python3.12 -c "import py_compile; py_compile.compile('<f>', doraise=True)"` clean on all 5 modified/created Python files.
- No DDL changes (`git diff --stat migrations/` empty).
- `_match_matter_slug` + `slug_registry.normalize` calls wrapped in try/except — fail-soft → `None` matter_slug.
- All instantiations of `SentinelStoreBack` go through `._get_global_instance()`.

---

## Dry-run executed against prod DB

```text
$ python3.12 scripts/backfill_matter_slug.py
2026-05-13 09:50:50,515 DRY RUN complete: 69 total | M=33 U=36 → /tmp/backfill_matter_slug_proposal_20260513T075050Z.md
```

**Bucket counts: M=33 / U=36 / total=69.**

Proposal file preserved at `briefs/_reports/B3_backfill_matter_slug_20260513T075050Z.md` (committed).

Sample M-section rows (top 5):

| id | description (truncated) | proposed slug |
|---:|---|---|
| 424 | Borrower must sign the Facility Agreement or Break-up Fee of EUR 75,000... | hagenauer-rg7 |
| 433 | Restructure AO's interest (Annaberg-related financing) | personal |
| 441 | TenderMax feasibility spike -- ingest section of MO brand standards... | claimsmax |
| 1033 | Patrick Piras will resign as director and coordinator of Sunny Immo... | austrian-tax |
| 1317 | Tax and legal administration of French company starting | austrian-tax |

Sample U-section: see full proposal file (committed in `briefs/_reports/`).

---

## What does NOT ship (AH1 owns post-merge)

1. Director ratification of the M-bucket sample (33 rows).
2. `--apply <ratified-proposal.md>` against prod from fresh `git pull --rebase origin main` checkout.
3. Render env flip `VAULT_SCANNER_ENABLED=true`.
4. Vault append: `deadline-system-contract-v1.md` v1.6 execution log section (Mac-Mini / Director commits per CHANDA Inv 9).

---

## Lesson application from predecessor (carry-forward — confirmed)

- ✅ Dry-run-by-default + 3 safety rails on `--apply` (verbatim from `backfill_assigned_to.py`).
- ✅ **Per-row SAVEPOINT pattern** for `_apply_updates()` — fixes predecessor v2_followup bug (T4 verifies via recorded SQL log: 3 SAVEPOINTs + 2 RELEASEs + 1 ROLLBACK TO SAVEPOINT on the bad row).
- ✅ Idempotent `WHERE matter_slug IS NULL` — re-run with same ratified file is a no-op.
- ✅ Singleton hook compliance: `SentinelStoreBack._get_global_instance()` only.
- ✅ No DDL touched (column pre-exists per `models/deadlines.py:99`).
- ✅ `/security-review` NOT required (no external surface, no new endpoint, no auth, no PII).
- ✅ `mandatory_2nd_pass: FALSE` honored.

---

## Bus posting

Bus-post on PR open, recipient `lead`, topic `ship/DEADLINE_MATTER_SLUG_BACKFILL_1`, including PR #, test counts, bucket counts, link to committed proposal file.
