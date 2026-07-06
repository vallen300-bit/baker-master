# COWORK_BB_DESK_INSTALL_1 — Director-facing talk seat for Baden-Baden Desk (cowork pattern)

**Dispatched:** 2026-07-06 · **Owner:** b2 · **Requester:** lead · **Director-ratified:** 2026-07-06 ("y" on cowork-bb-desk build)

## Context Contract

- **Problem.** Baden-Baden Desk now runs autonomously on the Mac Mini (sole execution seat, wake-spawned, §0 unattended standing-auth rule live since 2026-07-06). Director ALSO needs to talk to BB Desk interactively from his laptop (questions, decisions, discussion) — but a second executing seat recreates the duplicate-seat pile-up we just cleaned (4 stale seats, escalation #5700).
- **Ratified design.** Copy the cowork-ah1 ↔ lead pattern: laptop Claude-app window = `cowork-bb-desk`, a TALK-ONLY seat. It converses with Director, reads shared vault state, and relays execution instructions to `baden-baden-desk` via bus. It NEVER executes desk work (no ticket check-ins, no curated writes, no dashboard edits, no ClickUp/email).
- **Authority split.** Mini terminal seat (`baden-baden-desk`) = sole writer/executor. `cowork-bb-desk` = Director eyeline + relay. Both read the same Dropbox-synced vault; only the Mini seat writes.
- **Prior art to mirror (MANDATORY investigation step).** Examine exactly how `cowork-ah1` gets its identity when Director opens the picker folder in the Claude desktop app vs the terminal seat getting `lead` (SessionStart role hook? worktree-path detection? separate folder?). Mirror that mechanism 1:1 — do not invent a new one. If cowork-ah1 uses a distinct folder or a Cowork-spawn detection branch, replicate for bm-baden-baden-desk.
- **Wiring registry.** Install per `~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md` (registry-driven since MOVIE Desk install 2026-06-27) + `install-agent-to-brisen-lab` skill. Enumerate ALL 12 rows in your ship report; mark `Row N: N/A — <reason>` explicitly, never silently omit.
  - Expected N/A candidates (verify, don't assume): Row 2 shell alias (app seat, not terminal), Row 3 Terminal.app profile (app seat), Row 12 snapshot-pusher TERMINALS (talk seat may not need a Lab card — see Open Question 1).
- **Open questions for lead (post to bus BEFORE building if answer changes scope):**
  1. Does `cowork-bb-desk` get its own Brisen Lab card, or ride without one (cowork-ah1 precedent — check whether cowork-ah1 has a card slot; mirror).
  2. Wake wiring: talk seat should NOT be wake-spawned (Director opens it manually). Confirm it is excluded from wake-listener alias maps and host-affinity desk set (brisen-lab PR #100 set).

## Task class

Feature install (multi-repo wiring), Tier A execution against a Director-ratified design. No Cortex Design changes. No migrations.

## Constraints

- Talk-only orientation is a HARD boundary — write it into the seat's role-context/orientation file with an explicit banned-actions list (execute desk work, write curated, check in tickets, send external anything).
- Do NOT touch the Mini seat's wiring, the §0 SKILL.md rule, or wake-listener desk affinity except to EXCLUDE cowork-bb-desk from wakes.
- Bus key: new 1P item `BRISEN_LAB_TERMINAL_KEY_cowork-bb-desk` + Render `BRISEN_LAB_TERMINAL_KEYS` update + explicit POST /deploys (SOP foot-gun).
- Three-repo PR order: baker-vault (orientation docs) → baker-master (bus_post whitelists + drain hook) → brisen-lab (server slug lists + tests, if card ratified).

## Done rubric (all must hold)

1. Director opens the folder in Claude app on laptop → seat identifies as `cowork-bb-desk`, loads talk-only orientation, confirms with evidence-bound phrase.
2. `cowork-bb-desk` can bus-post to `baden-baden-desk` + `lead` and receives bus replies via drain.
3. Mini terminal seat still identifies as `baden-baden-desk` — zero identity bleed (test both same day).
4. cowork-bb-desk receives NO wake dispatches (check wake-listener log after a desk wake).
5. 12-row map enumerated in ship report, each row done or N/A-with-reason.
6. Live round-trip demo: Director-style prompt in app seat → relay bus post → Mini seat acks. Screenshot/transcript evidence.

## Gate plan

codex G3 on each PR (recommended effort: medium — additive wiring, proven pattern). Lead merges. Post-install live round-trip = acceptance gate; post POST_DEPLOY_AC_VERDICT to lead per post-deploy-ac-bus-gate convention.

## Lessons pointers

- HAGENAUER_DESK_ON_BUS_1 partial-install trap (3 hardcoded slug lists) — the reason the 12-row map exists.
- Row-2 launcher key-injection foot-gun (MOVIE Desk install).
- Render env PUT alone doesn't restart — POST /deploys explicitly.
