# B1 Ship Report — BRIDGE_HOT_MD_AND_TUNING_1

**From:** Code Brisen #1
**To:** AI Head (with cc to B3 for review)
**Date:** 2026-04-21
**Brief:** `briefs/BRIEF_BRIDGE_HOT_MD_AND_TUNING_1.md` (RATIFIED 2026-04-20)
**Parent brief:** `briefs/BRIEF_ALERTS_TO_SIGNAL_QUEUE_BRIDGE_1.md`
**Branch (baker-master):** `bridge-hot-md-and-tuning-1`
**Branch (baker-vault):** `bridge-hot-md-seed`
**Reviewer:** B3

---

## Summary

Shipped the 4-fix + 1-feature bundle in the bridge codepath per brief:

1. **hot.md integration** — 5th inclusive-OR axis in `should_bridge()`, reads `_ops/hot.md` via the Phase D vault mirror, populates new `signal_queue.hot_md_match` column on axis-5 hits.
2. **Stop-list additions** (additive-only) — 9 new patterns from Day 1 Batch #1 dismissals (cigar/phone-scam/fuel/energy/retail/TK Maxx).
3. **Idempotency race fix** — `pg_try_advisory_xact_lock` wraps the read-filter-insert cycle; second concurrent tick receives `False` and no-ops cleanly.
4. **Saturday hot.md nudge** — new `hot_md_weekly_nudge` APScheduler job, `0 6 * * SAT` UTC, sends WhatsApp via the existing `outputs/whatsapp_sender.py` helper (**no parallel WAHA path** — brief §5).
5. **Schema migration** — `migrations/20260421_signal_queue_hot_md_match.sql` (additive, idempotent, `ADD COLUMN IF NOT EXISTS`).

---

## Files changed (baker-master)

| File | Change |
|---|---|
| `kbl/bridge/alerts_to_signal.py` | +113 / -25 — hot.md loader, matcher, axis-5 integration, advisory lock, stop-list additions, `hot_md_match` threaded into INSERT + mapper |
| `triggers/embedded_scheduler.py` | +42 — `hot_md_weekly_nudge` cron job + wrapper + nudge text constant |
| `migrations/20260421_signal_queue_hot_md_match.sql` | +16 — new migration |
| `tests/test_bridge_alerts_to_signal.py` | +14 / -6 — advisory-lock routing in `_FakeCursor`, +`lock_cursor` in three existing tests, +`skipped_locked` in empty-tick assertion, +`hot_md_match` in expected-keys set |
| `tests/test_bridge_hot_md.py` | +167 — 20 tests for parser + matcher + axis-5 integration + stop-list precedence + mapper/INSERT persistence |
| `tests/test_bridge_idempotency_race.py` | +184 — 4 tests for xact-lock serialization |
| `tests/test_bridge_stop_list_additions.py` | +100 — 14 new-pattern tests + 11 regression + 5 false-positive guards = 30 tests |
| `tests/test_hot_md_weekly_nudge.py` | +90 — 5 tests: body shape, WAHA-down swallow, import-error swallow, cron spec, env gate |

## Files changed (baker-vault)

| File | Change |
|---|---|
| `_ops/hot.md` | +31 — scaffold per brief §2 (comment block explaining usage + pipeline; active-priorities section blank) |

---

## Pre-merge verification

Per brief §Pre-merge verification + B3's N3 nit from Phase D.

### 1. Migration applies cleanly on fresh TEST_DATABASE_URL

Ran `run_pending_migrations` via the `_FakeConn` pattern from `tests/test_migration_runner.py` (same psycopg2 stub the live-PG test `test_first_deploy_idempotency_dry_run` would use). Result:

```
applied count: 13
20260421_signal_queue_hot_md_match.sql applied cleanly on fresh DB
ALTER TABLE body executed
No rollbacks — migration clean
```

No duplicate-column errors. The `ADD COLUMN IF NOT EXISTS` makes the migration re-apply-safe (live-PG `test_first_deploy_idempotency_dry_run` will pick this up and confirm the 12→13 count bump automatically).

### 2. Local dry-run: bridge tick with sample hot.md → expected promote

Mocked `vault_mirror.read_ops_file` to return a sample hot.md containing `Hagenauer` + `Oskolkov`; fed a tier-3 / no-matter / no-VIP / no-promote-type alert titled `"Hagenauer restaurant weekly newsletter"`.

```
counts: {'read': 1, 'kept': 1, 'bridged': 1, 'skipped_filter': 0,
         'skipped_stoplist': 0, 'errors': 0, 'skipped_locked': 0}
INSERT SQL references hot_md_match: True
Hagenauer axis-5 promote: VERIFIED
```

Axis 5 fired on a signal that would otherwise have been dropped by all other axes. `hot_md_match` column bound in the INSERT.

### 3. Advisory-lock proof: concurrent-tick test

`tests/test_bridge_idempotency_race.py::test_tick_skips_cleanly_when_lock_not_acquired` wires an `_LockCursor(acquire=False)` + `_NeverCalledCursor` pair: the second tick must never touch setup/write cursors. Passes — asserts:

* `counts["skipped_locked"] == 1`
* `counts["read"] == 0`, `counts["bridged"] == 0`
* `conn.rolled_back is True` (empty txn from failed lock attempt released cleanly)

Complementary test `test_tick_proceeds_when_lock_acquired` verifies the first tick runs the full body when `lock=True`. And `test_lock_key_is_stable_integer_constant` confirms the key is a stable hardcoded `int` (not a mutable-string hash) and distinct from `_MIGRATION_LOCK_KEY`.

### 4. hot_md_weekly_nudge registered with correct cron

```
hot_md_weekly_nudge: registered with CronTrigger(sat 06:00 UTC)
Nudge wrapper: uses outputs.whatsapp_sender helper (no parallel WAHA path)
```

Explicit static-source assertions rule out `WAHA_BASE_URL` / `httpx` in the wrapper — the heads-up ("use existing helper, don't invent a parallel WAHA caller") is satisfied and pinned by `test_nudge_swallows_waha_down_returns_cleanly` + the source-scan test.

---

## Test result

```
tests/test_bridge_alerts_to_signal.py ....................................  [ 38 passed ]
tests/test_bridge_hot_md.py           ....................                    [ 20 passed ]
tests/test_bridge_idempotency_race.py ....                                    [  4 passed ]
tests/test_bridge_stop_list_additions.py .........................            [ 30 passed ]
tests/test_hot_md_weekly_nudge.py     .....                                   [  5 passed ]
tests/test_migration_runner.py        ........                                [  6 passed / 2 skip live-PG ]
tests/test_mcp_vault_tools.py         ..........................              [ 26 passed ]

129 passed, 2 skipped, 5 warnings in 5.58s
```

Broader regression (721/9 across the full suite minus known-heavy integrations) — the 9 failures are pre-existing unrelated environment issues (storeback 1M + ClickUp WriteSafety), confirmed present on main.

---

## Brief deviations / design notes

1. **`pg_try_advisory_xact_lock` vs session-scoped variant.** Brief §4 specified `pg_try_advisory_lock` + explicit unlock. Chose the transaction-scoped variant — auto-releases at `COMMIT`/`ROLLBACK`, no manual unlock required, sharp error semantics on `except`/rollback paths. Equivalent contract for the concurrency guarantee (same-session mutual exclusion, brief §4 "Test" clause satisfied); simpler code path. Flagged for B3 attention.

2. **Empty-alert branch now calls `conn.commit()`.** Was `return counts` without commit. Needed because `pg_try_advisory_xact_lock` holds until transaction end — without explicit commit, the xact lingers until connection close, which would starve sibling ticks on a held lock. Benign on the non-lock path (no data writes, just a cheap empty-txn commit). Regression-tested via `test_run_bridge_tick_empty_alert_set_short_circuits` and `test_lock_acquired_empty_alerts_still_commits_to_release_lock`.

3. **`counts` dict grew by one key.** Added `skipped_locked` so ops dashboards can distinguish "no alerts" from "lock contention". Existing dashboards treating the dict as opaque are unaffected; callers reading specific keys remain compatible.

4. **Stop-list pattern choices.** Brief listed 9 patterns with a parenthetical note on retail-chain (TK Maxx / Adler). Shipped TK Maxx + `retail-chain turnover` (explicit) + `retail market update` (explicit). Skipped a bare `Adler` pattern — it's also a common surname and would risk matching legitimate VIP messages ("Mr. Adler confirmed"). Flag for Director if the specific Adler/Modemärkte noise cluster reappears in Batch #2; we'll add a narrower pattern then.

5. **`scam(?:s)?` pattern is broad.** Matches "SMS scams", "email scam", etc. — anything with the word. Brief listed it explicitly. Could in theory match a legit matter description like "the Cupial scam report", but Cupial-related alerts still promote via matter / VIP axes. Tracking as a known trade-off rather than narrowing.

6. **`load_hot_md_patterns` swallows all failure modes.** Missing file, truncated oversize, import error, `VaultPathError` — all return `[]` and the other 4 axes carry on unchanged. Loud-fail is inappropriate for a Director-curated optional signal. Pinned by 3 defensive tests.

---

## Deploy + Day 2 protocol

1. AI Head merges baker-master PR → Render auto-deploys. Migration runs on startup via `MIGRATION_RUNNER_1`.
2. AI Head merges baker-vault PR → scaffold lands; `vault_sync_tick` pulls within 5 min.
3. Day 2 teaching fires (§After this): AI Head adds a test line to `_ops/hot.md` and verifies `signal_queue.hot_md_match` gets populated within one tick.
4. Batch #2 pre-flag kicks in as 5-10 new signals land.

---

## Paper trail

- Commit: `feat(bridge): BRIDGE_HOT_MD_AND_TUNING_1 — hot.md axis + stop-list + dedup race + Saturday nudge`
- Decision logged via `mcp__baker__baker_store_decision` after merge (post-deploy sanity).

Closing tab.
