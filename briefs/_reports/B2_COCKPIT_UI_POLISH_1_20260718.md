# B2 ship report — COCKPIT_UI_POLISH_1 (2026-07-18)

**Brief:** COCKPIT_UI_POLISH_1 (lead #12828, @cda17e3f) — D1-D9 + scope-adds #12862 (D8) / #12876 (D9).
**Report topic:** `gates/cockpit-ui-polish-1`. **Worker:** b2.
**Branches (both pushed):**
- baker-master `b2/cockpit-ui-polish` @ HEAD (D1-D3, D8, D9)
- brisen-lab `b2/cockpit-ui-polish` @ HEAD (D4-D5)

Multi-repo, Tier-A (UI + auth-gate). Codex gate requested on both tips; lead merges.

## What shipped, by deliverable

- **D1 — thin Lab-list rows.** Cards → one thin row per seat, fixed 5-col grid
  (dot · identity · unread · ctx · control) so columns align table-style; plate
  groups are slim headers. Whole fleet fits one 1440×900 screen.
- **D2 — ctx meter on every row.** Mini bar+% when numeric, em-dash placeholder
  when null. Never blank, never hidden.
- **D3 — state control on every row.** Start (down) / GO (needs_go) / status chip
  (else). Never conditionally absent.
- **D4 — code-entry page (brisen-lab).** Flag-ON + same-origin browser GET of the
  shell with no/expired token → minimal password-entry page (POSTs to
  `/cockpit/__auth`), no token in source, no logging. Flag-OFF and
  non-browser/cross-origin → bare 404 (surface stays invisible). Wrong code feeds
  a bounded per-client brute-force lockout (5 / 15 min → 429).
- **D5 — 30-day cookie.** Access cookie (entry page AND `?token=` bootstrap) now
  `Max-Age=2592000`, httponly/secure/samesite=strict (was session-only).
- **D6 — installed-copy sync.** Post-merge step for lead (see below).
- **D8 — local working signal.** Controller derives working from tmux's own
  `#{window_activity}` output clock (one batched `list-windows` call) OR'd with
  Lab telemetry. Working rows read amber (dot + wash); live-but-idle = calm blue
  dot. **Mechanism note:** chose `window_activity` over the brief's prescribed
  capture-pane hash-delta — it is the server's output-activity timestamp, not a
  rendered-grid capture, so it needs no force-redraw and is immune to the
  stale-render effect (from COMPOSER_RESIDUAL_DIAG) the hash approach was meant to
  dodge. Read-only, no keystrokes into any seat.
- **D9 — App-resident card → bus-message panel.** Two card modes, zero dead
  clicks: tmux-backed → terminal (unchanged); App-resident (any non-driveable
  seat) → a bus-message panel binding the Lab "Production & Lab" component shape +
  data (Unacknowledged(n) / Last message / Acknowledged(count), from · topic · #id
  · age, Copy, X). Controller surfaces `last_message` + `acked_count`. Passive
  flash-on-new-message + unacked badge on App cards.

## Acceptance criteria

| AC | Verdict | Evidence |
|----|---------|----------|
| AC1 local page thin rows, one screen @1440×900, every row ctx+control | **PASS (local)** | `.smoke/cockpit_ac/ac1_1440x900.png`, `ac1_d8_working_amber.png` (43 rows, one screen; phone 44px in `ac1_phone_390.png`) |
| AC2 Lab page 200 with cookie, grid renders through Render | **PENDING DEPLOY** | needs merge + deploy + access code (will request from lead post-merge) |
| AC3 no-cookie → entry page; correct→grid; wrong ×N→lockout; flag-off→404 | **PARTIAL** | gate branches unit-verified (helper + route tests); live end-to-end pending deploy |
| AC4 cookie Max-Age≈30d (entry + `?token=`) | **PASS** | `test_access_cookie_is_30_days_and_secure` asserts `max-age=2592000` |
| AC5 existing tests green both repos + new gate-branch tests | **PASS (baker) / codex-gate (lab)** | baker-master: 199 cockpit tests green locally. brisen-lab: 18 helper/composition gate tests green; 5 route TestClient tests run under the codex gate (local env lacks opentelemetry) |
| AC6 installed-copy sync + `diff -q` | **PENDING (post-merge, lead)** | D6 step below |
| AC8 mid-build seat amber ≤30s, quiet ≤60s | **PASS** | `test_d8_local_activity_ors_into_is_working` + live probe (b2/b4 activity≈now, researcher frozen); window_activity within 45s → amber next poll (4s) |
| AC9 App-card click opens panel; new message flashes card | **PASS** | live Chrome: panel opens with 3 sections (`.smoke/cockpit_ac/ac9_bus_panel.png`); `test_cockpit_msgpanel.py` locks flash + wiring |

## Tests

- baker-master: `pytest tests/test_cockpit_*.py tests/test_ai_hotel_cockpit.py` → **199 passed**.
  New/updated: `test_cockpit_card_geometry.py` (rewritten to the row contract),
  `test_cockpit_contrast.py` (row selectors, AA intent preserved),
  `test_cockpit_controller.py` (D8 activity + OR), `test_cockpit_msgpanel.py` (D9).
- brisen-lab: `pytest tests/test_cockpit_access_gate.py` → **18 passed, 5 skipped**
  (route tests skip locally on missing opentelemetry; run under the codex gate).

## D6 — installed-copy sync (post-merge, lead)

The live controller serves from `~/Library/Application Support/baker/cockpit/static/`
(confirmed: the running process is that installed copy). After merge:
```
rsync -a --delete ~/bm-b2/scripts/cockpit_static/ "~/Library/Application Support/baker/cockpit/static/"
diff -qr ~/bm-b2/scripts/cockpit_static/ "~/Library/Application Support/baker/cockpit/static/"
```
Then verify via the Lab. (The controller Python itself is also an installed copy;
D8 changes `cockpit_controller.py` — that installed copy needs the same sync +
a controller restart. Flagging so the D8 signal actually goes live.)

## Open items for lead

1. **No prior cockpit lockout existed** — the brief said "existing lockout,
   untouched," but there was none. Built a minimal bounded per-IP lockout
   (5 / 15 min) since a public code-entry surface must have brute-force
   protection. Override the policy if you want different numbers.
2. **D8 mechanism swap** (window_activity vs capture-pane hash) — flagged above;
   simpler + no stale-render dependence. Confirm acceptable.
3. **Access code for AC2/AC3 live** — will request on the bus post-merge to run
   the through-Render cells.
4. **D8 controller installed-copy sync** needs a controller restart to take effect.
