---
brief: BRISEN_LAB_SSE_DAEMON_LAST_SEEN_FIX_1
target_repo: brisen-lab
pr: https://github.com/vallen300-bit/brisen-lab/pull/15
branch: b2/brisen-lab-sse-daemon-last-seen-fix-1
head_sha: 23bd389
base_sha: 4fba231
shipped_at: 2026-05-12
shipped_by: b2
trigger_class: TIER_B_FRONTEND_SSE_BACKEND_FIX
gates:
  pytest: GREEN (119 passed, 1 skipped, 527.72s)
  py_compile: GREEN
  ah2_security_review: PENDING
  picker_architect: PENDING
---

# B2 ship report — BRISEN_LAB_SSE_DAEMON_LAST_SEEN_FIX_1

## Outcome

PR #15 open against `brisen-lab` main. Three files changed (`app.py`, `static/app.js`, new test). Backend `/api/snapshot` now emits `daemon_last_seen` as part of the SSE payload; the PR #14 frontend receipt-time stamp is removed.

## What changed

1. **`app.py` `/api/snapshot`** — compute `daemon_last_seen = datetime.now(timezone.utc)` once; thread it into both the `INSERT … VALUES` clause and the `ON CONFLICT … DO UPDATE SET` (replacing both `NOW()` calls), then attach the ISO string to the `_broadcast` payload via `{**body, "daemon_last_seen": daemon_last_seen.isoformat()}`. DB column and wire value are now the same instant — no read-back race, no client/server skew.
2. **`static/app.js` `ingest()`** — drop the PR #14 hotfix block; assign `msg.snapshot` directly to `state.snapshots[alias]`. `cardState()` already consumes `daemon_last_seen` + the 12h green window.
3. **`tests/test_snapshot_broadcast_daemon_last_seen.py`** — new regression test. Subscribes a queue to `app._subscribers`, POSTs `/api/snapshot`, asserts the resulting `snapshot` broadcast envelope contains `daemon_last_seen` as a timezone-aware ISO-8601 string.

## Ship gate evidence

Literal `python3 -m pytest tests/ -v` against the Neon test DB (`TEST_DATABASE_URL_BRISEN_LAB`):

```
============ 119 passed, 1 skipped, 3 warnings in 527.72s (0:08:47) ============
tests/test_snapshot_broadcast_daemon_last_seen.py::test_snapshot_broadcast_includes_daemon_last_seen PASSED [ 92%]
```

Full log retained at `/tmp/b2-pytest-full2.log` on this builder.

## In-flight notes

- First full-suite run failed the new test with a Python 3.9 `RuntimeError: There is no current event loop in thread 'MainThread'` — earlier `TestClient` contexts had torn down the implicit loop before my test ran solo (suite-order-sensitive). Fixed by re-seating the loop with `asyncio.set_event_loop(asyncio.new_event_loop())` inside the test, before instantiating `asyncio.Queue`. Suite is now order-stable.
- `_broadcast` is sync (`put_nowait`); no asyncio bridge needed for the new ISO field — it serialises through the existing `json.dumps(msg)` in the SSE gen loop.
- No DB schema change. `forge_snapshots.daemon_last_seen` was already `TIMESTAMPTZ`; we just switched from server-side `NOW()` to a Python-supplied timestamp.

## Out of scope (not touched)

- `/api/state` read path — already returned `daemon_last_seen` and continues to.
- `cardState()` logic — already canonical; no change.
- `_broadcast()` itself — only its caller in `/api/snapshot` changed.

## Gates still open

- AH2 `/security-review` on the diff (trigger class `TIER_B_FRONTEND_SSE_BACKEND_FIX` is non-auth + non-perimeter, but Tier B routing per brief).
- picker-architect static read on PR #15.
- Post-merge: force a daemon tick on prod `brisen-lab` and confirm cards hold green across 3 SSE cycles 30s apart.

## Bus

- `orient/brisen-lab-sse-daemon-last-seen-fix-1` posted on session start (msg #151).
- `ship/brisen-lab-sse-daemon-last-seen-fix-1` posted on PR open.
