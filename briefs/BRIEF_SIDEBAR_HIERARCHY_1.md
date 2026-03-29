# BRIEF: SIDEBAR-HIERARCHY-1 — Equal visual weight for Projects/Operations/Inbox

## Problem
Projects and Operations look like section headers (gold, uppercase, expandable). Inbox looks like a regular nav item below them. All three deserve equal attention from the Director — they are peer-level entry points.

## Goal
Make Projects, Operations, and Inbox visually equal — same font, same position, same treatment. Differentiate with subtle color accents.

## Design

### Three peer sections:
| Section | Accent color | Content below |
|---------|-------------|---------------|
| **PROJECTS** | Gold (#c9a96e) | Project list with red dots (existing) |
| **OPERATIONS** | Teal (#0d9488) | Operations list (existing) |
| **INBOX** | Amber (#d4a535) | Unread count badge (existing) |

### Visual rules:
- All three: **same font** (11px, uppercase, bold, letter-spacing 0.5px)
- All three: **same left alignment** (flush with sidebar edge)
- All three: **expandable arrow** (▾/▸) — Projects and Operations already have this
- Each has a **subtle accent** — either left border (3px) or colored dot before the label
- Count badges on the right (existing behavior, keep it)
- Items below each section (e.g., Hagenauer, Kempinski) remain **indented, smaller font, subordinate**

### What NOT to change:
- Below the three sections: Ask Baker, Ask Specialist, Search, Documents, Dossiers, Travel, Media, Baker Data — these stay as they are (regular nav items)
- Dashboard at the top stays gold and active-highlighted

## Files to modify
- `outputs/static/index.html` — restructure Inbox to match Projects/Operations markup pattern
- `outputs/static/style.css` — add accent colors for each section header
- `outputs/static/app.js` — if Inbox needs expand/collapse behavior

## Current HTML structure (index.html ~lines 30-50)
```html
<!-- Projects section -->
<div class="nav-section-header" id="navProjectsHeader" data-section="projects">
    <span class="nav-section-arrow">▾</span>
    <span class="nav-section-label">Projects</span>
    <span class="nav-count" id="projectsCount"></span>
</div>
<div class="nav-sub" id="projectsSubList"></div>

<!-- Operations section -->
<div class="nav-section-header" id="navOpsHeader" data-section="operations">
    <span class="nav-section-arrow">▸</span>
    <span class="nav-section-label">Operations</span>
    <span class="nav-count" id="operationsCount"></span>
</div>
<div class="nav-sub" id="operationsSubList" style="display:none;"></div>

<!-- Inbox (currently a regular nav-item, NOT a section header) -->
<div class="nav-item" data-tab="fires" data-matter="_ungrouped" id="navInbox">
    <span class="nav-label">Inbox</span>
    <span class="nav-count" id="inboxCount"></span>
</div>
```

## Target: make Inbox a section header too
Change Inbox from `nav-item` to `nav-section-header` pattern, OR style `#navInbox` to match the section headers visually. The simplest approach is CSS-only — give `#navInbox` the same styles as `.nav-section-header`.

## Accent colors (CSS)
```css
#navProjectsHeader .nav-section-label { color: #c9a96e; }  /* gold - already close to this */
#navOpsHeader .nav-section-label { color: #0d9488; }        /* teal */
#navInbox .nav-label { color: #d4a535; }                     /* amber */
```

## Verification
- [ ] All three (Projects, Operations, Inbox) look like equal-weight section headers
- [ ] Each has a distinct but subtle color accent
- [ ] Items below Projects (Hagenauer etc.) are visually subordinate (indented, smaller)
- [ ] Dashboard at top remains distinct
- [ ] Below the three sections, other nav items (Ask Baker etc.) remain unchanged

## 2. Remove Dashboard button — BAKER logo = home

### Problem
"Dashboard" button sits below BAKER logo with the same gold color. Redundant — wastes space and adds confusion.

### Change
- **Remove** the `nav-item` with `data-tab="morning-brief"` that says "Dashboard"
- **Make the BAKER logo clickable** — clicking it calls `switchTab('morning-brief')` (same as the old Dashboard button)
- The logo element is `.sidebar-logo` in index.html. Add `onclick="switchTab('morning-brief')"` and `style="cursor:pointer;"`
- If the logo already has a click handler, verify it goes to morning-brief

### Verify
- [ ] "Dashboard" text no longer appears in sidebar
- [ ] Clicking "BAKER" logo at top returns to main landing page
- [ ] All other sidebar navigation still works

---

## Rules
- Syntax check before commit
- Bump CSS/JS version in index.html
- Never force push to main
- Read `tasks/lessons.md` before starting
