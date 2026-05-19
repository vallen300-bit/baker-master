---
status: PENDING
brief_id: DASHBOARD_CORTEX_TAB_HITBOX_FIX_1
brief_inline: yes (see body — hot-fix, no separate brief file)
target_repo: baker-master
working_dir: ~/bm-b1
matter_slug: baker-internal
cross_matter_usage: [all-matters] (Director-facing dashboard ratify panel hit area broken)
dispatched_at: 2026-05-19T13:30:00Z
dispatched_by: lead
director_auth: 2026-05-19 chat — Director surfaced bug during prod smoke ("I cannot click on it. Nothing hovers over it.") + AH1 root-caused via Chrome MCP; hot-fix dispatch implicit
trigger_class: LOW (CSS-only, no auth/DB/external surface, fixes Director-blocking UI bug)
estimated_effort: 5-10 min
working_branch_suggestion: b1/cortex-tab-hitbox-fix-1
reply_target: lead (bus topic `ship/cortex-tab-hitbox-fix-1`)
prior_dispatch_closeout: |
  BRISEN_LAB_PR22_BUTTON_REPOINT_1 merged 2026-05-19 — brisen-lab squash commit 0afb432.
  PR #24 closed. Mailbox flipped COMPLETE; this hot-fix overwrites for next dispatch.
---

# CODE_1_PENDING — DASHBOARD_CORTEX_TAB_HITBOX_FIX_1 — 2026-05-19 (HOT-FIX)

## Problem (Director-blocking)

The Cortex card tab buttons (Events / Dedup / Lint / Pending) are not clickable in production. `document.elementFromPoint()` at the center of `#cortexTabPending` returns `#cortexCount` (the count text span), not the button. The cortexCount span is rendered ON TOP of the tab buttons, intercepting all clicks.

**Diagnostic (verified live via Chrome MCP at 13:25Z):**

```
Button rect:       top=338, left=1270, width=62, height=20
Element at center: <span id="cortexCount">  ← NOT the button
Button visible:    true
Button onclick:    "_cortexTab('pending')"
fnExists:          true
```

The JS click handler is correctly wired — the button just isn't reachable by mouse because the count span overlaps it.

## Root cause hypothesis

`.cortex-tabs` flex container + `.grid-cell-count` (the count span) share the same parent (`.grid-cell-header grid-header-cortex` at `outputs/static/index.html:230-238`). Adding the 4th tab (Pending) + the longer count string ("30 events, 20 lint, 18 pending" vs prior "30 events") caused layout overflow. The count span is likely positioned absolute or has insufficient flex-shrink, growing leftward across the tab bar.

## Scope — CSS-only

Patch `outputs/static/style.css` to ensure `.cortex-tabs` and `.grid-cell-count` don't overlap. Likely fixes (B1 picks the cleanest):

1. Add `flex-shrink: 0` to `.cortex-tabs` so it doesn't compress under count-span pressure;
2. Add `flex-shrink: 1` + `text-align: right` + `min-width: 0` to `.grid-cell-count` to make it shrink properly;
3. Or restructure parent `.grid-cell-header.grid-header-cortex` with explicit `gap` + `justify-content: space-between` so the three sections (label / tabs / count) have stable boundaries.

Verify the fix with `document.elementFromPoint(rect.left + rect.width/2, rect.top + rect.height/2) === document.getElementById('cortexTabPending')` for all 4 tab buttons.

## Ship gate (literal)

1. `pytest tests/test_dashboard*.py -v` — confirm no regressions.
2. **Mandatory `elementFromPoint` verification:** in B1's local browser (or via Chrome MCP), confirm all 4 tab buttons return themselves as `elementFromPoint` at button center. Include the JS snippet output in ship report. This is the click-path test the original brief should have demanded.
3. Cache-bust app.js OR style.css version bump.

## Reporting

- Bus-post `ship/cortex-tab-hitbox-fix-1` to `lead`.
- Heartbeat unnecessary for sub-10-min hot-fix.

## Surface contract: N/A — CSS-only fix to existing surface, no new endpoint or panel

## Anchors

- Original brief: `briefs/BRIEF_DASHBOARD_CORTEX_RATIFY_PANEL_1.md` (commit 4d63665)
- Merged ratify panel: baker-master squash commit 1264ca8 (PR #223)
- Director smoke bug report: 2026-05-19 ~13:25Z chat
- Skill v1.2 candidate update queued: "click test must be actual cursor click via elementFromPoint validation, not JS function call" — this brief's diagnostic JS is the template.
