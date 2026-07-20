---
brief_id: WAKE_LISTENER_NO_LEGACY_FALLBACK_1
attempt: 1
dispatched_by: lead (bus #13635, Director-ordered parallel lane)
report_topic: wake-listener-no-legacy-fallback-1
repos:
  - brisen-lab b1/wake-listener-no-legacy-fallback-1 @932f542 (rebased onto lab main @07cd4c8)
status: codex round-5 CLI FAIL #13811 (concurrency layer discarded wakes: P1a coalesce dropped later/newer; P1b saturation dropped 9th) RESOLVED @932f542 — pending-latest slot + pool-queues; re-gate round-6 requested #13816 (lead CLI lane). Awaiting re-gate -> merge -> deploy. Reconcile-retry (req3) + sent:false disposition + controller self-deadline (WAKE_DISPOSITION_REWAKE_1 §task-4) all deferred/out-of-scope.
gate: codex bus gate on @f2801b8 -> lead merge
---

# WAKE_LISTENER_NO_LEGACY_FALLBACK_1 — checkpoint

Brief = lead dispatch bus #13635 (Brief-C, self-contained). Repo brisen-lab,
`tools/wake-listener/wake-listener.py`. Do NOT touch cockpit_controller.py (deputy-codex B+D).

## Done (shipped, pushed @f2801b8)
- req1: `COCKPIT_CONTROLLER_TIMEOUT_S` default 5->15 (above ~11.5s controller worst-case).
- req2: `classify_controller_failure()` — unreachable(never-sent) / refusal(4xx) / ambiguous
  (timeout/5xx/malformed). Legacy fallback ONLY for unreachable+refusal; ambiguous NEVER
  falls back (the duplicate-wake defect).
- req3: `X-Wake-Request-Id` UUID per wake; `_reconcile_wake_landed()` via optional
  `WAKE_RECEIPT_URL`; `_handle_ambiguous_wake()` reconciles + retries via CONTROLLER only
  (never legacy). Receipt unset default = strict at-most-once (log loud + stop).
- req4: tests/test_wake_listener_no_legacy_fallback.py (10) + route test (timeout==15 + rid).

## Tests
- 14 pass (4 route + 10 new) under py3.9 AND py3.12; +18 dispatch-log wake tests green (py3.12).
- Local run needs TEST_DATABASE_URL (session autouse skip-gate) — used a throwaway local PG
  `brisen_lab_test` (dropped after). duplicate-spawn tests need opentelemetry (local-env dep
  gap, unrelated — they don't import the listener).

## codex #13727 P1 fixes (@2b05636)
- P1a: `_LocalWakeConfigError` raised on pre-send auth/request-build failure inside
  `_post_controller_wake`; `classify_controller_failure` maps it to 'unreachable' ->
  legacy fallback (README 'credentials unreadable -> legacy-fallback'). Split by PHASE:
  pre-send cred ValueError = unreachable(legacy); post-send parse ValueError = ambiguous.
- P1b: derived timeout — `_CONTROLLER_WORST_CASE_S`14.5 (command_timeout 10 + tmux 0.5 +
  verify 1 + recovery 3) x `_CONTROLLER_TIMEOUT_MARGIN`1.4 = 20.3s default, env-overridable.
  Chose Option A. Ambiguous handling unchanged (reconcile-when-available else LOUD stop).
- Tests: 16 pass py3.9 + py3.12 (+credentials-unreadable-legacy, +timeout-env-override,
  +classifier local-error branch).

## codex round-2 #13742 fix (@6377a68) — timeout budget only
Derived CONTROLLER_TIMEOUT_S line-by-line from the ACTUAL controller path
(baker-master scripts/cockpit_controller.py @b0f1d9bf, wake_session -> send_wake ->
_verify_wake_submit): full synchronous worst-case = glance 5 + stale-reread 5 +
inject/verify/recovery (8x _run_tmux @10 + settles) + park bus-post 15 = 107.6s;
x1.15 margin = 123.7s default, documented in-code, env-overridable. Listener-side
only (did NOT touch cockpit_controller.py). +cumulative-delay test (slow-but-live
past old 20.3s -> not dropped). 17 pass py3.9 + py3.12.

## codex round-3 #13763 fix (@3491cf0)
- P1a: added the INITIAL tmux_session_names() 'tmux ls' (10s, runs before glance) to the
  derivation -> worst-case 117.6s, x1.15 = 135.2s default; +derived-floor regression assert.
- P1b: phase-aware transport — ConnectionRefusedError/socket.gaierror = proven pre-send ->
  unreachable(legacy); ConnectionResetError/BrokenPipeError + unknown = post-send -> ambiguous
  (no legacy, no double-wake). +connection-reset test; existing unreachable test uses typed err.
- 18 pass py3.9 + py3.12 (isolated TEST_DATABASE_URL, not skipped). Rebased onto lab main @07cd4c8.

## codex round-4 CLI #13796 fix (@eb7a396) — async dispatch
Made dispatch asynchronous: submit_dispatch() runs each wake in a bounded
ThreadPoolExecutor (WAKE_DISPATCH_WORKERS=8), SSE reader never blocks; 135.2s budget
is now per-dispatch. Per-slug serialization via in-flight coalesce (same seat never
concurrent → at-most-once); different seats parallel. Saturated pool fails loud+drops.
dispatch_wake unchanged. +hung-A-does-not-delay-B test, +same-slug-coalesce test.
20 pass py3.9 + py3.12.

## codex round-5 CLI #13811 fix (@932f542) — never discard a wake
- P1a: replaced coalesce-drop with per-alias pending-LATEST slot (_pending_wakes);
  _run_dispatch loops to drain the parked newest before releasing the alias. At-most-one
  concurrent per alias, newest never lost.
- P1b: no drop on saturation — always submit(), pool queues internally; WARN when
  outstanding depth > 2x workers (WAKE_DISPATCH_BACKLOG_WARN).
- +pending-latest test, +saturation-queues test. 21 pass py3.9 + py3.12.

## Next concrete step (owner = lead, then deputy-codex cross-lane)
1. Lead: re-gate codex round-6 @932f542 (CLI lane) -> merge -> Render deploy.
2. deputy-codex (contract flagged #13670): controller echoes X-Wake-Request-Id into
   wake_events/audit + a receipt-read endpoint {url}/{request_id}->{"landed":bool}; then set
   WAKE_RECEIPT_URL in the listener launchd env to enable reconcile-retry.

## Other parked arc (this session)
CLERK_SEAT_COLLISION_FIX_1 — diagnosed, report B1_CLERK_SEAT_COLLISION_FIX_1_20260719.md on
branch b1/clerk-seat-collision-fix-1 (baker-master). Awaiting lead GO to land the gated
~/.zshrc clerkqwenterm fail-loud diff, then live probes 1/3/4.
