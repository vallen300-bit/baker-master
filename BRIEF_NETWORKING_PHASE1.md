# Brief: NETWORKING-PHASE-1 — Networking Tab (Replacing People)

**Author:** Code 300 (Session 16)
**For:** Code Brisen
**Priority:** HIGH — Director-designed, replaces People tab
**Reference:** Full product spec saved by Director (Deal Flow & Networking Radar v1.0)

---

## Context

The "People" tab has been renamed to "Networking" in the sidebar. The current view is a flat name list with no tiers, no health indicators, no actions. This brief builds Phase 1: a functional networking radar.

## What to Build

### 1. DB Schema Changes

**Extend `vip_contacts` table:**

```sql
ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS contact_type VARCHAR(20);
-- Values: principal, introducer, operator, institutional, connector
ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS relationship_score INTEGER DEFAULT 0;
-- 0-100 composite score
ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS net_worth_tier VARCHAR(20);
-- <30M, 30-70M, 70-150M, 150-300M, 300-500M, 500M-1B, 1B+
ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS investment_thesis TEXT;
ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS personal_interests TEXT[];
ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS gatekeeper_name VARCHAR(200);
ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS gatekeeper_contact VARCHAR(200);
ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS last_contact_date TIMESTAMPTZ;
ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS sentiment_trend VARCHAR(20);
-- warming, stable, cooling
ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS source_of_introduction TEXT;
```

**New table — `contact_interactions`:**

```sql
CREATE TABLE IF NOT EXISTS contact_interactions (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER REFERENCES vip_contacts(id),
    channel VARCHAR(30), -- email, whatsapp, meeting, slack, phone
    direction VARCHAR(10), -- inbound, outbound
    timestamp TIMESTAMPTZ NOT NULL,
    subject TEXT,
    sentiment VARCHAR(20), -- positive, neutral, negative
    source_ref TEXT, -- email_id, fireflies_transcript_id, etc.
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**New table — `networking_events`:**

```sql
CREATE TABLE IF NOT EXISTS networking_events (
    id SERIAL PRIMARY KEY,
    event_name VARCHAR(300) NOT NULL,
    dates_start DATE,
    dates_end DATE,
    location VARCHAR(200),
    category VARCHAR(50), -- conference, gala, private_dinner, sporting, auction
    brisen_relevance_score INTEGER DEFAULT 5,
    source_url TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

Run these migrations in `store_back.py` `__init__()` alongside existing table creation.

### 2. API Endpoints

**New endpoints:**

- `GET /api/networking/contacts` — returns vip_contacts with new fields, supports `?type=principal&tier=1` filters
- `GET /api/networking/alerts` — returns contacts going cold (last_contact_date > threshold for their tier), unreciprocated outreach, upcoming events
- `GET /api/networking/events` — returns networking_events list
- `POST /api/networking/events` — create event (manual curation)
- `GET /api/networking/contact/{id}/interactions` — recent interactions from contact_interactions table
- `POST /api/networking/contact/{id}/action` — route an action button query to Baker (Ask Baker with contact context pre-loaded)

### 3. Frontend — Networking Tab

Replace the current People tab content (in `loadPeopleTab()` in app.js) with:

**A. Top: Alert Strip**

A horizontal bar showing:
- "X contacts going cold" (Tier 1: no contact 14+ days, Tier 2: 30+ days)
- "X unreciprocated" (2+ outbound with no reply in 14 days)
- Upcoming events with contact count

Each badge is clickable (scrolls to relevant contact or event).

**B. Middle: Contact List**

Filter buttons: **All · Principals · Introducers · Operators · Connectors**

Each row:
```
Left: Tier badge (T1/T2/T3)
Center: Name, Type, Last Contact relative time, Connected matters
Right: Health dot (red=needs attention, green=active, amber=cooling, grey=dormant)
```

Health dot logic:
- **Red**: Tier 1 + no contact 14+ days, OR Tier 2 + no contact 30+ days
- **Amber**: approaching threshold (within 7 days of going red)
- **Green**: recently contacted within threshold
- **Grey**: Tier 4-5 (watch list / research)

**Click any row** → expands to show:

1. **Quick stats line**: Last contact · Response time · Sentiment · Outbound ratio
2. **Recent interactions**: Last 5 from contact_interactions, with channel icon + date + subject
3. **Connected matters**: badges showing linked matter_slugs
4. **Action buttons** (6 buttons, each routes to Ask Baker with pre-loaded context):

| Button | What it does |
|--------|-------------|
| **New Topic** | Ask Baker: "Suggest a new conversation topic for [Name] based on their interests and recent news" |
| **Engaged by Brisen** | Ask Baker: "What topics has Dimitry previously discussed with [Name]? Search emails, meetings, WhatsApp." |
| **Engaged by Person** | Ask Baker: "What topics has [Name] shown interest in? Search their messages and meeting contributions." |
| **Possible Connector** | Ask Baker: "Who in my network could introduce me to [Name] or strengthen this relationship?" |
| **Possible Place** | Ask Baker: "Where could I naturally meet [Name]? Check upcoming events, shared locations, industry conferences." |
| **Possible Date** | Ask Baker: "When would be a good time to meet [Name]? Check calendar availability and their timezone/travel patterns." |

Each button calls `POST /api/networking/contact/{id}/action` with the action type. The endpoint pre-loads the contact profile as context and routes to `scan_chat()` with SSE streaming. Response appears inline below the buttons.

**C. Bottom: Events of Interest**

A simple list of upcoming events from `networking_events` table + any events found in RSS/press:
```
IHIF Berlin — Mar 31-Apr 2 · Conference · 4 contacts attending
MIPIM Cannes — Mar 11-14 · Conference · 2 contacts attending
Monaco Yacht Show — Sep 24-27 · Networking
```

Each event clickable → shows which contacts are linked + brief status.

### 4. Event Sourcing from Press/Internet

Add to the existing RSS trigger (`triggers/rss_trigger.py`):

When processing RSS articles, check if the article mentions an event (conference, gala, summit) with a date and location. If so, auto-create a `networking_events` record. Use simple keyword detection: "conference", "summit", "forum", "gala", "awards", combined with a date pattern and location.

This gives the Director a rolling feed of events without manual curation.

## Files to Modify

| File | Change |
|------|--------|
| `memory/store_back.py` | Add migrations for new columns + tables |
| `outputs/dashboard.py` | 4 new endpoints |
| `outputs/static/app.js` | Replace `loadPeopleTab()` with new networking UI |
| `outputs/static/index.html` | Already renamed to "Networking" (done by Code 300) |
| `triggers/rss_trigger.py` | Optional: event detection from RSS articles |

## What NOT to Build (Phases 2-6)

- Network map visualization (Phase 5)
- Prospecting automation / new contact discovery (Phase 4)
- Relationship scoring auto-calculation (Phase 2)
- Introduction fee tracking (Phase 6)
- LinkedIn scraping (deferred)
- Sentiment analysis on messages (Phase 2)

## Verification

1. Open Networking tab → see alert strip + contact list + events
2. Filter by contact type → list updates
3. Click a contact → expand shows stats + interactions + 6 action buttons
4. Click "New Topic" → Baker generates a topic suggestion with SSE streaming
5. Events section shows any manually created or RSS-detected events
