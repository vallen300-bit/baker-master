# LAB_COCKPIT_CONTROLLER_1 — cockpit controller backend (Cockpit BRIEF B-1)

- **Status:** DISPATCHED 2026-07-16 → deputy-codex. Gate: codex-arch disposition #12047 — "Cut/gate B-1 with N1+N2"; backend ships BEFORE any UI (ui-surface-prebrief).
- **Parent scope (binding):** `briefs/SCOPE_LAB_TERMINAL_COCKPIT_1.md` **v1.3 @2b7f18e4** — §6b (manifest interface, consume-only), §6c, §7, §8 P1 B-1, §9 R3/R6/R7. Scope wins on conflict; flag, don't improvise.
- **Folded nits (codex-arch #12047, MANDATORY):** N1 (pinned Lab source contract), N2 (ttyd base path + WS header rewrite) — see Deliverables 2 and 4.
- **Dispatcher:** lead. **Builder:** deputy-codex. **Gate:** cross-vendor PR review (Claude deputy) → lead merge.
- **Repo:** baker-master. **NO UI in this brief** — reviewer instruction is exact URLs + expected non-error responses only.

## Context

Cockpit arc BRIEF B-1 of 3 (A = FLEET_TMUX_LAUNCH_1 @643e1bf2, in flight with b1; B-2 = LAB_COCKPIT_PAGE_1, gated on THIS brief merged + its exact URLs returning non-error). Controller is the same-origin security boundary in front of per-seat ttyd.

**Context Contract (Harness V2):** builder reads ONLY: parent scope §6b/§6c/§7/§8/§9, BRIEF A's launch-manifest + ledger interface (consume, never regenerate), brisen-lab `app.py` /api/v2/terminals handler (field shapes only). No vault libraries, no matter context.
**Task class:** local backend service (no Director-facing surface yet).
**Done rubric:** merged + controller live under launchd on this Mac + all ACs proven with curl/WS probes against a real tmux+ttyd pilot seat (B3, from BRIEF A Phase-1 sandbox) + POST_DEPLOY_AC_VERDICT posted.

## Problem (1-liner)

The cockpit page needs a local backend: one origin serving card data, Start/GO verbs, and an HTTP+WebSocket proxy to each seat's ttyd — with Basic auth and strict origin enforcement.

## Deliverables

1. **Python controller** (single file preferred; NOT bare `http.server`, NOT Caddy): launchd-managed (generated plist, `RunAtLoad` — controller is the named reboot owner ordered BEFORE `fleet_terminals.sh up` per scope AC4), bound 127.0.0.1 only. Routes: `GET /api/agents`, `POST /api/sessions/{slug}/start`, `POST /api/sessions/{slug}/go` (sends exactly Enter via `tmux send-keys -t <slug> Enter`), static file serving, `/term/<slug>/` proxy. Allowlist = launch manifest slugs; unknown slug → 404, no shell execution.
2. **Pinned Lab glance source (N1 — verbatim contract):** `GET https://brisen-lab.onrender.com/api/v2/terminals`, public-read, no auth, HTTP 200 live (verified 2026-07-16). Map ONLY: `is_working`, `has_telemetry`, `needs_go`, `unacked_count`, `oldest_unacked_age_sec`, `unacked_topics`. Metadata-only exposure — no transcript, no session UUIDs, no raw token detail. Proxy this through `/api/agents` (cache ≤30s, fail-soft: Lab unreachable ⇒ glance fields null, cards still render from manifest + `tmux ls`). The scope's earlier "build-resolves" wording is void — this pin IS the contract.
3. **`GET /api/agents`:** manifest eligible seats + live up/down from `tmux ls` + proxied Lab glance fields (Deliverable 2). Registry order preserved.
4. **`/term/<slug>/` HTTP+WS reverse proxy (N2 — verbatim contract):** each ttyd is started (by BRIEF A's plist generator — coordinate interface, don't own it) with base path `-b /term/<slug>/`. ttyd `--check-origin` is a boolean equality check between the `Origin` authority and `Host` — NOT a configurable allowlist. The proxy MUST rewrite `Host` and `Origin` headers on the upstream WebSocket handshake to match the ttyd target, or the WS is rejected. Prove the WS path live (AC-C3).
5. **Auth + origin (scope §6c):** shared Basic-auth credential (0600, `~/Library/Application Support/baker/cockpit/`); controller requires it at its single origin AND injects it upstream to each ttyd (browser never talks to ttyd directly); controller rejects any request whose `Origin`/`Host` is not `127.0.0.1:<cockpit-port>`; at most ONE credential prompt per browser session (full browser smoke lands in B-2; B-1 proves header/401 behavior with curl).

## Acceptance criteria (live — Lesson #8; reviewer gets exact URLs + expected responses)

- AC-C1: `curl -u <cred> http://127.0.0.1:<port>/api/agents` → 200, eligible seats with correct up/down vs `tmux ls`, Lab glance fields present for a seat with live Lab state; no cred → 401.
- AC-C2: `POST /api/sessions/b3/start` brings the downed sandbox B3 up via manifest cmd; rerun → idempotent no-dup; unknown slug → 404; `POST /api/sessions/b3/go` delivers exactly one Enter (visible in tmux).
- AC-C3: WS probe through `/term/b3/` reaches ttyd and echoes a keystroke into the real tmux session (rewritten Host/Origin proven — probe fails if rewrite removed).
- AC-C4: forged `Origin: http://evil.local` → rejected; `lsof` shows controller + ttyd on 127.0.0.1 only.
- AC-C5: kill controller → native Terminal windows unaffected; launchd relaunches controller; reboot-order documented (plist before fleet launcher).

## Out of scope

ANY UI/page/CSS (B-2). tmux/migration machinery, ttyd plist generation itself (BRIEF A — consume its interface). Lab-side /api/v2/terminals changes (separate slice LAB_CONTEXT_BAND_EXPOSURE_1). Stop/kill verbs. Remote access.

## Report

Ship report to `briefs/_reports/`, bus post to lead with PR ref + the exact URL list for B-2's reviewer instruction; POST_DEPLOY_AC_VERDICT after merge + live probes.
