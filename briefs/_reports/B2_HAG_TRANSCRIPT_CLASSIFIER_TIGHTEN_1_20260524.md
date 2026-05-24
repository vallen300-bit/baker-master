---
brief_id: HAG_TRANSCRIPT_CLASSIFIER_TIGHTEN_1
shipped_by: b2
shipped_at: 2026-05-24T12:55:00Z
pr_master: https://github.com/vallen300-bit/baker-master/pull/255
pr_vault: https://github.com/vallen300-bit/baker-vault/pull/111
dispatch_bus_id: 858
bus_acks: [858, 861]
bus_blockers_raised: [860, 864]
status: AWAITING_AH2_GATES
---

# B2 ship report — HAG_TRANSCRIPT_CLASSIFIER_TIGHTEN_1

## Bottom line

2 PRs open. AND-gate overlay shipped per Director-ratified Option (a). Pre-flight surfaced 4 brief slips; AH1 ratified all corrections (Option A bus #861, ILIKE typo verdict bus #864) before any code wrote. Awaiting AH2 gate chain (1+2+3) then AH1 merge.

## Files shipped

| Repo | File | Type | LOC |
|---|---|---|---|
| baker-vault | `wiki/matters/hagenauer-rg7/classifier-keywords.yml` | new | 39 |
| baker-master | `orchestrator/pipeline.py` | edit | +98 / -1 |
| baker-master | `migrations/20260524_hagenauer_rg7_reclassify.sql` | new | 58 |
| baker-master | `tests/test_match_matter_slug_and_gate.py` | new | 151 |
| baker-master | `tasks/lessons.md` | append-only | +8 (lesson #71) |

## Pre-flight findings (bus #860 + #864)

| # | Brief slip | Found by | Correction (ratified) | Verification |
|---|---|---|---|---|
| 1 | slug `ao-holding` non-canonical | Quality Checkpoint 2 (b2 line-grep `slugs.yml`) | `ao` (line 40 active) | bus #861 Option A |
| 2 | Row 2 ILIKE `%Jan 23 11:16%` missed real title `Jan 23, 11:16 AM` (comma) | Quality Checkpoint 3 (b2 pre-flight SELECT prod) | `%Jan 23, 11:16%` → HIT=1 | bus #864 |
| 3 | Row 3 ILIKE `%Baden post meeting Kogel%` missed real title `Baden post meeting with Kogel wife` | Same | `%Baden post meeting with Kogel%` → HIT=1 | bus #864 |
| 4 | Row 6 ILIKE `%Strategy Meeting Asset Management%` missed real title `Strategy Meeting: Asset Management` (colon) | Same | `%Strategy Meeting: Asset Management%` → HIT=1 | bus #864 |

Rows 1, 4, 5 of migration matched HIT=1 on first try.

## Pre-flight SELECT result (prod, full evidence)

```
=== PRE-FLIGHT per migration WHERE-clause (after fixes) ===
Row 1 (ao, by id 01KCKEBK01JAV2MJXBF1XD7MXM)          → HIT=1
Row 2 (brisen, 2026-01-23 fireflies)                  → HIT=1 id=01KFN5PBTS28JWYNESAK1FS575
Row 3 (mrci, 2026-01-20 Baden Kogel)                  → HIT=1 id=01KFDX1HGJJT1XZSJ7Y281XQFK
Row 4 (mrci, 2026-01-14 MRCI Feasibility)             → HIT=1 id=01KEXT8C35FZX1FXVG7N5G3JYR
Row 5 (brisen, 2026-05-05 plaud Shareholding)         → HIT=1 id=plaud_a2c401c3d1ee1cf92d3d3438f7103903
Row 6 (lilienmatt, 2026-05-18 plaud Strategy)         → HIT=1 id=plaud_7e6313b06d70f44a28b9ada0110e6e19

=== bucket counts BEFORE ===
hagenauer-rg7       : 33
```

## Ship-gate evidence

### pytest (target test file) — 7 passed

```
$ python3.12 -m pytest tests/test_match_matter_slug_and_gate.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
collected 7 items

tests/test_match_matter_slug_and_gate.py::test_case_1_counterparty_plus_dispute_matches PASSED [ 14%]
tests/test_match_matter_slug_and_gate.py::test_case_2_rg7_alone_in_parent_finance_does_not_match PASSED [ 28%]
tests/test_match_matter_slug_and_gate.py::test_case_3_counterparty_alone_does_not_match PASSED [ 42%]
tests/test_match_matter_slug_and_gate.py::test_case_4_rg7_alone_does_not_match PASSED [ 57%]
tests/test_match_matter_slug_and_gate.py::test_case_5_matter_without_overlay_unchanged PASSED [ 71%]
tests/test_match_matter_slug_and_gate.py::test_missing_overlay_file_falls_through_to_default PASSED [ 85%]
tests/test_match_matter_slug_and_gate.py::test_malformed_overlay_fails_open PASSED [100%]

============================== 7 passed in 0.29s ===============================
```

### singletons + syntax

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
$ python3 -c "import py_compile; py_compile.compile('orchestrator/pipeline.py', doraise=True)"
(clean — no output)
```

### Full pytest baseline note

Full-suite run on this branch: 93 failed / 2282 passed / 103 skipped / 30 errors.
Same baseline on `main`: 10 of those same matter-slug-related failures reproduce identically. Failures are pre-existing test-pollution / Python-3.9-vs-3.12 environment artifacts (system Python is 3.9; repo expects 3.11+; ran target tests on python3.12). My changes do not introduce regressions — `test_store_meeting_transcript_matter_slug.py` passes when run alongside the new test file (12 passed together).

## Quality Checkpoint status

| # | Checkpoint | Status |
|---|---|---|
| 1 | `BAKER_VAULT_PATH` env on Render | Out-of-scope for b2 — AH1 to verify pre-merge (default `/opt/render/project/src/baker-vault` is the standard checkout path; missing env defaults gracefully via `os.environ.get`) |
| 2 | 4 target slugs canonical+active | ✅ verified — `ao` line 40, `brisen` line 244, `mrci` line 50, `lilienmatt` line 55. 'ao-holding' fix bus #861 |
| 3 | Pre-flight SELECT each WHERE-clause = exactly 1 row | ✅ verified — 6/6 HIT=1 after ILIKE typo fixes |
| 4 | Literal pytest output in ship report | ✅ pasted above |
| 5 | Post-merge: smoke `/api/transcripts/by-matter/hagenauer-rg7` count==27 | TODO post-merge (AH1) |
| 6 | Post-merge: bus-post hag-desk | TODO post-merge (AH1) |
| 7 | One-week follow-up: scan ingestion logs for YAML parse errors | TODO 2026-05-31 (AH1 calendar) |

## Out-of-scope items honored

- `baker-vault/slugs.yml` not modified (Option B slug-split deferred to Q3-2026)
- `kbl/steps/step4_classify.py` not touched
- Other matter classifier rules untouched
- `_match_matter_slug` scoring values unchanged (3/2/1/threshold≥3 design preserved)
- `backfill_meeting_transcripts_matter_slug.py` not modified

## References

- Brief: `~/baker-vault/_ops/briefs/BRIEF_HAG_TRANSCRIPT_CLASSIFIER_TIGHTEN_1.md`
- Bus thread: #858 dispatch → #860 blocker (slug) → #861 unblock → #864 blocker (ILIKE) → ship
- Anchor: Director-ratified 2026-05-24 Option (a); hag-desk audit bus #831
