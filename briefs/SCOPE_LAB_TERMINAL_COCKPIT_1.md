# SCOPE_LAB_TERMINAL_COCKPIT_1 — In-Lab Live-Terminal Cockpit

- **Status:** DRAFT — awaiting codex design review (G0), then Director build ratification
- **Author:** cowork-ah1 · 2026-07-16
- **Reviewer:** codex (cross-vendor design pass — Director will relay)
- **Type:** Scope / design document. NOT a build brief. Build briefs are cut from this after G0 PASS.

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
- BRIEF A `FLEET_TMUX_LAUNCH_1`: brew install tmux+ttyd; fleet_terminals.sh;
  Terminal-profile migration script + rollback; launchd installer; port-map
  generator from registry.
- BRIEF B `LAB_COCKPIT_PAGE_1`: cockpit page (registry-driven grid, Lab CSS,
  iframe terminal panel); local serve; runbook + how-to entry.

AC (all must pass, live, not compile-clean — Lesson #8):
1. `fleet_terminals.sh up` creates all 26 sessions in registry order;
   rerun is a no-op.
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
- **R3 Writable terminal on localhost:** 127.0.0.1 bind + ttyd token auth;
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

## 11. Open questions for codex

1. One launchd-supervised ttyd *per agent* (26 procs) vs single supervisor
   script spawning all — which is cleaner under launchd KeepAlive?
2. Cockpit static serve: piggyback a ttyd instance vs tiny Python
   `http.server` under launchd vs Caddy — preference?
3. iframe-per-terminal vs single xterm.js client speaking ttyd's WebSocket
   directly (tighter UX, more build)?
4. Any objection to `window-size latest` fleet-wide?
5. P2 embed path: worth attempting PNA headers on ttyd, or lock the local
   page as the permanent answer?
6. Pilot scope: B3 only, or B3+one desk before fleet migration?

## 12. Rollback

Single script: restore original Terminal-profile commands, `launchctl unload`
cockpit plists, remove Application Support workers. tmux/ttyd binaries may
stay (inert). Sessions relaunch exactly as today.
