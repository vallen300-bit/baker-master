# SCOPE_LAB_TERMINAL_COCKPIT_1 — In-Lab Live-Terminal Cockpit

- **Status:** DRAFT v1.3 — third G0 round requested; Director-ratified build + card contract stand (mock confirmed 2026-07-16 evening)
- **v1.3 delta (per codex-arch re-G0 FAIL #12028):** §6b executable interface = validated alias → `/bin/zsh -lic '<alias>'`, no cwd field, generation-time `type` validation all seats; §6a rewritten = Phase-1 sandbox pilots + ONE coordinated global Terminal cutover (Lesson 76 — Cmd+Q is app-wide), named reboot owner (controller plist RunAtLoad → fleet up → ttyd KeepAlive); §6c same-origin HTTP+WS proxy `/term/<slug>/` = one credential prompt, ttyd `--check-origin`; stale branches removed (§6.3 plist ruling, R2 window-size, R4 order, §4 eligibility shorthand); P1 split backend-before-UI (B-1 controller, B-2 page).
- **Author:** cowork-ah1 · 2026-07-16 · v1.1 recut + v1.2 Director corrections by lead
- **Reviewer:** codex-arch (cross-vendor design pass)
- **Type:** Scope / design document. NOT a build brief. Build briefs are cut from this.
- **v1.1 delta:** three dispatch-blocker contracts added (§6a Migration, §6b Launch manifest, §6c Controller + auth) per codex-arch #12017; §11 open questions resolved with codex-arch picks; R3 auth claim corrected.
- **v1.2 delta (Director rulings, chat 2026-07-16 evening):** §5 rewritten — production Lab glance colors reused (blue-flash NEW / amber WORKING / dim IDLE), plate grouping (Control Tower / Verification / Builders / Specialists / Matter Desks / Ground System), GO-click affordance (`/go` route sends Enter), unacked-copy control (separate Lab brief). Director also confirmed the B3 mock interaction verbatim.

---

## 1. Problem

The fleet runs ~10–15 Claude Code CLI sessions, each in its own Terminal.app
window. The Director's screen is window clutter; finding the right agent means
hunting overlapping windows. Brisen Lab already renders the fleet beautifully
(registry-generated cards, status, unread counts) but is read-only: to *type*
to an agent, the Director must leave the Lab and find the raw window.

Director's picture (ratified direction 2026-07-16, this session): *cards in a
Brisen-Lab-look surface; click a card; the real, typeable terminal opens right
there; B-workers always grouped, always in the same order.*

## 2. Goal

A **Cockpit** page in the Brisen Lab design language where every
terminal-run agent is a card in a fixed, registry-driven order; clicking a
card opens the agent's **real live terminal** in-page (read + type); closing
it returns to the clean grid. Two-screen end state: screen 1 = Lab Control
Room (glance), screen 2 = Cockpit (interact).

## 3. Non-goals (v1)

1. No change to what agents *do* — only how their terminals are hosted/viewed.
2. No remote access (iPad/other machines). Localhost-only. Tailscale is P2+.
3. Cowork-App sessions (`runtime: app-claude`, 12 seats) are NOT wrapped —
   they get status-only cards. Only 2–3 such windows exist at a time.
4. No embedding inside the Render-hosted Lab page in v1 (see §9 R1). The
   Cockpit is a **local** page that *looks* identical.
5. No new model usage, no bus schema changes, no dashboard.py changes.

## 4. Current state (grounded 2026-07-16)

1. Fleet launch: per-agent Terminal.app profiles run `claude` CLI directly
   (install-agent runbook row "Terminal profile clone"). No session manager.
2. `~/baker-vault/_ops/registries/agent_registry.yml`: 45 agents; **26
   `runtime: terminal-claude`** (cockpit-eligible), 12 `app-claude`. Registry
   is already the Lab's card source → same file drives Cockpit order/groups.
3. `tmux` and `ttyd` are **not installed** on the Mac (verified). Homebrew
   assumed present (verify at build).
4. Proven launchd daemon pattern exists: `scripts/install_forge_push.sh` +
   `scripts/launchd/*.plist` — TCC-safe deploy to
   `~/Library/Application Support/baker/`, idempotent reinstall, KeepAlive.
5. Lab is served from Render (`brisen-lab.onrender.com`); terminals live on
   the local Mac. A cloud page cannot reach local processes without the
   cross-origin work deferred to P2 (§9 R1).

## 5. Target UX (v1.2 — Director corrections 2026-07-16 evening folded)

1. **Plate grouping (Director-corrected):** cards grouped on visually
   distinct "plates" — each group a bordered container with a slightly
   different background tint. Groups: **Control Tower** (lead, deputies,
   cowork-ah1, dispatcher), **Verification** (codex seats, reviewer lanes),
   **Builders** (B1–B4 always adjacent, same slots), **Specialists**
   (researcher, librarian, clerk, publisher, designer, arm…), **Matter
   Desks**, **Ground System**. Group membership generated from the registry
   (class/role fields), mirroring the Lab Control Room grouping — verify
   against the live Control Room at build; no hardcoded slug lists.
2. Card face: agent_id, display_name, slug, session up/down, PLUS the
   **live Lab glance state with today's production semantics** (Director
   ruling): flashing blue frame = new unacked bus not yet reacted to; amber
   frame = working; extinguished/dim = idle. Reuse `resolveGlanceState`
   semantics (brisen-lab `static/glance_state.js` — WORKING > NEW > UNKNOWN >
   DONE/IDLE) and the same bus-badge data (`unacked_count`,
   `oldest_unacked_age_sec`, topics; age colors amber >10 min, red >30 min).
   Data path: cockpit controller proxies the Lab state endpoints (localhost
   page cannot rely on cross-origin fetch to Render — build resolves).
3. Click card → terminal panel opens in-page (modal or right split), full
   xterm rendering, keyboard focus, scrollback. Esc/✕ → back to grid.
4. **GO affordance (Director-added):** when the open terminal is waiting for
   a confirmation, one click answers it. A prominent **GO** button on the
   open panel (and on the card face) sends Enter to that tmux session via
   the controller (`send-keys Enter` — new allowlisted route, §6c). No text
   injection beyond Enter in v1.
5. **Unacked copy (Director-added):** the Lab's white-circle unread badge
   popup (unacked count + topic list) gains a one-click **copy** control so
   the Director can paste the unacked summary into a misbehaving idle
   terminal. Lives in the Lab UI (separate small brief, brisen-lab repo);
   cockpit cards mirror it in P2.
6. The native Terminal.app window for the same agent keeps working — both
   views attach to one shared session (tmux), nothing is lost either way.
7. Dark register, Lab visual tokens (card bevel, AG-badge, plate headers).

## 6. Architecture

**Stack: tmux (session host) + ttyd (web terminal, xterm.js) + static local
cockpit page + launchd (persistence). All OSS, zero licence cost.**

1. **tmux layer** — every eligible agent (§6b prefix rule) launches inside
   `tmux new-session -A -s <slug> "/bin/zsh -lic '<alias>'"` where `<alias>`
   is the seat's validated Terminal-profile alias (§6b). `-A` =
   attach-if-exists, so double-launch is safe.
2. **fleet launcher** — `scripts/fleet_terminals.sh up|open <slug>|status`:
   reads the manifest, creates missing tmux sessions in registry order,
   `open <slug>` opens a Terminal window attached to that session.
3. **ttyd layer** — one ttyd per agent, **one launchd plist per agent**
   (resolved; generated from the manifest): `ttyd -W -p <port> -i 127.0.0.1
   -c <cred> --check-origin ...` attaching `tmux attach -t <slug>`. Port =
   7600 + registry index; no hand-kept lists (HAGENAUER trap). Browser never
   talks to ttyd directly — see §6c proxy. Installer mirrors
   `install_forge_push.sh`.
4. **Cockpit page** — static HTML/JS served by the controller (§6c, one
   origin). Renders cards from manifest-generated JSON (same generator
   family as `agent_identity_generated.sh`). Card click → iframe to
   `/term/<slug>/` on the controller origin (proxied to that seat's ttyd).
5. **Design source** — reuse the Lab's locked card design language; extract
   CSS tokens from the live Lab page / canonical mockup at build time. The
   Cockpit must be visually indistinguishable from a Lab page.

## 6a. Migration contract (v1.3 — rewritten per codex-arch #12028 blocker 2)

Two facts drive the design: running agents CANNOT be adopted by tmux, and
Terminal profile changes only take effect app-wide (Cmd+Q quits EVERY
window — Lesson 76). Per-seat profile cutover is therefore impossible; the
hybrid in v1.1 is withdrawn. v1.3 mechanism:

**Phase 1 — sandbox validation (NO Terminal profile edits, NO seat stops):**
pilot seats (B3, then Brisen Desk) get tmux sessions created directly by
`fleet_terminals.sh` alongside their (stopped-by-their-own-cadence or idle)
Terminal seats — validation happens on a seat that is cleanly down via the
existing daemon refresh cadence, never by killing a live one. Smoke: native
`open <slug>` attach AND web attach both render + accept keystrokes.

**Phase 2 — ONE coordinated global cutover (after both pilots green +
explicit lead GO):**
1. All active seats checkpoint (existing context-band rollover discipline;
   idle seats: lightweight migration pin).
2. Migration script rewrites ALL eligible Terminal-profile CommandStrings to
   the tmux wrapper in one pass.
3. Single Terminal.app quit (the ONLY Cmd+Q in the process, scheduled in a
   quiet window with the daemon's refresh cadence paused).
4. Relaunch: `fleet_terminals.sh up` creates all sessions; Terminal windows
   reopen attached via the new profile commands.
5. Per-seat smoke recorded in the generated migration ledger
   (`fleet_terminals.sh status`); any seat failing smoke gets its profile
   rolled back individually (§12) while the rest stay migrated.

`up` creates sessions only for manifest-eligible seats and is idempotent;
before Phase 2 it creates only the pilot sandbox sessions, so unmigrated
seats are never double-launched.

**Reboot owner + order (codex-arch blocker 4):** the controller's launchd
plist (`RunAtLoad`) is the named owner: at load it runs
`fleet_terminals.sh up`, THEN the per-agent ttyd plists (KeepAlive) find
their sessions; ttyd started before its session simply retries attach.
Documented in the runbook.

## 6b. Launch manifest contract (G0 blocker 2 — codex-arch #12017)

The agent registry has NO `cwd` or launch command, and live Terminal profiles
call materially different zsh functions — so the tmux wrapper cannot be
derived from the registry alone. Build adds a **generated launch manifest**
(same generator family as `agent_identity_generated.sh`):

- **Executable interface (v1.3, per codex-arch #12028 blocker 1):** profile
  CommandStrings are zsh alias/functions (`b3`, `brisendesk`, …) defined only
  in interactive login shells — `/bin/zsh -c` cannot see them. The manifest
  therefore stores the **validated alias**, and the ONE launch form
  everywhere is `/bin/zsh -lic '<alias>'`. No `cwd` field: the alias itself
  establishes cwd (function internals are never parsed or duplicated).
- Per seat: `slug`, `alias` (from the Terminal-profile CommandString),
  `port` (7600 + registry index), `eligible` flag.
- **Eligibility rule:** `status: active` AND `runtime` starts with
  `terminal-` (prefix match; supersedes §4's shorthand "26 terminal-claude"
  — the prefix rule is canonical).
- **Generation-time validation (all eligible seats):** generator probes
  `/bin/zsh -lic 'type <alias>'` per seat; any alias that does not resolve
  fails the generation LOUD (no partial manifests).
- Manifest is regenerated from registry + profile sources at install time;
  hand-editing it is forbidden (HAGENAUER hardcoded-list trap).
- `fleet_terminals.sh` and the ttyd installer consume ONLY the manifest.

## 6c. Controller + auth contract (G0 blocker 3 — codex-arch #12017)

A static HTML page cannot supply live session state or a Start action. v1
ships a **tiny Python controller** (codex-arch pick; not bare `http.server`,
not Caddy) bound to 127.0.0.1 under launchd:

- `GET /api/agents` — card list + live session state (manifest + `tmux ls`)
  + proxied Lab glance/bus-badge state (§5.2).
- `POST /api/sessions/{slug}/start` — allowlisted to manifest slugs only;
  starts the tmux session via the launch manifest.
- `POST /api/sessions/{slug}/go` — sends exactly `Enter` to the seat's tmux
  session (`tmux send-keys -t <slug> Enter`); allowlisted slugs only; no
  arbitrary key/text injection (v1.2, Director GO-click ruling). No other
  verbs in v1 (no stop/kill from the page — native window or CLI remains
  the path).
- Controller also serves the static cockpit page (one process, one port).
- **Same-origin proxy (v1.3, per codex-arch #12028 blocker 3):** each ttyd
  port is a distinct browser origin, so per-port Basic auth would prompt per
  agent. The controller therefore reverse-proxies HTTP + WebSocket at
  `/term/<slug>/` to the seat's ttyd — the browser sees ONE origin
  (`127.0.0.1:<cockpit-port>`), ONE Basic-auth prompt per browser session.
- **Auth layout:** ttyd `-c` is HTTP **Basic auth** (not token — R3
  corrected). Credential (0600,
  `~/Library/Application Support/baker/cockpit/`) is required by the
  controller at its single origin AND passed by the controller (not the
  browser) to each ttyd; every ttyd runs `--check-origin` restricted to the
  controller origin and binds 127.0.0.1. Controller rejects requests whose
  `Origin`/`Host` is not `127.0.0.1:<cockpit-port>`. Threat model unchanged:
  local user = Director; no widening of who can reach the
  `--dangerously-skip-permissions`-class sessions.
- **AC addition:** exact browser smoke — full flow (grid → open B3 →
  keystroke → GO) completes with at most ONE credential prompt, verified in
  a fresh browser profile.

## 7. Surface contract

- **Surface:** "Cockpit" — new local page, `http://127.0.0.1:<cockpit-port>`.
- **Audience:** Director only (Director-facing register — Lab design v2,
  content-contract rule 10 Director-legibility applies to card labels).
- **Pattern:** Brisen Lab fleet-grid pattern (dark, card grid, AG badges).
  Terminal panel itself is raw xterm — exempt from register (it IS the tool).
- **Data:** agent registry (order/groups/names) + tmux session state
  (up/down) + ttyd (live stream). No Baker DB reads, no bus writes.
- **States:** session-up (card active), session-down (card dimmed +
  "start" affordance via fleet launcher), ttyd-down (card error state).
- **Failure mode:** Cockpit down ⇒ native Terminal windows still work
  unchanged (tmux sessions are the substrate, viewers are optional).

## 8. Phases + acceptance criteria

**P1 — MVP (3 build briefs, backend before UI — codex-arch #12028
blocker 4 / ui-surface-prebrief):**
- BRIEF A `FLEET_TMUX_LAUNCH_1`: brew install tmux+ttyd; launch-manifest
  generator + alias validation (§6b); fleet_terminals.sh + migration ledger;
  Phase-1 sandbox pilot machinery + Phase-2 cutover + rollback scripts (§6a);
  per-agent ttyd plist generator + installer.
- BRIEF B-1 `LAB_COCKPIT_CONTROLLER_1` (backend, gated first): Python
  controller — /api/agents, /api/sessions/{slug}/start, /go, /term/<slug>/
  HTTP+WS proxy, Basic-auth + origin enforcement, launchd plist (RunAtLoad
  reboot owner). Reviewer instruction: exact URLs + expected non-error
  responses, no UI.
- BRIEF B-2 `LAB_COCKPIT_PAGE_1` (UI, after B-1 merged): cockpit page —
  plate grid (§5.1), glance colors (§5.2), on-demand iframe panel via
  /term/<slug>/, GO button, Lab CSS; runbook + how-to entry.

AC (all must pass, live, not compile-clean — Lesson #8):
1. `fleet_terminals.sh up` creates sessions ONLY for seats marked migrated
   in the ledger (§6a), in registry order; rerun is a no-op; an unmigrated
   seat is never double-launched (verified: old window + `up` ⇒ no dup seat).
2. Click B3 card → typeable live terminal; keystrokes reach the real session;
   native window (if open) mirrors them.
3. Kill Cockpit/ttyd → native windows unaffected; relaunch reattaches, zero
   session loss.
4. Reboot → launchd restores ttyd + cockpit without manual steps; tmux
   sessions restart via fleet launcher (documented: sessions do NOT survive
   reboot — the *processes* relaunch fresh, same as today's behavior).
5. All listeners bound to 127.0.0.1 only — verified with `lsof`; nothing
   answers from another machine.
6. Rollback script restores today's direct-launch Terminal profiles.

**P2 — candidates (separate ratification):** live last-lines preview on card
face (`tmux capture-pane`), Lab-telemetry status badges, embed inside the
Render Lab (solve mixed-content/Private-Network-Access), Tailscale remote,
Cowork-App deep-link cards.

## 9. Risks + mitigations

- **R1 Cross-origin embed (why v1 is local):** HTTPS Render page → 
  `http://127.0.0.1` iframes trips mixed-content/PNA rules in Chrome.
  Deferred to P2 investigation; v1 sidesteps entirely with a local page.
- **R2 tmux two-viewer sizing:** current tmux default already sizes to the
  latest client — NO fleet-wide override shipped (resolved §11.4; stale
  `window-size latest` instruction withdrawn v1.3); documented quirk only.
- **R3 Writable terminal on localhost:** 127.0.0.1 bind + ttyd Basic auth
  (`-c` — NOT token auth; corrected v1.1, see §6c);
  never tunneled/port-forwarded; threat = local user only (= Director).
  These sessions run `--dangerously-skip-permissions`-class agents — the
  cockpit must not widen who can reach them (it doesn't: same machine, same
  user).
- **R4 Launch migration breaks a seat:** Phase-1 sandbox pilots (B3 → Brisen
  Desk, §6a) before the single coordinated cutover; per-seat rollback (AC 6)
  after it; canonical order is §6a's (stale "per-profile, B3 then fleet"
  branch withdrawn v1.3).
- **R5 TUI-in-tmux quirks (mouse, scrollback, resize):** tmux mouse on;
  known-good pattern for Claude Code CLI; pilot seat validates before fleet.
- **R6 TCC/launchd path blocks:** solved pattern — deploy workers to
  `~/Library/Application Support/baker/` per forge-push installer.
- **R7 Registry drift:** port map + card list are generated from the
  registry at install time; regenerate step documented in runbook; no
  hardcoded slug lists anywhere.

## 10. Effort + cost

- 2 briefs, est. 2–3 elapsed days incl. pilot + fleet migration + runbook.
- Software cost: 0 (tmux, ttyd MIT/BSD). No new services, no Render change.
- Runtime overhead: negligible (tmux + N idle ttyd processes).

## 11. Open questions — RESOLVED v1.1 (codex-arch picks, #12017)

1. ttyd supervision: **generated plist per agent** (per-seat KeepAlive,
   per-seat restart isolation). Plists generated from the launch manifest.
2. Cockpit serve: **tiny Python controller** (§6c) — serves static page +
   the two API routes; not bare `http.server`, not Caddy.
3. Terminal panel: **on-demand iframe** per open card (no always-on
   connections; no custom xterm.js WebSocket client in v1).
4. `window-size latest`: **NOT set fleet-wide** — current tmux default
   already sizes to latest client; no override shipped.
5. P2 embed: **local page is the permanent answer** — Chrome moved from PNA
   preflights to the Local Network Access permission model; do not chase
   PNA headers on ttyd.
6. Pilot: **B3, then Brisen Desk, sequentially** — only then fleet
   migration in registry order (§6a).

## 12. Rollback

Single script: restore original Terminal-profile commands, `launchctl unload`
cockpit plists, remove Application Support workers. tmux/ttyd binaries may
stay (inert). Sessions relaunch exactly as today.
