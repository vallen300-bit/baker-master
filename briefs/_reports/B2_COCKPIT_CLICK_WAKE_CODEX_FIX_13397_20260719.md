# B2 — Cockpit card-click wake: codex FAIL #13397 fix round

- **Brief / gate:** gates/cockpit-card-click-wake-inject-1 @8ebc9507 (codex FAIL #13397, fix round dispatched by lead #13416)
- **Branch:** `b2/cockpit-card-click-wake-inject-1` (new HEAD pushed for gate re-route)
- **Date:** 2026-07-19

## What codex flagged → what changed

### P1 — card click on a lean/status-only glance never wakes (critical)
A card hydrated status-only via `/api/agents` carries `unacked_count>0` but
`unacked_messages=None`. `wake_skip_reason` returns `"no unacked message id"`
(controller.py:735-736), and the `/wake` stale-glance refresh only fired on the
exact `"no unacked"` result (1498) — so the click silently no-op'd.
**Fix:** the refresh now triggers on both `"no unacked"` and
`"no unacked message id"`. A forced fresh read carries the message rows and the
second `send_wake` sends.

### P2a — force=1 double-injects across reload / second tab / delayed repeat
A click nudge sets `force=1`, which INTENTIONALLY bypasses the per-message dedupe
+ seat-floor (merged WAKE_INJECT arc — do-not-touch). The only idempotence was a
per-PAGE JS `Map` debounce (cockpit.js:248-263) that does not carry across a
reload, a second tab, or a delayed repeat.
**Fix:** added an INDEPENDENT server-side per-slug click debounce
(`WAKE_CLICK_DEBOUNCE_SECONDS = 4.0`, mirrors the JS 4s), keyed on its own
`last_click_injection` state. It never reads or writes the protected
`message_last` / `last_injection` dedupe state, so the do-not-touch wake logic is
untouched. Only click-origin (`cockpit_click`) wakes are debounced; a genuine
re-nudge past the window still fires.

### P2b — 320px drawer bar overflows (scrollWidth 326 > clientWidth 319)
Copy + Nudge + GO + close overflowed the narrow termbar.
**Fix (cockpit.css @640px block):** tightened `gap` (12→8), button padding
(10→8), capped `.sub` (180→150 + ellipsis), `min-width:0` on the title block so it
yields first, and `flex-wrap: wrap` as a hard backstop so controls can never
overflow horizontally.

### P2c — authenticated client can spoof origin=sweep
The `/wake` endpoint honoured any origin in `_WAKE_AUDIT_ORIGINS` (which includes
`"sweep"`). A browser could label its wake as an internal sweep, forging the audit
source. The sweep origin is produced ONLY by the internal `_backlog_sweep_tick`,
which calls `send_wake` directly (never the HTTP endpoint).
**Fix:** added `_WAKE_CLIENT_ORIGINS = frozenset({cockpit_click})`; the endpoint
accepts only that from clients. A spoofed `origin=sweep` drops to `None`.

## Verification

### pytest (literal)
`python3 -m pytest tests/test_cockpit_wake.py tests/test_cockpit_controller.py -q`
→ **71 passed, 2 warnings in 0.87s**

New tests:
- `test_wake_endpoint_rechecks_after_lean_no_message_id_glance` (P1)
- `test_send_wake_click_debounce_coalesces_repeat_across_pages`,
  `_releases_after_window`, `_is_click_origin_only` (P2a)
- `test_wake_endpoint_rejects_client_spoofed_sweep_origin` (P2c)

### Live 2-seat proof (required by lead — codex found none)
Ran the working-tree controller on 127.0.0.1:7801 (isolated from the live 7800)
with a stub glance + two throwaway tmux seats (`b2proofa`, `b2proofb`), driven
over real HTTP; real tmux injection captured via `capture-pane`.

wake_audit.log (chronological):
```
slug=b2proofa msg=None  source=cockpit_click skipped=no unacked message id   ← P1 first pass (lean glance)
slug=b2proofa msg=13397 source=cockpit_click skipped=None                    ← P1 refresh → SENT (seat 1)
slug=b2proofb msg=99001 source=cockpit_click skipped=None                    ← seat 2 SENT
slug=b2proofb msg=99001 source=cockpit_click skipped=click_deduped           ← P2a debounce (2nd click)
slug=b2proofa msg=13397 source=None          skipped=None                    ← P2c: spoofed origin=sweep dropped to None
```
Both seats' panes showed the landed, submitted nudge:
```
proofa$ [wake] check your bus: 2 unacked — #13397 cockpit-card-click-wake-inject-1
proofb$ [wake] check your bus: 1 unacked — #99001 seat-b-proof (from lead)
```
Both `/wake` responses returned `"verified":"submitted"` (controller's own live
pane-read confirmation).

### P2b live render (headless Chrome, 320×700 device metrics)
Real index.html + cockpit.css, term dialog open, Copy+Nudge+GO+close all shown:
`#termbar scrollWidth 319 == clientWidth 319, overflow 0, flex-wrap wrap`; all four
controls visible in a single row within the 320px viewport.

## Files
- `scripts/cockpit_controller.py` — P1 refresh trigger, P2a click debounce, P2c client-origin allow-list
- `scripts/cockpit_static/cockpit.css` — P2b narrow-width termbar
- `tests/test_cockpit_controller.py`, `tests/test_cockpit_wake.py` — new tests
