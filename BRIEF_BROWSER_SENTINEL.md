# BRIEF: BROWSER-1 — Browser Sentinel (10th Sentinel)

**Author:** Code Brisen
**Date:** 2026-03-08
**Status:** Ready for Code 300 review
**Branch:** `feat/browser-sentinel`

---

## What This Is

A new Browser Sentinel — Baker's 10th data source. Monitors websites for changes and extracts structured data on schedule.

**Two modes:**
- **Simple** (httpx + BeautifulSoup): static pages, free, instant
- **Browser** (Browser-Use Cloud API): JS-rendered pages, login flows, ~$0.01-0.05/task

**No Dockerfile. No new Render service.** Zero infrastructure change.

---

## Files Created

| File | Purpose |
|------|---------|
| `triggers/browser_client.py` | Dual-mode client (simple HTTP + Browser-Use Cloud API) |
| `triggers/browser_trigger.py` | Sentinel entry point, change detection, pipeline integration |

## Files Modified

| File | Change |
|------|--------|
| `config/settings.py` | Added `BrowserConfig` dataclass + `browser_check_interval` |
| `triggers/state.py` | Added `browser_tasks` + `browser_results` table DDL |
| `memory/store_back.py` | Added `baker-browser` Qdrant collection init |
| `triggers/embedded_scheduler.py` | Registered `browser_poll` job (every 30 min) |
| `outputs/dashboard.py` | Added 8 CRUD + run + status API endpoints |
| `requirements.txt` | Added `beautifulsoup4>=4.12.0` |

## MCP Server (separate repo: baker-mcp/)

| Tool | Purpose |
|------|---------|
| `baker_browser_tasks` | List/search monitored websites |
| `baker_browser_results` | List recent scraping results |

---

## API Endpoints

| Method | Path | Function |
|--------|------|----------|
| GET | `/api/browser/tasks` | List all tasks |
| POST | `/api/browser/tasks` | Create new task |
| GET | `/api/browser/tasks/{id}` | Get task + recent results |
| PUT | `/api/browser/tasks/{id}` | Update task config |
| DELETE | `/api/browser/tasks/{id}` | Soft-delete (deactivate) |
| GET | `/api/browser/results/{id}` | List result history |
| POST | `/api/browser/tasks/{id}/run` | Manual trigger |
| GET | `/api/browser/status` | Health check |

---

## PostgreSQL Tables

**`browser_tasks`** — Registry of what to monitor
**`browser_results`** — History of all results with content hashing for change detection

---

## Environment Variables

| Variable | Required | Default |
|----------|----------|---------|
| `BROWSER_USE_API_KEY` | Only for browser-mode tasks | — |
| `BROWSER_CHECK_INTERVAL` | No | 1800 (30 min) |

---

## How Baker Should Use This — Skills & Capabilities

### 1. Scan Integration (Immediate)
Baker's Scan can already query browser results via Qdrant (`baker-browser` collection).
**Example queries:**
- "What are the current room rates at MO Vienna on booking.com?"
- "Has anything changed on the Grundbuch entry for RG7?"
- "Show me the latest browser monitoring results"

### 2. Standing Order Integration (Phase 4+)
Browser tasks can feed into existing standing orders:

| Standing Order | Browser Use Case |
|---------------|------------------|
| **#1 Deadline Proposals** | Scrape regulatory sites for filing deadlines |
| **#3 Morning Briefing** | Include overnight price changes, competitor moves |
| **#5 Proactive Intelligence** | Monitor competitor hotel rates, news sites without RSS |
| **#7 Calendar Protection** | Pre-meeting competitor research via browser |

### 3. New Capability: Price Intelligence
**Hotel rate monitoring** — Create browser tasks for:
- booking.com (MO Vienna + competitors)
- expedia, hotels.com
- Direct competitor websites

Baker detects price changes → creates alert → includes in briefing.

### 4. New Capability: Document Harvesting
**Automated PDF/report downloads** from:
- Bank portals (Neon dashboard, UBS)
- Government registries (Grundbuch)
- Regulatory filings

Browser mode can log in, navigate, download → store in Baker's memory.

### 5. New Capability: Competitive Intelligence
**Monitor competitor websites** for:
- New property listings
- Press releases
- Management changes
- Rate promotions

Simple mode (free) for most sites. Browser mode for JS-heavy or paywalled sites.

### 6. Suggested First Tasks to Seed

```json
[
  {
    "name": "MO Vienna - Booking.com rates",
    "url": "https://www.booking.com/hotel/at/mandarin-oriental-vienna.html",
    "mode": "browser",
    "task_prompt": "Extract current room rates for all room types for the next 7 days. Return as structured data with room type, date, and price.",
    "category": "hotel_rates"
  },
  {
    "name": "Park Hyatt Vienna - Booking.com rates",
    "url": "https://www.booking.com/hotel/at/park-hyatt-vienna.html",
    "mode": "browser",
    "task_prompt": "Extract current room rates for all room types for the next 7 days.",
    "category": "hotel_rates"
  },
  {
    "name": "Austrian Grundbuch - RG7 Baden",
    "url": "https://www.justiz.gv.at/",
    "mode": "simple",
    "category": "public_records"
  }
]
```

---

## Review Checklist for Code 300

- [ ] `browser_client.py`: Singleton pattern correct, error handling robust
- [ ] `browser_trigger.py`: Follows RSS trigger pattern exactly (watermarks, dedup, failures)
- [ ] `settings.py`: BrowserConfig + TriggerConfig additions clean
- [ ] `state.py`: Table DDL correct, indexes present
- [ ] `dashboard.py`: API endpoints follow existing auth/error patterns
- [ ] `embedded_scheduler.py`: Job registration matches existing pattern
- [ ] `requirements.txt`: Only beautifulsoup4 added (no browser-use pip — we use Cloud API)
- [ ] MCP server: Two read tools added with correct SQL
- [ ] No breaking changes to existing code
