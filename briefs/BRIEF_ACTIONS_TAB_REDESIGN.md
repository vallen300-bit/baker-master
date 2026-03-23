# BRIEF: Actions Tab Redesign (Mobile + Dashboard)

**Author:** AI Head (Claude Code)
**Date:** 2026-03-23
**Status:** Approved by Director
**Priority:** High — daily UX

## What Changed

Director feedback from live mobile testing session. Six issues:

## 1. Merge Feed + Digest → "Actions" Tab

**Problem:** Feed and Digest show nearly identical content with different triage buttons.
**Fix:** Single "Actions" tab replaces both. One unified stream.

- Rename tab from "Feed" to "Actions" (icon: unchanged bell)
- Remove Digest tab entirely
- Morning/evening digest items flow into Actions as regular cards
- Remove AM/PM toggle (confusing — "Morning Digest PM" makes no sense)
- Baker refers users here: "I've queued this for your confirmation in **Actions**"

## 2. Unified Triage Buttons: View / Dismiss / Run

**Problem:** Feed has Done/Dismiss. Digest has View/Dismiss. Browser has Preview/Confirm/Cancel. Inconsistent.

**Fix:** Three standard buttons on every card:

| Button | When shown | Action |
|--------|-----------|--------|
| **View** | Always | Expand card → show full body, source details, related context |
| **Dismiss** | Always | Remove card, mark alert dismissed |
| **Run** | Only when Baker proposes an action | Execute the proposal (confirm purchase, run dossier, send email) |

Special cases:
- Browser transactions: Run = "Confirm Purchase" (same action, consistent label)
- Research proposals: Run = "Run Dossier"
- Obligation proposals: Run = "Approve"
- Plain alerts (no action): View + Dismiss only (no Run button)

## 3. Sectioned Layout (Priority Grouping)

**Problem:** All items in one flat list — T1 browser confirmations mixed with T3 FYI cadence alerts.

**Fix:** Three visual sections:

```
┌─────────────────────────────┐
│ 🔴 NEEDS YOUR DECISION      │  ← T1 + browser_transaction + actions with Run
│  [Purchase card]             │
│  [Email draft to confirm]   │
├─────────────────────────────┤
│ 🟡 BAKER RECOMMENDS         │  ← T2 + research proposals + obligations
│  [Dossier proposal]         │
│  [Initiative suggestion]    │
├─────────────────────────────┤
│ ⚪ FOR YOUR INFO             │  ← T3 + calendar prep + cadence + intelligence
│  [Cadence alert]            │
│  [Meeting prep ready]       │
└─────────────────────────────┘
```

Section headers are sticky. Empty sections are hidden. Counts shown in headers.

Classification logic:
- **Needs Your Decision**: `action_required=true` OR `source IN ('browser_transaction', 'pending_draft')` OR tier=1
- **Baker Recommends**: `source IN ('research', 'obligation', 'initiative', 'convergence')` OR tier=2 with structured_actions
- **For Your Info**: Everything else

## 4. View Button → Expand Card

**Problem:** View button is a no-op.

**Fix:** Tapping View expands the card inline:
- Shows full `body` text (currently truncated)
- Shows source metadata (email from, WhatsApp contact, meeting name)
- Shows timestamp
- If there's a linked document or screenshot, show it
- Tap again or swipe to collapse

## 5. Flight Cards: Travel Day Only + Multi-Segment

**Problem:** Flight card (GVA→FRA) persists 3 days after the flight.

**Fix:**
- Show flight card only on `start_date` (travel day)
- Remove card at midnight local time (or next day 06:00 UTC)
- Multiple segments = multiple cards:
  - GVA→VIE on Monday = 1 card on Monday
  - VIE→GVA on Thursday = 1 card on Thursday
- Each card shows: origin → destination, departure time, flight number if known
- Position: pinned at top (above Actions sections), current styling preserved

Implementation: Filter trips in `loadActiveTrip()` — only show segments where `start_date == today`.

## 6. Document Upload/Download Fix

**Problem:**
- Mobile: attachment icon picker is confusing
- Desktop: document downloads fail
- No clear upload flow

**Fix:**
- **Mobile upload**: Tap attachment → camera or file picker (iOS native). Upload to `/api/documents/upload`. Show progress spinner. Confirm with filename.
- **Desktop download**: Fix broken `/api/documents/{id}/download` endpoint (likely missing Content-Disposition header or wrong file path)
- **Desktop upload**: Drag-and-drop zone on Documents panel, or click to browse

## Files to Modify

| File | Changes |
|------|---------|
| `outputs/static/mobile.js` | Merge Feed+Digest, new Actions tab, triage buttons, View expand, flight filter |
| `outputs/static/mobile.css` | Section headers, expanded card styling, remove digest styles |
| `outputs/static/mobile.html` | Rename tab, remove digest tab |
| `outputs/static/index.html` | Dashboard document download fix |
| `outputs/static/app.js` | Dashboard document download fix |
| `outputs/dashboard.py` | Fix document download endpoint if needed |

## Implementation Order

1. Merge tabs + rename to Actions (structural HTML/JS change)
2. Implement sectioned layout with classification logic
3. Unified triage buttons (View/Dismiss/Run)
4. View expand functionality
5. Flight card filtering (travel day only + multi-segment)
6. Document upload/download fixes

## Estimated Effort

- Steps 1-4: ~4 hours (heavy frontend)
- Step 5: ~1 hour
- Step 6: ~2 hours
- Total: **~7 hours**

Best split: Code Brisen handles frontend (steps 1-5), AI Head handles backend document fixes (step 6).
