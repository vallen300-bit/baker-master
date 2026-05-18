# B4 ship report — STALE_CYCLE_NUDGE_SENTINEL_1

- **PR:** https://github.com/vallen300-bit/baker-master/pull/219
- **Branch:** `b4/stale-cycle-nudge-sentinel-1`
- **Commit:** `497a561`
- **Brief:** `briefs/BRIEF_STALE_CYCLE_NUDGE_SENTINEL_1.md`
- **Trigger class:** LOW — Gate-1 (AH2 static) + Gate-2 (`/security-review`) required; Gate-3 + Gate-4 not required.
- **Dispatched by:** `lead` (2026-05-18T15:00Z)
- **Shipped:** 2026-05-18T15:25Z

## Files changed (6)

| File | LOC delta | Purpose |
|---|---|---|
| `migrations/20260518_cortex_cycles_add_last_nudge_at.sql` | +30 / new | F1 — additive `ADD COLUMN IF NOT EXISTS last_nudge_at TIMESTAMPTZ NULL`. |
| `memory/store_back.py` | +9 / -1 | Bootstrap mirror — `_ensure_cortex_cycles_table` adds the column + paired `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for already-bootstrapped DBs (migration-vs-bootstrap drift trap). |
| `triggers/stale_cycle_nudge_sentinel.py` | +234 / new | F2 — sentinel module (env-check first, stale + re-nudge SELECT, per-row try/except, sentinel_health reporting). |
| `triggers/embedded_scheduler.py` | +13 | F3 — APScheduler job at 07:00 UTC daily. |
| `tests/test_stale_cycle_nudge_sentinel.py` | +268 / new | 6 hermetic tests covering the 6 brief-required scenarios. |
| `briefs/_tasks/CODE_4_PENDING.md` | +7 / -1 | Mailbox status flips (CLAIMED → SHIPPED_AWAITING_GATES). |

Estimate vs actual: brief said ~120 LOC + 6 tests; actual ~280 module + 268 test (a tad larger to leave the error-isolation and SQL-bound assertions explicit, but kept within scope).

## Acceptance criteria status

1. **F1 + F2 + F3 implemented per contracts.** ✅
2. **Live dry-run (BAKER_CLICKUP_READONLY=true).** ✅ Sentinel returns `{"checked": 0, "nudged": 0, "skipped_readonly": True, "errors": 0}` with zero PG roundtrips (kill-switch is an operator state, not a sentinel outcome — early-exit per contract `step 1`). Flagging brief inconsistency: contract says early-exit with `checked=0`; acceptance §2 says "query executes" with `checked=N`. Went with the contract because the test plan explicitly asserts "zero PG writes."
3. **Live wet-run.** Not exercised in CI (requires seeded prod row + live ClickUp); covered hermetically by `test_nudges_cycle_older_than_threshold`. AH1 may want to run a one-off `python3 -c "from triggers.stale_cycle_nudge_sentinel import run_stale_cycle_nudge_sentinel; print(run_stale_cycle_nudge_sentinel())"` against a seeded `cortex_cycles` row post-merge to close criterion (3) end-to-end.
4. **Anti-spam smoke** — covered hermetically by `test_skips_cycle_nudged_within_window` + `test_renudges_cycle_after_window` at the SQL-boundary level.
5. **All existing tests still pass.** Sibling sentinel + clickup_client regressions clean (the 5 `test_*_wrong_space_raises` failures are pre-existing on `main` — confirmed by stashing my diff and re-running; Director authorized all-space writes 2026-03-25, those tests went stale).

## Literal test output

```
$ python3.12 -m pytest tests/test_stale_cycle_nudge_sentinel.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
collected 6 items

tests/test_stale_cycle_nudge_sentinel.py::test_skipped_when_clickup_readonly PASSED [ 16%]
tests/test_stale_cycle_nudge_sentinel.py::test_returns_zero_when_no_stale_cycles PASSED [ 33%]
tests/test_stale_cycle_nudge_sentinel.py::test_nudges_cycle_older_than_threshold PASSED [ 50%]
tests/test_stale_cycle_nudge_sentinel.py::test_skips_cycle_nudged_within_window PASSED [ 66%]
tests/test_stale_cycle_nudge_sentinel.py::test_renudges_cycle_after_window PASSED [ 83%]
tests/test_stale_cycle_nudge_sentinel.py::test_one_row_failure_does_not_block_others PASSED [100%]

============================== 6 passed in 0.04s ===============================
```

```
$ python3.12 -m pytest tests/test_cortex_stuck_cycle_sentinel.py -q
..........                                                               [100%]
10 passed in 0.05s
```

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

```
$ python3 -c "import py_compile; py_compile.compile('triggers/stale_cycle_nudge_sentinel.py', doraise=True); ..."
OK
```

## Notes for gates

- **Auth touched?** No. ClickUp write path goes through the existing `ClickUpClient` singleton; no new credentials, no new endpoint, no new env var read paths beyond the existing `BAKER_CLICKUP_READONLY` kill switch.
- **DB schema?** Yes — additive, idempotent column. `ADD COLUMN IF NOT EXISTS` is safe on the existing prod table; the bootstrap mirror was updated in lockstep to defeat the Lesson #50 drift trap.
- **External surface?** None. Single ClickUp create_task inside the BAKER-space allowlist; respects per-cycle 10-writes cap (LIMIT 10 on the SELECT enforces this at the source).
- **Per-row isolation.** Each row's ClickUp + UPDATE is wrapped in its own try/except in the entry-point loop. One bad row → other rows still process; sentinel_health reports the top-level outcome.
- **Anti-spam state correctness.** The brief said "UPDATE cortex_cycles SET last_nudge_at=NOW() WHERE cycle_id=%s". I parameterize as text (`WHERE cycle_id::text = %s`) because the SELECT projects cycle_id as text (UUID → str), keeping the round-trip type-safe.
- **Conflict with brief acceptance §2 (`checked=N` under readonly):** flagged above. Implementation followed the contract block (`step 1` early-exit). Trivial 4-line patch if AH1 wants the dry-run to count `checked` while still skipping writes — happy to spin a follow-up.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
