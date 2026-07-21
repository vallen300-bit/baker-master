# BRIEF: BUS_CONGESTION_503_DIAGNOSIS_1 — split bus 503s by cause, diagnose the 5.3k/hr wall

```yaml
brief_id: BUS_CONGESTION_503_DIAGNOSIS_1
dispatched_by: lead
assigned_to: b1
repo: brisen-lab (worktree ~/bm-b1/brisen-lab; branch b1/bus-503-diagnosis-1 from origin/main)
status: PENDING
```

## Context

Week-watch ruling threshold MET: 2 consecutive days (2026-07-20, 07-21) of
`bus_busy_retry` walls on nearly every fleet post/ack (3-5 retries each), plus
daemon-unreachable wake drains. Live evidence captured by lead 2026-07-21
morning (`GET /api/v2/pool_stats`):

- `bus_503_rate_1h: 5311` — 5,311 bus 503s in ONE hour.
- Yet `pool: maxconn=40, used=6, free=0` — the pool is NOT saturated.
- `db_gate: capacity 27, waited_count 60 / 66438 acquires, wait_avg 1.1ms` — the gate is NOT the wall.
- Executor: 48/48 live threads, queue_depth 0 — not thread-starved.

**The saturation story does not add up.** 503s at this rate with a near-idle
pool means the dominant raise path is probably NOT genuine pool exhaustion.
`BusPoolExhausted` (→ `app.py` `_pool_exhausted_handler` → 503 `bus_busy_retry`)
has THREE distinct raise sites in `db.py`:

1. `_acquire_conn` (~line 162) — pool genuinely full past the acquire budget (F503 Option A).
2. `"stale-connection probe budget exhausted during checkout"` (~line 386) — probe budget spent walking stale conns (Neon autosuspend fallout).
3. `"all pooled connections stale after N recycle attempts"` (~line 397) — whole pool stale.

The 503 metric (`_record_bus_503` / `bus_503_rate`) counts them as ONE bucket.
We are blind to which path fires. Hypothesis (lead, unconfirmed): stale-probe
paths 2/3 dominate — Neon direct-endpoint conns going stale under autosuspend
or aggressive idle-recycling, every checkout paying probe latency until the
budget blows. A pool-size bump would do NOTHING for that; hence
diagnosis-first, no capacity change in this brief.

## Estimated time: ~3h
## Complexity: Medium
## Prerequisites: none

## Harness V2

- **Context Contract:** read before building: this brief (whole); `db.py` (pool init, `_acquire_conn`, `get_conn` probe loop, `BusPoolExhausted` raise sites); `app.py` lines ~120-200 (`_record_bus_503`, `bus_503_rate`, `_pool_exhausted_handler`, executor sizing); `/api/v2/pool_stats` handler; `tests/test_db_conn_harden.py` + `tests/test_bus_read_path_false_empty_fix_1.py` (existing 503-contract tests). Nothing else required.
- **Task class:** small-fix-production (observability add) + diagnostic report (brisen-lab, production).
- **Done rubric:** terminal = Merged + Deployed + post-deploy AC passed + findings report on bus. Post-deploy AC (lead): `pool_stats` shows per-cause 503 counts live; after ≥30 min of live traffic the dominant cause is identifiable. Writeback: b1 findings report on bus topic `bus-503/diagnosis` with per-cause counts + root-cause verdict + recommended fix (fix itself is a FOLLOW-UP brief, lead-ratified — do not ship it here).
- **Gate plan:** b1 self-test (pytest + local repro of each raise path via monkeypatch) → push branch → blocking codex gate on pushed SHA → lead merge → Render auto-deploy → soak ≥30 min → b1 pulls live per-cause counts → findings report → lead POST_DEPLOY_AC_VERDICT.

---

## Feature 1: per-cause 503 accounting (the instrument)

### Problem
5,311 503s/hour and we cannot tell which of three raise sites fires. Any fix
chosen now would be a guess.

### Current State
- `BusPoolExhausted(str)` carries a message but the handler discards it.
- `_bus_503_events` is a bare timestamp ring; `bus_503_rate()` reports one number.
- `pool_stats` already exposes pool/executor/gate — natural home for the split.

### Engineering Craft Gates
- **Diagnose: THIS IS THE DIAGNOSIS.** Do not skip to a fix. The brief's product is evidence.
- Prototype: N/A — additive metric, established pattern.
- TDD: extend the existing 503-contract tests: each raise site (monkeypatched) increments its own cause bucket; `bus_503_rate` totals still correct.

### Implementation
1. Add a `cause` tag to `BusPoolExhausted` (e.g. constructor arg or subclass-free `cause` attribute set at each raise site: `acquire_timeout` / `stale_probe_budget` / `all_stale` / `other` default).
2. `_record_bus_503(cause)` — keep the bounded ring; add a bounded per-cause counter dict over the same 1h window (same prune discipline; best-effort try/except preserved).
3. `bus_503_rate()` returns the existing fields PLUS `by_cause: {cause: count}` — additive, no consumer breaks (grep dashboard consumers to confirm additive-only).
4. Also log ONE structured line per 503 at WARNING with cause + endpoint path, RATE-LIMITED (e.g. max 1 log per cause per 60s) — Render logs become a second evidence surface without a log flood.
5. Cache-bust N/A (no static assets).

### Key Constraints
- NO pool-size change, NO budget-tuning, NO behavior change on any request path — observability only. The fix is a separate ratified brief.
- 503 contract unchanged: same status, same `{"detail": "bus_busy_retry"}` body (fleet retry loops parse it).
- Metric writes must never break the error handler (existing best-effort discipline).

### Verification
1. `pytest` — extended tests green; suite no regressions (note the 8 known pre-existing registry-drift failures — confirm unchanged on origin/main).
2. Local: monkeypatch each raise path, hit an endpoint, assert per-cause bucket increments and body unchanged.
3. `git diff --stat` vs origin/main: `db.py`, `app.py`, tests only.

## Feature 2: findings report (the diagnosis product)

After merge + deploy, soak ≥30 min of live fleet traffic, then:
1. Pull `pool_stats` 3x over ~30 min; capture `by_cause` counts + pool/gate/executor numbers each pull.
2. Pull Render logs for the rate-limited WARNING lines; note which endpoints dominate.
3. If `stale_probe` causes dominate: capture `_PROBE_IDLE_THRESHOLD_S`, `_PROBE_TIMEOUT_S`, Neon autosuspend setting (report what's visible from code/env; do NOT change Neon config).
4. Post findings to lead on bus (`bus-503/diagnosis`): per-cause table, dominant path, root-cause verdict with confidence, ONE recommended fix + rough size. Surface conflicts if evidence is mixed — do not average.

## Files Modified
- `db.py` (cause tags at raise sites) · `app.py` (per-cause metric + rate-limited log) · existing 503-contract tests extended.

## Do NOT Touch
- Pool sizing / acquire budgets / probe thresholds (values stay as-is) · bus.py message paths · static/ · controller · Neon config · baker-vault.

## Quality Checkpoints
1. 503 body byte-identical (fleet retry parsers).
2. Handler still never throws (best-effort metrics).
3. Log volume bounded (rate limit proven in a test or by construction).
4. Ship report + findings report to lead on bus (`bus-503/diagnosis`) with branch + HEAD SHA; codex gate on pushed SHA.

## Verification SQL
N/A — in-process metrics; evidence via `/api/v2/pool_stats` + Render logs.
