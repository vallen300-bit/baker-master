# COCKPIT-V3 Phase C — Brief for Code Brisen

**Author:** Code 300 (architect)
**Date:** 2026-03-08
**Parent brief:** BRIEF_COCKPIT_V3.md v1.5
**Branch:** `feat/cockpit-v3-c` (create from `main`)
**Builds on:** Phase A1 + A2 + B (all sidebar tabs functional except People, Search, Travel, Media)

---

## Overview

Phase C completes the COCKPIT-V3 vision. 5 features in 3 commits.

| Step | Items | Files touched |
|------|-------|---------------|
| **C1** | People tab + Search tab | `dashboard.py`, `app.js`, `index.html`, `style.css` |
| **C2** | Travel tab + Media tab | `dashboard.py`, `app.js`, `index.html` |
| **C3** | Alert auto-expiry | `embedded_scheduler.py`, `dashboard.py` or `store_back.py` |

---

## Step 1 — People Tab + Search Tab

### 1a. People tab — backend

**Where:** `outputs/dashboard.py`

**Endpoint 1: `GET /api/people`**

List all known people — merge `vip_contacts` + `contacts` tables, deduplicate by name.

```python
@app.get("/api/people", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def list_people():
```

Implementation:
1. Query `vip_contacts` (all rows): id, name, role, email, whatsapp_id, tier, domain, role_context
2. Query `contacts` (all rows): id, name, email, company, role, relationship, last_contact
3. Merge by name (case-insensitive). VIP data takes precedence where both exist.
4. Sort: VIPs first (tier 1, then tier 2), then contacts alphabetically
5. Response: `{"people": [...], "count": N}`

Each person object:
```json
{
  "id": "uuid-or-int",
  "name": "Constantinos",
  "role": "Brisen Group GUP",
  "email": "...",
  "company": "Brisen",
  "tier": 1,
  "is_vip": true,
  "last_contact": "2026-03-07T..."
}
```

**Endpoint 2: `GET /api/people/{name}/activity`**

Get recent activity for a person across all sources.

```python
@app.get("/api/people/{name}/activity", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_person_activity(name: str, limit: int = Query(20, ge=1, le=100)):
```

Implementation — query 3 tables, merge by date:

1. **Emails:** `SELECT subject, sender_name, sender_email, received_date FROM email_messages WHERE sender_name ILIKE %s OR sender_email ILIKE %s ORDER BY received_date DESC LIMIT %s`
2. **WhatsApp:** `SELECT sender_name, full_text, timestamp FROM whatsapp_messages WHERE sender_name ILIKE %s ORDER BY timestamp DESC LIMIT %s`
3. **Meetings:** `SELECT title, organizer, participants, meeting_date FROM meeting_transcripts WHERE organizer ILIKE %s OR participants::text ILIKE %s ORDER BY meeting_date DESC LIMIT %s`

Use `%name%` for ILIKE (fuzzy match on name). Merge all results into a unified activity list sorted by date desc.

Each activity item:
```json
{
  "type": "email|whatsapp|meeting",
  "title": "Re: Loan covenant review",
  "date": "2026-03-07T...",
  "preview": "First 200 chars of content..."
}
```

Response: `{"name": "Constantinos", "activity": [...], "count": N}`

**Also:** Get related matters for the person. Query `alerts WHERE body ILIKE %name% OR title ILIKE %name%` and group by `matter_slug`. Return as `"matters": ["hagenauer", "cupial"]` in the person activity response.

### 1b. People tab — frontend

**Where:** `outputs/static/index.html`, `outputs/static/app.js`

**HTML:** Replace the "Coming Soon" placeholder for people:
```html
<!-- VIEW: People -->
<div class="view" id="viewPeople">
    <div class="section-label">People</div>
    <div id="peopleContent"></div>
</div>
```

**JS: `loadPeopleTab()`** — called from `switchTab('people')`:
1. Fetch `GET /api/people`
2. Render each person as a compact card:
   - VIP badge (if `is_vip`)
   - Name, role, company
   - Tier dot (color-coded)
   - Last contact date
3. Click a person → call `loadPersonDetail(name)`

**JS: `loadPersonDetail(name)`:**
1. Fetch `GET /api/people/{name}/activity`
2. Show back button ("Back to all people")
3. Person header: name, role, email, tier
4. Related matters as tag badges
5. Activity feed: chronological list of emails/WhatsApp/meetings with type icon, title, date, preview
6. Each activity item is a compact card with type badge (Email/WA/Meeting)

**CSS:**
```css
.person-card { cursor: pointer; }
.vip-badge {
    display: inline-block; padding: 2px 6px; background: var(--amber);
    color: white; border-radius: 3px; font-size: 9px; font-weight: 700;
    font-family: var(--mono); letter-spacing: 0.3px;
}
.activity-type {
    display: inline-block; padding: 2px 6px; border-radius: 3px;
    font-size: 9px; font-weight: 600; font-family: var(--mono);
}
.activity-type.email { background: #dbeafe; color: #1d4ed8; }
.activity-type.whatsapp { background: #dcfce7; color: #15803d; }
.activity-type.meeting { background: #fef3c7; color: #b45309; }
```

### 1c. Search tab — backend

**Where:** `outputs/dashboard.py`

The existing `GET /api/search` does semantic vector search across Qdrant collections. This is useful but not what the Search tab needs. The Search tab needs **structured alert search** with filters.

**Endpoint: `GET /api/alerts/search`**

```python
@app.get("/api/alerts/search", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def search_alerts(
    q: str = Query("", max_length=500),
    matter: Optional[str] = None,
    tag: Optional[str] = None,
    tier: Optional[int] = None,
    status: Optional[str] = None,
    source: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
):
```

Implementation:
1. Build dynamic SQL with parameterized WHERE clauses:
   - `q` → `(title ILIKE %s OR body ILIKE %s)` with `%q%`
   - `matter` → `matter_slug = %s`
   - `tag` → `tags ? %s`
   - `tier` → `tier = %s`
   - `status` → `status = %s` (pending, resolved, dismissed)
   - `source` → JOIN `trigger_log` on `trigger_id`, filter `trigger_log.type = %s`
   - `date_from` → `created_at >= %s`
   - `date_to` → `created_at <= %s`
2. ORDER BY `created_at DESC`
3. Response: `{"items": [...], "count": N, "filters_applied": {...}}`

**CRITICAL: All query parameters are parameterized. Build WHERE clauses as a list of conditions + params tuple. No string concatenation.**

### 1d. Search tab — frontend

**HTML:**
```html
<!-- VIEW: Search -->
<div class="view" id="viewSearch">
    <div class="section-label">Search</div>
    <div id="searchFilters"></div>
    <div id="searchResults"></div>
</div>
```

**JS: `loadSearchTab()`:**
1. Render filter bar:
   - Text input: "Search alerts..."
   - Matter dropdown (populated from `GET /api/matters`)
   - Tag dropdown (populated from `GET /api/tags`)
   - Source dropdown: hardcoded options (Email, WhatsApp, Meeting, ClickUp, RSS, Manual)
   - Date from/to inputs (type="date")
   - Search button
2. On search: call `GET /api/alerts/search` with all filter params
3. Render results as alert cards (reuse `renderAlertCard`)
4. Show result count: "12 results"

**Debounced live search:** Reuse the `debounce()` utility from Phase B. On text input change (300ms debounce), auto-search if query ≥ 3 chars.

**Wire up:** Add `'people'` and `'search'` to `FUNCTIONAL_TABS` and `TAB_VIEW_MAP`. Add `loadPeopleTab()` and `loadSearchTab()` to `switchTab()`.

---

## Step 2 — Travel Tab + Media Tab

### 2a. Travel tab

Travel is a **filtered alert view** — alerts tagged with `'travel'` that haven't passed their travel date.

**No new backend endpoint needed** for MVP. Reuse `GET /api/alerts/by-tag/travel` (from Phase B).

However, travel items need a **travel date** to know when they expire. Currently there's no travel_date field.

**Schema change:** Add `travel_date DATE` column to alerts table.

**Where:** `memory/store_back.py` — add to `_ensure_alerts_v3_columns()`:
```python
# Add travel_date if missing
try:
    cur.execute("ALTER TABLE alerts ADD COLUMN travel_date DATE")
except Exception:
    conn.rollback()
    conn = self._get_conn()  # get fresh connection after rollback
```

**Frontend:**

**HTML:**
```html
<!-- VIEW: Travel -->
<div class="view" id="viewTravel">
    <div class="section-label">Travel</div>
    <div id="travelContent"></div>
</div>
```

**JS: `loadTravelTab()`:**
1. Fetch `GET /api/alerts/by-tag/travel`
2. Split into two groups:
   - **Upcoming:** `travel_date` is in the future or null (show all, sorted by travel_date ASC)
   - **Past:** `travel_date` is in the past (dimmed, collapsed by default)
3. Render each as a compact card with travel date prominently displayed
4. If no travel items: "No travel alerts. Travel-related emails and bookings will appear here when detected."

**Wire up:** Add `'travel'` to `FUNCTIONAL_TABS` and `TAB_VIEW_MAP`.

### 2b. Media tab (RSS)

**Where:** `outputs/dashboard.py`

**Endpoint: `GET /api/rss/articles`**

```python
@app.get("/api/rss/articles", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_rss_articles(
    category: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
):
```

Implementation:
1. Query: `SELECT a.*, f.title as feed_title, f.category FROM rss_articles a JOIN rss_feeds f ON a.feed_id = f.id WHERE f.is_active = true ORDER BY a.published_at DESC LIMIT %s`
2. If `category` provided: add `AND f.category = %s`
3. Response: `{"articles": [...], "count": N}`

**Endpoint: `GET /api/rss/feeds`**

```python
@app.get("/api/rss/feeds", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_rss_feeds():
```

List active feeds with article counts. For the category filter dropdown.

**Frontend:**

**HTML:**
```html
<!-- VIEW: Media -->
<div class="view" id="viewMedia">
    <div class="section-label">Media</div>
    <div id="mediaContent"></div>
</div>
```

**JS: `loadMediaTab()`:**
1. Fetch `GET /api/rss/feeds` for the category filter
2. Fetch `GET /api/rss/articles`
3. Render filter bar: category dropdown (from feeds data)
4. Render articles grouped by date (Today, Yesterday, This Week, Older):
   - Article card: title (clickable link), feed name, published date, summary preview (first 200 chars)
   - External link opens in new tab
5. If no articles: "No media items yet. RSS feeds are polled every hour."

**Wire up:** Add `'media'` to `FUNCTIONAL_TABS` and `TAB_VIEW_MAP`.

**CSS:**
```css
.article-card {
    padding: 12px 16px; border-bottom: 1px solid var(--border-light);
}
.article-card:hover { background: var(--hover); }
.article-title {
    font-size: 13px; font-weight: 500; color: var(--text);
    text-decoration: none; line-height: 1.4;
}
.article-title:hover { color: var(--blue); }
.article-meta {
    font-size: 10px; color: var(--text3); margin-top: 4px;
    font-family: var(--mono);
}
.article-summary {
    font-size: 12px; color: var(--text2); margin-top: 4px;
    line-height: 1.5;
}
```

---

## Step 3 — Alert Auto-Expiry

### 3a. Expiry job

**Where:** `triggers/embedded_scheduler.py` (schedule) + new function in `orchestrator/pipeline.py` or `memory/store_back.py`

**Function: `run_alert_expiry_check()`**

```python
def run_alert_expiry_check():
    """Auto-expire stale alerts. Runs every 6 hours.
    Rules:
    - T2/T3/T4 alerts older than 3 days → expired
    - T1 alerts NEVER auto-expire
    - Travel-tagged alerts NEVER auto-expire (handled by travel_date)
    """
```

Implementation:
1. Query: `SELECT id, tier, tags FROM alerts WHERE status = 'pending' AND exit_reason IS NULL AND tier >= 2 AND created_at < NOW() - INTERVAL '3 days'`
2. For each alert: check if `'travel'` is in tags — if so, skip (travel never auto-expires)
3. Update: `UPDATE alerts SET status = 'dismissed', exit_reason = 'expired' WHERE id = %s`
4. Log: `logger.info(f"Auto-expired {count} stale alerts (T2/T3/T4, >3 days old)")`

**Schedule in `embedded_scheduler.py`:**
```python
scheduler.add_job(
    run_alert_expiry_check,
    'interval',
    hours=6,
    id='alert_expiry',
    name='Alert auto-expiry (T2-T4, 3-day rule)',
    replace_existing=True,
)
```

### 3b. Cleanup

**Remove stale "Coming soon" label entries** from `app.js` if any remain after wiring up all 4 new tabs. After Phase C, NO tabs should show "Coming soon" — all 11 sidebar tabs are functional.

**Verify the labels object** (around line 140-147 in app.js) — remove entries for tabs that are now functional.

---

## CRITICAL Rules

1. **All SQL is parameterized.** The search endpoint builds dynamic WHERE clauses — use a list of conditions and a params tuple. No string concatenation.

2. **All dynamic text uses `esc()`.** Article titles from RSS are external data — must be escaped. Person names from DB are semi-trusted but still escape.

3. **T1 alerts NEVER auto-expire.** The expiry job must check `tier >= 2`. T1 fires stay until Director resolves or dismisses.

4. **Travel-tagged alerts NEVER auto-expire.** Check tags before expiring. They persist until `travel_date` passes.

5. **Person activity uses ILIKE with parameterized queries.** The `%name%` pattern goes through `%s` — no f-string interpolation into SQL.

6. **RSS article links open in new tab** (`target="_blank"` with `rel="noopener"`). External URLs must not be rendered as clickable without `esc()` on the URL and `rel="noopener"` for security.

---

## Existing Code Reference

| What | Where | Notes |
|------|-------|-------|
| `vip_contacts` table | `models/deadlines.py:95` | Schema + 11 seed records |
| `contacts` table | `init_database.sql:13` | Schema + indexes + 10 seed records |
| `GET /api/contacts/{name}` | `dashboard.py:1471` | Existing fuzzy match — reference for People |
| `email_messages` table | `init_database.sql` | sender_name, sender_email, received_date |
| `whatsapp_messages` table | `init_database.sql` | sender_name, full_text, timestamp |
| `meeting_transcripts` table | `init_database.sql` | organizer, participants, meeting_date |
| `GET /api/search` | `dashboard.py:1489` | Existing semantic search — separate from alert search |
| `GET /api/alerts/by-tag/{tag}` | `dashboard.py` (Phase B) | Reuse for Travel tab |
| `rss_feeds` + `rss_articles` tables | `triggers/state.py:57` | Full schema, managed by RSS trigger |
| `/api/rss/import-opml` | `dashboard.py:2910` | Existing RSS endpoint |
| `run_rss_poll()` | `triggers/rss_trigger.py:51` | RSS polling, runs every 60 min |
| `embedded_scheduler.py` | `triggers/` | 12 existing jobs, add expiry as #13 |
| `_ensure_alerts_v3_columns()` | `store_back.py` | Add `travel_date` column here |
| `FUNCTIONAL_TABS` | `app.js:126` | Currently 7 tabs — add people, search, travel, media |
| `TAB_VIEW_MAP` | `app.js:116` | Currently 7 entries — add 4 new |
| `switchTab()` | `app.js:148` | Add 4 new `else if` branches |
| `debounce()` | `app.js` (Phase B) | Reuse for search live-search |
| `renderAlertCard()` | `app.js:330` | Reuse for search results + travel items |
| `populateAssignDropdowns()` | `app.js` (Phase B) | Call after rendering cards in search/travel |

---

## Gaps Brisen Must Address

| # | Gap | Where | What to do |
|---|-----|-------|------------|
| 1 | `people` not in FUNCTIONAL_TABS/TAB_VIEW_MAP | `app.js` | Add both |
| 2 | `search` not in FUNCTIONAL_TABS/TAB_VIEW_MAP | `app.js` | Add both |
| 3 | `travel` not in FUNCTIONAL_TABS/TAB_VIEW_MAP | `app.js` | Add both |
| 4 | `media` not in FUNCTIONAL_TABS/TAB_VIEW_MAP | `app.js` | Add both |
| 5 | No `viewPeople` HTML | `index.html` | Add view container |
| 6 | No `viewSearch` HTML | `index.html` | Add view container |
| 7 | No `viewTravel` HTML | `index.html` | Add view container |
| 8 | No `viewMedia` HTML | `index.html` | Add view container |
| 9 | No `travel_date` column on alerts | `store_back.py` | Add via _ensure_alerts_v3_columns() |
| 10 | No alert expiry scheduled job | `embedded_scheduler.py` | Add run_alert_expiry_check() |
| 11 | Stale "Coming soon" labels in app.js | `app.js` | Clean up after all tabs wired |

---

## Endpoints Summary (6 new)

| # | Endpoint | Method | Purpose |
|---|----------|--------|---------|
| 1 | `/api/people` | GET | List all contacts + VIPs merged |
| 2 | `/api/people/{name}/activity` | GET | Person's recent emails/WA/meetings |
| 3 | `/api/alerts/search` | GET | Structured alert search with filters |
| 4 | `/api/rss/articles` | GET | List RSS articles |
| 5 | `/api/rss/feeds` | GET | List active RSS feeds |
| 6 | (no endpoint) | — | Auto-expiry is a scheduled job, not an API |

---

## Commit Plan

```
Step 1: feat: COCKPIT-V3 C1 -- people tab + search tab
Step 2: feat: COCKPIT-V3 C2 -- travel tab + media tab
Step 3: feat: COCKPIT-V3 C3 -- alert auto-expiry + cleanup
```

3 commits on branch `feat/cockpit-v3-c`. Push to origin when complete. Code 300 will review before merge.
