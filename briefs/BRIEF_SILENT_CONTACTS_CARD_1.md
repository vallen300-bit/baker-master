# BRIEF: Silent Contacts Card on Landing Page

**For:** Code Brisen (Mac Mini)
**From:** AI Head (Session 26)
**Priority:** Medium — morning brief API now returns `silent_contacts`, needs frontend rendering
**Branch:** `feat/silent-contacts-card-1`

## Context

- Morning brief API (`GET /api/dashboard/morning-brief`) now returns `silent_contacts` array
- Each entry: `{name, last_contact_date, days_silent}`
- These are T1/T2 contacts with 30+ days no interaction
- The morning narrative also mentions them ("Consider reaching out to...")
- **No frontend rendering yet** — the data is returned but not displayed

## Deliverables

### 1. "Relationships" card on landing grid
- Add a small card/section to the landing page showing silent contacts
- Position: below the existing 2x2 grid, or replace one of the less-used cells
- Design: compact list, each contact as a row: name, days_silent, "Reach out" button
- "Reach out" button → opens Ask Baker with pre-filled: "Draft an email to [name]"
- **Files:** `outputs/static/app.js`, `outputs/static/index.html`

### 2. Render in morning brief section
- If `silent_contacts.length > 0`, show a subtle warning below the narrative
- Style: amber/orange left border (relationship warning, not fire-red)
- **Files:** `outputs/static/app.js`

## API Shape (already deployed)
```json
{
  "silent_contacts": [
    {"name": "Francesco Cefalu", "last_contact_date": "2025-12-16T19:32:54+00:00", "days_silent": 91},
    {"name": "Conrad Weiss", "last_contact_date": "2025-12-22T14:53:03+00:00", "days_silent": 86}
  ]
}
```

## DO NOT Touch
- Backend Python files — all stable

## Test
1. Landing page shows silent contacts if any exist (currently 5 contacts 30+ days silent)
2. "Reach out" button opens chat with pre-filled draft prompt
3. Card doesn't show if `silent_contacts` is empty
