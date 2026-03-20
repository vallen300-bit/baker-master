# Code Brisen Brief — Session 28B

**From:** AI Head | **Date:** 20 March 2026
**Priority:** C2 first, then D3

---

## Task 1: C2 — Relationship Health Scoring UI

### What
Add a relationship health view to the Contacts tab on desktop. Backend data exists — we need a visual representation showing which contacts are healthy, cooling, or cold.

### API Endpoints (all exist)

```
GET /api/contacts/cadence          → contacts with cadence tracking data
  Returns: [{name, avg_inbound_gap_days, last_inbound_at, last_contact_date, tier, domain}]

GET /api/contacts?search=name      → contact search
GET /api/data-freshness            → for context
```

The cadence endpoint returns contacts sorted by "silence ratio" — how long since last contact vs their normal communication frequency. A contact who emails every 5 days but hasn't been heard from in 20 days is more concerning than one who emails monthly and is 35 days silent.

### Design Spec

1. **Health indicator on each contact card** in the Contacts tab
   - Green dot: last contact within 1x their avg gap (healthy)
   - Yellow dot: 1-2x their avg gap (cooling)
   - Red dot: >2x their avg gap (cold / at risk)
   - Grey dot: no cadence data (insufficient interactions)

2. **Sortable by health** — add a "Health" sort option alongside existing sorts
   - Default: show red/cold contacts first (needs attention)

3. **Hover/tap detail** — show mini card:
   - "Avg contact every X days"
   - "Last heard: Y days ago"
   - "Status: Cooling (1.5x normal gap)"

4. **Summary bar** at top of Contacts tab:
   - "36 tracked: 12 healthy, 15 cooling, 9 at risk"

### Files to Modify
- `outputs/static/index.html` — health indicators on contact cards
- `outputs/static/app.js` — fetch cadence data, compute health status, sort
- `outputs/static/styles.css` or inline styles — green/yellow/red dots

### Acceptance Criteria
- [ ] Health dots visible on contact cards
- [ ] Sort by health status works
- [ ] Hover/tap shows cadence detail
- [ ] Summary bar shows counts
- [ ] Contacts without cadence data show grey (not broken)

---

## Task 2: D3 — Obligation Bulk Triage

### What
Card-deck swipe interface for triaging deadlines/obligations. Director can quickly dismiss, acknowledge, or escalate items without opening each one.

### API Endpoints (all exist)

```
GET /api/deadlines?status=active&limit=50    → active deadlines
  Returns: [{id, description, due_date, priority, status, confidence, severity}]

PATCH /api/deadlines/{id}                     → update deadline status
  Body: {"status": "dismissed"} or {"status": "completed"} or {"priority": "high"}
```

Note: Check if PATCH endpoint exists. If not, I'll add it — let me know.

### Design Spec

1. **Triage mode button** in the Deadlines/Obligations section
   - "Triage (X pending)" button opens the card deck

2. **Card deck** — full-width overlay, one card at a time
   - Shows: description, due date, priority, confidence level, source
   - Color-coded by priority (red=critical, orange=high, blue=normal, grey=low)

3. **Swipe actions** (or button row for desktop):
   - Swipe right / "Keep" → acknowledged, stays active
   - Swipe left / "Dismiss" → status = dismissed
   - Swipe up / "Escalate" → priority bumped to high
   - Tap "Done" → status = completed

4. **Progress** — "5 of 23 reviewed" counter at top

5. **Auto-advance** — after action, next card slides in

6. **Undo** — last action can be undone (keep previous state in memory)

### Files to Modify
- `outputs/static/index.html` — triage overlay markup
- `outputs/static/app.js` — card deck logic, swipe gestures, API calls
- `outputs/static/styles.css` — card deck styles, swipe animations

### Acceptance Criteria
- [ ] Triage button appears with pending count
- [ ] Card deck shows one obligation at a time
- [ ] Swipe/button actions work (dismiss, keep, escalate, done)
- [ ] PATCH API called on each action
- [ ] Progress counter updates
- [ ] Undo works for last action
- [ ] Works on desktop (buttons) and mobile (swipe gestures)

---

## API Check Needed

Before starting D3, check if `PATCH /api/deadlines/{id}` exists. If not, tell me and I'll add it. Quick grep:
```
grep -n "PATCH.*deadline\|patch.*deadline" outputs/dashboard.py
```

---

## General Notes
- **API key:** `bakerbhavanga` (X-Baker-Key header)
- **git pull before starting** — I just pushed admin endpoints + memory summaries
- **Don't touch backend files** — AI Head handles those
- **Cache bust:** bump ?v=N on CSS/JS
