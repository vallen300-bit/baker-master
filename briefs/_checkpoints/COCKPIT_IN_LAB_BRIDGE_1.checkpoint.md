---
brief_id: COCKPIT_IN_LAB_BRIDGE_1
attempt: 1
branch: b1/cockpit-in-lab-bridge-1 (both repos: baker-master + brisen-lab)
dispatched_by: lead (bus #12566)
report_topic: gates/cockpit-in-lab-bridge-1
status: MERGED both repos (lead #12636, codex PASS #12633) — baker-master PR #596 @a7cf2abf, brisen-lab PR #153 @4538ca5. Lab redeploying; lead runs flag-OFF 404 probe when live. Flip stays Director-GO-gated per .claude/how-to/cockpit-cloud-access.md. Flag OFF. B1 build lane CLOSED — no further action.
gate: /security-review clean; codex PASS-WITH-NOTE both tips; ConnectionClosedOK close-race fixed + test (baker 28); #2 resolved via Option A; report internally consistent (row 19 fixed)
---

# COCKPIT_IN_LAB_BRIDGE_1 — checkpoint

Brief: `briefs/_tasks/COCKPIT_IN_LAB_BRIDGE_1.md` @c1828591. Reverse bridge: laptop
outbound WS -> Lab proxies /cockpit/* + terminals down to 127.0.0.1:7800.

## Done (shipped, pushed)
- baker-master tip @c08ac3db + report @31d09a54; brisen-lab tip @ac2ffd1.
- Phase 1 (HTTP) + Phase 2 (ttyd WS) built. Shared codec sha256-identical.
- Tests: lab 75, baker 27. Loopback probe 10/10 (needs a venv with
  fastapi 0.115 / uvicorn 0.32 / **websockets 13** — NOT websockets 15, which
  breaks uvicorn-0.32 WS; that's why requirements pins <14).
- Build-not-flip verified: COCKPIT_EMBED_ENABLED default OFF; installer staged NOT
  loaded; no secret in plist.
- /security-review clean (token-in-query fixed). Codex FAIL both tips; all findings
  fixed with own verdict EXCEPT #2.

## Open / next concrete step
1. **BLOCKER #2 (awaits lead ruling, bus #12574):** `cockpit_static/cockpit.js:23`
   uses `location.origin` absolute URLs, so at /cockpit/ the page's fetches hit
   root -> empty grid. Fix (needs lead to lift "Do NOT Touch cockpit_static"):
   - Option A (recommended): `cockpit.js` line 23 -> `const BASE = window.__COCKPIT_BASE__ || location.origin;`
     + Lab injects `<script>window.__COCKPIT_BASE__=location.origin+'/cockpit'</script>`
     into the proxied index.html (in `cockpit_bridge.proxy_http` when path is the
     cockpit index / content-type text/html). Backward-compatible (local page unaffected).
   - Then extend the loopback probe: assert the served index.html carries the
     base-inject and that a page-driven fetch resolves under /cockpit/.
2. Auth policy (bus #12569): recommend COCKPIT_ACCESS_TOKEN mandatory before flip.
3. Optional: re-run codex on post-fix tips (would still flag #2 until A/B lands).
4. Lead: line-read + merge both repos; then morning flip checklist in
   `.claude/how-to/cockpit-cloud-access.md` (Director GO). Flag stays OFF until then.

## Key paths
- Lab: `brisen-lab/cockpit_bridge.py`, routes in `brisen-lab/app.py` (grep COCKPIT_IN_LAB_BRIDGE_1).
- Agent: `scripts/cockpit_bridge_agent.py`, `scripts/install_cockpit_bridge.sh`, `scripts/launchd/com.baker.cockpit-bridge.plist`.
- Probe: `scripts/cockpit_bridge_loopback_probe.py`. Report: `briefs/_reports/B1_cockpit_in_lab_bridge_1_20260718.md`.
