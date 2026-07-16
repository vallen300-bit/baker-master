# SCOPE_LAB_TERMINAL_COCKPIT_1 — In-Lab Live-Terminal Cockpit

- **Status:** DRAFT v1.1 — recut after codex-arch G0 FAIL (#12017); awaiting re-G0, then Director build ratification
- **Author:** cowork-ah1 · 2026-07-16 · v1.1 recut by lead (cowork-ah1 seat overloaded, Director handoff 2026-07-16 evening)
- **Reviewer:** codex-arch (cross-vendor design pass)
- **Type:** Scope / design document. NOT a build brief. Build briefs are cut from this after G0 PASS.
- **v1.1 delta:** three dispatch-blocker contracts added (§6a Migration, §6b Launch manifest, §6c Controller + auth) per codex-arch #12017; §11 open questions resolved with codex-arch picks; R3 auth claim corrected.

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

## 5. Target UX

1. Grid of cards grouped exactly like the Lab fleet page (Orchestrators /
   Builders / Desks / Specialists), order fixed by registry sequence — B1–B4
   always adjacent, always same slots.
2. Card face: agent_id, display_name, slug, live/idle dot, "session up/down".
3. Click card → terminal panel opens in-page (modal or right split), full
   xterm rendering, keyboard focus, scrollback. Esc/✕ → back to grid.
4. The native Terminal.app window for the same agent keeps working — both
   views attach to one shared session (tmux), nothing is lost either way.
5. Dark register, Lab visual tokens (card bevel, AG-badge, section headers).

## 6. Architecture

**Stack: tmux (session host) + ttyd (web terminal, xterm.js) + static local
cockpit page + launchd (persistence). All OSS, zero licence cost.**

1. **tmux layer** — every terminal-claude agent launches inside
   `tmux new-session -A -s <slug> '<existing launch cmd>'`. Terminal profiles
   change their command to exactly that (one-time migration, scripted).
   `-A` = attach-if-exists, so double-launch is safe.
2. **fleet launcher** — `scripts/fleet_terminals.sh up|open <slug>|status`:
   reads the registry, creates missing tmux sessions in registry order,
   `open <slug>` opens a Terminal window attached to that session.
3. **ttyd layer** — one ttyd per agent: `ttyd -W -p <port> -i 127.0.0.1
   [-c auth] tmux attach -t <slug>`. Port = 7600 + registry index (map
   generated from registry — no hand-kept list; HAGENAUER_DESK_ON_BUS_1
   hardcoded-list trap is the anti-pattern). Managed by one launchd agent
   (`com.baker.cockpit-ttyd`) supervising all instances, or one plist per
   agent — build decides; installer mirrors `install_forge_push.sh`.
4. **Cockpit page** — static HTML/JS served by a tiny local server (or the
   ttyd `--base-path` trick / one extra ttyd serving static). Renders cards
   from a registry-generated JSON (build step, same generator family as
   `agent_identity_generated.sh`). Card click → iframe to
   `http://127.0.0.1:<port>` for that agent.
5. **Design source** — reuse the Lab's locked card design language; extract
   CSS tokens from the live Lab page / canonical mockup at build time. The
   Cockpit must be visually indistinguishable from a Lab page.

## 6a. Migration contract (G0 blocker 1 — codex-arch #12017)

Running agents CANNOT be adopted by tmux; a naive `fleet up` while old
windows live would create duplicate seats. Migration is therefore a per-seat
five-step state machine, never a fleet-wide switch:

1. **Checkpoint** — seat writes/refreshes its checkpoint per the existing
   context-band rollover discipline (`briefs/_checkpoints/` for workers, PINNED
   for binding seats); for idle seats a lightweight "migration pin" suffices.
2. **Stop old seat** — clean exit of the existing session (same path as the
   daemon refresh cadence / Terminal Cmd+Q refresh); never kill mid-write.
3. **Create tmux seat** — relaunch via the launch manifest (§6b) inside
   `tmux new-session -A -s <slug>`.
4. **Smoke both viewers** — native Terminal attach AND ttyd web attach must
   both render + accept keystrokes before the seat counts as migrated.
5. **Mark migrated** — recorded in a generated migration ledger
   (`fleet_terminals.sh status` shows migrated/pending per seat); `up` only
   creates sessions for seats marked migrated, so unmigrated seats are never
   double-launched.

Order: pilot B3 → Brisen Desk (sequential, per codex-arch pick) → rest of
fleet in registry order. Rollback per seat = §12 script restores the
direct-launch profile for that seat only.

## 6b. Launch manifest contract (G0 blocker 2 — codex-arch #12017)

The agent registry has NO `cwd` or launch command, and live Terminal profiles
call materially different zsh functions — so the tmux wrapper cannot be
derived from the registry alone. Build adds a **generated launch manifest**
(same generator family as `agent_identity_generated.sh`):

- Per seat: `slug`, `cwd`, `launch_cmd` (the exact command the current
  profile runs), `port` (7600 + registry index), `eligible` flag.
- **Eligibility rule:** `status: active` AND `runtime` starts with
  `terminal-` (prefix match, NOT exact `terminal-claude` — per codex-arch).
- Manifest is regenerated from registry + profile sources at install time;
  hand-editing it is forbidden (HAGENAUER hardcoded-list trap).
- `fleet_terminals.sh` and the ttyd installer consume ONLY the manifest.

## 6c. Controller + auth contract (G0 blocker 3 — codex-arch #12017)

A static HTML page cannot supply live session state or a Start action. v1
ships a **tiny Python controller** (codex-arch pick; not bare `http.server`,
not Caddy) bound to 127.0.0.1 under launchd:

- `GET /api/agents` — card list + live session state (manifest + `tmux ls`).
- `POST /api/sessions/{slug}/start` — allowlisted to manifest slugs only;
  starts the tmux session via the launch manifest. No other verbs in v1
  (no stop/kill from the page in v1 — native window or CLI remains the path).
- Controller also serves the static cockpit page (one process, one port).
- **Auth decision:** ttyd `-c` is HTTP **Basic auth**, not token auth (R3
  corrected). v1: all listeners 127.0.0.1-only (threat = local user = Director,
  same machine/user as the `--dangerously-skip-permissions`-class sessions —
  no widening), plus one shared Basic-auth credential on ttyd + controller
  stored 0600 in `~/Library/Application Support/baker/cockpit/`; browser
  caches it per-origin so the Director types it once per session. Origin
  enforcement: controller rejects requests whose `Origin`/`Host` is not
  `127.0.0.1:<cockpit-port>`.

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

**P1 — MVP (2 build briefs):**
- BRIEF A `FLEET_TMUX_LAUNCH_1`: brew install tmux+ttyd; launch-manifest
  generator (§6b); fleet_terminals.sh + migration ledger; per-seat migration
  state machine + rollback (§6a); per-agent ttyd plist generator + installer.
- BRIEF B `LAB_COCKPIT_PAGE_1`: Python controller + API (§6c); cockpit page
  (manifest-driven grid, Lab CSS, on-demand iframe panel); Basic-auth +
  origin enforcement; runbook + how-to entry.

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
- **R2 tmux two-viewer sizing:** smallest client wins by default →
  `set -g window-size latest`; documented quirk.
- **R3 Writable terminal on localhost:** 127.0.0.1 bind + ttyd Basic auth
  (`-c` — NOT token auth; corrected v1.1, see §6c);
  never tunneled/port-forwarded; threat = local user only (= Director).
  These sessions run `--dangerously-skip-permissions`-class agents — the
  cockpit must not widen who can reach them (it doesn't: same machine, same
  user).
- **R4 Launch migration breaks a seat:** migration is per-profile + scripted
  + reversible (AC 6); pilot on B3 first, then fleet.
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
