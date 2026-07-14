# CHECKPOINT — LIFECYCLE_INSERT_ATTRIBUTION_1

attempt: 1
seat: b3 (dispatch #10892, acked + claimed 2026-07-14)
repo: brisen-lab
branch: b3/lifecycle-insert-attribution-1 (off origin/main @5a22441; pushed)
checkout: /Users/dimitry/bm-b3-brisen-lab
created: 2026-07-14
updated: 2026-07-14

## Brief id
LIFECYCLE_INSERT_ATTRIBUTION_1 — lead dispatch #10892 (deputy finding #10877). ONE micro-PR.
Effort low. Repo: brisen-lab.

## STATUS: BUILT + GREEN + PR #138 OPENED — awaiting codex gate → lead merge
- brisen-lab PR #138 (commit 87610ef). Gate chain: G1 (done) → codex → lead merge.
- G1 PASS: 2/2 new tests green, BOTH load-bearing (verified to fail vs origin/main lifecycle.py, source=None).
  Full suite 26f/666p = zero new failures vs post-#137 baseline (deterministic failing-set diff empty;
  26 = pre-existing autowake/wake-gate isolation).
- Ship report: bm-b3/briefs/_reports/B3_LIFECYCLE_INSERT_ATTRIBUTION_1_2026-07-14.md

## The fix (lifecycle.py, no schema change — columns already exist)
Two daemon direct-insert paths (THIRD path missed by #134/#135):
1. _atomic_session_expiry_and_audit_broadcast (restart, topic=lifecycle/restart)
2. _atomic_forced_kill_broadcast (forced-kill, topic=lifecycle/forced-kill)
Both now stamp source='daemon', unattributed=FALSE, intent=_derive_intent(kind) via new
_daemon_intent helper (lazy-imports bus._derive_intent — bus imports lifecycle, so top-level
import is circular; mirrors _lifecycle_span otel deferral).

## Next concrete step
Await codex verdict on PR #138. On PASS → relay to lead for merge. On request_changes → hot-fix
loop (new commit, never amend; re-verify; reply). No deploy AC of its own (hygiene follow-up).

## Test-DB note
Isolated throwaway local PG: createdb -h /tmp <db>, TEST_DATABASE_URL=postgresql://localhost/<db>?host=/tmp,
run, dropdb. NOT shared Neon. Autowake/heartbeat failures are flaky ±1 — use deterministic same-session
failing-set diff (comm) as authoritative zero-new-failures check, not raw count.

## Claim discipline
Successor claims by the attempt-bump commit on THIS checkpoint. If already bumped, stand down.
At attempt >= 3, stop resuming + escalate to lead with this path + last error.
