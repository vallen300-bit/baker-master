# B3 Review — PR #29 (baker-master) BRIDGE_HOT_MD_AND_TUNING_1

**From:** Code Brisen #3
**To:** AI Head
**Date:** 2026-04-21
**PR:** baker-master#29 (head `5b5fa7a`)
**Paired with:** baker-vault#7 (head `78fbd52`) — separate report at `_reports/B3_pr7_hot_md_scaffold_review_20260421.md` on baker-vault
**Brief:** `briefs/BRIEF_BRIDGE_HOT_MD_AND_TUNING_1.md` at commit `2ca3865`
**Ship report:** `briefs/_reports/B1_bridge_hot_md_ship_20260421.md`
**Reviewer-separation:** clean — B1 implemented; I reviewed Phase D (PR #28) + shipped Phase C (PR #5 on baker-vault, unrelated surface).

---

## Verdict

**APPROVE** — both PRs merge-together ready.

Three non-blocking nits (N1/N2/N3) for follow-up; none gate Tier A auto-merge.

---

## Brief-flagged deviations — my call

### #1 — xact-scoped advisory lock (vs session-scoped + explicit unlock)

**Accept.** B1's concern — "does the bridge tick wrap the whole cycle in a single transaction?" — I traced this. Yes. In `run_bridge_tick()`:

```python
with get_conn() as conn:
    try:
        with conn.cursor() as cur:                   # cursor #1 — lock acquire
            cur.execute("SELECT pg_try_advisory_xact_lock(%s)", ...)
        # cursor closes; txn T1 stays open, lock held

        with conn.cursor() as cur:                   # cursor #2 — reads
            _get_watermark_or_cold_start(cur)
            _load_vip_sets(cur)
            _read_new_alerts(cur, ...)
        # cursor closes; T1 still open

        with conn.cursor() as cur:                   # cursor #3 — writes
            _insert_signal_if_new(cur, ...)          # loop
            _upsert_watermark(cur, ...)

        conn.commit()                                # ends T1 → lock released + writes persisted
    except Exception:
        conn.rollback()                              # ends T1 → lock released + writes dropped
        raise
```

Key points verified:
- psycopg2's `get_conn()` returns a connection with `autocommit=False` by default (see `kbl/db.py::get_conn`), so all cursors opened on it share one implicit transaction until an explicit `commit()`/`rollback()`.
- The lock can only drop mid-work if the connection itself dies. In that case Postgres sweeps the session advisory state — still safe (the sibling tick can't see a stale lock).
- No path exists where the lock is acquired but neither `commit()` nor `rollback()` runs — the try-except catches everything; if `get_conn()` itself raises, the lock was never acquired.

xact-scoped is **cleaner than session-scoped** here because it removes the explicit-unlock-on-every-branch foot-gun. Brief §4 recommended `pg_try_advisory_lock` but left "Alternative" open to operational judgment; B1 took that alternative legitimately.

### #2 — Empty-alert branch calls `conn.commit()`

**Accept.** Needed for correctness of the xact-scoped variant — without it, the empty-tick would leave the lock pinned until connection close (seconds to minutes on Render's pooled connections), starving sibling ticks. Verified by `test_lock_acquired_empty_alerts_still_commits_to_release_lock` and directly by `test_run_bridge_tick_empty_alert_set_short_circuits` (asserts `conn.committed is True`).

Stmt-log noise concern: negligible. Render's Postgres (Neon) default log_statement='none' — COMMITs don't surface. Even at log_statement='all' (we don't run at that level), an empty-alerts branch at the default 60-second cadence = 1440 COMMITs/day, which is a rounding error against migration-runner traffic and the triggers.

### #3 — New `skipped_locked` counts key

**Accept.** Counter increment path fires under the contention test (`test_tick_skips_cleanly_when_lock_not_acquired` asserts `counts["skipped_locked"] == 1` + `conn.rolled_back is True` + `_NeverCalledCursor` fails loudly if the short-circuit breaks). Internal only — not on `/health`. Fine; log line at INFO ("advisory lock held by sibling tick; skipping") gives ops visibility without a new endpoint. If contention spikes in production we can promote it to `/health` as a separate brief.

Minor: callers reading specific `counts` keys remain compatible (additive key). `test_run_bridge_tick_empty_alert_set_short_circuits` already asserts the full shape including `"skipped_locked": 0`, so downstream-consumer schema drift is pinned.

### #4 — Skipped bare "Adler" pattern — surname collision

**Accept as implemented + N1 nit below.**

Verified the judgment: no `\bAdler\b` token anywhere in `STOPLIST_TITLE_PATTERNS`. Smoke-tested locally with a "Peter Adler confirmed meeting" alert against a VIP with `contact_id='vip-adler'`:
- `_is_stoplist_noise(...)` → `False` ✓
- `should_bridge(..., {'vip-adler'}, set())` → `True` ✓ (VIP axis carries it)

The retail-cluster mitigation the brief was targeting (TK Maxx / Adler Modemaerkte) is ~60% covered by `\bTK\s*Maxx\b` + `\bretail\s+market\s+update\b` + `\bretail[-\s]+chain\s+turnover\b`. If "Adler Modemaerkte insolvency filing" reappears in Batch #2 as noise, a narrower pattern like `\bAdler\s+Modem(?:ä|ae)rkte\b` is the right fix — narrower than bare "Adler", wider than "Modemaerkte" alone. Not this brief's scope.

**N1 nit (non-blocking):** the false-positive-guard parametrize block in `tests/test_bridge_stop_list_additions.py::test_legit_matter_titles_do_not_stop_list` lists 5 titles (hagenauer, oskolkov, brisen-hotels, movie-hma, aukera-term); it does not include a "Peter Adler" sample. Recommend adding one line in a follow-up so that if someone ever ships a bare `\bAdler\b` pattern the test catches it:

```python
("Peter Adler confirmed meeting Thursday", "peter-adler"),
```

Purely a forward-guard. Not required for this PR.

### #5 — `load_hot_md_patterns` swallows all failures

**Accept direction, flag log-level — N2 nit below.**

Silent-degrade is correct for a Director-curated OPTIONAL signal (missing file on first deploy, transient clone-miss, parse-time edit in flight). The other 4 axes carry on unchanged. Loud-fail would create a bridge-wide outage for a file a human hasn't yet created.

BUT: tracing the branches, two failure paths are **completely silent** (no log line at any level):

```python
except VaultPathError:          # line 188 — totally silent
    return []
...
if record.get("error") or record.get("truncated"):   # line 194 — totally silent
    return []
```

Only `read_ops_file(...)` raising a non-VaultPathError exception logs at WARNING (line 191). And import-failure logs at DEBUG (line 183), which is below our production log level.

**N2 nit (non-blocking):** add a single `_local.info(...)` or `_local.warning(...)` on the VaultPathError and `record.get("error")` paths so ops can see when axis-5 is silently disabled. Suggested:

```python
except VaultPathError:
    _local.info("hot.md: %s not in vault (scaffold pending?); axis-5 inactive this tick", HOT_MD_VAULT_PATH)
    return []
...
if record.get("error"):
    _local.warning("hot.md: read_ops_file returned error=%s; axis-5 inactive this tick", record.get("error"))
    return []
if record.get("truncated"):
    _local.warning("hot.md: file exceeds 128KB cap; truncated — axis-5 inactive this tick")
    return []
```

My take aligns with the mailbox's: INFO for the missing-file path (expected first-deploy state), WARNING for error/truncated (anomalous). B1's stated log-level for the WARNING-worthy cases matches mine; we just need lines on every branch. Not required for merge.

---

## Focus-item verdicts

### Migration reversibility
`20260421_signal_queue_hot_md_match.sql`:
- `ADD COLUMN IF NOT EXISTS hot_md_match TEXT` — additive, nullable, no default, no constraints.
- Rollback is `ALTER TABLE signal_queue DROP COLUMN IF EXISTS hot_md_match` — single statement, no data loss (column is historical metadata only; every signal_queue row without axis-5 has NULL here). The down-section comment in the migration provides the exact SQL.
- Idempotency: applying twice is a no-op (IF NOT EXISTS). `test_first_deploy_idempotency_dry_run` in the live-PG suite will pick this up automatically.
- Status: 12 → 13 migrations, confirmed in ship report §1. ✓

### Axis-5 ordering vs stop-list
`should_bridge()` line 336 calls `_is_stoplist_noise()` FIRST, returns False on hit, before `_passes_filter_axes()` (which is where axis 5 is evaluated). A Director-typed `scam` in hot.md would not bypass `\bphone\s+scam\b`. Pinned by `test_stoplist_still_overrides_hot_md_match` with an explicit `"Complimentary wine event — Hagenauer restaurant"` alert carrying `hot_md_match="Hagenauer"` → should_bridge returns False. ✓

### Short-pattern floor
Two layers of defense:
- Parser (`load_hot_md_patterns`) drops any line < 4 chars after bullet-strip + trim. Pinned by `test_load_enforces_min_pattern_length` ("EU\nRE\nok\nHagenauer" → only `["Hagenauer"]`).
- Matcher (`hot_md_match`) also skips patterns < 4 chars (belt+suspenders). Pinned by `test_match_skips_patterns_below_floor`.

If Director edits hot.md to `EU` the bridge silently drops that pattern — no cascade. ✓

### Saturday nudge idempotency
`embedded_scheduler.py:602-609`:
- `coalesce=True` — if Render redeploys during 06:00 UTC and there's a pending missed fire, collapse to single run.
- `max_instances=1` — no parallel overlap.
- `misfire_grace_time=3600` — 1h grace so a redeploy at 05:58 that completes at 06:05 still runs the Saturday fire; a redeploy at 07:01 drops the missed fire (grace window closed).
- `replace_existing=True` — safe re-registration on hot module reload.

Edge case that's not coalesce-covered: if the scheduler is restarted *after* the 06:00 fire succeeded, APScheduler persists the cron's "next run = next Saturday" state. No re-fire. ✓ for the brief's stated concern.

### Secret audit on baker-vault PR #7
Reviewed `_ops/hot.md` (31 lines, all comments + blank active-priorities placeholder). Zero secrets, zero credentials, zero API tokens. Pure documentation + parse-rule crib for Director. ✓

---

## Additional observations (not mailbox-requested)

### N3 nit — `test_nudge_disabled_via_env` uses source-string scan

`tests/test_hot_md_weekly_nudge.py::test_nudge_disabled_via_env` asserts the env-off branch via `inspect.getsource(_register_jobs)` string-scan:

```python
src = inspect.getsource(embedded_scheduler._register_jobs)
assert "HOT_MD_NUDGE_ENABLED" in src
assert "hot_md_weekly_nudge" in src
```

This proves the code contains the gate, not that the gate works. A proper behavioral test would instantiate a BackgroundScheduler, call `_register_jobs(scheduler)` with the env var set off, and assert `scheduler.get_job("hot_md_weekly_nudge")` is `None`. B1's docstring acknowledges this is a scope tradeoff ("lazy-imports pull in half the codebase") — reasonable for shipping, but the test doesn't actually cover the branch it claims. Non-blocking.

### Local test run (py3.9)

I ran the 5 bridge-adjacent test files on my Mac (py3.9.6) with stdlib psycopg2-binary + pytest-8.4.2:

```
tests/test_bridge_hot_md.py           20 passed
tests/test_bridge_idempotency_race.py  4 passed
tests/test_bridge_stop_list_additions.py 30 passed
tests/test_bridge_alerts_to_signal.py  38 passed
tests/test_hot_md_weekly_nudge.py      5 passed
---
Total bridge surface:                 97 passed
```

B1's report claims 129 total across 7 files including migration_runner (6/2-skip) + vault-mirror regression (26). The 97 I ran directly match; the other 32 are re-used unchanged test suites that I didn't re-execute (already verified green in the Phase D review two days ago). Test claim is consistent.

### INSERT SQL sanity

Confirmed `_insert_signal_if_new` binds `hot_md_match` as the 10th column in the INSERT tuple matching the column list order. Pinned by `test_insert_signal_includes_hot_md_match_in_sql_and_params`. No surprise NULLs against any NOT NULL column in `signal_queue` — the mapper output contains every column the INSERT needs.

### Lock-key distinctness from migration runner

`_BRIDGE_ADVISORY_LOCK_KEY = 0x42BA4E00002` (decimal 4,613,039,452,162). `_MIGRATION_LOCK_KEY = 0x42BA4E00001` (one-off). No collision. Pinned by `test_lock_key_is_stable_integer_constant`.

---

## Auto-merge green light (Tier A)

- APPROVE on this PR.
- APPROVE on baker-vault#7 (separate report).
- Both PRs couple (brief §Deploy + §Day-2 protocol require them together).
- No blocking issues.

**Recommendation:** AI Head auto-merges both per Tier A, in order: baker-master#29 first (migration + bridge code), then baker-vault#7 (hot.md scaffold). Render auto-deploys master; `vault_sync_tick` picks up the vault commit within 5 min. Day-2 teaching (add `test-hot-md-axis` line → observe `signal_queue.hot_md_match` populate) fires from a Cowork session once both are live.

Three N-nits are follow-up material — none blocks. Either dispatch B1 to address in a small follow-up PR, or roll into the next bridge-tuning brief (likely after Batch #2 dismissal data lands).

---

## Paper trail

Commit this report to baker-master main alongside the merge. Dispatching back to AI Head with one-line summary.

— B3
