# B3 Ship Report — LIFECYCLE_INSERT_ATTRIBUTION_1

- **Dispatch:** lead bus #10892 (topic `case-one/lifecycle-insert-attribution`), deputy finding #10877.
- **Repo:** brisen-lab. **Branch:** `b3/lifecycle-insert-attribution-1` off fresh `origin/main` @5a22441 (post-#136 @4f77475, post-#137).
- **PR:** https://github.com/vallen300-bit/brisen-lab/pull/138 (commit 87610ef).
- **Effort:** low. **Gate:** G1 (done) → codex → lead merge.

## Problem
`lifecycle.py` has two daemon direct-insert paths that #134/#135 missed — the THIRD such path:
- `_atomic_session_expiry_and_audit_broadcast` (restart, `topic=lifecycle/restart`)
- `_atomic_forced_kill_broadcast` (forced-kill, `topic=lifecycle/forced-kill`)

Both INSERTs omitted `source`/`unattributed`/`intent`, so live rows #10851/#10853/#10855 landed `source=NULL`, `intent=NULL`.

## Fix
Both inserts now write `source='daemon'`, `unattributed=FALSE`, `intent=_derive_intent(kind)` — identical to the `bus.emit_audit` / `post_daemon_message` pattern shipped in #135 item 3. No schema change (columns already exist).

`_derive_intent` reached via a small `_daemon_intent` helper that **lazy-imports** from `bus` — `bus.py` imports `lifecycle` at module load (line 58), so a top-level import would be circular; deferral mirrors the existing `_lifecycle_span`→`otel_setup` pattern. Single source of truth; derivation not duplicated.

## Done rubric
- [x] Both lifecycle broadcast inserts stamp `source='daemon'`, `unattributed=FALSE`, `intent='event'` (broadcast not obligation-bearing).
- [x] Load-bearing test added and verified to FAIL against origin/main, PASS with fix.
- [x] No new test failures vs baseline.

## Test evidence (isolated local PG, not shared Neon)
`tests/test_lifecycle_insert_attribution.py` — calls both functions directly, asserts the inserted row's `source`/`unattributed`/`intent`.

```
tests/test_lifecycle_insert_attribution.py::test_restart_broadcast_is_attributed PASSED
tests/test_lifecycle_insert_attribution.py::test_forced_kill_broadcast_is_attributed PASSED
2 passed
```

Load-bearing proof (lifecycle.py reverted to origin/main, test kept):
```
FAILED ...::test_restart_broadcast_is_attributed  — AssertionError: source not stamped (got None)
FAILED ...::test_forced_kill_broadcast_is_attributed
2 failed
```

Full suite with fix:
```
26 failed, 666 passed, 1 skipped
```
The 26 are pre-existing autowake / bus-wake-topic-gate failures (cross-region latency + test isolation, orthogonal to lifecycle). Deterministic failing-set diff (fix vs origin/main baseline) = empty; the one transient `test_agent_queue::test_session_heartbeat_touches_active_jobs` blip passes in isolation both with and without the fix (flaky heartbeat timing under full-suite concurrency, present on baseline).

## Files
- `lifecycle.py` — `_daemon_intent` helper + 2 INSERTs (restart + forced-kill).
- `tests/test_lifecycle_insert_attribution.py` — new load-bearing test.
