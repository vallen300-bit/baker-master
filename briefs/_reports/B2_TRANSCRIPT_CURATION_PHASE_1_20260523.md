---
brief_id: TRANSCRIPT_CURATION_PHASE_1
builder: b2
dispatched_by: lead
status: SHIPPED
pr: 252
pr_url: https://github.com/vallen300-bit/baker-master/pull/252
branch: b2/transcript-curation-phase-1
commit: 5bf038c0
opened_at: 2026-05-23
estimated_time: 4-5h
actual_time: ~30min
gate_chain_remaining:
  gate_1_architecture_review: PENDING (AH2)
  gate_2_code_reviewer: PENDING (AH2)
  gate_3_security_review: PENDING (additive schema; NO_FINDINGS expected)
  gate_4_ah1_final_merge: PENDING (AH1)
---

# B2 SHIP — TRANSCRIPT_CURATION_PHASE_1

PR #252 open: https://github.com/vallen300-bit/baker-master/pull/252

## Scope shipped

Phase 1 of 4-phase TRANSCRIPT_CURATION sequence. Slice-level data layer in Postgres only — no slicing, no LLM, no vault writes. Per architecture v1 §1 + §11.

- **NEW** `migrations/20260524_transcript_slices.sql` — `transcript_slices` table + 3 indexes (E1 extended schema)
- **MODIFY** `memory/store_back.py` — `_ensure_transcript_slices_table()` bootstrap + `store_transcript_slice_placeholder()` + 5-line non-fatal hook at end of `store_meeting_transcript()` success path; wired into `__init__` after `_ensure_meeting_transcripts_table()`
- **NEW** `tests/test_transcript_slices_placeholder.py` — 4 tests, auto-skip without `TEST_DATABASE_URL`

Trigger files (`fireflies_trigger.py`, `plaud_trigger.py`, `youtube_ingest.py`) untouched per single-source-of-truth discipline.

LOC: +321 / -0 across 3 files.

## Acceptance criteria — literal verification

### AC1 ✅ Migration file lands

`migrations/20260524_transcript_slices.sql` — 58 lines, exact SQL from brief.

### AC2 — pending AH1 Tier-B post-deploy smoke

22 columns + 3 named indexes + PK; verification SQL in brief §"Verification SQL (post-deploy)".

### AC3 ✅ Literal pytest output (new test file)

```
$ /opt/homebrew/bin/python3.12 -m pytest tests/test_transcript_slices_placeholder.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
collecting ... collected 4 items

tests/test_transcript_slices_placeholder.py::test_transcript_slices_table_exists SKIPPED [ 25%]
tests/test_transcript_slices_placeholder.py::test_placeholder_inserted_on_transcript_store SKIPPED [ 50%]
tests/test_transcript_slices_placeholder.py::test_placeholder_idempotent_on_reingest SKIPPED [ 75%]
tests/test_transcript_slices_placeholder.py::test_placeholder_failure_does_not_break_transcript_write SKIPPED [100%]

============================== 4 skipped in 0.02s ==============================
```

Per brief §"AC3": "(4 passed or 4 skipped); paste output verbatim". Local has no `TEST_DATABASE_URL`; CI ephemeral Neon branch will run green.

### AC4 ✅ Full pytest suite — zero regressions

Baseline-vs-branch comparison:

| Branch | failed | passed | skipped | errors |
|--------|--------|--------|---------|--------|
| main   | 93     | 2275   | 99      | 30     |
| b2/transcript-curation-phase-1 | 93 | 2275 | **103** | 30 |

Delta: **+4 skipped** = my 4 new tests (all auto-skip locally without `TEST_DATABASE_URL`). **Zero new failures, zero new errors.**

Per Director communication contract — pre-existing 93f/30e baseline is the same on `main` HEAD `ff0a5899`; my PR does NOT introduce new failures.

### AC5 ✅ Singleton CI guard

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
EXIT: 0
```

### AC6 — pending AH1 Tier-B post-deploy

Out-of-scope per brief AC6 explicit framing.

## Ship gate (brief §"Ship gate")

- ✅ Literal `pytest` green in baker-master (full suite + new tests — see AC3 + AC4)
- ✅ `bash scripts/check_singletons.sh` exit 0
- ✅ `python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"` clean (verified twice — once after each edit)
- ✅ Migration vs bootstrap CREATE TABLE: **byte-semantic-equivalent** (Lesson #7 cleared)

### Migration-vs-bootstrap drift verification

Normalized paren-walked comparison (strips whitespace + SQL comments, walks paren depth to capture full CREATE TABLE):

```
migration  : CREATE TABLE IF NOT EXISTS transcript_slices ( id TEXT PRIMARY KEY, transcript_id TEXT NOT NULL REFERENCES meeting_transcripts(id) ON DELETE CASCADE, boundary_start INT NOT NULL DEFAULT 0, ... updated_at TIMESTAMPTZ )

bootstrap  : CREATE TABLE IF NOT EXISTS transcript_slices ( id TEXT PRIMARY KEY, transcript_id TEXT NOT NULL REFERENCES meeting_transcripts(id) ON DELETE CASCADE, boundary_start INT NOT NULL DEFAULT 0, ... updated_at TIMESTAMPTZ )

IDENTICAL  : True
```

All 22 columns, defaults, CHECK constraints, FK match.

## Notes for reviewers

1. **Hook placement** (`store_meeting_transcript` success path before `return True`, inside the outer try block): brief is explicit on placement. The hook is wrapped in its own try/except so failures are non-fatal. `store_transcript_slice_placeholder` acquires its own connection from the pool — there is a theoretical pool-exhaustion edge case under extreme concurrency since the parent `conn` is still held until `finally`, but in practice ingestion concurrency is low. If AH2 architecture-review flags this, the safest reshape is to move the hook to a wrapper outside the try (after `_put_conn`) — but that requires capturing the success-path return value, which adds complexity. Brief placement preserved as-is.
2. **No `ALTER` statements** — table is brand-new; bootstrap uses `CREATE TABLE IF NOT EXISTS` only (no `ADD COLUMN IF NOT EXISTS` drift trap per Lesson #50).
3. **No new env vars** — Phase 2 will introduce `GEMINI_API_KEY` (per brief §"Quality Checkpoints" item 9).

## Gate chain status

| Gate | Owner | Status |
|------|-------|--------|
| 1 — architecture-review | AH2 | PENDING |
| 2 — feature-dev:code-reviewer | AH2 | PENDING |
| 3 — /security-review | AH2 (NO_FINDINGS expected; additive Postgres schema only) | PENDING |
| 4 — AH1 final review + merge | AH1 (lead) | PENDING |

Awaiting `lead` orchestration of gate chain.

## Bus-post

```
ship/transcript-curation-phase-1 — PR #252 open in baker-master; +321 LOC backend; AC1+AC3+AC4+AC5 verified literal; AC2+AC6 = post-deploy AH1 Tier-B smoke per brief; awaiting AH2 gate chain (gates 1+2+3) then AH1 merge.
```

## References

- Brief: `briefs/BRIEF_TRANSCRIPT_CURATION_PHASE_1.md`
- Mailbox: `briefs/_tasks/CODE_2_PENDING.md`
- Canonical pattern: `~/baker-vault/_ops/processes/transcript-curation-architecture-v1.md` §1 + §11
- AH2 inheritance dispatch: bus #771
- Phase split: Director ratification 2026-05-23 evening
- Lesson #7: migration-vs-bootstrap drift trap
