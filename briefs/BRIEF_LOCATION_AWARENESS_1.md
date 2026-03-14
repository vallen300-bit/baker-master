# BRIEF: LOCATION-AWARENESS-1 — Baker Knows Where You Are

**Author:** AI Head
**Date:** 2026-03-14
**Status:** SCOPING
**Effort:** Medium (2 sessions)

---

## Problem

Baker has no unified sense of where the Director is. Location signals exist but are fragmented:
- Calendar events have `location` field — displayed but not reasoned about
- Travel-tagged emails detect keywords ("flight", "hotel") — but no structured extraction
- `travel_date` column on alerts exists — rarely populated
- No real-time location, no city-level awareness, no contextual suggestions

Result: Baker can't say "you're in Kitzbuhel this week — here are your local contacts, dinner options, and the Kempinski meeting is 10 min walk from your hotel."

## Goal

Baker knows the Director's current city/region and uses it to:
1. Surface local contacts (VIPs in the same city)
2. Suggest dining/accommodation (via web search capability)
3. Add travel context to briefings ("you land in Vienna at 14:00, first meeting at 16:00")
4. Auto-detect timezone for scheduling suggestions

---

## Architecture: 3 Layers

### Layer 1 — Passive Intelligence (from existing data)
**Zero new infrastructure.** Make Baker smarter about signals he already receives.

| Signal | Already captured | Enhancement |
|--------|-----------------|-------------|
| Calendar events | location text field | Extract city/country, store as `current_city` |
| Travel emails | "travel" tag | New Haiku extraction: origin, destination, dates |
| Hotel booking PDFs | stored as documents | New `travel_booking` extraction schema |
| Flight confirmations | stored as documents | Same schema — departure/arrival/dates |

**New table: `director_location`**
```sql
CREATE TABLE director_location (
    id SERIAL PRIMARY KEY,
    city VARCHAR(100),
    country VARCHAR(100),
    source VARCHAR(50),        -- 'calendar', 'email', 'travel_doc', 'manual', 'shortcut'
    source_ref VARCHAR(200),   -- event ID, doc ID, etc.
    valid_from TIMESTAMPTZ,
    valid_until TIMESTAMPTZ,   -- NULL = indefinite (home base)
    confidence VARCHAR(20),    -- 'confirmed', 'inferred'
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Logic:** Baker maintains a timeline of where the Director is/will be. Query: "WHERE NOW() BETWEEN valid_from AND valid_until ORDER BY confidence DESC LIMIT 1" gives current location.

**Home base:** A permanent row with `city='Zurich', confidence='confirmed', valid_until=NULL` — the fallback when no travel is detected.

### Layer 2 — Active Location Push (iPhone Shortcuts)
**Lightweight, no third-party dependency.** A single iOS Shortcut:

1. **Trigger:** Runs on schedule (every 2 hours) or on arrival at new location
2. **Action:** Get Current Location → POST to `POST /api/director/location`
3. **Payload:** `{"lat": 47.37, "lon": 8.54}`
4. **Baker side:** Reverse geocode (free Nominatim API or simple city lookup table) → upsert `director_location`

**Endpoint:**
```
POST /api/director/location
X-Baker-Key: <auth>
{"lat": float, "lon": float}
```

Baker reverse-geocodes to city/country, stores with `source='shortcut'`, `confidence='confirmed'`, `valid_until=NOW() + 4 hours` (auto-expires if phone stops reporting).

**Why not Life360:** Unofficial API, breaks regularly, adds a dependency. iPhone Shortcuts is native, free, and under your control.

### Layer 3 — Contextual Actions (Baker uses location)

Once Baker knows current city, he can:

| Action | How | When |
|--------|-----|------|
| **Surface local contacts** | Query VIPs where city matches (need city field on contacts) | Morning briefing, on location change |
| **Dining/accommodation** | `web_search` tool: "best restaurants near {city}" | On demand via Scan, or proactive for travel days |
| **Travel context in briefings** | Inject location timeline into morning briefing prompt | Daily briefing job |
| **Timezone awareness** | Map city → timezone, flag scheduling conflicts | Meeting prep (Standing Order #1) |
| **"Who's nearby"** | Cross-ref meeting attendees' known cities | Before networking events |

---

## Implementation Sequence

### Batch 1 — Passive (Layer 1)
1. Create `director_location` table (idempotent, in store_back.py)
2. Add `travel_booking` extraction schema (in extraction_schemas.py + document_pipeline.py)
3. Calendar trigger: extract city from meeting locations → write to `director_location`
4. Travel email processing: when "travel" tag detected, extract destination + dates → write to `director_location`
5. Seed home base row: `Zurich, Switzerland, confidence=confirmed, valid_until=NULL`

### Batch 2 — Active (Layer 2)
6. `POST /api/director/location` endpoint (dashboard.py)
7. Reverse geocoding (simple city lookup — no external API needed for major cities, Nominatim fallback)
8. iPhone Shortcut: Director installs on phone (2 min setup)

### Batch 3 — Contextual (Layer 3)
9. Morning briefing: inject current location + upcoming travel into prompt
10. Meeting prep: add "you are in {city}, meeting is in {city}" context
11. Add `city` field to VIP contacts → "local contacts" query
12. Scan prompt: location-aware mode (when Director asks "where should I eat tonight?")

---

## Travel Booking Extraction Schema

Add to `_EXTRACTION_SCHEMAS` in document_pipeline.py:
```
"travel_booking": "booking_type (flight/hotel/train/car), origin, destination, departure_date, return_date, confirmation_number, provider, price (EUR), notes"
```

Add to `_CLASSIFY_PROMPT` type list:
```
"travel_booking"
```

Add Pydantic model in extraction_schemas.py:
```python
class TravelBookingExtraction(_ExtractionBase):
    booking_type: Optional[Any] = None    # flight, hotel, train, car
    origin: Optional[Any] = None
    destination: Optional[Any] = None
    departure_date: Optional[Any] = None
    return_date: Optional[Any] = None
    confirmation_number: Optional[Any] = None
    provider: Optional[Any] = None
    price: Optional[Any] = None
    notes: Optional[Any] = None

    _coerce_price = field_validator('price', mode='before')(_amount_validator)
```

---

## What Baker Already Has (no work needed)

- Travel tag detection on emails (keywords: flight, hotel, booking, travel, airport, train, itinerary)
- `travel_date` column on alerts (just needs auto-population)
- Travel card on landing grid (reads from `/api/alerts/by-tag/travel`)
- Document pipeline for PDFs (flight confirmations, hotel bookings already ingested)
- Web search capability on 8 specialists (can search for restaurants, hotels)

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Privacy — real-time location stored in DB | Director-only visibility, no external exposure, auto-expire after 4h |
| Reverse geocoding dependency | Start with simple city lookup table (50 cities), Nominatim as fallback |
| Over-notification ("you're near...") | Location-based suggestions only in briefings or on-demand, never push |
| iPhone Shortcut stops running | Graceful degradation — falls back to Layer 1 (passive from calendar/emails) |

## Success Criteria

- Baker's morning briefing includes "You are in {city} today" with local context
- Meeting prep says "This meeting is in {city}, you are currently in {city}"
- "Where should I eat tonight?" returns location-aware results
- Travel bookings auto-extracted with destination + dates
- System works without iPhone Shortcut (passive layer alone = 80% value)

---

## Estimate

| Batch | Effort | Dependency |
|-------|--------|-----------|
| Batch 1 (Passive) | 1 session | None |
| Batch 2 (Active) | 0.5 session | Director sets up iPhone Shortcut |
| Batch 3 (Contextual) | 0.5 session | Batch 1 |
