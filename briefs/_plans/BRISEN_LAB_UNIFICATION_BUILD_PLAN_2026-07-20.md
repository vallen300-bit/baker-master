# Brisen Lab unification — BUILD PLAN (for Director sign-off)

Author: lead (AH1), 2026-07-20 evening.
Source spec: `briefs/_plans/BRISEN_LAB_UNIFICATION_RATIFIED_LAYOUT_2026-07-20.md`
(Director-ratified layout: 6-entry sidebar, ACTIVE landing, 3 phases).
Gate: Director signs off on THIS plan before any implementation brief dispatches.

## Bottom line

One address — the Lab website — gets the new 6-entry sidebar. The cockpit you
use today slots in unchanged as the AGENTS section (it already has the ratified
sub-views: ACTIVE, ALL, Control Tower, Pilots, Engineering, Support,
Legal/Finance, Interns, History). Everything else folds in around it in three
phases. Old pages stay reachable until each is absorbed; no data or machine
feed is touched.

## Where it lives (lead's technical call — no decision needed)

- The unified shell is built in the Lab cloud site (brisen-lab.onrender.com) —
  always on, works from any device, one URL.
- AGENTS = the existing cockpit, embedded through the already-proven bridge.
  The cockpit code just shipped 9/9 and is NOT rebuilt — lowest risk.
- While the new shell is being built it lives at a side door (`/v2`). The old
  Lab front page stays the default until you look at the new one and say
  "switch". Then `/v2` becomes the front page and old pages retire
  section-by-section (per the ratified drop list).

## Phase 1 — Shell + AGENTS + links + Settings & Logs skeleton

What you will see when Phase 1 ships:

1. New sidebar with all 6 entries; landing view = AGENTS → ACTIVE
   (quiet-when-healthy).
2. AGENTS: the live cockpit, exactly as today, inside the new frame.
3. BAKER DASHBOARD and ARRIVALS BOARD: link entries that open the existing
   sites (engines stay separate, as ratified).
4. SETTINGS & LOGS skeleton with three tabs:
   - Token burn — the burn numbers surfaced in the shell (feed exists today,
     page was local-only; this puts it where you can see it).
   - Maintenance — deploy/controller/watchdog status in one place.
   - History — the cockpit's job-history + verdict cards, reused.
5. LOOPS and SKILLS entries present but marked "coming Phase 3 / Phase 2".

Build shape: 2 briefs (shell+sidebar+embed; Settings & Logs skeleton).
Codex gate + live AC each, per standing ship discipline.

## Phase 2 — SKILLS catalog

1. Browsable catalog in your ratified groups: Business (Financial / Legal /
   Analytical / Communication…), Docs Writing, Research, Sources Ingestion,
   Technical, Design, Publishing.
2. Columns per skill: full description · source · location · templates-gallery
   links (HTML samples open in place) · which agents have it.
3. Feed: the fleet skill registry (135 skills, ARM-maintained markdown master)
   + the deterministic HTML generator committed today (vault @4bc37c2). The
   catalog updates whenever ARM updates the master — no hand-rebuilds.
4. Your Phase-2 groups need a fresh grouping pass (today's registry groups are
   engineering-oriented, not your Business/Docs/Research cut). Lead does the
   grouping, you eyeball the result in the page itself — no separate approval
   round needed unless you want one.

Build shape: 1 brief + the grouping data file. Old templates-gallery page
retires here (its content becomes the catalog's template links).

## Phase 3 — LOOPS as first-class entities

1. LOOPS entry with two named loops: Research Loop (today "Villa Gabbiano")
   and Airport Loop (today "Aukera financing").
2. Each loop page: interactive diagram + description on one page — agents
   involved, the prompt, the output. Research Loop diagram first; Airport
   diagram later, per your workbook note.
3. Existing loop pages absorbed; old loops page retires.

Build shape: 1-2 briefs (loop page frame; diagrams).

## What retires, what stays

- Retire as pages (after absorption, per ratified LAYOUT verdicts): templates
  gallery, token burns, loops page, bus hails, delivery hails, wake health,
  Production & Lab split.
- Stay untouched: every machine feed and endpoint behind those pages; Baker
  dashboard engine; Arrivals engine; the cockpit's controller on your laptop;
  bus, wake, and telemetry plumbing.
- Bus-health / delivery-health / wake-health numbers stay reachable for agents
  and diagnostics (they are API feeds); their standalone pages fold into
  Settings & Logs → Maintenance.

## Order, discipline, safety

- Sequence: Phase 1 → 2 → 3; each phase = formal briefs (no mailbox-only
  dispatches), codex gate, live AC, registry-style status page updated at
  every state change (same discipline as the cockpit revamp).
- One-step rollback at all times: old front page remains until your "switch"
  ruling; after the switch, old pages stay at legacy URLs until their
  replacement section is accepted.
- Nothing in this plan touches baker-master production or matter data.

## What I need from you

Sign off on this plan (or mark changes). After sign-off I brief Phase 1
immediately; Phases 2-3 brief as each prior phase goes live.
