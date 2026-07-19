# FLEET COCKPIT REVAMP — Director-ratified spec (2026-07-19 walkthrough)

Source: live Director walkthrough with lead (AH1), 2026-07-19 ~08:30–12:00Z.
Every item below is Director-ratified verbatim ruling or explicitly adopted
recommendation. Build target: `scripts/cockpit_static/` + `scripts/cockpit_controller.py`
(baker-master), local deploy via App-Support re-sync. No brisen-lab changes in
this round. Successor session: split into per-item briefs, dispatch, merge.

## 1 — Context bars on every card

- Controller reads local band files DIRECTLY (`~/forge-agent/context-band/`,
  per-session json + `<alias>.current` symlinks) — no Lab round-trip, no
  staleness nulling. Lab value stays as fallback only.
- Always render last-known %; DIMMED when stale, with age shown (Director:
  "show stale bars dimmed rather than hiding them").
- Meter hook install on 15 missing pickers DONE 2026-07-19 (5 desks, ben, aid,
  researcher, russo-ai, clerk, librarian, CM-1..4; smoke-tested fail-safe;
  bands appear after each seat's next completed turn).
- Codex-family seats (codex, codex-arch, deputy-codex): no Claude hooks —
  controller parses the seat's own tmux pane status line ("Context N% used")
  for context %, AND uses pane/process activity for is_working (fixes falsely
  "idle" Codex seats — Director flagged CT & Verification plate).

## 2 — Copy button on open-terminal drawer

- The unacked list inside the opened terminal view gets the same Copy control
  as the card message panel / Lab drawer (`doMsgCopy` wiring).

## 3 — State colors (FINAL palette, Director-ratified; supersedes all earlier proposals)

- running — bright green.
- GO waiting for Director — bright blue, PULSATING.
- idle / plain no-signal / not-started — muted grey.
- unread 0–10 min — muted amber (from second zero; Director explicitly rejected
  a neutral sub-2-min window: "sometimes I don't have two minutes").
- unread > 10 min — bright red.
- no-signal + offline combined — muted red, PULSATING.
- everything else — muted grey.
- Agent NAME takes the same color as its chip (slightly softer intensity OK).
- Cockpit deliberately diverges from Lab colors; Lab untouched this round —
  revisit fleet-wide alignment after a week of living with it.

## 4 — True split view (replaces modal + blur)

- Left sidebar | middle live grid | right terminal pane.
- Grid stays live, unblurred, clickable while a terminal is open.
- Clicking another card switches the right pane. Esc / X closes.
- Keystrokes reach the terminal only when cursor is in it.

## 5 — Left sidebar navigation (supersedes top-tab ruling same day)

- Entries: ACTIVE (default home) · ALL · Pilots · Control Tower · Engineering ·
  Support · Legal/Finance · Interns (mirror layout plate labels in plain words).
- ACTIVE view = all non-grey seats + one collapsed count line per group for
  grey seats (click to expand).
- Red alert badge on a group entry when any of its seats needs attention while
  you're in another view.
- View choice persisted across sessions. Narrow screens: sidebar collapses to
  icons, expands on hover. Sidebar reserved for future buttons — add NOTHING
  else now (candidates parked: bus health, brief queue, kill switches, Lab link).

## 6 — Header rework

- Title: `FLEET COCKPIT` — all capitals.
- Oversized digit block REMOVED.
- Top-right stays: `live · N driveable / M seats` — ALL words bright green,
  current small size (green = healthy heartbeat; turns red only when the feed
  is stale/dead). NOTE: supersedes the earlier same-day "relocate under title +
  mute grey" rulings — this is the final form.
- Relabel jargon to plain words at build time ("agents / with terminal /
  attention" direction ratified).
- Bell (notify-mute toggle) REMOVED from header. Banners stay ON;
  `COCKPIT_NOTIFY_ENABLED` env kill switch remains for engineers.
- Freed top-right/corner space: reserved, empty. Future tenant candidate:
  fleet cost today (parked).

## 7 — Standing design rule: QUIET WHEN HEALTHY

- Color is an attention budget. Healthy elements are colorless/muted; color
  appears only for states needing Director's eyes — single exception: the one
  green health line (item 6). Apply to every future cockpit element by default.

## 8 — Task-history tab (Rescale borrow, adopted)

- New view listing dispatches/briefs as job rows: status tick, seat, topic,
  duration, created, outcome. Cockpit today shows only live state; this adds
  receipts/history. Data source: bus + briefs/_tasks + gate verdicts (design
  at brief time; likely controller aggregation, no Lab change).

## 9 — Gate verdicts as pass/fail cards (Rescale borrow, adopted)

- Render gate verdicts (codex PASS/FAIL, post-deploy AC) as scannable
  green-pass / red-fail cards in the history view — not raw bus text.

## Parked (explicitly NOT this round)

- Fleet cost counter in header; per-card "send task" box; docked
  "ask an agent" command box (revisit after items 1–9 ship and split view
  proves itself); Lab color alignment.

## Related in-flight (NOT part of this spec, merge separately)

- COCKPIT_MSG_PANEL_BODY_PREVIEW_1 @588d5d06 — codex gate #13207 pending, then
  lead merges + re-syncs App Support staging.
- WAKE_RESPAWN_BACKLOG_DRAIN_1 baker @b2380d1b + lab @1038018 — delta re-gate
  #13180 pending; lab deploy waits on Render Frankfurt incident.
- SWEEP_TIMING_ACTIVE_WORK_GUARD_1 — deputy brief at
  ~/bm-aihead2/briefs/SWEEP_TIMING_ACTIVE_WORK_GUARD_1.md; build green-lit
  (#13208), deputy-codex builds, deputy reviews, codex gates. ~10 SIGKILLs/day
  of working seats — high priority.
- ARM housekeeping grant — cowork-ah1 amendment V2 in codex-arch G0
  (#13198); after install ARM self-serves archive restores (Director-GO-cited)
  + dead-symlink removal.

## NEXT WEEK (Director directive, not started)

**Brisen Lab dashboard unification** — one style/colors/logic across the whole
Lab hosting dashboard: templates gallery, token burns, loops, bus hails,
delivery hails, etc. "One big website." Cockpit revamp style becomes the
reference register. Schedule after cockpit revamp ships.
