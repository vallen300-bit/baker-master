# LAB_COCKPIT_CONTROLLER_1 — Deputy-Codex ship report

- **Branch:** `deputy-codex/lab-cockpit-controller-1`
- **Status:** implementation ready for cross-vendor gate
- **Scope:** backend controller only; no cockpit UI
- **Dependency:** B1's `fleet_terminals.sh`, launch manifest, and real B3 tmux/ttyd sandbox

## Delivered

- `scripts/cockpit_controller.py`
  - manifest-only eligible-seat allowlist in registry order
  - `GET /api/agents`
  - `POST /api/sessions/{slug}/start`
  - `POST /api/sessions/{slug}/go` with exactly `tmux send-keys -t <slug> Enter`
  - static serving behind the same Basic-auth boundary
  - HTTP and WebSocket ttyd proxy at `/term/<slug>/`
  - upstream `Host` and `Origin` rewrite to the ttyd authority
  - pinned Lab glance mapping limited to the six contracted fields
  - 30-second Lab cache with null-field fail-soft behavior
- `scripts/cockpit_controller_launch.sh`
  - runs `fleet_terminals.sh up` before starting the controller
- `scripts/install_cockpit_controller.sh`
  - TCC-safe Application Support deployment
  - generated 0600 launchd plist
- `scripts/launchd/com.baker.cockpit-controller.plist`
  - `RunAtLoad` reboot owner and `KeepAlive`
- `tests/test_cockpit_controller.py`

## Evidence

### Automated

- `python3 -m pytest -q tests/test_cockpit_controller.py` → **6 passed**
- `python3 -m py_compile scripts/cockpit_controller.py` → pass
- `bash -n scripts/cockpit_controller_launch.sh scripts/install_cockpit_controller.sh` → pass
- `plutil -lint scripts/launchd/com.baker.cockpit-controller.plist` → OK
- `git diff --check` → pass

### Local HTTP probes

Run against a live uvicorn controller bound to `127.0.0.1:17802`, with the real
public Lab `/api/v2/terminals` endpoint and a fixture tmux command:

- no Basic auth → `401`
- valid Basic auth `/api/agents` → `200`, manifest seat plus six live Lab fields
- forged `Origin: http://evil.local` → `403`
- `POST /api/sessions/b3/go` → `200`, response confirms `sent: "Enter"`
- unknown slug start → `404`
- `lsof` → controller listened on `127.0.0.1:17802` only

### Proxy probe

Fixture ttyd WebSocket echoed a keystroke through `/term/b3/ws` and captured:

- upstream `Host: 127.0.0.1:18603`
- upstream `Origin: http://127.0.0.1:18603`
- echoed payload returned unchanged

This proves the N2 rewrite path. **AC-C3 real-seat probe is
`PENDING-REAL-SEAT`** until B1 posts the B3 sandbox tmux+ttyd pilot, per lead
ruling #12065. No tmux or ttyd installation was performed in this lane.

### Launchd packaging

Installer dry-run generated and linted the plist. The launch wrapper executes:

1. `fleet_terminals.sh up`
2. controller Python process

Install note: `scripts/install_cockpit_controller.sh` creates the shared
`director:<openssl-rand>` credential at mode `0600` only when absent; it never
overwrites an existing credential. B1's ttyd plist generator reads this same
file.

## Exact URL list for B-2 reviewer

Default controller port: `7800`.

- `GET http://127.0.0.1:7800/`
- `GET http://127.0.0.1:7800/api/agents`
- `POST http://127.0.0.1:7800/api/sessions/<slug>/start`
- `POST http://127.0.0.1:7800/api/sessions/<slug>/go`
- `GET http://127.0.0.1:7800/term/<slug>/`
- `WS ws://127.0.0.1:7800/term/<slug>/ws`

All routes require the shared Basic credential. Browser `Origin` and `Host`
must both be the controller authority. Unknown slugs return `404`; invalid
origin returns `403`; missing credentials return `401`.
