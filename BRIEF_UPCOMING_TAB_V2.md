# Brief: UPCOMING-TAB-V2 — Matter Grouping + Action Buttons

**Author:** Code 300 (Session 16)
**For:** Code Brisen
**Priority:** HIGH — Director is actively using dashboard

---

## Context

The dashboard now has two main tabs:
1. **Dashboard** — T1 alerts (max 5/day) + stats + Haiku narrative
2. **Upcoming** — T2/T3/T4 alerts grouped by matter

The Upcoming tab currently works (shows T2+ grouped by `matter_slug`) but has three problems:

## Problem 1: Matter Auto-Assignment Broken (99% ungrouped)

160 of 161 alerts have `matter_slug = NULL` → all land in "Ungrouped". The matter auto-assignment in `orchestrator/pipeline.py` (`_match_matter_slug()`) uses keyword matching but it's too weak.

**Fix needed:** Improve `_match_matter_slug()` to match more alerts to matters. There are 17 active matters in `matter_registry`. The function should:
1. Check alert title + body against matter keywords
2. Check contact names against matter `connected_people`
3. Use case-insensitive partial matching
4. Consider adding a Haiku-based fallback for ambiguous cases

**Also:** Retroactively assign matter_slugs to existing pending alerts. Write an endpoint like `POST /api/alerts/reassign-matters` that re-runs `_match_matter_slug()` on all pending alerts with `matter_slug IS NULL`.

**Files:** `orchestrator/pipeline.py` (search for `_match_matter_slug`)

## Problem 2: Dot Colors in Sidebar

The sidebar matter sub-list should use colored dots:
- **Red dot** — matter has T2 alerts (important, needs attention soon)
- **Grey dot** — matter has only T3/T4 alerts (routine, informational)

Currently the dots don't differentiate. The `loadMattersSummary()` function in `app.js` populates the sidebar list. It already gets `worst_tier` from the API (`GET /api/dashboard/matters-summary`).

**Fix:** In `loadMattersSummary()`, set dot class based on `worst_tier`:
- `worst_tier <= 2` → red dot
- `worst_tier >= 3` → grey/slate dot

**Files:** `outputs/static/app.js` (search for `loadMattersSummary`)

## Problem 3: Action Buttons on All Alerts

Currently only T1/T2 alerts get `structured_actions` (Plan/Analyze/Draft/Specialist buttons). T3 alerts show as plain cards with no actions.

**Fix:** In `orchestrator/pipeline.py`, the `_generate_structured_actions()` call is gated on `tier <= 2`. Change to `tier <= 3` to include T3 alerts.

**Files:** `orchestrator/pipeline.py` (search for `structured_actions` or `_generate_structured_actions`)

## Verification

After implementing:
1. `GET /api/dashboard/matters-summary` — matters should show `worst_tier` values
2. Click Upcoming tab — alerts should be grouped under named matters, not all in "Ungrouped"
3. Sidebar dots should be red for urgent matters, grey for routine
4. T3 alerts should have action buttons (Plan/Analyze/Draft)

## Rules

- Do NOT modify the Dashboard tab (T1 section) — only Upcoming
- Do NOT change the T1 daily cap logic in `store_back.py`
- All text rendering must use `esc()` or `md()` — no raw innerHTML
- Test that `min_tier=2` filter on `/api/alerts` correctly excludes T1s
