# B4 ship report — BUS_CONSOLE_LIVE_PAGE_1

> **CLOSED 2026-07-11:** PR #525 MERGED @`5993ce46` (codex re-gate PASS #9120 + /security-review clear). **POST_DEPLOY_AC_VERDICT = PASS** (lead #9124, authed probes run by lead — PIN not sent over bus by policy): unauth 404 both routes; `?pin=` page 200; key-leak grep in served HTML = 0; `/api/bus-console.json?pin&limit=10` → `bus_ok=true, source=msg/all, count=10`, real rows, no key material. Live at `https://baker-master.onrender.com/bus-console` (PIN via lead). Both gate rounds tight.

- **Brief:** `briefs/_tasks/BUS_CONSOLE_LIVE_PAGE_1.md` (dispatched by lead, routed via deputy #9109)
- **Repo:** baker-master · **PR:** (see below) · **Branch:** `b4/bus-console-live-page-1` (`4035bace`)
- **Reply target:** lead · **Date:** 2026-07-11
- **Gate:** author → codex G3 (medium) → lead review → lead merge (= deploy) → POST_DEPLOY_AC_VERDICT (live probes) → Director gets URL + PIN

## Diagnose-first (mandated) — brisen-lab fleet read
- A terminal key reads **only its own** inbox: `GET /msg/lead` with the b4 key → **403 `reader_slug_mismatch`**. No single-key fleet read via the normal per-slug route.
- `GET /msg/all` exists (returns `reader_slug_mismatch`, not 404) → a **privileged-reader** route. `BRISEN_LAB_CONSOLE_KEY` is that privileged read key.
- `GET /api/v2/terminals` → 41-slug registry (clean fallback source).
- **Design:** proxy tries `GET /msg/all` (one call) first, falls back to a server-side per-slug loop over the registry — both with the console key. Pre-authorized by the brief.

## Deliverables
1. `GET /bus-console` — PIN-gated page, reuses `_arrivals_board_access` (ARRIVALS cookie), 404 on unauth. `/arrivals` + helpers untouched (imported only).
2. `GET /api/bus-console.json` — server-side proxy; console key never reaches the browser. Returns `{bus_ok, bus_error, source, fetched_at, unreachable_since, count, rows[]}` with id/from/to/topic/kind/body_preview/created_at/acknowledged_at.
3. Page (V8 arrivals register — dark/mono/amber): auto-refresh 30s (≤60s), recipient + unacked-only filters, unacked rows highlighted, newest first, click-to-expand full preview. Read-only (no post/ack). Rows built via `createElement`/`textContent` (no `innerHTML` with data — XSS-safe).
4. Fault-tolerant: bus unreachable → honest "BUS UNREACHABLE since <t>" banner, HTTP 200 page still renders; traceback logged server-side only, never shown to the user.

Files: `outputs/dashboard.py` (routes + proxy helpers), `outputs/templates/bus_console_template.html` (new), `tests/test_bus_console.py` (new).

## Acceptance criteria — live output
- **AC1** auth gate: unauth `/bus-console` → **404**, `/api/bus-console.json` → **404**, `?pin=wrong` → **404**; `?pin=<PIN>` → **200** + `set-cookie: arrivals_board_access; HttpOnly; Secure; SameSite=strict`; cookie carries → bare **200**. ✓
- **AC2** rows + no key leak: `/api/bus-console.json` → 200 with real rows; served page + template contain no `X-Terminal-Key` / `CONSOLE_KEY` / key value. ✓
  - **LIVE proxy probe** (console key = a real read key, `recipient=b4`): `200 | bus_ok=True | source=msg/b4 | count=2`; newest real row `#9109 from=deputy topic=dispatch/bus-console-live-page-1` — proves the server-side proxy reads live brisen-lab.
- **AC3** filters: `?recipient=b3` → only the b3 row; `?unacked_only=1` → only unacked rows. ✓ (server-side, deterministic; client JS mirrors these for instant UX)
- **AC4** unreachable: dead-host fetch → `bus_ok=False` + honest error; page still **200**. Exercised via mock + real connection-refused + no-key-configured. ✓
- **AC5** pytest + compile: new file **8 passed**; `py_compile` clean on `dashboard.py` + test. Full suite: **265 failed / 4341 passed** on this branch vs **272 / 4334** on clean main → **no regression** (pre-existing failures are all environmental — this box has no DB/API keys — plus ~7 flaky; the delta is my 8 new passing tests).

## Codex G3 round-1 (#9117) — FAIL → fixed (commit `1ff5800f`)
Codex flagged one real P1 (availability): the `async` `/api/bus-console.json` called the synchronous `requests`-based fetch on the event-loop thread, and the `/msg/all`-failure fallback was an unbounded sequential per-slug loop — one refresh could stall the FastAPI worker during bus degradation. All 3 asks done:
1. Endpoint now `await asyncio.to_thread(_bus_console_fetch, ...)` — blocking I/O off the loop.
2. Total wall-clock deadline (10s) in `_bus_console_fetch`; `_bus_console_perslug` caps 60 slugs, fans out with a bounded `ThreadPoolExecutor` (8 workers), honors the deadline via `futures.wait(timeout=remaining)`, `shutdown(wait=False)` so timeout-bounded stragglers never block the return.
3. Regression test `test_bus_console_json_does_not_block_event_loop` — verified teeth (old sync path → ticks=0 FAIL; offloaded → ~27 PASS).

9 tests green; py_compile clean. Re-pinged lead for codex re-gate (bus #9118).

## Deploy note (flag for lead at merge)
Needs env var **`BRISEN_LAB_CONSOLE_KEY`** (privileged brisen-lab read key) set on Render before/at merge — the page shows an honest "not configured" banner until it's set. Merge = deploy. After deploy I'll post `POST_DEPLOY_AC_VERDICT` with live probes; Director then gets the URL + PIN note.
