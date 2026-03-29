# Brief: LANDING-GRID-1 — Unified 2x2 Landing Grid with Consistent Cards

**Author:** AI Head (Session 21, Director design direction)
**For:** Code 300
**Priority:** HIGH — Director wants uniform attention-directing on landing page

---

## Problem

The landing page has 3 sections (Travel, Top Fires, Deadlines) stacked vertically with completely different card formats:
- Travel: color dot + title + time
- Fires: tier badge + title + tags + assign dropdown + relative time
- Deadlines: color dot + description + days text

This makes it hard to scan and know where to direct attention. Items are also stacked top-to-bottom, wasting the wide page width.

## Design

### Layout: 2x2 Grid

```
┌─────────────────────────────┬─────────────────────────────┐
│  TRAVEL                     │  TOP FIRES                  │
│  ● Flight to Frankfurt  ▾   │  ● Hagenauer contest...  ▾  │
│  ● Flight to SF         ▾   │  ● Cupial deadline...    ▾  │
│                             │  ● Insurance renewal...  ▾  │
├─────────────────────────────┼─────────────────────────────┤
│  DEADLINES THIS WEEK        │  (4th quadrant — see below) │
│  ● Termination decision  ▾  │                             │
│  ● Security delivery     ▾  │                             │
│  ● Contest letter        ▾  │                             │
└─────────────────────────────┴─────────────────────────────┘
```

Each quadrant is a **lightly highlighted card** — subtle background (`var(--card)`), soft border (`var(--border)`), rounded corners (`var(--radius-sm)`), generous padding.

CSS:
```css
.landing-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-top: 16px;
}
.landing-quadrant {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 16px;
    min-height: 120px;
}
.landing-quadrant .section-label {
    margin-bottom: 10px;
}
```

### 4th Quadrant Options (Director to decide later)

For now, use a placeholder. Suggestions:
- **Commitments due** — overdue + due this week from commitments table
- **Awaiting reply** — emails/WA sent by Director with no response
- **Baker activity** — last 3 actions Baker took autonomously
- **Quick actions** — buttons for common tasks (draft email, check matter, etc.)

Implement as empty placeholder with label "COMING SOON" and a subtle dashed border.

### Unified Card Format

**All items across all 4 quadrants use the SAME card row format:**

```
● Title text                                    meta ▾
  subtitle line (optional)
```

Structure:
```html
<div class="landing-item" onclick="toggle expand">
  <div class="landing-item-header">
    <span class="nav-dot {color}"></span>
    <span class="landing-item-title">{title}</span>
    <span class="landing-item-meta">{meta}</span>
    <span class="landing-item-chevron">▾</span>  <!-- only if expandable -->
  </div>
  <div class="landing-item-sub">{subtitle}</div>  <!-- optional -->
  <div class="landing-item-detail" style="display:none">
    {expanded content}
  </div>
</div>
```

CSS:
```css
.landing-item {
    padding: 8px 0;
    border-bottom: 1px solid var(--border-light);
}
.landing-item:last-child { border-bottom: none; }
.landing-item-header {
    display: flex;
    align-items: center;
    gap: 8px;
}
.landing-item-title {
    flex: 1;
    font-size: 13px;
    font-weight: 500;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.landing-item-meta {
    font-size: 11px;
    color: var(--text3);
    font-family: var(--mono);
    white-space: nowrap;
}
.landing-item-chevron {
    font-size: 10px;
    color: var(--text3);
    cursor: pointer;
    transition: transform 0.2s;
}
.landing-item-sub {
    font-size: 11px;
    color: var(--text3);
    padding-left: 18px;
    margin-top: 2px;
}
.landing-item-detail {
    font-size: 12px;
    color: var(--text2);
    padding: 8px 0 4px 18px;
    line-height: 1.5;
    white-space: pre-wrap;
    border-top: 1px solid var(--border-light);
    margin-top: 6px;
}
```

### Color Dot Rules (unified across all types)

| Color | Meaning | Used when |
|-------|---------|-----------|
| Red | Needs attention NOW | Overdue deadline, T1 fire, failed item |
| Amber | Coming soon / pending | Upcoming deadline, T2 fire, unprepped travel |
| Green | Handled / prepped | Prepped travel, resolved fire |
| Gray | Informational | Low-priority deadline, T3 item |

### Per-Quadrant Specifics

**Travel (top-left):**
- Dot: green if prepped, amber if pending
- Title: event title (strip `[Baker Prep]` prefix — those are duplicates of the main event)
- Meta: departure time (e.g., `06:45`)
- Subtitle: attendees if any
- Expandable: Baker's prep notes (from `prep_notes` field)
- **Dedup:** Filter out `[Baker Prep]` items — they're internal scheduler events, not real travel. Only show the actual calendar event.

**Top Fires (top-right):**
- Dot: red if T1, amber if T2
- Title: alert title (strip "DUE TODAY:" / "OVERDUE:" prefixes for cleaner look — the dot color already signals urgency)
- Meta: relative time (e.g., `2d ago`, `4h ago`)
- Subtitle: tags as inline text (not badges)
- Expandable: alert body (truncated to 500 chars, with "See full →" link to fires tab)

**Deadlines (bottom-left):**
- Dot: red if today/overdue, amber if this week, gray if later
- Title: deadline description
- Meta: days text (e.g., `Today`, `Tomorrow`, `3 days`)
- Subtitle: matter_slug if assigned
- Expandable: source_snippet if available

**4th Quadrant (bottom-right):**
- Placeholder for now: dashed border, "COMING SOON" label, subtle styling

### Click Behavior

All expandable items use the same toggle:
```javascript
onclick="var d=this.querySelector('.landing-item-detail');if(d){d.style.display=d.style.display==='none'?'block':'none'}"
```

Chevron only appears if the item has expandable content.

## Files to Modify

| File | Change |
|------|--------|
| `outputs/static/index.html` | Replace Travel + Fires + Deadlines sections with 2x2 grid |
| `outputs/static/app.js` | New `renderLandingGrid()` function, unified `renderLandingItem()`, remove old `renderMeetingCard`/`renderDeadlineCompact` |
| `outputs/static/style.css` | Add `.landing-grid`, `.landing-quadrant`, `.landing-item` styles |

## What to Remove

- `renderMeetingCard()` — replaced by `renderLandingItem()`
- `renderDeadlineCompact()` — replaced by `renderLandingItem()`
- `renderAlertCard(alert, true)` call for top fires — replaced by `renderLandingItem()`
- `<div id="systemWidgets">` — already removed (BAKER-DATA-TUCK-1)
- `[Baker Prep]` duplicate events — filter out in rendering

## Verification

1. Landing page shows 2x2 grid with 4 quadrants
2. All items use same card format (dot + title + meta + chevron)
3. Travel items are clickable → prep notes expand
4. Fire items are clickable → alert body expands
5. Deadline items are clickable → source snippet expands
6. 4th quadrant shows placeholder
7. Dots are correctly colored per urgency
8. `[Baker Prep]` duplicates are filtered out
9. Grid is responsive — stacks to 1 column on narrow screens

## What NOT to Build

- Don't implement the 4th quadrant content yet — placeholder only
- Don't change the stat cards above the grid (those are separate)
- Don't touch the sidebar or other tabs
