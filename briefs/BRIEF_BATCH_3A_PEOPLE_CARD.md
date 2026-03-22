# BRIEF: Batch 3A — Card 4: People to Meet

**Author:** AI Head
**Date:** 2026-03-17
**Status:** READY FOR CODE BRISEN
**Effort:** 1 session
**Depends on:** Batch 2 (SHIPPED), trip_contacts table (EXISTS)

---

## What

Replace the "Coming in Batch 3" placeholder on the trip view's Card 4 with a real **People to Meet** card. This card shows who the Director is meeting, their background, relationship history, and mutual obligations — all from Baker's existing memory. No external APIs needed.

## Why

The GTC trip (id=4) already has 2 linked contacts (Peter Storer, Sandy Hefftz) with rich data in Baker's memory. Card 4 is the most valuable card on a business trip — it's the counterparty dossier. Right now it shows a placeholder.

---

## Data Already Available

### trip_contacts table (2 rows for GTC trip)
```
Peter Storer  | ROI 9 | partnership | NVIDIA Travel & Hospitality vertical lead
Sandy Hefftz  | ROI 7 | partnership | CEO Bellboy Robotics, NVIDIA Inception Partner
```

### vip_contacts table (enriched profiles)
- `role`, `role_context`, `expertise`, `tier`, `last_contact_date`, `primary_location`

### contact_interactions table
- Per-contact interaction history (channel, direction, subject, timestamp)
- Sandy Hefftz has 1 email interaction (GTC Meeting Intro, Mar 14)

### deadlines table (obligations)
- "NVIDIA GTC -- Peter Storer meeting" (due Mar 19, HARD severity)
- "NVIDIA GTC 2026 — fly to California" (due Mar 14, FIRM severity)

### email_messages + whatsapp_messages
- Searchable by contact name/email for recent communications

---

## Implementation

### 1. Backend: Add `people` to trip cards API

**File:** `outputs/dashboard.py` — in `get_trip_cards()` function

Add a new card section between agenda and reading:

```python
# --- Card 4: People to Meet ---
people_card = {"contacts": []}
trip_contacts = trip.get("contacts", [])
if trip_contacts:
    people_card["contacts"] = _build_people_dossiers(trip_contacts, store)
cards["people"] = people_card
```

**New function: `_build_people_dossiers(trip_contacts, store)`**

For each trip contact, build a dossier:

```python
def _build_people_dossiers(trip_contacts: list, store) -> list:
    """Build counterparty dossiers for trip contacts from Baker memory."""
    dossiers = []
    conn = store._get_conn()
    if not conn:
        return trip_contacts  # fallback: raw contact data
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        for tc in trip_contacts:
            contact_id = tc.get("contact_id")
            name = tc.get("contact_name", "")

            dossier = {
                "name": name,
                "role": tc.get("contact_role", ""),
                "trip_role": tc.get("role", ""),        # counterparty/internal_team/etc
                "roi_type": tc.get("roi_type", ""),
                "roi_score": tc.get("roi_score"),
                "notes": tc.get("notes", ""),
                "outreach_status": tc.get("outreach_status", "none"),
                # From vip_contacts (already joined in get_trip):
                "tier": tc.get("tier"),
                "role_context": tc.get("role_context", ""),
                "expertise": tc.get("expertise", ""),
                "last_contact_date": tc.get("last_contact_date"),
                # To be enriched below:
                "recent_interactions": [],
                "obligations": [],
                "recent_emails": [],
            }

            # Recent interactions (last 90 days)
            cur.execute("""
                SELECT channel, direction, subject, timestamp
                FROM contact_interactions
                WHERE contact_id = %s
                ORDER BY timestamp DESC LIMIT 5
            """, (contact_id,))
            dossier["recent_interactions"] = [_serialize(dict(r)) for r in cur.fetchall()]

            # Mutual obligations
            name_lower = name.lower()
            cur.execute("""
                SELECT description, due_date, severity, priority
                FROM deadlines
                WHERE status = 'active'
                  AND LOWER(description) LIKE %s
                ORDER BY due_date LIMIT 5
            """, (f"%{name_lower}%",))
            dossier["obligations"] = [_serialize(dict(r)) for r in cur.fetchall()]

            # Recent emails (last 30 days)
            if tc.get("contact_email"):
                cur.execute("""
                    SELECT subject, sender_name, received_date
                    FROM email_messages
                    WHERE LOWER(sender_email) = LOWER(%s)
                    ORDER BY received_date DESC LIMIT 5
                """, (tc["contact_email"],))
                dossier["recent_emails"] = [_serialize(dict(r)) for r in cur.fetchall()]
            else:
                # Search by name
                cur.execute("""
                    SELECT subject, sender_name, received_date
                    FROM email_messages
                    WHERE LOWER(sender_name) LIKE %s
                      AND received_date >= NOW() - INTERVAL '30 days'
                    ORDER BY received_date DESC LIMIT 5
                """, (f"%{name_lower}%",))
                dossier["recent_emails"] = [_serialize(dict(r)) for r in cur.fetchall()]

            dossiers.append(dossier)

        cur.close()
    except Exception as e:
        logger.warning(f"People dossier build failed: {e}")
    finally:
        store._put_conn(conn)
    return dossiers
```

**IMPORTANT:** The `get_trip()` method already JOINs `vip_contacts` onto `trip_contacts` — check what fields it returns. You may need to add `email`, `role_context`, `expertise`, `tier` to the JOIN if not already there.

### 2. Backend: get_trip() JOIN check

**File:** `memory/store_back.py` — `get_trip()` method

Verify the trip contacts JOIN includes these fields from vip_contacts:
- `name`, `role`, `email`, `tier`, `role_context`, `expertise`, `last_contact_date`

If any are missing, add them to the SELECT.

### 3. Backend: Add person endpoint

**File:** `outputs/dashboard.py`

```python
@app.post("/api/trips/{trip_id}/people", tags=["trips"], dependencies=[Depends(verify_api_key)])
async def add_trip_contact(trip_id: int, req: dict = Body(...)):
    """Add a contact to a trip. Body: {contact_id, role?, roi_type?, notes?}"""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=500, detail="DB unavailable")
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO trip_contacts (trip_id, contact_id, role, roi_type, notes)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id
        """, (trip_id, req.get("contact_id"), req.get("role", "counterparty"),
              req.get("roi_type"), req.get("notes")))
        conn.commit()
        result = cur.fetchone()
        cur.close()
        return {"ok": True, "id": result[0] if result else None}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        store._put_conn(conn)
```

**Note:** Add `from fastapi import Body` if not already imported.

### 4. Frontend: Card 4 renderer

**File:** `outputs/static/app.js`

Replace the placeholder in `loadTripCards()`:

```javascript
// BEFORE:
html += renderTripCardSection('People to Meet', '<div style="font-size:12px;color:var(--text3);">Coming in Batch 3 (Proxycurl integration)</div>');

// AFTER:
html += renderTripCardSection('People to Meet', renderPeopleCard(cards.people || {}));
```

**New function: `renderPeopleCard(data)`**

Design: Each contact is a collapsible card showing:
- **Header row:** Name, role, ROI badge (score/10), tier dot
- **Click to expand** reveals: role_context, expertise, recent interactions, obligations, recent emails
- **Bottom:** "Add person" button (opens simple modal/prompt)

```javascript
function renderPeopleCard(data) {
    var contacts = data.contacts || [];
    if (contacts.length === 0) {
        return '<div style="font-size:12px;color:var(--text3);">No contacts linked to this trip yet.</div>';
    }
    var html = '';
    for (var i = 0; i < contacts.length; i++) {
        var c = contacts[i];
        // ROI badge color
        var roiColor = (c.roi_score >= 8) ? 'var(--green)' : (c.roi_score >= 5) ? 'var(--amber)' : 'var(--text3)';
        // Tier dot
        var tierDot = c.tier ? '<span class="nav-dot" style="display:inline-block;width:6px;height:6px;margin-left:6px;background:' + (c.tier <= 1 ? 'var(--red)' : c.tier <= 2 ? 'var(--amber)' : 'var(--text3)') + ';"></span>' : '';

        // Expand section
        var details = '';

        // Role context / expertise
        if (c.role_context) details += '<div style="margin-bottom:6px;"><span style="font-weight:600;font-size:11px;">Context:</span> ' + esc(c.role_context) + '</div>';
        if (c.expertise) details += '<div style="margin-bottom:6px;"><span style="font-weight:600;font-size:11px;">Expertise:</span> ' + esc(c.expertise) + '</div>';
        if (c.notes) details += '<div style="margin-bottom:6px;"><span style="font-weight:600;font-size:11px;">Trip notes:</span> ' + esc(c.notes) + '</div>';

        // Recent interactions
        var interactions = c.recent_interactions || [];
        if (interactions.length > 0) {
            details += '<div style="margin-top:8px;"><span style="font-weight:600;font-size:11px;">Recent interactions:</span>';
            for (var j = 0; j < interactions.length; j++) {
                var ri = interactions[j];
                var arrow = ri.direction === 'inbound' ? '←' : '→';
                details += '<div style="font-size:11px;color:var(--text3);padding:2px 0 2px 8px;">' + arrow + ' ' + esc(ri.channel || '') + ': ' + esc(ri.subject || '') + ' <span style="color:var(--text4);">(' + esc(fmtRelativeTime(ri.timestamp)) + ')</span></div>';
            }
            details += '</div>';
        }

        // Obligations
        var obligations = c.obligations || [];
        if (obligations.length > 0) {
            details += '<div style="margin-top:8px;"><span style="font-weight:600;font-size:11px;">Obligations:</span>';
            for (var k = 0; k < obligations.length; k++) {
                var ob = obligations[k];
                var sevColor = ob.severity === 'hard' ? 'var(--red)' : ob.severity === 'firm' ? 'var(--amber)' : 'var(--blue)';
                details += '<div style="font-size:11px;padding:2px 0 2px 8px;"><span style="color:' + sevColor + ';font-weight:600;font-size:10px;">' + esc((ob.severity || '').toUpperCase()) + '</span> ' + esc(ob.description || '') + '</div>';
            }
            details += '</div>';
        }

        // Recent emails
        var emails = c.recent_emails || [];
        if (emails.length > 0) {
            details += '<div style="margin-top:8px;"><span style="font-weight:600;font-size:11px;">Recent emails:</span>';
            for (var m = 0; m < emails.length; m++) {
                var em = emails[m];
                details += '<div style="font-size:11px;color:var(--text3);padding:2px 0 2px 8px;">' + esc(em.subject || '') + ' <span style="color:var(--text4);">(' + esc(fmtRelativeTime(em.received_date)) + ')</span></div>';
            }
            details += '</div>';
        }

        html += '<div style="border:1px solid var(--border);border-radius:6px;margin-bottom:8px;overflow:hidden;" onclick="var d=this.querySelector(\'.people-detail\');d.style.display=d.style.display===\'none\'?\'block\':\'none\'" style="cursor:pointer;">';
        // Header
        html += '<div style="padding:10px 12px;display:flex;align-items:center;justify-content:space-between;cursor:pointer;">';
        html += '<div>';
        html += '<span style="font-size:13px;font-weight:600;color:var(--text1);">' + esc(c.name || '') + '</span>' + tierDot;
        html += '<div style="font-size:11px;color:var(--text3);margin-top:2px;">' + esc(c.role || c.trip_role || '') + '</div>';
        html += '</div>';
        html += '<div style="display:flex;align-items:center;gap:8px;">';
        if (c.roi_score) html += '<span style="font-size:11px;font-weight:700;color:' + roiColor + ';">ROI ' + c.roi_score + '/10</span>';
        if (c.roi_type) html += '<span style="font-size:9px;font-weight:600;color:var(--text3);background:var(--bg2);padding:1px 4px;border-radius:3px;">' + esc(c.roi_type) + '</span>';
        html += ' <span style="font-size:10px;color:var(--text3);">&#9662;</span>';
        html += '</div></div>';
        // Detail (hidden by default)
        html += '<div class="people-detail" style="display:none;padding:8px 12px 12px;border-top:1px solid var(--border-light);font-size:12px;color:var(--text2);line-height:1.5;">' + details + '</div>';
        html += '</div>';
    }

    // Add person button
    html += '<button onclick="addTripContact()" style="margin-top:8px;background:none;border:1px dashed var(--border);border-radius:6px;padding:8px 12px;font-size:12px;color:var(--text3);cursor:pointer;width:100%;font-family:var(--font);">+ Add person</button>';

    return html;
}
```

**Add person function** (simple prompt-based for now):

```javascript
async function addTripContact() {
    var tripId = /* get current trip ID from the rendered view */;
    var name = prompt('Contact name to add:');
    if (!name) return;
    // Search contacts by name
    var resp = await bakerFetch('/api/contacts/search?q=' + encodeURIComponent(name));
    // ... match and POST to /api/trips/{tripId}/people
}
```

This can be a simple implementation — the full "search and add" flow can be polished later.

### 5. Also replace the "Outreach" placeholder

While at it, replace the "Coming in Batch 3" on the Outreach card with a simple display of `outreach_status` per contact (already in trip_contacts). No workflow yet — just show the status.

---

## Files to Modify

| File | Change |
|------|--------|
| `outputs/dashboard.py` | Add `_build_people_dossiers()`, add `people` to cards response, add POST endpoint |
| `memory/store_back.py` | Verify `get_trip()` JOIN includes email, role_context, expertise, tier |
| `outputs/static/app.js` | Add `renderPeopleCard()`, `addTripContact()`, replace placeholder |
| `outputs/static/index.html` | Bump cache version |

## Testing

1. Open GTC trip (id=4) → Card 4 should show Peter Storer and Sandy Hefftz
2. Click Peter Storer → expands to show role_context, expertise, obligations (including "Peter Storer meeting" deadline)
3. Click Sandy Hefftz → expands to show email interaction (GTC Meeting Intro)
4. Click "Add person" → prompt, search, add (basic flow)
5. Verify no regressions on other trip cards

## Design Notes

- Follow ClaimsMax banking design (clean, no color noise)
- ROI score: green ≥8, amber ≥5, gray below
- Tier dot: red = T1, amber = T2, gray = T3+
- Click to expand (same pattern as Fires compact cards)
- Severity badges on obligations: HARD red / FIRM amber / SOFT blue
