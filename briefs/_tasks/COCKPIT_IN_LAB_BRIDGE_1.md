# BRIEF: COCKPIT_IN_LAB_BRIDGE_1 — Cockpit inside Brisen Lab via native reverse bridge (build-not-flip)

**Dispatch: b1.** Director-ratified: verbatim goal #12558 ("install cockpit inside Brisen Lab overnight") + ruling #12562 (build fully overnight, deploy-behind-flag OK, **nothing internet-reachable before morning GO**). Supersedes the Cloudflare draft `COCKPIT_CLOUD_EMBED_1.md` (blocked: no Brisen domain is on Cloudflare — verified `dig NS` 2026-07-17; that draft stays for the record).

## Context

Cockpit today: laptop-only page `127.0.0.1:7800` — controller (`scripts/cockpit_controller.py`, baker-master) + per-seat ttyd behind a same-origin proxy (`/term/<slug>/`) + tmux (28/28 live post-cutover). Director wants it reachable inside Brisen Lab (Render, FastAPI, `brisen-lab.onrender.com`).

Architecture (lead-decided under charter §3, engineering rationale in `COCKPIT_CLOUD_EMBED_1.md` + this file): the laptop opens an **outbound** websocket to the Lab; the Lab proxies the cockpit UI down that connection to Director sessions. No new vendor, no DNS, no inbound laptop ports; the whole surface sits behind the Lab's existing auth + a server-side env flag.

```
Director browser ──(Lab auth)── brisen-lab /cockpit/* ──(mux over one WS)── laptop agent ── 127.0.0.1:7800
```

## Estimated time: ~5-7h (Phase 1 ~3h, Phase 2 ~2-3h)
## Complexity: High (bidirectional mux proxy, two repos)
## Prerequisites: none blocking — both checkouts exist in `~/bm-b1/` (baker-master + brisen-lab)

## Baker Agent Vault Rails
Relevant: standing-contract (Tier-A security), verification-surfaces, bus-and-lanes (new terminal-key slug), build-command-center.
Ignored: memory-and-lessons (routine), loop-runner, skills-and-playbooks.

## Harness V2

- **Context Contract:** worker needs ONLY — this brief; brisen-lab `app.py` (route+auth patterns), `auth_lab.py` (terminal-key + director auth), `requirements.txt`, `render.yaml`/`start.sh`; baker-master `scripts/cockpit_controller.py` (what is being proxied — read, do not modify), `scripts/install_forge_push.sh` (launchd installer pattern), `.claude/how-to/lab-cockpit.md`. NOT needed: bus schema, Baker dashboard, matter context, cutover scripts.
- **Task class:** production-infra, Tier-A (control surface for fleet terminals), security-relevant, two-repo.
- **Done rubric (done-state class: staged-verified):** because "nothing internet-reachable before GO", live end-to-end is EXCLUDED from tonight's DONE. Tonight's DONE = loopback integration green (Phase-1 mandatory, Phase-2 if reached) + flag-off deploy returns 404 on every `/cockpit` path + agent installer built NOT loaded + codex PASS on exact tips + `/security-review` clean + morning flip checklist written. Report Phase-2 honestly if not reached — flag stays off either way.
- **Gate plan:** (1) prototype probe (loopback, below) → (2) build Phase 1 → loopback AC → (3) build Phase 2 if time → (4) `/security-review` (MANDATORY Tier-A) → (5) codex cross-vendor gate, own verdict on exact tip per repo (Lesson #114) → (6) lead line-read + merge → (7) Lab deploy flag-OFF + 404 probe → (8) morning: Director GO → flag flip + agent load + live AC (separate checklist, NOT tonight).

---

## Feature 1 (Phase 1, mandatory): bridge transport + HTTP proxying — cockpit grid renders inside Lab

### Problem
Lab cannot reach the laptop; cockpit is loopback-only.

### Current State
brisen-lab: FastAPI + uvicorn 0.32.0; `websockets` NOT in requirements (add it — bare uvicorn has no WS impl). Auth: `X-Terminal-Key` → slug via `BRISEN_LAB_TERMINAL_KEYS` JSON env (`auth_lab.py` line 43-75); the Director UI at `GET /` has its own auth pattern — reuse it verbatim for `/cockpit`. Cockpit page is a pure client (static + `/api/agents` + POSTs) — proxying HTTP is sufficient for the full grid, cards, glance, panels, Start/GO buttons.

### Engineering Craft Gates
- **Diagnose: N/A** — new capability.
- **Prototype: APPLIES.** Question: *does WS-mux relay of HTTP through uvicorn hold up (latency, frame ordering) with the real cockpit page?* Throwaway: run brisen-lab `app.py` LOCALLY (uvicorn on 127.0.0.1:9xxx) + agent connecting to it + real local controller; open `http://127.0.0.1:9xxx/cockpit/` in a browser. Entirely loopback — compliant with the no-internet-exposure ruling. Absorb (not delete): the probe IS the integration test skeleton.
- **TDD: APPLIES.** Public seam = mux framing. Write the frame codec test FIRST (encode/decode round-trip, interleaved streams, max-size rejection), then one vertical test: fake origin server ↔ mux ↔ fake agent ↔ fake controller responds 200.

### Implementation (server, brisen-lab — new module `cockpit_bridge.py`, wire into `app.py`)
1. `WS /api/cockpit/bridge` (agent side): auth via existing `X-Terminal-Key` header resolving to NEW dedicated slug `cockpit-bridge` (never reuse `lead`/`director` keys). Single active bridge: a second connect closes the first (log it). Heartbeat ping 30s; drop dead peers.
2. `/cockpit/{path:path}` (GET+POST, Director side): auth = SAME dependency as the existing Director UI route; **gated on env `COCKPIT_EMBED_ENABLED` — anything falsy → plain 404 (not 403; do not advertise existence). Default: unset.** Forward method/path/query/body/headers (strip hop-by-hop + strip inbound Authorization) over the mux; stream response back. Agent absent → 503 JSON `{"detail":"laptop offline"}`.
3. Mux framing (shared design, implement twice — repos must match byte-for-byte): binary WS frames, 9-byte header `stream_id:u32 | type:u8 | len:u32`, types OPEN/DATA/END/RESET/WS_OPEN/WS_DATA/WS_CLOSE/PING/PONG; OPEN payload = JSON request head; **max frame 256 KiB, hard-reject larger (OOM history on this service — stream, never buffer whole bodies)**; per-request timeout 30s → RESET both ways.
4. `requirements.txt`: add `websockets>=13,<14`.

### Implementation (agent, baker-master — new `scripts/cockpit_bridge_agent.py` + `scripts/install_cockpit_bridge.sh`)
1. Agent: asyncio client; outbound `wss://brisen-lab.onrender.com/api/cockpit/bridge`; key resolved via existing `brisen_lab_read_terminal_key` precedence for slug `cockpit-bridge` (env → `~/.brisen-lab/keys/` cache → 1P) — **never on argv, never logged** (mirror `brisen_lab_ack.sh` hardening). Reconnect: exponential backoff 1s→60s + jitter, forever. Forwards each mux request to `http://127.0.0.1:8080`→NO→`http://127.0.0.1:7800`, injecting the local Basic-auth header read at request time from `~/Library/Application Support/baker/cockpit/credentials` (password never leaves the laptop process; never sent to Lab, never in config).
2. Installer: launchd `com.baker.cockpit-bridge` KeepAlive plist, `install_forge_push.sh` pattern. **Tonight: script committed, plist NOT loaded** (build-not-flip). Loading is a morning-GO step.

### Key Constraints
- `cockpit_controller.py`: READ-ONLY. Zero changes; bind stays loopback.
- No secrets in any commit (terminal key, Basic-auth cred). Env/key-cache names only.
- brisen-lab checkout `~/bm-b1/brisen-lab` currently sits on a deputy-codex branch with untracked scratch (`doc_backfill_driver*.sh`, logs): `git fetch origin && git switch -c b1/cockpit-in-lab-bridge-1 origin/main`; do NOT touch the scratch files, do NOT stash/checkout over them (Lesson #121).
- Commit+push per green block with hashes in the report (Lesson #115).

## Feature 2 (Phase 2, stretch): live terminals — ttyd websocket piping

`WS /cockpit/term/{slug}/ws` (Director-auth + same flag) ↔ mux WS_OPEN/WS_DATA/WS_CLOSE ↔ agent dials `ws://127.0.0.1:7800/term/{slug}/ws` (verify exact ttyd WS path by reading the controller proxy routes — do not guess). Static ttyd assets already covered by Feature-1 HTTP proxying. Binary passthrough, no inspection; close propagates both directions. If not solid by hand-back: report NOT DONE, list the seam, flag stays off — an honest partial beats a flaky terminal.

## Feature 3: Lab entry point

"Cockpit" nav button on the Lab main page → `/cockpit/`; rendered ONLY when the server says the flag is on (bootstrap/config endpoint or template conditional — match how the Lab page already does conditional UI). Flag off (tonight): invisible.

---

## Files Modified
- brisen-lab: NEW `cockpit_bridge.py`; `app.py` (wire routes); `requirements.txt` (+websockets); `static/` (nav button); NEW `tests_unit/test_cockpit_bridge.py`
- baker-master: NEW `scripts/cockpit_bridge_agent.py`; NEW `scripts/install_cockpit_bridge.sh`; NEW `tests/test_cockpit_bridge_agent.py`; `.claude/how-to/cockpit-cloud-access.md` (runbook: kill switches FIRST — server flag-off AND `launchctl bootout gui/$(id -u)/com.baker.cockpit-bridge` — then morning flip checklist) + INDEX line

## Do NOT Touch
- `scripts/cockpit_controller.py`, `scripts/cockpit_static/*` — the design is zero cockpit-side change
- brisen-lab `bus.py` / bus schema — bridge is a separate surface
- The dirty scratch files in `~/bm-b1/brisen-lab` (not yours)

## Quality Checkpoints
1. Frame-codec unit tests green both repos (same vectors — copy the test vectors file across so drift is impossible).
2. Loopback integration: real cockpit grid renders + Start/GO POST works through local Lab instance.
3. Flag-off = 404 on every `/cockpit` path incl. the WS route; nav button absent.
4. Agent absent = 503 loud, never hang.
5. `/security-review` + codex gate (both repos, exact tips) before merge.
6. `post-deploy-ac-bus-gate` verdict after flag-off deploy.
7. Morning flip checklist exists and names every step + owner.

## Verification SQL
N/A — no DB surface. Verification = checkpoints above.

## Rollback
Server: unset `COCKPIT_EMBED_ENABLED` (Render env) → 404, instant. Laptop: `launchctl bootout` the agent. Both are one-command; document both in the runbook before anything else.
