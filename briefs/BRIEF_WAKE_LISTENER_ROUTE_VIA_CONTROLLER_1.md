# BRIEF: WAKE_LISTENER_ROUTE_VIA_CONTROLLER_1 — route tmux-seat wakes through the cockpit controller (kill the bare-parked wake)

**Priority:** P1 · **Executor:** b4 · **Author:** deputy (AH2) · **Dispatch:** lead #12993 (lead live-diagnosed 2026-07-18 ~19:1xZ)
**Repo:** `brisen-lab` (`tools/wake-listener/`) — forward-port discipline as PR #156.
**Report topic:** `gates/wake-listener-route-via-controller-1`

## Context
There are **two** wake paths and the wrong one is the default:
- **Legacy (current default):** `~/.brisen-lab/wake-listener.py` `dispatch_wake()` shells `open brisen-lab://wake/<alias>` → legacy AppleScript Wake.app → Terminal keystroke nudge. It sends a **bare, untagged `check bus`**, is submit-gap-prone (#3746), and **parks in the composer** — while the D3 attribution log still records `result=ok`. Tonight b4 logged `ok` but the line sat parked bare; b2+b3 "ghosts" have the same signature.
- **FIX_2 (tagged + verified + park-recovering):** lives ONLY in baker-master `cockpit_controller.py` `send_wake` (`POST http://127.0.0.1:7800/api/sessions/<slug>/wake`). A lead-fired controller wake on the same seat returned `sent:true` instantly. **A bare parked line then BLOCKS later controller wakes** — the controller's AC3 untagged-human guard treats it as a Director draft.

**Fix:** for seats that are controller-driveable tmux sessions, `dispatch_wake` routes through the controller `/wake`; the legacy open-URL path is retained ONLY for App-resident / no-tmux aliases. The D3 log gains a `route` field + the controller's verified result. Fail loud (fall back to legacy + log `route=legacy-fallback`) if the controller is unreachable.

### Surface contract: N/A — no user-clickable surface; this is internal wake-dispatch routing (machine wake template only).

## Estimated time: ~3–4h
## Complexity: Medium (routing + auth + fail-loud fallback + route-selection tests; no new UI, no new controller endpoint)
## Prerequisites
- brisen-lab checkout on **`origin/main`** (currently `c0bcc49`). Repo `tools/wake-listener/wake-listener.py` == the live `~/.brisen-lab/wake-listener.py` (verified identical) — start from a fresh `git fetch && git switch main && git pull`.
- The cockpit controller runs locally at `127.0.0.1:7800` (baker-master `scripts/cockpit_controller.py`). Its `/api/sessions/{slug}/wake` + `/api/agents` already exist — **no controller change in this brief.**

## Baker Agent Vault Rails
Relevant rails: `bus-and-lanes` (wake dispatch), `verification-surfaces` (D3 attribution log), `loop-runner` (launchd persistence).
Ignore: `standing-contract`, `memory-and-lessons`, `skills-and-playbooks` (no doctrine change).

---

## Fix 1: dispatch_wake routes tmux seats via controller `/wake`

### Problem
`dispatch_wake` unconditionally uses the legacy open-URL keystroke path, which parks a bare untagged `check bus` in the composer and mis-logs it as `ok`. The reliable, verified controller path is never used by the listener, and the parked bare line then blocks subsequent controller wakes.

### Current State (verified)
- `tools/wake-listener/wake-listener.py`:
  - `dispatch_wake(alias, foreground)` — shells `subprocess.run(["open", f"brisen-lab://wake/{alias}?fg={fg}"], timeout=5)`, classifies the `open` result, calls `_log_dispatch`.
  - `_log_dispatch(alias, foreground, result)` (D3, `WAKE_INJECT_SUBMIT_FIX_2`) — appends to `DISPATCH_LOG_PATH` (`~/.brisen-lab/wake-dispatch.log`) the record `{"ts", "origin":"wake", "alias", "foreground", "result"}`. Best-effort; never raises.
  - `ALLOWED_ALIASES` / `WAKEABLE_TERMINALS` (imported from `agent_identity_generated`) — host-filtered wake allowlist. The listener today knows **aliases**, not slugs or runtime class.
- baker-master `scripts/cockpit_controller.py` (READ-ONLY reference — do not edit):
  - `POST /api/sessions/{slug}/wake` → `send_wake(...)` returns on success `{"ok":true,"sent":true,"slug","msg_id","topic","line"}`; on guard/dedupe/down `{"ok":true,"sent":false,"skipped":"<reason>","slug"}`. (Down seat → `{"ok":true,"sent":false,"skipped":"session down"}`.)
  - Auth = HTTP Basic; `CredentialStore.read()` reads `~/Library/Application Support/baker/cockpit/credentials` (a `username:password` line, **mode 0600 required**), compared with `hmac.compare_digest`. Same-origin guard passes for a `Host: 127.0.0.1:7800` request.

### Engineering Craft Gates
- **Diagnose:** applies (already diagnosed by lead). Feedback loop: fire a wake at a live tmux seat, then read `~/.brisen-lab/wake-dispatch.log` (route + result) AND the seat's composer (tagged line submitted, not parked). Reproduction of the bug: legacy path parks bare `check bus`; controller path returns `sent:true`. Regression: the route-selection unit tests below + a live controller-mock.
- **Prototype:** N/A — the target path already exists (controller `send_wake`); no open design question except the route-classification source, resolved in Implementation.
- **TDD/verification:** applies. Public seam = `dispatch_wake`'s route decision + the D3 record shape. Write route-selection unit tests FIRST: (a) driveable tmux seat → controller POST; (b) App-resident/no-tmux alias → legacy open-URL; (c) controller unreachable → legacy-fallback + `route=legacy-fallback` logged. Plus one controller-mock test asserting the POST URL, Basic-auth header, and result passthrough. Do not couple mocks to `open`'s internals.

### Implementation
1. **Route classification.** Resolve `alias → slug` and whether the alias is a controller-driveable tmux seat. **Recommended source:** the cockpit launch manifest (`~/Library/Application Support/baker/cockpit/static/cockpit_launch_manifest.json` — entries carry both `slug` and `alias`; driveable seats are the terminal seats). An alias present as a driveable seat ⇒ controller route; anything else (App-resident / not in the manifest) ⇒ legacy. Read-only; tolerate a missing/unreadable manifest by treating the alias as legacy (never crash the listener).
2. **Controller path (driveable tmux seats):** `POST http://127.0.0.1:7800/api/sessions/<slug>/wake` with header `Authorization: Basic <base64(username:password)>` read from the credentials file at call time (read-only; never cache the secret in the log; enforce nothing about mode here — the controller enforces 0600). Short timeout (e.g. 3–5s).
   - `2xx` → log `route=controller`, `result` = the controller's `sent` (`true`/`false`) plus `skipped` reason when present. **Do NOT also fire the legacy path** (no double-wake).
   - Connection refused / timeout / `5xx` → **fail loud** (`log.warning`) and fall back to the legacy open-URL path; log `route=legacy-fallback`.
3. **Legacy path (App-resident / no-tmux aliases, unchanged behavior):** existing `open brisen-lab://wake/<alias>?fg=<0|1>`; log `route=legacy`.
4. **D3 log extension:** add `route` (`controller` | `legacy` | `legacy-fallback`) and pass through the controller verified `result` (`sent:true/false`, `skipped`) into the `_log_dispatch` record. Keep it best-effort / never-raise. Preserve the existing keys (`ts`, `origin`, `alias`, `foreground`, `result`) for backward-compatible log readers.
5. Keep the `foreground` / Focus-Guard-V2 semantics intact on the legacy path.

### Key Constraints
- **No controller change.** `scripts/cockpit_controller.py` and its endpoints are out of scope — the `/wake` contract already exists.
- Never log or persist the credential; read it read-only per call.
- The listener must **never crash** on a missing manifest, missing credentials, or an unreachable controller — degrade to legacy and log loudly.
- No double-wake: exactly one of {controller, legacy, legacy-fallback} fires per dispatch.
- Preserve the existing D3 record keys; only ADD fields.

### Verification
1. **Route-selection unit tests** (new) + **controller-mock test** — the three route cases + POST URL/auth/result passthrough. Run the brisen-lab test suite green.
2. **Live smoke (laptop):**
   - Fire a wake at a live tmux seat → composer shows the **tagged** `check bus #<id> <topic>` line **submitted** (not parked); `~/.brisen-lab/wake-dispatch.log` last record has `route=controller`, `result` sent.
   - Fire a wake at an App-resident alias → `route=legacy`, existing behavior.
   - Stop the controller (or point at a dead port) and fire → `route=legacy-fallback` logged at WARNING, legacy path still nudges.
3. **Deploy (AC — same forward-port discipline as PR #156):**
   - `rsync`/`cp` the merged `tools/wake-listener/wake-listener.py` to `~/.brisen-lab/wake-listener.py`, then `launchctl kickstart -k gui/$(id -u)/com.baker.wake-listener`.
   - Confirm the listener reconnects (startup log line) and a post-deploy live wake goes `route=controller`.
4. Ship via PR to brisen-lab `main`; codex bus-seat gate; hand to lead to merge (b4 does not self-merge).

## Harness V2
- **Context Contract:** everything b4 needs is in this brief + the brisen-lab repo (`tools/wake-listener/`) + the READ-ONLY controller contract quoted above; no vault reads required. Live probe surfaces: `~/.brisen-lab/wake-dispatch.log`, a live tmux seat's composer, and `127.0.0.1:7800`. No secrets in the brief (credentials read at runtime from the 0600 file).
- **Task class:** production bug-fix, P1, brisen-lab launchd service (Tier-A merge path, codex-gated). No UI, no new endpoint.
- **Done rubric / done-state class:** post-deploy AC verdict on the bus (`post-deploy-ac-bus-gate`) on topic `gates/wake-listener-route-via-controller-1` — each verification item (unit tests / controller route / legacy route / legacy-fallback / deploy-sync + kickstart) PASS/FAIL, with the relevant `wake-dispatch.log` lines attached.
- **Gate plan:** route-selection + controller-mock unit tests → codex bus-seat gate on the brisen-lab branch tip (pre-merge) → lead line-read + merge → laptop deploy-sync + `launchctl kickstart com.baker.wake-listener` → post-deploy AC verdict.
- **Report topic:** `gates/wake-listener-route-via-controller-1`.

## Files Modified
- `tools/wake-listener/wake-listener.py` (brisen-lab) — route selection in `dispatch_wake`; controller POST w/ Basic auth; `_log_dispatch` gains `route` + result passthrough; fail-loud fallback.
- `tools/wake-listener/` test file(s) (brisen-lab) — route-selection unit tests + controller-mock (match the repo's existing wake-listener test layout).

## Do NOT Touch
- baker-master `scripts/cockpit_controller.py` / any `/api/*` route — the `/wake` contract is complete and out of scope.
- The credentials file `~/Library/Application Support/baker/cockpit/credentials` — read-only, never rewrite, never log.
- The legacy open-URL behavior for App-resident aliases — must stay byte-for-byte for that class.
- The existing D3 record keys — ADD fields only.

## Quality Checkpoints
1. Live tmux-seat wake is **tagged + submitted** (not parked); `route=controller` in the D3 log.
2. App-resident alias still uses legacy; `route=legacy`.
3. Controller-down → `route=legacy-fallback` at WARNING; legacy still fires; listener never crashes.
4. No double-wake in any path.
5. Credential never appears in the log or process table.
6. Route-selection + controller-mock unit tests green; brisen-lab suite green; `python -m py_compile tools/wake-listener/wake-listener.py` clean.
7. Deploy AC done: deployed copy synced + `com.baker.wake-listener` kickstarted + post-deploy live wake `route=controller`.

## Gate-1 + Gate-2 reviewer instructions
Reviewers MUST exercise the actual flow, not compile-clean: fire a real wake at a live tmux seat and confirm the D3 log shows `route=controller` with a submitted (not parked) tagged line, then fire with the controller down and confirm `route=legacy-fallback`. Reading the diff is necessary but NOT sufficient (Lesson #8 — compile-clean ≠ done).
