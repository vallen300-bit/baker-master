# BRIEF: DASHBOARD-STATS-1 — ClaimsMax-Style Layout + Director Stats + Baker Data Tab

**Author:** AI Head (Session 20, v3 — Director feedback from screenshot)
**For:** Code 300
**Priority:** HIGH — Director feedback from live testing
**Estimated scope:** 4 files (index.html, style.css, app.js, dashboard.py), ~250 lines
**Reference:** ClaimsMax dashboard screenshot at /Users/dimitry/Desktop/claimmax_image.png

---

## Design Reference (ClaimsMax layout)

ClaimsMax hero area is a two-column layout:
- LEFT: Title, description, 2 CTA buttons, search bar
- RIGHT: 2x2 grid of stat cards (Documents, Emails, Investigations, Chunks)

Each stat card has: small uppercase label at top, large number below, subtle description underneath.

Baker should follow this exact pattern.

## Four Changes

### Change 1: Hero Area — Two-Column Layout with Right-Side Stats

Replace the current horizontal stats strip with a ClaimsMax-style layout.

**HTML in index.html — replace the Morning Brief view structure:**

Current:
```
brief-header (greeting + narrative)
stats (5 horizontal boxes)
quick-row (6 buttons)
```

New:
```
brief-hero (flex row)
  LEFT: brief-header (greeting + narrative + 2 CTA buttons)
  RIGHT: brief-stats-grid (2x2 stat cards)
quick-row (keep, but trim to 4 buttons max)
```

Replace lines 100-121 with:

```html
<div class="view active" id="viewMorningBrief">
    <div class="brief-hero">
        <div class="brief-hero-left">
            <div class="brief-greeting" id="briefGreeting">Good morning, Dimitry</div>
            <div class="brief-narrative" id="briefNarrative">Baker is loading your morning summary...</div>
            <div class="brief-cta-row">
                <button class="brief-cta primary" data-action="briefing">Morning Briefing</button>
                <button class="brief-cta secondary" data-action="draft">Draft Email</button>
            </div>
        </div>
        <div class="brief-stats-grid">
            <div class="brief-stat-card">
                <div class="brief-stat-label">Awaiting Reply</div>
                <div class="brief-stat-num" id="statUnanswered">-</div>
                <div class="brief-stat-desc">WhatsApp (24h)</div>
            </div>
            <div class="brief-stat-card">
                <div class="brief-stat-label">Fires</div>
                <div class="brief-stat-num" id="statFires">-</div>
                <div class="brief-stat-desc">Urgent matters</div>
            </div>
            <div class="brief-stat-card">
                <div class="brief-stat-label">Deadlines</div>
                <div class="brief-stat-num" id="statDeadlines">-</div>
                <div class="brief-stat-desc">Due this week</div>
            </div>
            <div class="brief-stat-card">
                <div class="brief-stat-label">Meetings</div>
                <div class="brief-stat-num" id="statMeetings">-</div>
                <div class="brief-stat-desc">Scheduled today</div>
            </div>
        </div>
    </div>

    <div class="quick-row">
        <button class="quick-btn" data-action="legal">Legal Review</button>
        <button class="quick-btn" data-action="research">Research</button>
        <button class="quick-btn" data-action="finance">Financial Analysis</button>
        <button class="quick-btn" data-action="it">IT Status</button>
    </div>
```

Note: "Morning Briefing" and "Draft Email" move into the hero as primary/secondary CTAs (like ClaimsMax's "Open Investigate" + "Ask AI"). The quick-row keeps the remaining 4 as secondary pills.

Also remove the "Baker activity today" section (line 134-136) — it moves to Baker Data tab:

```html
    <!-- REMOVE this section: -->
    <!-- <div class="activity" style="margin-top:16px;">
        <div class="section-label">Baker activity today</div>
        <div id="activityList"></div>
    </div> -->
```

### Change 2: CSS for New Layout

```css
/* === HERO AREA (ClaimsMax-style) === */
.brief-hero {
  display: flex; gap: 32px; margin-bottom: 28px; align-items: flex-start;
}
.brief-hero-left { flex: 1; min-width: 0; }

/* CTA buttons in hero */
.brief-cta-row { display: flex; gap: 10px; margin-top: 20px; }
.brief-cta {
  padding: 10px 24px; border-radius: var(--radius-pill);
  font-size: 14px; font-weight: 500; cursor: pointer;
  font-family: var(--font); transition: all 0.15s; border: none;
}
.brief-cta.primary { background: var(--blue); color: #fff; }
.brief-cta.primary:hover { background: var(--blue-hover); }
.brief-cta.secondary {
  background: var(--bg); color: var(--text2);
  border: 1px solid var(--border);
}
.brief-cta.secondary:hover { border-color: var(--blue); color: var(--blue); }

/* Right-side stat cards (2x2 grid) */
.brief-stats-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
  flex-shrink: 0; width: 340px;
}
.brief-stat-card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 16px 18px;
  box-shadow: var(--shadow-sm);
}
.brief-stat-label {
  font-family: var(--mono); font-size: 10px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.8px; color: var(--text3);
}
.brief-stat-num {
  font-size: 32px; font-weight: 700; letter-spacing: -1px;
  color: var(--text); margin: 4px 0 2px;
}
.brief-stat-desc {
  font-size: 11px; color: var(--text3);
}
```

Also remove the old `.stats` and `.stat` CSS (or leave them — they won't be referenced).

### Change 3: Sidebar Restyle + Baker Data Tab

**Sidebar CSS — update .nav-item:**

```css
.nav-item {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px; border-radius: var(--radius-sm); cursor: pointer;
  transition: all 0.15s; margin-bottom: 1px; font-size: 13px; font-weight: 400;
  color: var(--text3); overflow: hidden; flex-wrap: nowrap;
}
.nav-item:hover { background: rgba(0,0,0,0.03); color: var(--text2); }
```

Active state stays the same.

**HTML — add Baker Data tab (last in sidebar, before closing nav):**

```html
<div class="nav-divider"></div>
<div class="nav-item" data-tab="baker-data">
    <span class="nav-label">Baker Data</span>
</div>
```

**HTML — add view:**

```html
<div class="view" id="viewBakerData">
    <div class="section-label">Baker System</div>
    <div id="bakerDataContent"></div>
</div>
```

**JS — loadBakerData() function:**

Build using DOM methods (createElement, textContent — NOT innerHTML for security). Show:
- Processed (24h) + Actions completed (2-col grid using pcs-box)
- Recent capability runs (list)
- System health placeholders (Render, Triggers, API cost)

Data comes from the morning-brief API (already returns processed_overnight, actions_completed, activity).

Wire into switchTab: `if (tab === 'baker-data') loadBakerData();`

### Change 4: Backend — Add Unanswered Count

**dashboard.py — get_morning_brief():**

Add this query (keep existing processed_overnight and actions_completed for Baker Data tab):

```sql
SELECT COUNT(DISTINCT sender_name) AS cnt
FROM whatsapp_messages
WHERE is_director = FALSE
  AND timestamp > NOW() - INTERVAL '24 hours'
  AND NOT EXISTS (
      SELECT 1 FROM whatsapp_messages reply
      WHERE reply.chat_id = whatsapp_messages.chat_id
        AND reply.is_director = TRUE
        AND reply.timestamp > whatsapp_messages.timestamp
  )
```

Add `unanswered_count` to return dict. Keep all existing fields.

**app.js — loadMorningBrief():**

```javascript
setText('statUnanswered', data.unanswered_count || 0);
setText('statFires', data.fire_count || 0);
setText('statDeadlines', data.deadline_count || 0);
setText('statMeetings', data.meeting_count || 0);
// Remove: statProcessed, statActions
```

Wire the CTA buttons: brief-cta buttons use the same data-action pattern as quick-btns (already handled by existing click delegation in init).

### Bump Cache

v=29 on both style.css and app.js in index.html.

## Testing

1. Syntax check dashboard.py, app.js
2. Dashboard hero: greeting+narrative on left, 2x2 stat grid on right
3. Two CTA buttons: "Morning Briefing" (blue) + "Draft Email" (outline)
4. Stat cards show: Awaiting reply, Fires, Deadlines, Meetings
5. Sidebar: smaller lighter text
6. Baker Data tab: shows operational metrics
7. No regression on other tabs
