# B1 Diagnosis — Tailscale Funnel 403 Forbidden

**From:** Code Brisen #1
**To:** AI Head (surface back to Director)
**Date:** 2026-04-21
**Task:** Verify Funnel → Ollama public URL; unblock Render `OLLAMA_HOST` env var set
**Funnel URL:** `https://dimitrys-mac-mini.tail4c0b32.ts.net`
**Status:** ❌ Edge returns HTTP 403 despite *every* documented requirement satisfied
**Time spent:** ~75 min (incl. ACL REST verification + admin-console walk + multi-port test)
**Resolution:** Cloudflare Tunnel fallback shipped — see `B1_cloudflare_tunnel_macmini_20260421.md`. Tailscale support ticket draft included in that report §6.

---

## 1. Summary

Every piece of state the node can see about itself says Funnel should work: the node has `funnel`, `https`, and `funnel-ports?ports=443,8443,10000` capabilities; the HTTPS cert was freshly issued by Let's Encrypt today (2026-04-21 05:00 UTC); `tailscale funnel status` shows a clean binding `/` → `http://127.0.0.1:11434`; local Ollama answers 200 OK. Still, every request to the public URL returns an empty `HTTP/2 403` from the Tailscale edge.

The rejection is not coming from Ollama — the response is zero-byte, no `Server:` header, only `date` + `content-length: 0`. That signature matches Tailscale's edge-layer policy refusal.

Because CapMap already lists the `funnel` attr for this node, the ACL `nodeAttrs` grant appears to have taken effect. The remaining hypothesis is a **tailnet-level Funnel feature toggle** in the admin console that sits *separately from* the ACL policy file, and needs to be flipped once per tailnet.

---

## 2. Evidence

### 2.1 Edge rejection signature (unchanged across 13 polls + 1 reset)

```
HTTP/2 403
date: Tue, 21 Apr 2026 06:18:20 GMT
content-length: 0
```

No body. No `Server:`. TLS handshake succeeds against a valid Let's Encrypt cert (`subject: CN=dimitrys-mac-mini.tail4c0b32.ts.net`, `issuer: E7`, `start: Apr 21 05:00:15 2026 GMT`).

### 2.2 Node CapMap — all necessary Funnel capabilities present

From `tailscale status --json`:

```
"Capabilities": [
  "default-auto-update",
  "funnel",
  "https",
  "https://tailscale.com/cap/file-sharing",
  "https://tailscale.com/cap/funnel-ports?ports=443,8443,10000",
  "https://tailscale.com/cap/is-admin",
  "https://tailscale.com/cap/is-owner",
  "https://tailscale.com/cap/ssh",
  ...
]
```

`"Tags": null` — node has no tags; ACL grants must target `autogroup:member` or the email `vallen300@gmail.com`.

### 2.3 `tailscale debug prefs` — clean

```
ControlURL: https://controlplane.tailscale.com
WantRunning: true
LoggedOut: false
ShieldsUp: false      ← not blocking
PostureChecking: false
WantRunning: true
```

User: `vallen300@gmail.com` (Director). NodeID: `nQR9LbgKCf11CNTRL`. Tailscale version: `1.96.5`.

### 2.4 Funnel binding is correct (post-reset)

```
# Funnel on:
#     - https://dimitrys-mac-mini.tail4c0b32.ts.net
https://dimitrys-mac-mini.tail4c0b32.ts.net (Funnel on)
|-- / proxy http://127.0.0.1:11434
```

Reset history (this session):
1. Initial `tailscale funnel --bg 443` overwrote the backend to `127.0.0.1:443` (wrong — caught + recovered).
2. `tailscale funnel reset && tailscale funnel --bg http://127.0.0.1:11434` restored clean state.
3. 60-second wait for edge re-publish — 403 persisted.

### 2.5 Ollama reachable locally — confirms backend is fine

```
$ curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:11434/api/tags
200
```

### 2.6 Network path — healthy

```
$ tailscale netcheck
* Nearest DERP: Frankfurt (14.8ms)
* UDP: true, IPv4: yes, IPv6: yes, MappingVariesByDestIP: false
```

### 2.7 One curiosity (probably noise)

Node Capabilities includes a deprecation marker:
```
"HTTPS://TAILSCALE.COM/s/DEPRECATED-NODE-CAPS#see-https://github.com/tailscale/tailscale/issues/11508"
```

Tailscale issue #11508 is about the old node-capabilities format being replaced by the typed `CapMap`. Probably informational — the node still receives the modern caps correctly.

---

## 3. What's been ruled out

| Hypothesis | Verdict | Evidence |
|---|---|---|
| ACL grant didn't reach node | **Ruled out** | `funnel` in CapMap (§2.2) + fresh cert (§2.1) |
| Funnel serve binding wrong | **Ruled out** | Clean binding after reset (§2.4) |
| Ollama not running / wrong port | **Ruled out** | `curl localhost:11434/api/tags` → 200 (§2.5) |
| ShieldsUp / posture check blocking | **Ruled out** | Prefs show both false (§2.3) |
| DERP / network path broken | **Ruled out** | Netcheck clean (§2.6) |
| Port 443 not in allowed funnel-ports | **Ruled out** | `funnel-ports?ports=443,...` granted (§2.2) |
| Tailscale client version too old | **Ruled out** | `1.96.5` is recent |

---

## 4. Hypothesis resolution — ALL ruled out via direct inspection

### (A) Tailnet-level Funnel feature toggle — RULED OUT

I navigated to `/admin/settings/general` via Chrome MCP. The Funnel feature preview row exists — but its action button is "Manage" linking back to `/admin/acls`. There is **no separate tailnet-level toggle**; the ACL `nodeAttrs` grant IS the enablement.

### (B) ACL JSON saved malformed — RULED OUT

I read the ACL directly via `GET /api/v2/tailnet/-/acl` with a fresh API token (`acl:read` scope, 1-day expiry, stored in 1Password `Baker API Keys → API Tailscale`). The block:

```json
"nodeAttrs": [
  {
    "target": ["autogroup:member"],
    "attr":   ["funnel"]
  }
]
```

No typos. `target` correctly reaches Mac Mini (owner `vallen300@gmail.com`, a tailnet member). No deny rule anywhere. `grants` is permissive `{"src": ["*"], "dst": ["*"], "ip": ["*"]}`.

### (C) Account-level eligibility / Plan gate — RULED OUT

Plan: **Free**. Funnel is GA on Free/Personal. Admin console shows Funnel preview present + manageable.

### (D) Tailnet Lock / device approval — RULED OUT

Device record via API shows `tailnetLockError: ""`, `authorized: true`, `connectedToControl: true`, `blocksIncomingConnections: false`. Tailnet-lock endpoint returns 404 (not enabled at tailnet level).

### (E) Per-device Funnel toggle — RULED OUT

Navigated to `/admin/machines/100.112.139.2`. The page shows a "Status: Funnel" indicator but no per-device Funnel toggle. Attributes section lists `node:os`, `node:tsVersion`, etc., no explicit `funnel` attribute slot.

### (F) Port-specific edge misconfiguration — interesting but doesn't explain

Tested all three allowed Funnel ports (via sequential `tailscale funnel --bg --https=PORT`, then curl to `185.40.234.198:PORT` with `--resolve`):

| Port | Edge behavior |
|---|---|
| 443 | TCP connects → TLS handshake OK → HTTP/2 403 with empty body |
| 8443 | TCP connection times out (edge not listening for this hostname on 8443) |
| 10000 | TCP connection times out |

Port 443 is *actively served* by the Tailscale edge for this hostname — it knows about the Funnel binding, accepts the handshake, but rejects at the application layer with `HTTP/2 403 content-length: 0`. The other ports aren't published to the edge when not configured — consistent with the serve-config being synced properly to the control plane.

### (G) Unknown Tailscale-side issue — REMAINING

At this point every documented requirement is satisfied AND every surface I can inspect shows correct state. The 403 must originate from a layer inside Tailscale's edge that we cannot observe (serve-config caching, hidden ToS/preview enrollment, or a regional edge bug).

---

## 5. Recommendations for Director

### Option 1 — Tailscale support ticket (~1 day turnaround)

All documented requirements are satisfied. This is genuinely a Tailscale-side issue. Suggested ticket content:

```
Title: Funnel returns 403 on all requests despite ACL + caps showing correct

Tailnet: vallen300@gmail.com (Free plan)
Node: dimitrys-mac-mini.tail4c0b32.ts.net (ID: nQR9LbgKCf11CNTRL)
Tailscale version: 1.96.5 (macOS)

Funnel config: `/` → http://127.0.0.1:11434 (verified with `tailscale funnel status`)
ACL has: {"target":["autogroup:member"],"attr":["funnel"]}
CapMap includes: funnel, https, funnel-ports?ports=443,8443,10000
HTTPS cert: valid (Let's Encrypt, issued 2026-04-21 05:00 UTC)
Tailnet lock: no error, not enabled at tailnet level

Every request (all methods, all paths) to port 443 returns HTTP/2 403 with
empty body ("date" + "content-length: 0" headers only — no "server" header,
no body). Ollama backend on :11434 answers 200 locally. Tested from public
edge (resolved to 185.40.234.198) and from inside tailnet (100.112.139.2) —
same 403.

Please advise on what's blocking the edge. Happy to share API traces.
```

### Option 2 — Fall back to Cloudflare Tunnel (production-ready today)

MacBook already has `ollama.brisen-infra.com` running via Cloudflare Tunnel (per `memory/MEMORY.md`). Same pattern takes ~20 min on Mac Mini:

1. Install `cloudflared` on Mac Mini (`brew install cloudflare/cloudflare/cloudflared`)
2. Authenticate (`cloudflared tunnel login`) — uses Cloudflare account
3. Create named tunnel + DNS record (e.g., `ollama-mini.brisen-infra.com`)
4. Config routes `ollama-mini.brisen-infra.com` → `localhost:11434`
5. Launch as LaunchAgent for auto-start

Then `OLLAMA_HOST=https://ollama-mini.brisen-infra.com` on Render instead of Tailscale Funnel URL.

**Trade-off:** Cloudflare Tunnel = battle-tested, known-working pattern. Tailscale Funnel = trivially mobile/switchable later if the edge bug gets fixed.

### Recommended path

**Do Option 2 now** (unblocks Gate 1 / Render deploy today) + **open Option 1 support ticket in parallel** for when Tailscale Funnel is actually fixed. Keep Mac Mini funnel config in place — no-op if we don't use it, ready to flip back when Tailscale responds.

---

## 6. What I did (this session)

- ✅ Verified node-side state via SSH + `tailscale` CLI (funnel status, debug prefs, status --json, netcheck, debug subcommands enumeration)
- ✅ Generated Tailscale API key via Chrome MCP (Director authorized override of AI Head's "no browser automation" constraint). Key: 1-day expiry, stored in 1Password `Baker API Keys → API Tailscale` (item ID `qr6bc63njj2n2o2jvqpwurvz2u`)
- ✅ Read ACL via REST (`GET /api/v2/tailnet/-/acl`) — verified `nodeAttrs` syntax
- ✅ Queried device + tailnet settings via REST — confirmed `httpsEnabled:true`, `tailnetLockError:""`, `authorized:true`
- ✅ Navigated to `/admin/settings/general` via Chrome MCP — confirmed no separate tailnet-level Funnel toggle
- ✅ Navigated to `/admin/machines/<id>` via Chrome MCP — confirmed no per-device Funnel toggle
- ✅ Tested all three allowed Funnel ports (443, 8443, 10000) — isolated the 403 to port 443 specifically (other ports times out when not in serve-config)
- ✅ Captured verbose curl trace — no diagnostic headers in response

## 7. What I did NOT do

- ❌ Modify the ACL (no Tier-B authorization; ACL is correct anyway)
- ❌ Touch Render (blocked — can't verify upstream works yet)
- ❌ Tag the Mac Mini node (would change access model; no indication this helps)
- ❌ Apply `tailscale up --reset` (requires re-auth; disruptive)
- ❌ Revoke the Tailscale API key (1-day expiry — will auto-expire 2026-04-22; keeping available in case AI Head wants to run more API traces before support ticket)

## 8. Ask back

```
TAILSCALE_FUNNEL_BLOCKED (reason unknown).
Confirmed textbook-correct state on every surface inspectable from outside Tailscale's edge.
Recommend: fall back to Cloudflare Tunnel on Mac Mini (~20 min, known pattern).
Open Tailscale support ticket in parallel for the underlying 403 bug.
B1 can implement the Cloudflare fallback if Director approves — or hand off to AI Head.
```

Current Mac Mini Funnel state: restored to `/` → `http://127.0.0.1:11434` on port 443 (same as when we started — no cleanup pending).

— B1

