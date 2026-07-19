# COCKPIT_MSG_PANEL_BODY_PREVIEW_1 — show message content in Cockpit card panels

**Dispatched by:** lead · 2026-07-19 · **Assignee:** deputy-codex · **Tier:** A (local cockpit, no prod deploy)

**Harness-V2:** N/A — local-laptop cockpit tooling (controller + static page), not production baker-master runtime; no deploy, no DB, lead reviews on merge.

**Task class:** small feature (one endpoint + one renderer). **Done-state:** AC 1–5 below verified live on the local cockpit. **Gate plan:** self-verify + lead merge review; no codex gate (Tier-A local).

## Problem

Director opened an app-seat card in the Cockpit (`http://127.0.0.1:7800/`) and the
message panel shows only envelopes — `from / topic / #id / age` — for
Unacknowledged and Last message. He cannot see WHAT the message says. The
production Lab view gives him the last-task content; the Cockpit panel must reach
parity. (Director request 2026-07-19 ~08:3xZ, this session.)

Root cause is by design, twice over:

1. Lab `GET /api/v2/terminals` is **public-read** — `_message_envelope()` in
   `brisen-lab/bus.py:512` says "Never add body/body_preview here". Correct;
   DO NOT touch it.
2. Cockpit controller copies only `GLANCE_FIELDS` (cockpit_controller.py ~line
   61–66, "no body/transcript... no new leak surface") into `/api/agents`.

So bodies must come from the **authenticated per-seat** surface, fetched lazily
by the local controller — not from the public glance.

## Context

### Surface contract (ui-surface-prebrief skill, V1)

1. **User action:** Director clicks a seat card to read the content of its unacknowledged and last bus messages.
2. **Backend route (NEW):** `GET /api/messages/<slug>` on the local cockpit controller (`scripts/cockpit_controller.py`; FastAPI app, same Basic-auth dependency as `/api/agents`). Upstream it calls Lab `GET /msg/<slug>?limit=N` — VERIFIED live 2026-07-19: returns rows incl. `body_preview`, `topic`, `from_terminal`, `created_at`, `acknowledged_at`.
3. **Endpoint contract:** upstream needs header `X-Terminal-Key: <that seat's key>`; per-seat keys are cached at `~/.brisen-lab/keys/<slug>` (mode 0600, 48 slugs present — verified). Response field is `body_preview` (server-truncated), NOT `body`.
4. **State location:** bus messages Postgres in brisen-lab (Render); read-only access via `/msg/<slug>`.
5. **UI repo:** baker-master `scripts/cockpit_static/` (cockpit.js panel) + controller — the Cockpit owns this surface. NO brisen-lab change (also: Render Frankfurt deploys are currently broken, incident open — a Lab-side fix would be undeployable today).
6. **Director surface preference:** Cockpit card panel — Director named the surface himself in the request. Ratified by the request.
7. **Gate reviewer instruction:** Reviewers MUST curl `/api/messages/<slug>` on the live controller (with Basic auth) for one app seat + one terminal seat and confirm non-error response containing `body_preview`. Code-shape review is not sufficient.

## Build

1. **Controller — new endpoint** `GET /api/messages/<slug>`:
   - Validate slug against the launch-manifest/layout slug set (reject unknown — no path traversal into the key dir).
   - Read `~/.brisen-lab/keys/<slug>`; if missing → `{"available": false, "reason": "no key"}` 200 (panel degrades gracefully).
   - Call Lab `GET /msg/<slug>?limit=12` with `X-Terminal-Key`; 3–5s timeout; wrap in try/except; on upstream failure return `{"available": false}` — never 500 the panel.
   - Return trimmed rows: `id, from_terminal, topic, kind, created_at, acked, body_preview` (cap body_preview at 400 chars defensively even though server truncates).
   - Small TTL cache (~10s per slug) so panel re-opens don't hammer the Lab.
   - Same Basic-auth guard as every other route. Never log key material or bodies.
2. **cockpit.js — panel enrichment** (`renderMsgSummary` / `msgEnvelope`):
   - On panel open, fetch `/api/messages/<slug>`; merge by message id.
   - Render `body_preview` as a muted second line under each Unacknowledged row and the Last-message row (textContent only — keep the XSS-safe `el()` pattern; no innerHTML).
   - While loading / on `available:false`: show current envelope-only view unchanged (zero regression).
   - Applies to BOTH panel types: app-seat message panel AND the unacked list shown in the open-terminal drawer (`renderPanelUnacked`) if trivially shareable; app-seat panel is the must-have.
3. **Deploy:** commit to baker-master, then re-sync staging:
   `rsync -a --delete scripts/cockpit_static/ "$HOME/Library/Application Support/baker/cockpit/static/"` + copy controller file + `launchctl kickstart -k gui/$(id -u)/com.baker.cockpit-controller`. (Cockpit merges MUST re-sync App Support — standing rule.)

## Files to touch

- `scripts/cockpit_controller.py` — new `/api/messages/<slug>` route + TTL cache + key read.
- `scripts/cockpit_static/cockpit.js` — panel fetch + body_preview render.
- (staging re-sync, not a repo file: `~/Library/Application Support/baker/cockpit/`.)

## Verification

- `curl -u <cred> http://127.0.0.1:7800/api/messages/codex-arch` → 200 with `body_preview` fields.
- `curl -u <cred> http://127.0.0.1:7800/api/messages/../etc` and unknown slug → 4xx, no key-file read.
- Open Cowork AO card in browser → previews visible; Lab unreachable → envelope-only fallback, no errors.

## Constraints

- Do NOT modify brisen-lab (`bus.py` / `_message_envelope`) — public-endpoint no-body invariant stands.
- Do NOT add bodies to `/api/agents` (polled every ~15s; keep bodies lazy).
- Fault-tolerant or it doesn't ship: every upstream call try/except'd; panel never breaks on Lab outage (Lab glance 503s are happening right now — good live test).
- Keys: read-only access, never echoed, never in logs, never in the browser beyond the returned previews.

## Acceptance criteria

1. Click an app-seat card (e.g. Cowork AO, codex-arch): panel shows body_preview text under each unacked message and under Last message.
2. Terminal-seat panel data path works too (curl AC in Surface contract row 7).
3. Kill network to Lab (or point at bad host in a test): panel still opens, envelope-only, no console error storm.
4. Unknown slug → 4xx, no file read attempted.
5. Existing tests pass; add a unit test for the slug-validation guard + one for the merge-by-id renderer if a JS test rig exists (else document manual check).

## Report

Reply on bus to `lead`, topic `cockpit-msg-panel-body-preview-1`, with commit hash + AC evidence. Codex gate not required (local Tier-A cockpit static + controller; self-verify + lead review on merge).
