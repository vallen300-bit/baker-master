# BRIEF 5C — Dashboard Frontend

**Punch:** 5C of 5 (CEO Cockpit)
**Goal:** Single-page dashboard frontend that consumes the 5B REST API and renders Baker's CEO cockpit. Fresh build in `outputs/static/` — the Cowork HTML mockup (`02_working/baker_dashboard_v2.2_FINAL_DESIGN.html`) is a **visual reference only**, not source code.

---

## What Exists Today

| Layer | What exists | What's missing |
|-------|------------|----------------|
| **Dashboard API (5B)** | FastAPI on `:8080` — 7 endpoints returning JSON ✅ | No consumer — only cURL tested |
| **Static serving** | `outputs/static/` mounted at `/static`, root `/` serves `index.html` | Placeholder HTML with API links |
| **Cowork mockup** | `02_working/baker_dashboard_v2.2_FINAL_DESIGN.html` (1766 lines) | Static demo — hardcoded data, base64 images, no API calls |
| **Slack output (5A)** | `SlackNotifier` posting alerts + briefings ✅ | No dependency on dashboard |

**Key insight:** The API data layer is complete and tested. This brief adds a clean frontend that fetches live data and renders it using the mockup's visual design language — but built from scratch for dynamic data, not ported from the static HTML.

---

## Critical Directive

> **Fresh build.** The Cowork HTML (1766 lines) is a design mockup only — use it as visual reference for layout, sections, and hierarchy, but **don't port the code**. Production dashboard needs dynamic rendering from live data, not static HTML with base64 images. Build clean from scratch in `outputs/static/`.

---

## Design System (extracted from Cowork mockup)

### Fonts
```
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@300;400;500&family=Jura:wght@300;400;500;600;700&family=Work+Sans:wght@300;400;500;600&display=swap');
```
- **Jura** — brand title ("baker"), headings
- **Work Sans** — body text, cards, labels
- **DM Mono** — subtitle ("chief of staff"), metadata, timestamps, code-like values

### Colors

**Page background:** `#e8eaed` (light warm gray)

**Top bar gradient:** `#1e2636` → `#4d6080` (dark sky)

**Role-based accent colors:**

| Role | Accent | Dark variant | Use |
|------|--------|-------------|-----|
| Chairman | `#fbbf24` | `#8B5E00` | Gold — chairman-related items |
| Projects/PM | `#3b82f6` | `#0842A0` | Blue — project/deal items |
| Network | `#10b981` | `#046C4E` | Green — contact/network items |
| Private | `#a855f7` | `#6B21A8` | Purple — personal items |
| Travel | `#0891b2` | `#0E7490` | Cyan — travel items |

**Alert tier colors:**
| Tier | Color | Label |
|------|-------|-------|
| 1 (Urgent) | `#ef4444` (red) | 🔴 URGENT |
| 2 (Important) | `#f59e0b` (amber) | 🟡 IMPORTANT |
| 3 (Info) | `#3b82f6` (blue) | 🔵 INFO |

**Scan dot:** `#22c55e` (green) with pulse animation — "system operational" indicator

### Layout

- **App container:** max-width `1200px`, centered, `border-radius: 20px`, subtle shadow
- **Top bar:** full-width dark gradient, "baker" in Jura font, "chief of staff" in DM Mono, green pulse dot
- **Sidebar rail:** `180px` wide, vertical nav with role buttons (Home, Chairman, Projects, Network, Private, Travel)
- **Main content:** flexible, scrollable, padding `24px`
- **Footer:** muted text, "baker v2.1 · feb 2026"

### Responsive breakpoints
- `900px` — sidebar collapses to icons only
- `600px` — sidebar becomes top horizontal bar

---

## API Contract (from 5B — all confirmed working)

| Endpoint | Method | Response shape |
|----------|--------|---------------|
| `/api/status` | GET | `{"system": "operational"\|"degraded", "alerts_pending": N, "alerts_tier1": N, "alerts_tier2": N, "deals_active": N, "last_checked": "ISO"}` |
| `/api/alerts` | GET | `{"alerts": [{id, tier, title, body, action_required, contact_name, deal_name, status, created_at, ...}], "count": N}` |
| `/api/alerts?tier=1` | GET | Same shape, filtered by tier |
| `/api/alerts/{id}/acknowledge` | POST | `{"status": "acknowledged", "id": N}` |
| `/api/alerts/{id}/resolve` | POST | `{"status": "resolved", "id": N}` |
| `/api/deals` | GET | `{"deals": [{id, name, stage, value, ...}], "count": N}` |
| `/api/contacts/{name}` | GET | `{id, name, role, company, email, phone, ...}` (fuzzy match) |
| `/api/decisions` | GET | `{"decisions": [{id, decision, reasoning, confidence, trigger_type, created_at}], "count": N}` |
| `/api/decisions?limit=N` | GET | Same shape, custom limit (max 50) |
| `/api/briefing/latest` | GET | `{"date": "YYYY-MM-DD"\|null, "content": "markdown"\|"No briefings found.", "filename": "..."\|null}` |

---

## Files to Create

### 1. `outputs/static/index.html` (~80 lines)

Replace the current placeholder. Minimal shell that loads CSS + JS. No inline content — all rendering is in `app.js`.

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Baker · CEO Dashboard</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@300;400;500&family=Jura:wght@300;400;500;600;700&family=Work+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <div id="app">
        <!-- Top bar -->
        <header id="topBar">
            <div class="brand">
                <span class="brand-title">baker</span>
                <span class="brand-sub">chief of staff</span>
            </div>
            <div class="status-area">
                <span id="scanDot" class="scan-dot"></span>
                <span id="statusLabel" class="status-label">connecting...</span>
            </div>
        </header>

        <!-- Layout: sidebar + main -->
        <div id="layout">
            <!-- Sidebar rail -->
            <nav id="sideRail">
                <button class="rail-btn active" data-section="home">Home</button>
                <button class="rail-btn" data-section="alerts">Alerts</button>
                <button class="rail-btn" data-section="deals">Deals</button>
                <button class="rail-btn" data-section="decisions">Decisions</button>
                <button class="rail-btn" data-section="briefing">Briefing</button>
            </nav>

            <!-- Main content area -->
            <main id="mainContent">
                <!-- Sections rendered by app.js -->
                <div id="homeSection" class="section active"></div>
                <div id="alertsSection" class="section"></div>
                <div id="dealsSection" class="section"></div>
                <div id="decisionsSection" class="section"></div>
                <div id="briefingSection" class="section"></div>

                <!-- Loading state -->
                <div id="loadingOverlay" class="loading">
                    <span>Loading...</span>
                </div>
            </main>
        </div>

        <!-- Footer -->
        <footer id="appFooter">
            <span>auto-refresh every 60s</span>
            <span>baker v2.1 · feb 2026</span>
        </footer>
    </div>

    <script src="/static/app.js"></script>
</body>
</html>
```

**Navigation model:** The Cowork mockup uses a 3-layer drill-down (Home → Category → Detail) with 5 role-based categories. For the **production build**, simplify to a **flat section model** with sidebar tabs: Home (overview), Alerts, Deals, Decisions, Briefing. This matches the actual API surface and avoids empty stub sections (the mockup's "Chairman", "Travel", etc. categories have no backend endpoints). The role-based structure can be layered in later when those data sources exist.

**Rationale:** Baker's PostgreSQL has alerts, deals, contacts, decisions, and briefings. It does NOT have role-based categorization (chairman items vs. project items vs. travel items). The mockup's 5-role taxonomy is aspirational — the production dashboard should only render what the API can actually serve.

---

### 2. `outputs/static/style.css` (~350 lines)

Full CSS implementing the design system above.

**Key sections:**

```
/* === Reset & Base === */
/* Box-sizing, body background (#e8eaed), font (Work Sans) */

/* === App Shell === */
/* #app: max-width 1200px, centered, border-radius 20px, shadow */

/* === Top Bar === */
/* Dark gradient (#1e2636 → #4d6080), flexbox row */
/* .brand-title: Jura 700, 1.6rem, white */
/* .brand-sub: DM Mono 300, 0.75rem, rgba(255,255,255,0.6) */
/* .scan-dot: 8px circle, #22c55e, pulse animation */
/* .status-label: DM Mono, 0.7rem */

/* === Layout === */
/* #layout: flex row */
/* #sideRail: 180px, flex-shrink 0, vertical buttons */
/* #mainContent: flex 1, overflow-y auto, padding 24px */

/* === Rail Buttons === */
/* .rail-btn: full-width, text-align left, Work Sans 500 */
/* .rail-btn.active: left border accent, background tint */

/* === Sections === */
/* .section: display none */
/* .section.active: display block, fadeUp animation */

/* === Cards === */
/* .card: white bg, border-radius 12px, padding 20px, shadow */
/* .card-header: flex row, title + metadata */
/* .card-tier-1: left border 3px #ef4444 */
/* .card-tier-2: left border 3px #f59e0b */
/* .card-tier-3: left border 3px #3b82f6 */

/* === Stats Row === */
/* .stats-row: flex row, gap 16px */
/* .stat-card: flex 1, centered, large number + label */

/* === Briefing === */
/* .briefing-content: DM Mono, pre-wrap, white bg, padding */

/* === Alert Actions === */
/* .btn-ack, .btn-resolve: small pill buttons */

/* === Animations === */
/* @keyframes fadeUp: translateY(12px) → 0, opacity 0 → 1, 0.35s */
/* @keyframes pulse: scale(1) → 1.6, opacity 1 → 0, 2s infinite */

/* === Responsive === */
/* @media (max-width: 900px): rail collapses, labels hidden */
/* @media (max-width: 600px): rail becomes top bar, stack vertical */

/* === Footer === */
/* Muted text, DM Mono, centered, padding 12px */

/* === Loading / Error === */
/* Centered spinner or message */
```

**Implementation notes:**
- No CSS framework — hand-written to match the mockup's visual language
- Use CSS custom properties (`--color-accent`, `--color-tier1`, etc.) for easy theming
- Cards use `backdrop-filter` or plain white bg depending on browser support
- Animations are subtle — `fadeUp` on section switch, `pulse` on scan dot

---

### 3. `outputs/static/app.js` (~400 lines)

Vanilla JavaScript. No React, no build step, no bundler. Fetches from the 5B API and renders sections dynamically.

**Architecture:**

```javascript
// === State ===
let currentSection = 'home';
let refreshTimer = null;
const REFRESH_INTERVAL = 60_000; // 60 seconds

// === API Layer ===
async function api(path) { /* fetch, parse JSON, handle errors */ }

// === Data Fetchers ===
async function fetchStatus() { return api('/api/status'); }
async function fetchAlerts(tier = null) { /* optional tier param */ }
async function fetchDeals() { return api('/api/deals'); }
async function fetchDecisions(limit = 20) { /* limit param */ }
async function fetchBriefing() { return api('/api/briefing/latest'); }

// === Renderers ===
function renderHome(status, alerts, deals) { /* overview cards */ }
function renderAlerts(alerts) { /* alert cards with ack/resolve buttons */ }
function renderDeals(deals) { /* deal cards */ }
function renderDecisions(decisions) { /* decision timeline */ }
function renderBriefing(briefing) { /* markdown content display */ }
function renderStatusBar(status) { /* top bar system status */ }

// === Navigation ===
function showSection(name) { /* toggle .active, load data for section */ }

// === Alert Actions ===
async function acknowledgeAlert(id) { /* POST, then re-render */ }
async function resolveAlert(id) { /* POST, then re-render */ }

// === Auto-refresh ===
function startRefresh() { /* setInterval, refresh active section */ }
function stopRefresh() { clearInterval(refreshTimer); }

// === Init ===
document.addEventListener('DOMContentLoaded', init);
async function init() { /* wire nav buttons, load home, start refresh */ }
```

**Section-by-section rendering:**

#### Home Section
- **Stats row:** 4 stat cards from `/api/status`:
  - "Alerts Pending" (count, red if tier1 > 0)
  - "Tier 1 (Urgent)" (count)
  - "Active Deals" (count)
  - "System" (operational / degraded)
- **Recent alerts:** Last 3 alerts from `/api/alerts` — compact card preview
- **Latest briefing:** Date + first 300 chars of `/api/briefing/latest` content, with "View full →" link that switches to Briefing section

#### Alerts Section
- **Tier filter tabs:** All | Urgent (1) | Important (2) | Info (3)
- **Alert cards:** For each alert:
  - Left border color by tier (red/amber/blue)
  - Title (bold), body text, created_at timestamp (DM Mono)
  - Contact name and deal name if present
  - Action buttons: "Acknowledge" / "Resolve" (POST to API, then re-fetch)
- **Empty state:** "No pending alerts — Baker is watching."

#### Deals Section
- **Deal cards:** For each deal:
  - Name (heading), stage badge, value (formatted)
  - Any additional fields from the API response
- **Empty state:** "No active deals tracked."

#### Decisions Section
- **Timeline layout:** Vertical timeline with decision cards
- For each decision:
  - Decision text, reasoning (collapsible), confidence (percentage bar or badge)
  - Trigger type badge, created_at timestamp
- **Limit selector:** Show 10 / 20 / 50

#### Briefing Section
- **Date header:** "Morning Briefing — YYYY-MM-DD"
- **Content area:** Render briefing markdown as formatted text
  - Use a simple markdown-to-HTML conversion (headings, bold, lists, links)
  - Or render as preformatted text in DM Mono (simpler, still readable)
- **Empty state:** "No briefings available yet."

**Markdown rendering:** For the briefing content, implement a minimal markdown renderer (~30 lines) that handles: `# headings`, `**bold**`, `- lists`, `[links](url)`, `\n` → `<br>`. No external library needed — the briefing format is predictable.

**Error handling:**
- If an API call fails, show inline error message in that section (not a full-page crash)
- Status bar changes scan dot to red + "degraded" if `/api/status` returns `system: "degraded"` or errors
- All fetches use try/catch — network errors are caught and displayed gracefully

**No authentication:** Dashboard is local-only (as specified in 5B — no auth needed).

---

## Files to Modify

### None.

All 3 files are new creates in `outputs/static/`. The existing `dashboard.py` (5B) already serves this directory — no backend changes needed.

---

## Dependencies

**None.** Pure HTML/CSS/JS — no npm, no build step, no bundler.

The fonts are loaded from Google Fonts CDN. If offline access is needed later, fonts can be self-hosted in `outputs/static/fonts/`.

---

## How to Run

```bash
# From 01_build/ directory (same as 5B):
uvicorn outputs.dashboard:app --host 0.0.0.0 --port 8080 --reload

# Then open: http://localhost:8080
# The dashboard loads immediately — no build step.
```

---

## Test Plan

### Manual tests (run in order):

```bash
# 1. Make sure the API is running
uvicorn outputs.dashboard:app --host 0.0.0.0 --port 8080 &
sleep 2

# 2. Verify index.html loads (not the old placeholder)
curl -s http://localhost:8080 | head -5
# Expected: <!DOCTYPE html> with "Baker · CEO Dashboard" title
# NOT: "API is running. Frontend will be deployed in Brief 5C."

# 3. Verify CSS loads
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/static/style.css
# Expected: 200

# 4. Verify JS loads
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/static/app.js
# Expected: 200

# 5. Verify no console errors (browser test)
# Open http://localhost:8080 in browser
# Open DevTools Console
# Expected: No JavaScript errors
# Expected: Network tab shows successful fetches to /api/status, /api/alerts, etc.

# 6. Verify Home section renders
# Expected: Stats row shows alert count, deal count, system status
# Expected: Recent alerts preview (up to 3)
# Expected: Briefing preview

# 7. Verify Alerts section
# Click "Alerts" in sidebar
# Expected: Alert cards with tier coloring
# Expected: Tier filter tabs work (All/Urgent/Important/Info)

# 8. Verify alert acknowledge
# Click "Acknowledge" on an alert card
# Expected: Card updates or disappears, count decreases

# 9. Verify alert resolve
# Click "Resolve" on an alert card
# Expected: Card removed from list, count decreases

# 10. Verify Deals section
# Click "Deals" in sidebar
# Expected: Deal cards rendered from API data

# 11. Verify Decisions section
# Click "Decisions" in sidebar
# Expected: Decision timeline rendered from API data
# Expected: Limit selector changes number of items shown

# 12. Verify Briefing section
# Click "Briefing" in sidebar
# Expected: Latest briefing content displayed with date header

# 13. Verify auto-refresh
# Wait 60 seconds (or temporarily set REFRESH_INTERVAL to 5000 for testing)
# Expected: Data refreshes without page reload
# Expected: No visible flicker during refresh

# 14. Verify responsive layout
# Resize browser to 900px wide → sidebar should collapse to icons
# Resize to 600px → sidebar becomes horizontal top bar

# 15. Verify error handling
# Stop the API server (kill uvicorn)
# Refresh the dashboard
# Expected: Scan dot turns red, status shows "degraded" or connection error
# Expected: No JavaScript crash — sections show inline error messages

# 16. Stop server
kill %1
```

### Success criteria:
1. `http://localhost:8080` serves the production dashboard (not placeholder)
2. All 3 static assets load (HTML, CSS, JS) — status 200
3. Home section shows live data from `/api/status`, `/api/alerts`, `/api/briefing/latest`
4. Alerts section renders all pending alerts with correct tier coloring
5. Alert acknowledge/resolve buttons work (POST to API, UI updates)
6. Deals and Decisions sections render live data
7. Briefing section displays latest briefing markdown content
8. Auto-refresh updates data every 60 seconds without page reload
9. Responsive layout works at 900px and 600px breakpoints
10. API failures show inline error messages, not page crashes
11. No console errors in normal operation

---

## What NOT to build in 5C

- ❌ No build system (no npm, webpack, vite — plain HTML/CSS/JS)
- ❌ No framework (no React, Vue, Svelte)
- ❌ No role-based categories (Chairman, Projects, Network, Private, Travel) — the API doesn't serve role-tagged data yet. The sidebar uses **data-type sections** (Alerts, Deals, Decisions, Briefing) that map 1:1 to existing endpoints
- ❌ No contact search UI (the `/api/contacts/{name}` endpoint exists but a search box can be added later)
- ❌ No WebSocket (60-second polling is sufficient at this scale)
- ❌ No authentication (local-only, per 5B)
- ❌ No Baker's Scan / AI chat overlay (the mockup has this, but it requires a separate LLM endpoint — defer to a future punch)
- ❌ No base64 embedded images or icons (use CSS-only indicators, Unicode symbols, or simple SVG inline)

---

## Architecture Note

```
┌─────────────────────┐     ┌────────────────────┐     ┌──────────────────┐
│  Scheduler Process   │────▶│   PostgreSQL (Neon) │◀────│  FastAPI (5B)    │
│  (triggers + pipeline)│     └────────────────────┘     │  :8080           │
└─────────────────────┘                                  └────────┬─────────┘
                                                                  │ serves
                                                         ┌────────┴─────────┐
                                                         │  Static Files    │
                                                         │  (5C)            │
                                                         │  index.html      │
                                                         │  style.css       │
                                                         │  app.js          │
                                                         └────────┬─────────┘
                                                                  │ fetches
                                                         ┌────────┴─────────┐
                                                         │  Browser         │
                                                         │  /api/status     │
                                                         │  /api/alerts     │
                                                         │  /api/deals      │
                                                         │  /api/decisions  │
                                                         │  /api/briefing   │
                                                         └──────────────────┘
```

The FastAPI server (5B) serves both the static frontend files and the JSON API. The browser fetches data via `fetch()` to the same origin — no CORS issues in production.

---

## File Checklist

| # | Action | File | ~Lines |
|---|--------|------|--------|
| 1 | REPLACE | `outputs/static/index.html` (overwrite placeholder) | ~80 |
| 2 | CREATE | `outputs/static/style.css` | ~350 |
| 3 | CREATE | `outputs/static/app.js` | ~400 |

**Total new code:** ~830 lines across 3 files.
