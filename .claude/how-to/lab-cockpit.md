---
name: lab-cockpit
description: Baker Cockpit — the local Director-facing page that shows every fleet seat as a Lab-style card and opens the real terminal in-page. How to open it, deploy/refresh it, add a pilot seat, and its failure modes.
when_to_use: Director asks "open the cockpit / fleet page", a seat card is wrong or missing, the cockpit is blank/offline, you changed the registry or Control Room grouping and the plates look stale, or you are (re)deploying the cockpit static page.
---

# Baker Cockpit — runbook (LAB_COCKPIT_PAGE_1)

The Cockpit is a local page served by the B-1 controller at **http://127.0.0.1:7800/**.
It renders every fleet seat as a Lab-style card grouped into plates (mirroring the
live Lab Control Room), and opens the seat's **real** tmux session in-page (an
on-demand iframe to `/term/<slug>/`). It is Director-only, loopback-only, behind
one Basic-auth prompt per browser session.

- **Substrate:** tmux sessions (the seats) + one ttyd per seat (web viewer) + the
  B-1 Python controller (API + reverse proxy + static host) + launchd (persistence).
- **The page is a pure client:** it builds NO backend. It consumes the controller's
  `GET /api/agents` (live state) + a generated `cockpit_layout.json` (plates + card
  metadata) and posts to `/api/sessions/<slug>/start|go`.

## Open it

Browse to `http://127.0.0.1:7800/`. Enter the local Basic-auth credential when
prompted (stored at `~/Library/Application Support/baker/cockpit/credentials`,
mode 0600 — **read it, never hardcode**). One prompt covers the grid, every
terminal iframe, and every action (same-origin design).

Card reading:
- **AG-### · TERMINAL** = a driveable seat. Green dot + "session up" ⇒ click the
  card to open its live terminal. Dimmed + "▶ Start" ⇒ session down; click Start.
- **AG-### · APP** = an app-claude seat (Cowork). Status-only, no terminal (marked
  "status only — app seat, no terminal").
- **Glance frame** (production Lab semantics, precedence NEEDS_GO > WORKING > NEW):
  green pulse = the seat is asking you "GO?"; amber = working; cyan pulse = new
  unacked bus message.
- **GO ⏎** (card face + open-terminal bar) sends **only Enter** to that tmux
  session — the one-click answer to a "GO?" prompt.
- Open terminal: type directly (keystrokes hit the real session; the native
  Terminal window mirrors them). **Esc**, **✕**, or click the backdrop to return
  to the grid.

## Deploy / refresh the page

Static source lives in the repo at `scripts/cockpit_static/` (index.html,
cockpit.css, cockpit.js, glance_state.js, cockpit_layout.json). The controller
serves them from `~/Library/Application Support/baker/cockpit/static`.

- Full install (controller + static + launchd): `bash scripts/install_cockpit_controller.sh`
  (it now stages `scripts/cockpit_static/` into the deploy static dir).
- Static-only refresh without touching launchd:
  `rsync -a --delete scripts/cockpit_static/ "$HOME/Library/Application Support/baker/cockpit/static/"`
  (StaticFiles serves from disk, so a hard-refresh in the browser picks it up).

## Regenerate the plate layout

`cockpit_layout.json` is a GENERATED artifact — regenerate it when the agent
registry or the live Lab Control Room grouping changes:

```
python3 scripts/generate_cockpit_layout.py --write
```

It mirrors the live Lab `CONTROL_GROUPS` (in `brisen-lab/static/app.js`),
reconciled with the registry (display names, `runtime` → driveable vs app-claude)
and the launch manifest (ports). `--strict` fails if any card can't be placed.
The `_sources` block records the registry + Control-Room SHAs for drift detection.
Commit the regenerated file, then refresh the static dir.

## Add / start a pilot seat

Bring a downed seat up either from the page (its **Start** button) or the
sanctioned sandbox path (also installs the seat's ttyd + marks the ledger):

```
bash scripts/cockpit_migrate.sh sandbox <slug>
```

To add only the web viewer for a seat whose session is already up:
`bash scripts/install_cockpit_ttyd.sh <slug>`.

## Failure modes

- **Cockpit blank / "offline":** the controller is down. It is launchd
  KeepAlive-managed and self-heals in ~1s; check
  `lsof -nP -iTCP:7800 -sTCP:LISTEN`. Killing the controller or any ttyd does
  **not** touch the tmux sessions — native Terminal windows keep working; viewers
  are optional.
- **A card is missing or in the wrong plate:** the layout is stale — regenerate it
  (above). Membership is 100% registry + Control-Room derived; there is no
  hand-kept slug list to edit.
- **"session down" on a seat you expect up:** the tmux session isn't running;
  click Start (sessions do not survive reboot — the processes relaunch fresh).
- **Rollback:** `bash scripts/cockpit_rollback.sh` restores the direct-launch
  Terminal profiles; tmux/ttyd binaries stay inert.

See also: `briefs/SCOPE_LAB_TERMINAL_COCKPIT_1.md` (§5/§6c/§7/§8) and
`COCKPIT_CARD_BEHAVIOR_MOCK.html` (interaction contract).
