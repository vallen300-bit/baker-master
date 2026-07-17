# BRIEF: COCKPIT_CLOUD_EMBED_1 — Reach the fleet cockpit from Brisen Lab (off-laptop)

**STATUS: DRAFT — awaiting Director ratification. Do NOT dispatch.**
Origin: Director question via cowork-ah1 bus #12556 (2026-07-17); lead answer #12557 (brief promised, no overnight build). Authored overnight by lead per #12554 handoff.

## Decision for Director (plain English)

Today the fleet cockpit (the card grid that opens each seat's real terminal) works only on your laptop. You asked whether it should be reachable from inside Brisen Lab (the cloud page), i.e. from anywhere. Three ways to do it:

| Option | What you get | Exposure | Cost |
|---|---|---|---|
| **A — Secure tunnel + "Open Cockpit" button in Lab (recommended)** | The full cockpit — cards, live terminals, GO button — from any device, behind your email login | Internet-reachable but double-locked (Cloudflare Access email check + existing cockpit password) | ~$0/mo (Cloudflare free tier) |
| B — Private network (Tailscale) | Full cockpit, but only from devices you enroll | Zero public exposure | ~$0/mo |
| C — Status-only cards in Lab + GO via bus | Glance + one-click GO in the Lab page itself; **no live terminal** | Zero new exposure | $0 |

**Recommendation: A — it is the only option that actually puts the working cockpit a click away from the Lab page on any device; the double lock (email + password) plus a one-command kill switch keeps the risk controlled.** B fails the "inside Brisen Lab" ask (a public page cannot reach a private network). C is the safe fallback if you don't want fleet terminals reachable from the internet at all — say so and we re-scope.

**Honest risk statement:** option A makes "type into any fleet terminal" reachable from the internet behind two locks. A compromise of your Cloudflare login + the cockpit password = keyboard access to every seat. Mitigations below (Access policy = your email only, session length 24h, kill switch, audit log). This is a Tier-A security-relevant change: `/security-review` gate is mandatory before merge, per Lesson #52 / repo hard rule.

## Context

- Cockpit: local page at `127.0.0.1:7800` — B-1 Python controller (`scripts/cockpit_controller.py`, binds loopback only, line 236) + ttyd per seat + tmux substrate (post-Phase-2, 28/28 live). Basic-auth from `~/Library/Application Support/baker/cockpit/credentials`.
- Brisen Lab: cloud Render app (`brisen-lab.onrender.com`), separate repo (local checkouts at `~/bm-b1/brisen-lab` etc.), already renders fleet cards from forge-snapshot telemetry.
- No tunnel infra exists anywhere in the repo today (verified: zero cloudflared/tailscale/ngrok references).

## Estimated time: ~4-6h (excl. prerequisite)
## Complexity: Medium (infra + auth, minimal code)
## Prerequisites: **a Cloudflare-managed domain for Brisen** — route confirmation to AID-T (IT owns domains). If none exists, Director decision needed on which domain to onboard. HARD BLOCKER for Option A.

## Baker Agent Vault Rails
Relevant: standing-contract (Tier-A security gate), verification-surfaces (live probes), build-command-center (dispatch flow).
Ignored: bus-and-lanes (no bus schema change), memory-and-lessons (routine), loop-runner, skills-and-playbooks.

## Harness V2

- **Context Contract:** worker needs ONLY — this brief; `scripts/install_forge_push.sh` (launchd installer pattern to mirror); `.claude/how-to/lab-cockpit.md` (cockpit surface); `.claude/how-to/forge-snapshot-push-install.md` (KeepAlive pattern); brisen-lab repo header component (Feature 3 only). Worker does NOT need: cockpit_controller.py internals (unchanged by design), bus/wake code, Baker dashboard, any matter context.
- **Task class:** production-infra, Tier-A (internet-facing control surface), security-relevant.
- **Done rubric (done-state class: live-verified):** all 6 live probes in §Verification pass, `/security-review` clean, codex gate PASS on the exact merge tip (Lesson #114), post-deploy AC verdict posted to bus. Compile-clean/committed is NOT done (Lesson #8). Prototype-gate FAIL (websockets don't survive tunnel) is an honest DONE-as-blocked: report and stop, option falls.
- **Gate plan:** (1) Director ratifies option + prerequisite domain (this draft's decision block) → (2) prototype probe (throwaway trycloudflare) → (3) build → (4) `/security-review` skill — MANDATORY Tier-A → (5) codex cross-vendor gate, own verdict post per repo, exact tip → (6) lead line-read + merge → (7) live probes 1-6 → (8) `post-deploy-ac-bus-gate` verdict → (9) Director eyeball from off-laptop device.

---

## Feature 1: Cloudflare Tunnel exposing the cockpit (laptop side)

### Problem
Cockpit is loopback-only; Director cannot reach it off-laptop.

### Current State
`cockpit_controller.py` binds `127.0.0.1:7800` (line 236 default, `--host` flag line 1056). ttyd viewers proxied same-origin through the controller (`/term/<slug>/`), so ONE tunnel to :7800 covers grid + terminals + actions. Controller is launchd KeepAlive-managed.

### Engineering Craft Gates
- **Diagnose: N/A** — new capability, no bug.
- **Prototype: APPLIES** — question: *do ttyd websockets + Basic auth survive a Cloudflare tunnel end-to-end (typing works, GO works)?* Throwaway probe: `cloudflared tunnel --url http://127.0.0.1:7800` (ephemeral trycloudflare URL, no account, no DNS). Run BEFORE any named-tunnel or Lab work; delete nothing (no artifacts). If websockets fail through the tunnel, STOP and report — the whole option falls.
- **TDD/verification: live probes** (below) — no honest unit seam for tunnel/Access behavior; controller code is unchanged so its 52-test suite must simply stay green.

### Implementation
1. `brew install cloudflared`; authenticate to the Brisen Cloudflare account (operator does this interactively — NO tokens in repo).
2. Named tunnel `baker-cockpit` → ingress `cockpit.<domain>` → `http://127.0.0.1:7800`. Config at `~/.cloudflared/config.yml` (laptop-local, never committed).
3. New `scripts/install_cockpit_tunnel.sh` mirroring `install_forge_push.sh` pattern: writes launchd plist `com.baker.cockpit-tunnel` (KeepAlive, log to `~/Library/Logs/cockpit-tunnel.log`), loads it. Copy the KeepAlive + self-resume hardening from the forge pusher installer verbatim.
4. Controller stays loopback — the tunnel terminates locally and originates the connection to 127.0.0.1. Do NOT change `bind_host`.
5. **Kill switch (document in how-to):** `launchctl bootout gui/$(id -u)/com.baker.cockpit-tunnel` — cockpit instantly unreachable from outside; local use unaffected. Also killable from Cloudflare dashboard (disable tunnel).

## Feature 2: Cloudflare Access policy (auth wall)

### Implementation
1. Access application for `cockpit.<domain>`: policy = allow ONLY `dvallen@brisengroup.com` (One-Time PIN or configured IdP), session 24h. Everyone else: deny.
2. Basic-auth stays ON underneath (defense in depth — two locks, per repo credential at `~/Library/Application Support/baker/cockpit/credentials`; read it, never hardcode/commit).
3. Access logging on (Cloudflare audit trail of every login).

### Key Constraints
- NEVER a wildcard/`*@brisengroup.com` policy — Director's address only until he ratifies wider access.
- No secrets in repo: tunnel credentials + Access config live in Cloudflare/laptop only. Brief references env/e-mail names only.

## Feature 3: "Open Cockpit" button in Brisen Lab (cloud side)

### Problem
Ask was "cockpit inside Brisen Lab" — Lab needs the entry point.

### Implementation
- brisen-lab repo (separate PR, shared-checkout discipline per Lesson #121 — feature branch, never dirty scratch): header button `Cockpit ↗` → opens `https://cockpit.<domain>` in a new tab.
- **Link-out, NOT iframe.** Rationale: ttyd websockets + Access cookies + Basic auth inside a cross-origin iframe = three stacked failure modes (third-party cookie blocking kills Access session in Safari/iOS). A new tab keeps the cockpit same-origin with itself. If Director insists on true in-page embed later, that is a follow-up brief with its own prototype gate.
- Button visible only when Lab session is authenticated (existing Lab auth gating).

### Verification (live probes — all must pass before DONE)
1. Prototype probe passed (websocket typing through tunnel).
2. Anonymous browser (incognito, no Access session) → `cockpit.<domain>` → Access login wall, NO cockpit content, NO Basic-auth prompt leak.
3. Director email OTP → Basic auth → grid renders, cards live, opening a seat terminal works, typing works, GO ⏎ works — from a NON-laptop device (phone on cellular, not home Wi-Fi).
4. Kill switch drill: `launchctl bootout` → outside URL dead <10s; `http://127.0.0.1:7800` still fine; re-bootstrap → back up.
5. Controller suite still green: `pytest` cockpit tests (52) — proves zero controller-code drift.
6. Lab button: renders, opens new tab, absent for unauthenticated Lab visitors.

---

## Files Modified
- NEW `scripts/install_cockpit_tunnel.sh` — launchd installer (forge-pusher pattern)
- NEW `.claude/how-to/cockpit-cloud-access.md` + INDEX line — runbook incl. kill switch
- brisen-lab (separate repo/PR): header button

## Do NOT Touch
- `scripts/cockpit_controller.py` — bind stays loopback; zero code change is the design
- `scripts/cockpit_static/*` — page unchanged (it is origin-relative already)
- `~/Library/Application Support/baker/cockpit/credentials` — never committed, never rotated silently

## Quality Checkpoints
1. `/security-review` skill run on the PR — MANDATORY (Tier-A, internet-facing control surface).
2. Codex cross-vendor gate before merge (both repos).
3. No secret material in any commit (tunnel creds, Access config, cockpit password).
4. How-to documents the kill switch FIRST (failure mode before happy path).
5. Post-deploy: `post-deploy-ac-bus-gate` verdict on the bus.

## Verification SQL
N/A — no database surface. Verification is the 6 live probes above.

## Rollback
`launchctl bootout` the tunnel agent + delete the Cloudflare Access app + revert the Lab button PR. Cockpit returns to loopback-only in <1 min. No state to migrate either direction.
