---
brief_id: BRISEN_LAB_REDESIGN_PHASE_1
reporter: b1
dispatched_by: cowork-ah1
status: COMPLETE
pr_url: https://github.com/vallen300-bit/brisen-lab/pull/33
pr_number: 33
branch: b1/brisen-lab-redesign-phase-1
commit: 837d727
bus_post_id: 903
bus_topic: ship/brisen-lab-redesign-phase-1
target_repo: brisen-lab
shipped_at: 2026-05-24T15:37:07Z
---

# B1 ship report — BRISEN_LAB_REDESIGN_PHASE_1

Dashboard redesign per Director ratification 2026-05-24 chat Steps 1-5.

## What shipped (5 features)

1. **Two-zone DOM** (`static/index.html`). `<section class="zone zone-fleet">` wraps supervisors / workers / cm-pool / system rows. `<section class="zone zone-matter">` wraps per-matter panels.
2. **Five card types** (`static/styles.css` + `static/app.js`). `CARD_TYPE` map routes each slug to `card-supervisor` | `card-worker` | `card-system` | `card-matter-desk` | `card-shared-specialist`. Supervisor cards trimmed (min-height 110px, was 180px).
3. **Corner unread badge** (`static/styles.css` + `static/app.js`). 24px circle top-right via `renderUnreadBadge()`. Color escalation blue → amber > 10min → red > 30min. Pulse first 30s. Tooltip from `unacked_topics`. Legacy inline badge replaced.
4. **Tab title + favicon dot** (`static/app.js`). `updateDocumentTitle(total)` shows `Brisen Lab (N unread)` / `Brisen Lab`. `updateFavicon(total)` canvas-composites a red dot. Module-level `_lastUnreadTotal` cache prevents redundant redraws.
5. **Matter panels** (`static/index.html` + `static/styles.css`). Hagenauer (warm-tan dark tint) holds `hag-desk` + `hag-filer`. Faded placeholders for MOVIE / AO / Baden-Baden / Brisen / Origination. Shared panel for the researcher.

## Cache-bust

- `styles.css?v=11` → `v=12`
- `app.js?v=13` → `v=14`

## Reconciliation with hot-fix commits

Brief flagged: AH1 landed `c733b0b` (TERMINALS array + LABELS dict) and `486b2dd` (`row-fleet` div with 5 `<article>` scaffolds) just before dispatch. Resolution:
- TERMINALS + TERMINAL_LABELS additions **retained** (still needed for renderCard discovery).
- `row-fleet` div **superseded** by `row-cm-pool` inside `<section class="zone zone-fleet">` per brief Step 1.1.

## Verification

- `node -c static/app.js` — syntax OK.
- `pytest tests/ -x -q` — 134 skipped (DB-gated; no Python touched).
- Local DOM grep `zone-fleet | zone-matter | row-cm-pool | matter-panel | matter-hagenauer` — 10 matches in `static/index.html`.
- Post-deploy verification deferred to Render auto-deploy + Director hard-refresh.

## PR + bus

- PR: https://github.com/vallen300-bit/brisen-lab/pull/33
- Bus ship-post: #903 → cowork-ah1 (topic `ship/brisen-lab-redesign-phase-1`).
- Dispatch ack: bus #900 acked at session start.

## Step 6 status

Deferred at Director's request per brief — interactivity work scoped out of Phase 1.

## Next

Awaiting cross-lane review (AH2) + cowork-ah1 merge gate.
