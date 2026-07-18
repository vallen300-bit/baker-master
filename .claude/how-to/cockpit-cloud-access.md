---
name: cockpit-cloud-access
description: Reach the Baker Cockpit inside Brisen Lab (Render) via the native reverse bridge — kill switches FIRST, then morning flip checklist.
when_to_use: Turning on / off cockpit-in-Lab, or when the Director reports the in-Lab Cockpit page is down / misbehaving.
---

# Cockpit inside Brisen Lab — access + kill switches

COCKPIT_IN_LAB_BRIDGE_1 (b1, lead #12566). The laptop opens ONE outbound
websocket to the Lab; the Lab proxies the cockpit UI at `/cockpit/*` down that
socket to the laptop's loopback controller (`127.0.0.1:7800`). No inbound laptop
port, no DNS, no new vendor.

```
Director browser ──(Lab auth+flag)── brisen-lab /cockpit/* ──(mux over 1 WS)── laptop agent ── 127.0.0.1:7800
```

## KILL SWITCHES (do these FIRST if anything is wrong)

Either one takes the surface down; do both to fully stop it.

1. **Server (instant, authoritative):** unset `COCKPIT_EMBED_ENABLED` on the Lab
   Render service (or set it to anything falsy). Every `/cockpit` path — HTTP and
   the terminal WS — returns `404` immediately, and the Cockpit nav button
   disappears. Re-read per request, so no redeploy needed.
   - Use the Render env guard, never a raw array PUT (`.claude/rules/python-backend.md`).

2. **Laptop (stops the transport):**
   ```
   launchctl bootout gui/$(id -u)/com.baker.cockpit-bridge
   ```
   The agent dies; the Lab then answers `/cockpit` with `503 {"detail":"laptop offline"}`.

## Security model (know this before flipping on)

- The whole Lab is public on Render (`brisen-lab.onrender.com`) under an
  "internal/low-threat/obscure-URL" posture. `/cockpit` adds a same-origin gate
  (mirrors `/api/wake`) + the `COCKPIT_EMBED_ENABLED` flag. **Same-origin does NOT
  stop a human who navigates straight to the URL** — see b1 bus flag #12569.
- Cockpit drives Start/GO + wake keystrokes into live laptop terminals, so blast
  radius is higher than the read-mostly dashboard.
- **Access token — MANDATORY before flip (ratified #12577):** set
  `COCKPIT_ACCESS_TOKEN` on the Lab. When set, every `/cockpit` request must carry
  it (`X-Cockpit-Token` header, `cockpit_token` cookie, or a one-time `?token=`
  that seeds the cookie); a no-token caller is denied. Unset → same-origin only,
  which is NOT sufficient for a remote-command surface — never flip the flag on
  without the token set.
- The agent WS authenticates with a DEDICATED key (`BRISEN_LAB_COCKPIT_BRIDGE_KEY`),
  never a bus/terminal key. The laptop Basic-auth credential never leaves the
  laptop process (injected into upstream requests only).

## MORNING FLIP CHECKLIST (Director GO required — nothing internet-reachable before)

Owner in brackets. Do in order.

1. **[lead] Provision the bridge key (same value both ends):**
   - Laptop cache: `mkdir -p ~/.brisen-lab/keys && chmod 700 ~/.brisen-lab/keys`
     then `printf '%s' '<key>' > ~/.brisen-lab/keys/cockpit-bridge && chmod 600 ~/.brisen-lab/keys/cockpit-bridge`.
   - Lab env: set `BRISEN_LAB_COCKPIT_BRIDGE_KEY=<same key>` (Render env guard).
2. **[lead] Deps on the Lab:** confirm `websockets>=13,<14` deployed (already in
   `requirements.txt`). The `<14` pin is load-bearing — uvicorn 0.32 + websockets
   ≥14 breaks the WS handshake.
3. **[lead] Set the access token — MANDATORY (ratified #12577):** `COCKPIT_ACCESS_TOKEN=<token>`
   on the Lab, set BEFORE the flag goes on. Share the `?token=` bootstrap URL with
   the Director only. This is REQUIRED, not optional: the origin gate alone cannot
   guard fleet keyboards on a public Lab (`Sec-Fetch-Site` is forgeable). Without
   the token set, do NOT flip `COCKPIT_EMBED_ENABLED` on.
4. **[lead] Deploy the Lab** with the flag still OFF; verify `GET /cockpit/` and
   `GET /cockpit/api/agents` and the terminal WS all return `404`, nav button
   absent. (post-deploy-ac-bus-gate verdict.)
5. **[lead] Load the laptop agent:**
   ```
   COCKPIT_BRIDGE_PYTHON=<python-with-httpx+websockets> bash ~/bm-b1/scripts/install_cockpit_bridge.sh --load
   ```
   Verify: `launchctl list | grep com.baker.cockpit-bridge` and
   `tail ~/Library/Logs/cockpit-bridge-agent.log` shows "bridge connected".
6. **[Director GO] Flip the flag ON:** set `COCKPIT_EMBED_ENABLED=1` on the Lab.
7. **[lead] Live AC:** open `https://brisen-lab.onrender.com/cockpit/` (with
   `?token=` if set) — grid renders, a Start/GO POST works, a terminal opens
   (Phase 2). If anything is flaky, hit a kill switch and report.

## Rollback

Either kill switch above. Both are one command and instant.

## Files

- Lab: `brisen-lab/cockpit_bridge.py`, routes in `brisen-lab/app.py`, nav in
  `brisen-lab/static/{index.html,app.js}`.
- Laptop: `scripts/cockpit_bridge_agent.py`, `scripts/install_cockpit_bridge.sh`,
  `scripts/launchd/com.baker.cockpit-bridge.plist`.
- Shared codec: `scripts/cockpit_mux.py` == `brisen-lab/cockpit_mux.py` (byte-for-byte).
- Integration proof: `scripts/cockpit_bridge_loopback_probe.py` (10/10, loopback only).
