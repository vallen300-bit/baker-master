# B1 ship report — LAB_COCKPIT_PAGE_1 (Cockpit BRIEF B-2)

- **PR:** #585 — `b1/lab-cockpit-page` → `main`
- **Brief:** `briefs/_tasks/LAB_COCKPIT_PAGE_1.md` @2b55d251; scope `SCOPE_LAB_TERMINAL_COCKPIT_1` v1.3.2 §5/§6c/§7/§8/§11
- **Dispatched by:** lead (#12149); claim = attempt-bump commit 2987f5dc, build commit 147eabea
- **Task class:** production UI (Director-facing). Done-state class: local-deploy + live ACs on real seats.

## Done rubric (not just "tests pass")

The brief's done rubric: all ACs live on real tmux seats; pilots B3 + Brisen Desk fully driveable from the page; POST_DEPLOY_AC_VERDICT posted. Status: **build complete, all live ACs green pre-merge on the deployed static; PR open for the gate; POST_DEPLOY_AC_VERDICT posted below (local page — no Render step).**

## What shipped

- `scripts/cockpit_static/` — `index.html` + `cockpit.css` + `cockpit.js` + vendored `glance_state.js` + generated `cockpit_layout.json`. Served by the B-1 controller (static mount at `/`); **no backend built**, interface-consume only.
  - Plate-grouped card grid mirroring the live Control Room (Control Tower / Verification / Specialists / Builders / Matter desks / Ground systems), B1–B4 adjacent.
  - Card face per mock: `AG-### · TERMINAL|APP`, name, session up/down dot; down ⇒ dimmed + **Start**; app-claude ⇒ status-only, no terminal.
  - Glance frames (§5.2) precedence **NEEDS_GO > WORKING > NEW** via `resolveGlanceState`.
  - Click driveable card → on-demand iframe to `/term/<slug>/` (same origin); **Esc/✕/backdrop** closes and drops the iframe (no lingering WS).
  - **GO ⏎** on card face + panel → `POST /api/sessions/<slug>/go` (Enter only), visible feedback.
- `scripts/generate_cockpit_layout.py` — registry-generated plate layout: parses live `CONTROL_GROUPS`, reconciles with registry `runtime` (26 driveable + 12 app-claude) + manifest ports. No hand-kept slug list; provenance SHAs.
- `scripts/install_cockpit_controller.sh` — stages `cockpit_static/` into the deploy static dir (static-asset wiring only).
- `.claude/how-to/lab-cockpit.md` runbook + INDEX one-liner.
- `tests/test_cockpit_layout.py`.

## Test evidence (literal)

```
$ python3 -m pytest tests/test_cockpit_layout.py -q
5 passed

$ python3 -m pytest tests/test_cockpit_controller.py tests/test_cockpit_serve.py tests/test_cockpit_manifest_strict.py -q
18 passed
```

JS: `node --check` clean on cockpit.js + glance_state.js. Generator: `py_compile` clean; `generate_cockpit_layout.py --write` → 38 cards (26 driveable, 12 app-claude, 0 unplaced).

## Live AC results (Chrome, real seats — Lesson #8)

| AC | Result |
|---|---|
| §8 AC-2 / AC-U1 | Open **B3** → real Claude Code session rendered in-page (tmux `[b3] 0:claude.exe`); typed probe reached the **brisen-desk** tmux session (`❯ COCKPIT_KEYSTROKE_PROBE_7742`, then cleared); **GO** → `POST /api/sessions/b3/go` 200, toast "GO → b3 ✓" |
| AC-U1 ≤1 cred prompt | same-origin design: iframe `/term/<slug>/` + all fetches reuse the single Basic-auth session — no per-agent prompt |
| AC-U2 | **brisen-desk** card `down → up` live via its Start button (`POST /start` 200), no page reload |
| AC-U3 | killed controller (:7800) + b3 ttyd (:7608) → tmux b3 + brisen-desk sessions survived (native windows unaffected); launchd relaunched both in <1s, `GET /` 200 |
| AC-U4 | forced a seat to `needs_go=true AND is_working=true` → card rendered `glance-needs-go` (working suppressed); pure resolver confirms `NEEDS_GO` |
| AC-U5 | N/A — context badge flag OFF (`LAB_CONTEXT_BAND_EXPOSURE_1` not live), per brief |
| §8 AC-5 | all listeners (controller + ttyd) bound 127.0.0.1 only |

Grid screenshot: `briefs/_reports/_assets/B1_cockpit_grid_20260717.png`. Pilots b3 + brisen-desk marked migrated in the ledger.

## POST_DEPLOY_AC_VERDICT v1

- **surface:** Baker Cockpit (local page, http://127.0.0.1:7800/) — no Render deploy path; "deploy" = static staged into the controller's static dir + served live.
- **verdict:** PASS (pre-merge, live on real seats). AC-2/AC-U1/AC-U2/AC-U3/AC-U4 PASS; AC-U5 N/A (flag off); §8 AC-5 PASS.
- **re-confirm on merge:** after lead merges, `install_cockpit_controller.sh` restages the static from `main`; re-eyeball pilot cards.

## Decisions / notes for the gate

- **Mock:** was untracked on the lead machine only; now on `main` @b44a7132 (merged into this branch). Behavior aligned to it; scope prose was the fallback for GO + glance (mock doesn't cover them).
- **Grouping:** registry has no class/group fields, so §5.1's "generated from registry class/role fields" is literally unsatisfiable — the binding instruction "mirror the live Control Room, verify at build" is what the generator implements (accepted by lead #12160). No hand-kept slug list.
- **Bug caught by live smoke:** `fetch()` rejects request URLs that inherit credentials from the document URL — fixed by building all request URLs from `location.origin` (also hardens bookmark-with-creds).

## Gate

codex cross-vendor PR review + cross-vendor UI critique → lead line-read + merge → Director eyeball on pilot cards.
