---
brief_id: BRISEN_LAB_REDESIGN_PHASE_1
title: Dashboard layout + badge + matter-zone redesign
status: COMPLETE
completed_at: 2026-05-24T15:37:07Z
pr_url: https://github.com/vallen300-bit/brisen-lab/pull/33
pr_number: 33
ship_report: briefs/_reports/B1_BRISEN_LAB_REDESIGN_PHASE_1_20260524.md
bus_ship_post: 903
authored_by: cowork-ah1
dispatched_by: lead
dispatched_at: 2026-05-24T15:25:00Z
ratified_by: Director (chat 2026-05-24 Steps 1-5)
target: b1
target_repo: brisen-lab
brief_path: ~/baker-vault/_ops/briefs/BRIEF_BRISEN_LAB_REDESIGN_PHASE_1.md
estimated_time: ~10-14h
complexity: Medium
priority: HIGH
prerequisites: HAG_WORKERS_PHASE_1 (merged; CM-1..4 + hag-filer slugs now registered)
reply_to: lead
prior_mailbox_state: superseded — HAG_WORKERS_PHASE_1 COMPLETE (merged 13:50-13:51Z)
---

# CODE_1_PENDING — BRISEN_LAB_REDESIGN_PHASE_1

**Read the full brief first:** `~/baker-vault/_ops/briefs/BRIEF_BRISEN_LAB_REDESIGN_PHASE_1.md` (authored by cowork-ah1, Director-ratified 2026-05-24 chat Steps 1-5).

## TL;DR
Redesign brisen-lab dashboard. 5 features in scope:
1. Two-zone layout (Fleet vs Matter Desks) with zone headers
2. Five card types with sizing system (replace current 4-class flat)
3. Unread badge redesign — circle + age-based colors + count + tooltip (replaces "small blue letters")
4. Browser tab title + favicon dot for unread totals
5. Matter panel structure — Hagenauer first as anchor; other matters (MOVIE/AO/Baden-Baden/Brisen/Origination) as faded placeholders

## Critical — reconcile with my hot-fix landed just before this dispatch
I landed 2 hot-fix commits to brisen-lab today AFTER HAG_WORKERS merged but BEFORE this redesign dispatch:
- `c733b0b` — static/app.js TERMINALS array + LABELS dict added CM-1..4 + hag-filer
- `486b2dd` — static/index.html added `row-fleet` div with 5 `<article>` scaffolds

Both hot-fixes are the minimum to make cards render at all. The redesign **supersedes** the `row-fleet` row structure entirely — replace with the proper `row-cm-pool` inside `zone-fleet` per brief Step 1.1. The TERMINALS array + LABELS dict additions stay (still needed for renderCard()).

## Repos touched (1)
brisen-lab only (no baker-master, no baker-vault).

## Ship gate
- Literal HTML grep + visual smoke (new AC12 amendment): `curl https://brisen-lab.onrender.com/ | grep -E "zone-fleet|zone-matter|row-cm-pool|matter-panel|matter-hagenauer"` returns the expected DOM markers
- Existing playwright/visual tests if present
- Cache-bust `?v=N` on every static asset reference in index.html (brief Step 1.2 specifies v8→v9)
- Singletons + syntax checks per repo defaults

## Bus-post on ship
Post to lead with:
- 1 PR number + URL
- HTML grep output (zone + row + matter-panel selectors present)
- Cache-bust confirmation (v=N bumped on all static refs)
- Director-visible smoke note: "ready for Director hard-refresh"

## Dispatch lane choice
b1 — free post HAG_WORKERS merge. brisen-lab repo work, no overlap with b2 (b2 just shipped classifier-tighten in baker-master).

End mailbox.
