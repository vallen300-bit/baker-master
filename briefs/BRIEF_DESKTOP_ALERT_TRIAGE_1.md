# BRIEF: Desktop Alert Triage + Polish

**For:** Code Brisen (Mac Mini)
**From:** AI Head (Session 26)
**Priority:** High — Director has 173 pending alerts, needs management UI
**Branch:** `feat/desktop-alert-triage-1`

## Context

- Alert dedup improved (ALERT-DEDUP-3 just shipped — universal title dedup in `create_alert()`)
- Mobile alert badge shipped (your `feat/mobile-polish-1` — merged to main)
- Desktop dashboard has NO alert badge and limited alert management
- 173 pending alerts — Director needs bulk triage capability

## Deliverables

### 1. Desktop Alert Badge (match mobile pattern)
- Add red badge to desktop header showing pending T1+T2 alert count
- Refresh every 5 min (same as mobile)
- Click navigates to Fires tab
- **Files:** `outputs/static/index.html`, `outputs/static/app.js`

### 2. Alert Bulk Actions on Fires Tab
- Add "Select All" checkbox + individual checkboxes on alert cards
- "Dismiss Selected" button — calls new endpoint
- "Dismiss All T3" button — quick cleanup of low-priority alerts
- **Files:** `outputs/static/app.js`, `outputs/static/index.html`

### 3. New Endpoint: POST /api/alerts/bulk-dismiss
- Accept JSON body: `{"alert_ids": [1,2,3]}` OR `{"tier": 3, "older_than_days": 7}`
- Update status to 'dismissed' for matching alerts
- Return count dismissed
- Auth: X-Baker-Key required
- **File:** `outputs/dashboard.py`

### 4. Alert Source Filter
- Add dropdown/chips to filter Fires by source: pipeline, email_intelligence, deadline_cadence, sentinel_health
- Helps Director focus on specific alert types
- **Files:** `outputs/static/app.js`

## DO NOT Touch
- `memory/store_back.py` — AI Head is working on this
- `orchestrator/commitment_checker.py` — AI Head modifying
- `orchestrator/deadline_manager.py` — AI Head area

## API Reference

Existing alert endpoints in `dashboard.py`:
- `GET /api/alerts` — returns pending alerts (used by Fires tab)
- Alert schema: `{id, tier, title, body, status, source, matter_slug, tags, created_at}`

## Test

1. Desktop: badge shows count, clicking goes to Fires
2. Fires tab: checkboxes appear, bulk dismiss works
3. T3 quick dismiss: clears old low-priority alerts
4. Source filter: filters update alert list correctly
