# B1 Ship Report — BUS_CONGESTION_DIAG_2

- **Date:** 2026-07-21
- **Dispatched by:** lead (out-of-band pane nudge — bus write path down both sides)
- **Repo:** brisen-lab
- **Branch/commit:** `b1/bus-congestion-diag-2` @ `449b161` (off main `f8162c3`)
- **PR:** https://github.com/vallen300-bit/brisen-lab/pull/170
- **Status:** shipped, ready for codex gate. NOT merged (b-code scope).
- **Delivery note:** bus writes to `lead` failed (curl_exit=28 / HTTP 000 ×4 = did not land). Per lead's fallback, reporting via pane + this durable file.

## Task (lead verdict dispatch)
Instrument the `stale_probe_budget` cause split — `probe_timeout` vs `stale_detected` vs `connect_timeout` — plus a connect-ms/probe-ms timing histogram in `get_conn`. Evidence-first: **no cure attempt** until the split shows where the 2s budget goes.

## H1 falsified (independently verified b1-side)
- `GET brisen-lab /healthz` → `commit: f8162c3` (lead's deploy-proof marker).
- `git merge-base --is-ancestor d5a19e2 f8162c3` → **TRUE**; only the marker commit sits between.
- ⟹ round-3 discard fix `d5a19e2` has been live since ~12:00Z. Storm persists anyway ⟹ **H2** (2s budget is a time budget; with `free:0` a fresh Neon CONNECT alone can exhaust it and be mislabeled `stale_probe_budget`).

## Changes (observability only — no control-flow / 503-cause change)
- **db.py**: per-checkout timing of connect (`_acquire_conn`) vs probe (`_probe_live`); on budget-exhaust attribute to dominant phase (`connect_timeout` / `probe_timeout` diag counters); count `stale_detected`; bounded `connect_ms`/`probe_ms` rings + `probe_timing_stats()` (count/max/p50/p90/p99 + budget-relative buckets, `>2000ms` bucket = the H2 tell). `get_conn` still raises the **same** `cause="stale_probe_budget"` — request-path contract untouched.
- **app.py**: expose `probe_timing_stats()` at `/api/v2/pool_stats` → `probe_timing`.
- **tests/test_bus_congestion_diag_2.py**: 5 deterministic fake-clock tests.

## How to read during soak
- Fat `connect_ms` `>2000` bucket + `connect_timeout` ≫ `stale_detected` ⟹ **H2** (Neon connect latency — discard can't cure; needs a connect-side fix / by-cause on connect timeout).
- Fat `probe_ms` tail + high `stale_detected` ⟹ stale recycling.

## Tests (python3.12 — repo targets 3.11+; local python3 is 3.9)
- New file: **5 passed** (connect-dominated→connect_timeout, probe-dominated→probe_timeout+stale_detected, hot-trusted, histogram buckets, ring bound).
- `test_stale_probe_discard.py` (direct get_conn regression risk): **pass** — existing `stale_probe_budget` cause assertion unchanged.
- `test_db_conn_harden.py` (by_cause split + 503 handler): **pass**.
- Full suite: **489 passed, 481 skipped** (live-PG), 20 failed. The 20 are **pre-existing env gaps** (missing `pytest-asyncio` for cockpit WS tests + local vault-registry parity data) — identical on the clean base, verified by `git stash`.

## Next (lead-owned)
Codex gate → merge → deploy → poll `/api/v2/pool_stats.probe_timing` during soak to confirm H2 and choose the cure (likely: connect-timeout by-cause + connect-side mitigation, since discard cannot cure Neon connect latency).
