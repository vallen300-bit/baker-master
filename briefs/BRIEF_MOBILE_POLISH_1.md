# BRIEF: Mobile Polish + Alert Cleanup — Code Brisen

**Date:** 2026-03-18
**From:** AI Head
**Priority:** High — Director is at NVIDIA GTC using /mobile from iPhone RIGHT NOW

---

## Context

Session 25 shipped `/mobile` — a standalone mobile page with Ask Baker + Ask Specialist. It's live at `baker-master.onrender.com/mobile` and the Director added it to his iPhone home screen. A "New" chat button was just added. Now we need polish and operational cleanup.

**IMPORTANT:** `git pull` first — the mobile files were updated after the brief was first written.

---

## Task 1: Mobile Polish

### Files
- `outputs/static/mobile.js` (~290 lines)
- `outputs/static/mobile.css`
- `outputs/static/mobile.html`

### Issues to fix

1. **Loading state on capability fetch** — When the page loads, capabilities take a moment to fetch from the API. The picker shows just "Select a specialist..." with no indication it's loading. Add a "Loading..." disabled option that gets replaced when capabilities arrive.

2. **Scroll during streaming** — Messages prepend (newest at top, Cowork-style). During long streaming responses, verify the scroll stays pinned to top so the user sees tokens arriving. If not, add `container.scrollTop = 0` inside the streaming token handler.

3. **Bump cache version** — After your changes, bump `?v=2` to `?v=3` in mobile.html for both CSS and JS links.

### Testing
- Open `baker-master.onrender.com/mobile` on a phone or responsive view
- Ask Baker a question → verify streaming, thinking dots, status labels work
- Tap "New" → verify conversation resets
- Switch to Specialist → pick capability → ask → verify streaming
- Test dark mode

---

## Task 2: Alert Bulk Cleanup

~265 pending alerts, many duplicates from before the ALERT-DEDUP-2 fix (shipped this session). Need to dismiss duplicate clusters.

### Approach

Use Baker MCP tools (`baker_raw_write` or `baker_raw_query`) to run:

```sql
-- Step 1: Check how many duplicates exist
SELECT LEFT(title, 60) as prefix, COUNT(*) as cnt
FROM alerts WHERE status = 'pending'
GROUP BY LEFT(title, 60) HAVING COUNT(*) > 1
ORDER BY cnt DESC LIMIT 20;

-- Step 2: Dismiss duplicates (keep oldest per cluster)
WITH dupes AS (
    SELECT LEFT(title, 60) as prefix,
           COUNT(*) as cnt,
           MIN(id) as keep_id
    FROM alerts
    WHERE status = 'pending'
    GROUP BY LEFT(title, 60)
    HAVING COUNT(*) > 1
)
UPDATE alerts SET status = 'dismissed', exit_reason = 'dedup — bulk cleanup Session 25'
WHERE status = 'pending'
  AND LEFT(title, 60) IN (SELECT prefix FROM dupes)
  AND id NOT IN (SELECT keep_id FROM dupes);

-- Step 3: Verify
SELECT COUNT(*) FROM alerts WHERE status = 'pending';
```

Target: pending count < 100.

---

## Task 3: Alert Badge on Mobile (Nice-to-have)

Add a small red dot or count badge showing T1/T2 pending alerts on the mobile page header.

### Approach
- On init + every 5 minutes, fetch `GET /api/alerts` with `X-Baker-Key` header
- Count T1+T2 alerts
- Show as a small badge next to Baker logo or in the header
- If 0, hide the badge

---

## Definition of Done
- [ ] Capability picker shows loading state
- [ ] Cache busted (v=3)
- [ ] Alert duplicates dismissed (pending < 100)
- [ ] Push to main, verify on Render
- [ ] (Optional) Alert badge on mobile

---

## Key Files Reference
- `outputs/dashboard.py` — API endpoints (don't modify unless needed)
- `outputs/static/app.js` — Desktop JS (reference for patterns)
- `outputs/static/mobile.css` — Mobile styles
- `outputs/static/mobile.js` — Mobile JS
- `outputs/static/mobile.html` — Mobile HTML
- `BAKER_API_KEY` = `bakerbhavanga`
