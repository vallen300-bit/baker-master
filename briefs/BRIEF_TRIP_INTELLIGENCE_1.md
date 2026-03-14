# BRIEF: TRIP-INTELLIGENCE-1 — Baker's Travel ROI Engine

**Author:** AI Head + Director (brainstorm session)
**Date:** 2026-03-14
**Status:** APPROVED FOR DEVELOPMENT
**Effort:** 4-5 sessions (phased)
**Supersedes:** BRIEF_LOCATION_AWARENESS_1.md (folded in as Batch 0)

---

## Strategic Intent

Every trip is an investment. A conference costs ~EUR 20,000 (airfare, hotel, car, time). A meeting trip to Baden-Baden costs ~EUR 3,000. Even a personal trip has logistics that need attention. Baker's job: maximize the return on every trip — contacts, contracts, introductions, intelligence — and handle the logistics so the Director's mind is free for what matters.

## Core Concept

When a flight or travel event appears on the Director's calendar, Baker creates a **Trip Card** — a living, full-screen workspace that accumulates context over days/weeks, activates full prep when confirmed, guides the Director through the trip, and feeds outcomes into the Networking section after.

The trip is ephemeral (dies 2 days after return). The relationships and intelligence it produced are permanent.

---

## Trip Classification

### Categories (what kind of trip)

| Category | Example | Baker's Prep Level |
|---|---|---|
| **Meeting** | Baden-Baden to meet Andrey Oskolkov at Brisen office | Counterparty dossier, internal team agenda, opportunistic radius (what's happening in transit cities) |
| **Event** | NVIDIA GTC in San Jose, MIPIM in Cannes, IHIF in Berlin | Full ROI — conference attendees, speaker research, outreach drafts (proactive flag), scheduled meetings, market intel |
| **Personal** | Family trip to Mallorca, weekend in Cap Ferrat | Full logistics (flights, hotel, car, restaurant). Friend messages. No business prep unless manually toggled. |

### Status (lifecycle)

| Status | Color (font) | Meaning | Baker's Action |
|---|---|---|---|
| **Planned** | Blue | Considering going, maybe tickets bought | Light prep — track event, start researching attendees. Accumulate notes. No outreach. |
| **Confirmed** | Green | Going for sure | Full prep activates — trip card, conference intelligence, outreach drafts, reading list |
| **Discarded** | Red | Was planned, cancelled (e.g. MIPIM ticket lost) | Archive. Note financial loss if relevant. |
| **Completed** | Orange | Trip happened, wrapping up | Outcomes logging active. Fades from dashboard +2 days after return date. Data flows to Networking. |

### Auto-classification Rules

| Signal | Classification |
|---|---|
| Geneva | Always Personal/home — no trip card |
| Zurich | Home — no card |
| Vienna, Frankfurt | Commute — logistics-only card by default |
| Commute city + conference on calendar | Auto-upgrade to Event + Confirmed |
| Flight to non-commute city | Meeting or Event (Planned). Baker guesses based on calendar context. |
| Any ambiguity | **Manual toggle always visible**: `Meeting | Event | Personal` button on route card |

**Key rule:** If Baker didn't classify as business and didn't prepare the Trip Card properly, the Director can always click the Business toggle on the route card. Baker then generates full prep retroactively. No WhatsApp needed — one tap.

**Commute cities** stored in `director_preferences` table (category: `domain_context`, key: `commute_cities`, value: `Geneva, Vienna, Frankfurt`).

---

## Trip Card — Full Screen View

Clicking a route card on the landing grid opens a full-screen trip workspace. Back button returns to landing grid.

### Card Sequence

| # | Card | Category: Meeting | Category: Event | Category: Personal |
|---|---|---|---|---|
| 1 | **Trip Logistics & Comms** | Full | Full | Full |
| 2 | **Why You're Going** | Meeting objective | Event strategic purpose | — |
| 3 | **Daily Agenda** | Meeting schedule + internal team | Event schedule + side meetings | Light itinerary |
| 4 | **People to Meet** | Counterparty dossier + internal team prep | Conference attendee intelligence + outreach | — |
| 5 | **Flight Reading** | Curated 3-5 items | Curated 3-5 items | — |
| 6 | **Opportunistic Radar** | What's happening in transit/destination cities | Local market intel | Local recommendations |
| 7 | **Europe While You Sleep** | Active monitoring | Active monitoring | Light |
| 8 | **Trip Outcomes** | Post-trip: contacts, decisions, follow-ups | Post-trip: contacts, deals, introductions | — |

### Card 1: Trip Logistics & Comms

Everything the Director needs walking to the gate:
- Hotel: name, address, confirmation number, check-in time
- Ground transport: car rental confirmation, transfer details
- All WhatsApp messages related to the trip (friend messages, logistics chats)
- All emails related to the trip (booking confirmations, travel agent)
- Weather at destination
- Time difference: "SF is -9h from CET. When it's 9am for you, it's 6pm in Vienna."

**Data source:** Baker searches WhatsApp + emails for messages containing destination name, hotel name, dates, travel-related keywords within the trip date range.

### Card 2: Why You're Going

Not logistics — **purpose**.
- "You're attending GTC to evaluate AI applications for Project clAIm and explore tech partnerships."
- "Meeting with AO to discuss Baden-Baden project financing and Siegfried's capex proposal."

**Data source:** Baker infers from calendar event descriptions, recent emails about the trip, Director's notes. If unclear, Baker asks once via WhatsApp when trip goes to Confirmed.

### Card 3: Daily Agenda (Live, Updatable)

Clean daily timeline in local time (not CET). Updated in real-time.

**Input channels for updates:**
- Calendar sync (automatic)
- WhatsApp: "Baker, meeting with John tomorrow 3pm at Blue Bottle" — Baker updates agenda
- Dashboard: editable agenda on the trip card

**Output:** Formatted daily itinerary, not raw data. Human-readable.

**Networking link:** Every person appearing in the agenda is tagged with: when met, where, context. After the trip, this feeds into the Networking section.

### Card 4: People to Meet

#### For Meeting trips:
- **Counterparty dossier** (deep): AO's recent activity, deal history with Brisen, last meeting summary, outstanding commitments (both ways), negotiation context
- **Internal team prep**: What does Siegfried need to discuss? What has Merz been working on? Recent emails/ClickUp between Director and team.
- **Commitments**: "You promised AO a tour of the Vienna site (Nov 2025)" / "AO owes updated valuation report"

#### For Event trips:
- **Conference intelligence**: Baker researches attendee list (public: speakers, sponsors, exhibitors. LinkedIn: attendee profiles via Proxycurl)
- **Ranked by ROI potential**:

| ROI Type | What Baker Looks For |
|---|---|
| Deal lead | AUM, portfolio, past luxury/RE investments, LP interest signals |
| Introduction multiplier | Board seats, network breadth, mutual connections |
| Strategic partnership | Capabilities matching Director's open needs (tech, operations) |
| Competitive intelligence | Developers doing similar projects in other markets |
| Relationship upgrade | Existing contacts attending — time to deepen |

- **Research: autonomous.** Baker scans, profiles, ranks without being asked.
- **Outreach: proactive flag only.** Baker drafts the message, Director approves before send.
- **LinkedIn integration via Proxycurl** (~EUR 40/month): profile lookup by name + company. Enrich with role, company, recent posts, mutual connections.

### Card 5: Flight Reading

Baker curates 3-5 items for long flights:
- Unread high-priority documents (legal opinions, valuation reports)
- Emails needing thoughtful replies (not quick answers)
- Deal memos awaiting decision
- Background reading relevant to the trip destination/purpose

**Baker picks. Director can swap items out.** No need to ask — Baker knows the inbox.

**Selection logic:** Priority score = (days_unread * importance_weight) + trip_relevance_bonus. Items related to the trip destination or contacts get boosted.

### Card 6: Opportunistic Radar

**Medium aggressiveness** (to be upgraded to Full later when quality proven):
- Flag dormant contacts in transit/destination cities: "You have 3 contacts in Frankfurt. Last spoke to X in January."
- Search for public events in transit cities: "PropTech meetup in Frankfurt on the 15th"
- NOT yet: proactive recommendations like "visit this development site"

### Card 7: Europe While You Sleep

Baker monitors Europe while the Director is in a different timezone:
- Urgent emails that arrived (above threshold)
- Deadline triggers
- VIP messages
- Morning briefing items queued

Surfaces as a summary when the Director wakes up in the destination timezone.

### Card 8: Trip Outcomes (Post-Trip)

Active for 2 days after return date.
- Dashboard form: "Who did you meet? Key takeaways? Follow-ups?"
- WhatsApp: "Baker, met Sarah Chen at GTC. She runs a RE tech fund. Follow up next week."
- **Passive pickup**: Baker extracts outcomes from post-trip emails, Fireflies meeting transcripts, WhatsApp conversations

All outcomes flow to Networking section: new contacts created, existing contacts updated with latest interaction, follow-up commitments tracked.

---

## Trip Context Accumulator (The "Trip Folder")

The trip card starts accumulating context from the moment it's created (Planned status). Three input channels feed the same place:

### 1. WhatsApp (lightweight, natural)
> "For Baden-Baden: AO owes us the updated valuation report"
> "For GTC: check if Jensen's keynote is on Day 1"

Baker matches to trip by destination, person name, or event name. If ambiguous: "Is this for your Baden-Baden trip Apr 5 or your Frankfurt trip Apr 12?"

### 2. Dashboard (structured)
Text input on the trip card — even in Planned status. All notes visible when you open the trip.

### 3. Passive pickup (Baker does it himself)
Baker's pipeline scans emails and WhatsApp. When content relates to a future trip (mentions the person, destination, event), Baker auto-links it to the trip context. Not a copy — a reference: "Email from Siegfried (Mar 20) re Baden-Baden capex — attached to your Apr 5 trip."

### 4. Networking section (reverse pull)
When the Networking matrix is built, Baker pulls relationship data automatically: last meeting, commitments, deal history. The Director only needs to add what Baker can't know — political context, soft signals, feelings about a relationship.

---

## Commitment/Deadline Unification

**Current state:** Commitments and deadlines are split across two systems (`deadlines` table + commitment checker). This creates a problem for Trip Intelligence — "what's owed/promised" for each contact lives in two places.

**Proposed merge:** One unified `obligations` concept with severity levels:

| Severity | Color | Meaning | Example |
|---|---|---|---|
| **Hard** | Red | Legal, contractual, regulatory. Financial/legal consequence if missed. | Hagenauer Gewaehrleistungsfrist expires Mar 2027 |
| **Firm** | Amber | Promised with a date. Relationship damage if missed. | AO: deliver valuation report by April 1 |
| **Soft** | Blue | Mentioned, no specific date. Social expectation. | "We should visit the Vienna site together sometime" |

**Implementation:** Add `severity` column to `deadlines` table. Migrate commitment data into deadlines with `severity = 'firm'` or `'soft'`. One table, one tracker, one query for the Trip Card.

**Deferred to:** Separate brief (OBLIGATIONS-UNIFY-1). Trip Intelligence v1 reads from both tables; unification happens in parallel.

---

## Data Model

### New table: `trips`

```sql
CREATE TABLE trips (
    id SERIAL PRIMARY KEY,
    destination VARCHAR(200),       -- "San Francisco" / "Baden-Baden"
    origin VARCHAR(200),            -- "Zurich" / "Frankfurt"
    category VARCHAR(20),           -- 'meeting', 'event', 'personal'
    status VARCHAR(20),             -- 'planned', 'confirmed', 'discarded', 'completed'
    start_date DATE,
    end_date DATE,
    event_name VARCHAR(200),        -- "NVIDIA GTC 2026" / null
    strategic_objective TEXT,       -- "Evaluate AI for clAIm, explore tech partnerships"
    calendar_event_ids JSONB,       -- linked Google Calendar event IDs
    notes JSONB DEFAULT '[]',       -- Director's manual notes [{text, source, created_at}]
    auto_context JSONB DEFAULT '[]', -- Baker's auto-linked references [{type, ref_id, summary, created_at}]
    outcomes JSONB DEFAULT '[]',    -- Post-trip [{contact, takeaway, follow_up, created_at}]
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_trips_status ON trips(status) WHERE status IN ('planned', 'confirmed');
CREATE INDEX idx_trips_dates ON trips(start_date, end_date);
```

### New table: `trip_contacts`

```sql
CREATE TABLE trip_contacts (
    id SERIAL PRIMARY KEY,
    trip_id INTEGER REFERENCES trips(id),
    contact_id INTEGER REFERENCES vip_contacts(id),
    role VARCHAR(50),               -- 'counterparty', 'internal_team', 'conference_attendee', 'local_contact'
    roi_type VARCHAR(50),           -- 'deal_lead', 'introduction', 'partnership', 'competitive_intel', 'relationship_upgrade'
    roi_score INTEGER,              -- 1-10 Baker's assessment
    outreach_status VARCHAR(20),    -- 'none', 'drafted', 'approved', 'sent', 'responded'
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_trip_contacts_trip ON trip_contacts(trip_id);
```

### Preferences seed:
```sql
-- director_preferences
category: domain_context, key: commute_cities, value: "Geneva, Vienna, Frankfurt"
category: domain_context, key: home_city, value: "Zurich"
```

---

## LinkedIn Integration (Proxycurl)

**Cost:** ~EUR 40/month (pay-per-lookup, ~0.01-0.03 per profile)
**Capability:** Lookup by name + company → full profile (role, experience, education, skills, recent posts)

**Usage in Trip Intelligence:**
1. Conference attendee enrichment: Baker has a name + company from the speaker/sponsor list → Proxycurl returns full profile
2. Contact enrichment: Before a meeting, Baker refreshes the counterparty's LinkedIn data
3. Network discovery: "Who in my LinkedIn connections is also attending GTC?"

**Implementation:** New tool `lookup_linkedin(name, company)` available to `profiling` and `research` capabilities. Cached 30 days per person (profiles don't change daily).

**Deferred decision:** LinkedIn Sales Navigator (~EUR 100/month) for deeper network mapping. Evaluate after Proxycurl proves value.

---

## Landing Grid Integration

### Route Card (existing, enhanced)

The route card on the landing grid gains:
- **Status color** on font: blue (planned), green (confirmed), red (discarded), orange (completed)
- **Category badge**: small `MTG` / `EVT` / `PER` label
- **Click → full-screen trip view** (not inline expand)
- **Toggle button**: `Meeting | Event | Personal` — always visible for manual override

### Trip View (new, full-screen)

- Back button returns to landing grid
- 8 cards in vertical scroll
- Each card collapsible
- Trip notes input at the bottom (persistent)
- Status dropdown: Planned → Confirmed → Completed / Discarded

---

## Implementation Sequence

### Batch 0 — Location Foundation (1 session)
*From LOCATION-AWARENESS-1, folded in*
1. `director_location` table + home base seed
2. `poll_todays_meetings()` already shipped (TRAVEL-FIX-1)
3. Calendar event → city extraction
4. Commute cities preference
5. iPhone Shortcuts endpoint (optional, nice-to-have)

### Batch 1 — Trip Lifecycle (1 session)
6. `trips` + `trip_contacts` tables (idempotent migration)
7. Auto-detect trips from calendar flights → create Planned trip
8. Trip status management (API endpoints: create, update status, add note)
9. Route card enhanced: status colors, category badge, click → trip view
10. Trip view: full-screen skeleton with Back button, 8 card placeholders
11. Manual toggle: Meeting / Event / Personal
12. WhatsApp: "For [trip]: [note]" command
13. Commute city auto-classification logic
14. Trip lifecycle: auto-complete +1 day after end_date, fade from dashboard +2 days

### Batch 2 — Trip Intelligence (1.5 sessions)
15. Card 1: Trip Logistics & Comms — aggregate trip-related emails + WhatsApp
16. Card 2: Why You're Going — infer from calendar + emails, editable
17. Card 3: Daily Agenda — calendar events at destination, local timezone
18. Card 5: Flight Reading — curate unread high-priority items, trip-relevant boost
19. Card 6: Opportunistic Radar — dormant contacts in destination city, public events
20. Card 7: Europe While You Sleep — timezone-aware monitoring summary
21. Trip context accumulator: passive pickup from email/WA pipeline

### Batch 3 — People Intelligence (1 session)
22. Proxycurl integration: `lookup_linkedin(name, company)` tool
23. Card 4 (Meeting): Counterparty dossier + internal team prep + commitments
24. Card 4 (Event): Conference attendee research, ROI ranking, outreach drafts
25. `trip_contacts` population: auto from agenda + manual add
26. Outreach workflow: Baker drafts → Director approves → Baker sends

### Batch 4 — Outcomes & Networking Bridge (0.5 session)
27. Card 8: Trip Outcomes — dashboard form + WhatsApp input
28. Passive outcome extraction from post-trip emails/Fireflies
29. Flow outcomes to Networking section (contacts, interactions, follow-ups)
30. Trip archive: completed trips queryable for relationship history

---

## Dependencies

| Dependency | Status | Impact |
|---|---|---|
| Networking section | Not yet built | Batch 4 feeds into it. Batch 1-3 work standalone. |
| Obligations unification | Separate brief | Trip card reads from both tables until merged. |
| Proxycurl account | Need to sign up | Batch 3 blocked until active. |
| Conference attendee data | Varies per event | Public data (speakers/sponsors) first. LinkedIn enrichment in Batch 3. |

## Success Criteria

- Director clicks a flight → sees a full trip workspace, not a meeting template
- Trip context accumulates over 2-3 weeks before travel
- Baker auto-classifies 80%+ of trips correctly (manual toggle covers the rest)
- Conference trips: Baker surfaces 5-10 high-ROI contacts with rationale
- Meeting trips: counterparty dossier ready without Director asking
- Post-trip: outcomes flow to Networking within 48 hours
- Commute trips: no unnecessary prep noise
