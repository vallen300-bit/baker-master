---
type: report
brief: BUS_AUTOWAKE_CONTAINMENT_1
author: b3
status: pr-open
pr: 42
pr_url: https://github.com/vallen300-bit/brisen-lab/pull/42
branch: b3/bus-autowake-containment-1
branch_sha: 5f41e5c5d1fc1748d0f0d0effe8b417faf11f4ac
dispatched_by: cowork-ah1
reply_to: cowork-ah1
authored: 2026-05-25
target_repo: brisen-lab
---

# B3 ship report — BUS_AUTOWAKE_CONTAINMENT_1

## What shipped

Five containment primitives layered on PR #40's bus-arrival auto-wake. Replaces the single global `BRISEN_LAB_AUTOWAKE_ENABLED` kill-switch with surgical, slug-scoped controls.

- **Fix 1** — per-slug 1h sliding cap (`BRISEN_LAB_AUTOWAKE_CAP_PER_HOUR=20`); breach emits `wake_cap_breached` SSE deduped to once per slug per hour.
- **Fix 2** — `BRISEN_LAB_AUTOWAKE_DISABLED_SLUGS` env list (comma-sep), read at hook call time so Render PUTs land on next request.
- **Fix 3** — ping-pong loop detector. 3 loop edges in 5min for one `(sender, recipient)` direction auto-disables both slugs for 1h, emits `wake_loop_auto_disabled` SSE.
- **Fix 4** — `wake_events` audit table; one row per fire AND per suppress (`suppressed_reason ∈ {NULL, 'debounce', 'disabled_slugs', 'cap_hour', 'loop_auto_disabled'}`). Fire-and-forget; audit failures log but cannot poison the post.
- **Fix 5** — `GET /api/wake_health` (Origin-gated identically to `/api/wake`). Returns per-slug `fired_1h` / `fired_24h` / `suppressed_1h` over top 50 slugs by 24h volume, plus `current_disabled` + `auto_disabled_until`.

## Files

| File | Change |
|---|---|
| `bus.py` | 5 module-level state dicts; `_current_disabled_slugs()` + `_maybe_emit_cap_alert()` + `_audit_wake_event()` helpers; expanded auto-wake hook block in `_post_msg_inner` |
| `app.py` | new `GET /api/wake_health` endpoint |
| `db.py` | new `wake_events` table + 2 indices in `SCHEMA_V2_SQL` |
| `tests/test_bus_autowake_containment.py` | NEW — 8 unit tests |

## Hook order (each skip writes audit row)

1. `recipient ∈ TERMINALS` (existing) — `*` / non-picker → skip silently (no audit row, consistent with PR #40)
2. `recipient ∈ BRISEN_LAB_AUTOWAKE_DISABLED_SLUGS` → `suppressed_reason='disabled_slugs'`
3. `_auto_disabled_until[recipient] > now_mono` → `suppressed_reason='loop_auto_disabled'`
4. `_now_mono - _last_wake_emit_at[recipient] < 5.0` (existing debounce) → `suppressed_reason='debounce'`
5. `len(_wake_count_by_slug[recipient]) >= cap` → emit alert + `suppressed_reason='cap_hour'`
6. Loop edge tracking; 3rd loop edge for `(sender,recipient)` in 5min → set `_auto_disabled_until[both]=now+3600` + emit `wake_loop_auto_disabled` + `suppressed_reason='loop_auto_disabled'`
7. Fire `wake_request` + `suppressed_reason=NULL`

## Test plan (literal pytest)

```
$ pytest tests/test_bus_autowake.py tests/test_bus_autowake_containment.py -v
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0
collecting ... collected 16 items

tests/test_bus_autowake.py::test_single_message_to_picker_fires_wake PASSED [  6%]
tests/test_bus_autowake.py::test_burst_within_window_fires_once PASSED   [ 12%]
tests/test_bus_autowake.py::test_burst_spanning_window_fires_twice PASSED [ 18%]
tests/test_bus_autowake.py::test_wildcard_broadcast_does_not_fire_wake PASSED [ 25%]
tests/test_bus_autowake.py::test_two_distinct_slugs_both_fire PASSED     [ 31%]
tests/test_bus_autowake.py::test_non_picker_recipient_does_not_fire_wake PASSED [ 37%]
tests/test_bus_autowake.py::test_kill_switch_off_suppresses_wake PASSED  [ 43%]
tests/test_bus_autowake.py::test_kill_switch_unset_defaults_to_enabled PASSED [ 50%]
tests/test_bus_autowake_containment.py::test_cap_per_hour_default_caps_at_20 PASSED [ 56%]
tests/test_bus_autowake_containment.py::test_cap_per_hour_env_override PASSED [ 62%]
tests/test_bus_autowake_containment.py::test_disabled_slugs_env_skips_b1_but_b2_fires PASSED [ 68%]
tests/test_bus_autowake_containment.py::test_loop_detector_auto_disables_after_three_edges PASSED [ 75%]
tests/test_bus_autowake_containment.py::test_loop_auto_disable_clears_after_window PASSED [ 81%]
tests/test_bus_autowake_containment.py::test_audit_row_on_fire PASSED    [ 87%]
tests/test_bus_autowake_containment.py::test_wake_health_origin_gate_blocks_bad_origin PASSED [ 93%]
tests/test_bus_autowake_containment.py::test_wake_health_returns_per_slug_counts PASSED [100%]

================== 16 passed, 3 warnings in 160.34s (0:02:40) ==================
```

## Implementation notes

- **Cap-alert dedupe bug caught locally.** First implementation used `now_mono - last < 3600` for dedupe; `last` defaulted to `0.0` and `time.monotonic()` on macOS Python starts at ~0 at process spawn, so the first cap-breach within a process's first hour was silently suppressed. Fix: dict-membership sentinel — `last = _cap_alert_emitted_at.get(recipient)` returns `None` on first call → no suppression.
- **Loop detector is directed.** `_recent_edges` is keyed on `(sender, recipient)` and `_loop_edges_5min` increments only when the reverse edge fired within 60s. Three loop edges in one direction within 5min trigger the auto-disable; the brief's "A→B→A→B→A→B" example corresponds to 6 alternating posts where the 6th (B→A) crosses the threshold.
- **Audit writes are awaited inline** (not `asyncio.create_task`) so tests can verify rows synchronously against the response. Failure path swallows + logs; cannot break the parent post.
- **State bounds**: `|TERMINALS|=14`, `|WORKER_AUTHORITY|≈17` → pair-keyed dicts cap at ~238 entries; per-slug dicts at 14. Lists inside dicts prune to 300s/3600s windows. No unbounded growth.
- **FK + TRUNCATE CASCADE**: `wake_events.msg_id REFERENCES brisen_lab_msg(id)`, so the existing `fresh_db` fixture's `TRUNCATE brisen_lab_msg RESTART IDENTITY CASCADE` cleans `wake_events` between tests.

## Bus reports

- Ship report: bus-post `cowork-ah1` topic `ship/bus-autowake-containment-1` — msg #1138 at 2026-05-25T20:30:03Z.

## Gate chain

1. b3 self-test (pytest green) — ✅ done
2. AH2 (deputy) static review — pending
3. `/security-review` — pending
4. cowork-ah1 merge on PASS / PASS-WITH-NITS

## Post-merge smoke (not in scope for b3)

- 25 rapid posts to b1 → 20 fired + 1 `wake_cap_breached` SSE
- `BRISEN_LAB_AUTOWAKE_DISABLED_SLUGS=b1` env + redeploy → b1 skips with `suppressed_reason='disabled_slugs'`
- 6-post A→B→A→B→A→B ping-pong → `wake_loop_auto_disabled` + both slugs disabled
- `curl -H "Origin: https://brisen-lab.onrender.com" https://brisen-lab.onrender.com/api/wake_health` → 200 + JSON; bad origin → 403
