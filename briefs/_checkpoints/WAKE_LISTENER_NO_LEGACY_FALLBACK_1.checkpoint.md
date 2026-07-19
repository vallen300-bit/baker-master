---
brief_id: WAKE_LISTENER_NO_LEGACY_FALLBACK_1
attempt: 1
dispatched_by: lead (bus #13635, Director-ordered parallel lane)
report_topic: wake-listener-no-legacy-fallback-1
repos:
  - brisen-lab b1/wake-listener-no-legacy-fallback-1 @f2801b8 (off main @505f299)
status: BUILD COMPLETE + pushed; report + codex-gate request posted to lead #13670. Awaiting lead codex gate -> merge -> deploy. Reconcile-retry (req3) dormant until deputy-codex lands the controller echo + receipt endpoint (cross-lane contract flagged #13670).
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

## Next concrete step (owner = lead, then deputy-codex cross-lane)
1. Lead: codex gate @f2801b8 -> merge -> Render deploy.
2. deputy-codex (contract flagged #13670): controller echoes X-Wake-Request-Id into
   wake_events/audit + a receipt-read endpoint {url}/{request_id}->{"landed":bool}; then set
   WAKE_RECEIPT_URL in the listener launchd env to enable reconcile-retry.

## Other parked arc (this session)
CLERK_SEAT_COLLISION_FIX_1 — diagnosed, report B1_CLERK_SEAT_COLLISION_FIX_1_20260719.md on
branch b1/clerk-seat-collision-fix-1 (baker-master). Awaiting lead GO to land the gated
~/.zshrc clerkqwenterm fail-loud diff, then live probes 1/3/4.
