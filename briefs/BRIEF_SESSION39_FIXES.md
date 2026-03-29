# BRIEF: Session 39 — Verification & Remaining Fixes

## Context
Session 39 shipped several features and fixes. Your job is to verify everything works on the live dashboard and fix anything that doesn't.

## What Was Shipped (already deployed on Render)

### 1. DRAG-DROP-1 — Pointer event drag between landing grid sections
- **What:** Drag Promised To Do / Critical cards between sections using grip handle (⠇)
- **How it works:** mousedown on grip → mousemove creates floating ghost → mouseup on target drops
- **Files:** `outputs/static/app.js` (IIFE at bottom), `outputs/static/style.css` (drag classes)
- **Backend:** `POST /api/landing/move` in `outputs/dashboard.py`
- **Verify:**
  - [ ] Hover a Promised To Do card → grip handle (⠇) appears on left
  - [ ] Click and hold grip, drag toward Critical section → gold action bar appears, drop zones highlight
  - [ ] Drop on Critical → toast says "Moved to Critical", grid refreshes, card appears in Critical
  - [ ] Drag from Critical back to Promised → card moves back
  - [ ] Drop on Dismiss → card disappears
  - [ ] Drop on Ask Baker → switches to Ask Baker with context
  - [ ] Travel and Meeting cards have NO grip handle (not draggable)

### 2. "Add to Critical" / "Add to Promised" triage buttons
- **What:** Renamed "Critical" to "Add to Critical" in sidebar triage. Added new "Add to Promised" button.
- **Backend:** `POST /api/deadlines/from-alert` creates non-critical deadline from alert
- **Files:** `outputs/static/app.js` (renderTriageCard, _handleTriageAction, _triageAddToPromised)
- **Verify:**
  - [ ] Open any project (e.g., Hagenauer) from sidebar
  - [ ] Click a card to expand triage buttons
  - [ ] See "Add to Critical" and "Add to Promised" buttons
  - [ ] Click "Add to Promised" → toast says "Added to Promised To Do"
  - [ ] Go to Dashboard → item appears in Promised To Do section
  - [ ] Click "Add to Critical" → toast says "Marked as critical"
  - [ ] Go to Dashboard → item appears in Critical section

### 3. Critical / Promised To Do separation
- **What:** Promised To Do query now excludes `is_critical = TRUE` items
- **File:** `outputs/dashboard.py` line ~1693 — `AND (is_critical IS NOT TRUE)`
- **Verify:**
  - [ ] Items in Critical do NOT appear in Promised To Do (no duplicates)
  - [ ] Moving a card from Promised to Critical removes it from Promised

### 4. Search input visibility (dark theme)
- **What:** Added `color:var(--text)` to knowledge base search input
- **File:** `outputs/static/app.js` line ~4028
- **Verify:**
  - [ ] Click "Search" in sidebar
  - [ ] Click in the search input and type → text is visible (white on dark background)

### 5. Documents tab fix
- **What:** Column name mismatch — code said `doc_type`, DB has `document_type`. Fixed with alias.
- **File:** `outputs/dashboard.py` — GET `/api/documents` endpoint
- **Verify:**
  - [ ] Click "Documents" in sidebar
  - [ ] Documents load (should show ~4,728 documents)
  - [ ] Filter by type works
  - [ ] Search by filename works

## Database Changes Already Applied
- `ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS is_critical BOOLEAN DEFAULT FALSE`
- `ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS critical_flagged_at TIMESTAMPTZ`
- These columns were added directly to Neon DB, not via migration script

## Known Data State
- Deadline ID 1272 (Sergey commitment) — is_critical=TRUE, status=active
- Deadline ID 1287 (Balducci NVIDIA) — is_critical=TRUE, status=active
- Both should appear in Critical section on dashboard

## If Drag Doesn't Work
The drag uses pointer events (mousedown/mousemove/mouseup), NOT HTML5 Drag API. Key things to check:
- Drag only starts from the `.drag-grip` element (the ⠇ dots)
- 8px threshold before drag activates
- Ghost is a cloned element with `position: fixed`
- `elementFromPoint` detects drop targets (ghost hidden during detection)
- If console shows errors, check the IIFE at the bottom of app.js

## Rules
- Syntax check before commit: `python3 -c "import py_compile; py_compile.compile('file.py', doraise=True)"`
- Bump `?v=N` on CSS/JS in index.html for any changes
- Never force push to main
- Read `tasks/lessons.md` before starting — it has patterns to avoid
- **Verify before marking done** — test the actual user flow on the live dashboard
