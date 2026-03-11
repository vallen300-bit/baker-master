# BRIEF: DASHBOARD-STATS-1 — Director's Lens Dashboard + Sidebar Restyle + Baker Data Tab

**Author:** AI Head (Session 20, revised with Director feedback)
**For:** Code 300
**Priority:** HIGH — Director feedback from live testing
**Estimated scope:** 4 files (index.html, style.css, app.js, dashboard.py), ~200 lines
**Reference:** ClaimsMax dashboard at /Users/dimitry/Desktop/claimmax_image.png

---

## Three Changes

### Change 1: Sidebar Restyle (ClaimsMax-style)

Current sidebar: 14px font, semi-bold text, feels heavy.
ClaimsMax sidebar: smaller, lighter, uniform — items are understated until hovered/active.

**CSS changes in style.css — update .nav-item:**

- font-size: 14px to 13px (smaller)
- color: var(--text2) to var(--text3) (lighter by default)
- hover color: var(--text) to var(--text2) (subtler hover)
- margin-bottom: 2px to 1px (tighter)
- padding: 9px to 8px (slightly more compact)

Active state stays the same (blue background, blue text, left border).

### Change 2: New "Baker Data" Tab (last in sidebar)

Add a new tab at the bottom of the sidebar. All operational/Baker-internal metrics go here — tucked away from the main dashboard.

**HTML:** Add nav-item with data-tab="baker-data" after the last divider. Add a view section with id="viewBakerData".

**Content for Baker Data tab (built in JS using DOM methods, NOT innerHTML for security):**
- Activity Today: processed (24h), actions completed (grid of 2 boxes)
- Recent Capability Runs: list of recent specialist runs with slug, status, iterations, time
- System Health: Render status, Trigger status, API cost today (placeholders for now)

Use the existing card/pcs-box patterns and DOM createElement methods. The data comes from the morning-brief API response which already returns processed_overnight, actions_completed, and activity.

Wire into switchTab() — when tab is baker-data, call loadBakerData().

### Change 3: Dashboard Stats — Director's Lens

Replace the 5 stat boxes with 4 meaningful ones:

| # | ID | Label | Source |
|---|-----|-------|--------|
| 1 | statUnanswered | Awaiting reply | Count distinct WA senders with no Director reply in 24h |
| 2 | statFires | Fires | Alerts table, tier=1, status=pending |
| 3 | statDeadlines | Due this week | Deadlines, active, due within 7 days |
| 4 | statMeetings | Meetings today | Calendar API (existing) |

**Backend (dashboard.py):** Add unanswered count query to get_morning_brief():

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

KEEP processed_overnight and actions_completed queries — they move to Baker Data tab. Add unanswered_count to the return dict.

**Frontend (app.js):** Update loadMorningBrief to set statUnanswered instead of statProcessed/statActions.

**HTML (index.html):** Replace 5 stat divs with 4 new ones (no color classes — all use default text color per ClaimsMax design).

### Bump Cache Version

style.css?v=29, app.js?v=29

## Security Note

Use DOM createElement/textContent methods for the Baker Data tab content (not innerHTML with string concatenation). All data from API should be escaped via esc() or textContent assignment. Follow the existing pattern in app.js.

## Testing

1. Syntax check dashboard.py, app.js
2. Dashboard: 4 stats (Awaiting reply, Fires, Due this week, Meetings today)
3. Sidebar: smaller lighter text, hover brightens subtly
4. Baker Data tab: shows processed, actions, capability runs, system health
5. No regression on other tabs
