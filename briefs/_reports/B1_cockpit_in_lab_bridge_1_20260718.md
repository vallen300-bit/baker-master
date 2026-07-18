# B1 ship report — COCKPIT_IN_LAB_BRIDGE_1

**Brief:** `briefs/_tasks/COCKPIT_IN_LAB_BRIDGE_1.md` @c1828591 (lead dispatch #12566).
**Date:** 2026-07-18. **Reply-to:** lead, topic `gates/cockpit-in-lab-bridge-1`.
**Branches (pushed):** baker-master `b1/cockpit-in-lab-bridge-1` @c08ac3db · brisen-lab `b1/cockpit-in-lab-bridge-1` @ac2ffd1.
**Status: NOT merge-ready — one design blocker (#2) awaits lead ruling.** Transport (Phase 1 + Phase 2) built + green; all gates run; all codex findings fixed except #2 (escalated, crosses a Do-Not-Touch boundary).

## Done rubric (done-state class: staged-verified)

| Rubric item | Status |
|---|---|
| Loopback integration green (Phase-1 mandatory) | ✅ 10/10 real-uvicorn+WS+agent probe |
| Phase-2 (stretch) ttyd WS | ✅ built + in the 10/10 probe (echo + `tty` subprotocol) |
| Flag-off → 404 on every `/cockpit` HTTP path + nav absent | ✅ verified in probe |
| Flag-off terminal WS | ⚠️ refused/closed (probe verified) but returns **403 not 404** — protocol-inherent (a pre-accept WS cannot emit a 404 body). Kill switch works. |
| Agent installer built NOT loaded | ✅ staged only; `launchctl list` shows nothing; stray test-plist removed |
| Codex PASS on exact tips | ❌ codex returned **FAIL** both repos. All findings addressed with my own verdict; **#2 escalated, unresolved**. No clean re-verify yet. |
| `/security-review` clean | ✅ 1 sub-threshold (token-in-query) found + fixed |
| Morning flip checklist written | ✅ `.claude/how-to/cockpit-cloud-access.md` (kill switches first) |

## What shipped

Reverse bridge: laptop opens ONE outbound WS to the Lab (`/api/cockpit/bridge`, dedicated `BRISEN_LAB_COCKPIT_BRIDGE_KEY`); Lab muxes Director `/cockpit/*` HTTP + `/cockpit/term/{slug}/ws` terminals down it to the loopback controller (`127.0.0.1:7800`). Flag `COCKPIT_EMBED_ENABLED` default OFF → every path 404s/closes.

- **Shared codec** `cockpit_mux.py` (both repos, **sha256-identical**, guarded by `cockpit_mux_vectors.json`): 9-byte-header binary mux, 256KiB cap, 9 frame types.
- **Lab** `cockpit_bridge.py` + `app.py` routes: single-active bridge, per-stream demux, 30s heartbeat/timeout, flag+origin+token gate, strips inbound Authorization/Origin/Cookie + token-in-query, 32MiB body caps. Flag-gated nav button + `/api/cockpit/config`. `websockets>=13,<14` added.
- **Agent** `cockpit_bridge_agent.py` + `install_cockpit_bridge.sh` + launchd plist: reconnect backoff, key never argv/logged, Basic-auth injected loopback-only (`trust_env=False`), build-not-flip (load gated behind `--load`), no secret in plist.

## Tests (literal)

- brisen-lab: `python3 -m pytest tests_unit/test_cockpit_mux.py tests_unit/test_cockpit_bridge.py` → **75 passed**.
- baker-master: `python3 -m pytest tests/test_cockpit_mux.py tests/test_cockpit_bridge_agent.py` → **27 passed**.
- Loopback integration probe (production-pinned venv: fastapi 0.115 / uvicorn 0.32 / **websockets 13**): **10/10** — page + `/api/agents` + Start/GO POST through the mux, inbound-Auth stripped, cross-origin 404, flag-off 404, agent-absent 503, Phase-2 ttyd echo + subprotocol, flag-off terminal refused.
- Codec parity: `shasum` → 1 distinct hash (byte-for-byte identical).

## Gates

- **/security-review:** no findings ≥8 confidence. One sub-threshold (~7): `?token=` bootstrap forwarded to the laptop → fixed (`strip_token_query`, lab 4a05bed).
- **Codex cross-vendor (gpt-5.6-luna, xhigh, exact tips):** FAIL both repos. My own verdict per finding (Lesson #114):
  - **baker-master:** #1 proxy trust_env secret-leak (fixed), #3 websockets 12/13 kwarg (fixed), #4 1P canonical ref (fixed), #5 body cap (fixed), #6 Phase-2 reconnect task/state leak (fixed), #7 installer mkdir (fixed). All in c08ac3db.
  - **brisen-lab:** #1 raw-caller auth hole when token unset — **real, fixed** (rebuilt `cockpit_access`); #3 Origin-to-controller — false-positive at system level (agent overrides) but stripped anyway; #4 cookie-token leak — fixed; #5 body caps — fixed; #6 WS RESET hang — fixed; #7 flag-off WS 403-not-404 — protocol-inherent, documented. All in ac2ffd1.
  - **#2 (P1) NOT fixed — escalated to lead (#12574).**

## BLOCKER — codex #2 (needs lead ruling before this is browser-functional)

The brief's premise "cockpit page is a pure client, HTTP proxying is sufficient, zero cockpit-side change" is **factually wrong**: `scripts/cockpit_static/cockpit.js:23` builds every request URL as `location.origin + path` (absolute `/api/agents`, `/term/<slug>/`, `/api/sessions/<slug>/go`, `/cockpit_layout.json`). Served at `brisen-lab.onrender.com/cockpit/`, those fetch **root** paths → 404 (none collide with real Lab routes, but none are served there), so the grid shell loads but renders **empty** and terminals never open. The loopback probe missed it because it drives prefixed paths directly, not the page's own JS. The transport is proven; this is the last-mile page-wiring, and the fix touches the "Do NOT Touch cockpit_static" boundary — lead's call:

- **A (recommend):** one backward-compatible line in `cockpit.js` — `const BASE = window.__COCKPIT_BASE__ || location.origin;` — plus the Lab injects `<script>window.__COCKPIT_BASE__=location.origin+'/cockpit'</script>` into the proxied index.html. Local laptop page unaffected. Robust.
- **B:** proxy-side string-rewrite of `location.origin` in the served `cockpit.js` — no source edit but a fragile hidden coupling.

## Also open

- Auth policy (bus #12569): for a remote-command surface, `COCKPIT_ACCESS_TOKEN` should be **mandatory** before flip — without it the gate is same-origin-only and `Sec-Fetch-Site` is forgeable. Runbook + code recommend it; lead's policy call.
- Codex has NOT re-verified the post-fix tips (would still flag #2 by design). Offer: re-run codex on request before merge.

## Next (owner)

Lead: rule on #2 (A vs B) + the token-mandatory policy; line-read + merge; then the morning flip checklist in `cockpit-cloud-access.md` (Director GO) — flag stays OFF until then.
