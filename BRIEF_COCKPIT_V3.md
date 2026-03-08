# BRIEF: COCKPIT-V3 — Baker Dashboard Redesign

**Version:** 1.0
**Date:** 2026-03-07
**Author:** Code 300 (architect), Director (design decisions)
**For:** Code Brisen (implementation)
**Prototype:** `_01_INBOX_FROM_CLAUDE/baker_cockpit_v3_final.html`

---

## Summary

Complete redesign of the Baker CEO Cockpit. The current dashboard was built for Phase 1 (reactive Baker). Phase 2 added capabilities, structured alerts, web search, document reader — but the UX didn't evolve. This brief brings the interface up to the capability layer.

**Core principle:** Baker has the brain of a Chief of Staff but the face of a chatbot. This redesign gives it the face it deserves.

---

## Design Decisions (Director-approved)

All decisions below were made in a live session with the Director on 2026-03-07.

### Layout
- **Split layout:** Full-height sidebar (left) + content area (right)
- **Sidebar** runs from top to bottom, Baker logo at top, navigation tabs below
- **Command bar** sits at top of the right area (not full width — sidebar is independent)
- **Morning narrative** sits below command bar in the content area
- **Target devices:** Laptop + iPad. No phone for now.
- **Mobile fallback (<768px):** Show a centered message: "Baker Cockpit is designed for laptop and tablet. Open on a larger screen for the full experience." No responsive layout needed.

### Navigation Tabs (sidebar)
```
Baker                    ← logo, top of sidebar

Morning Brief            ← landing page
Fires (n)                ← T1 matters only, red badge with count
Matters                  ← expandable sub-list of all matters from DB
  ● Hagenauer    4  2new
  ● Cupial       2  1new
  ● UBM          2
  ...
  ● Ungrouped    3  3new
People
Deadlines
Tags
─────────────
Search
Ask Baker
Ask Specialist
─────────────
Travel
Media
```

### Color System (6 colors, no exceptions)
| Color | Hex | Meaning | Used for |
|-------|-----|---------|----------|
| Red | #ef4444 | T1 — fire, act now | Dot, tier badge, card border |
| Amber | #f59e0b | T2 — important, time-sensitive | Same |
| Slate | #94a3b8 | T3 — routine, informational | Same |
| Light gray | #d1d5db | T4 — all others | Same |
| Blue | #3b82f6 | New / unread since last visit | Card background, "new" badge |
| Green | #10b981 | Done / completed | Run button after execution |

**No emojis anywhere.** No decorative colors. Action type badges (Draft, Analyze, Plan, etc.) are uniform muted gray (#f1f5f9 bg, #475569 text). Minimalist.

### Tier Rules
| Tier | Auto-expiry | Slack push | Dashboard |
|------|-------------|------------|-----------|
| T1 | Never — dismiss only | Yes (sb-inbox) | Visible, expanded |
| T2 | 3 days or dismissed | Yes (sb-inbox) | Visible, expanded |
| T3 | 3 days or dismissed | No | Visible, compact (one line, expand on click) |
| T4 | 3 days or dismissed | No | Visible, compact (title only, expand on click) |
| Travel | Never — until date passes | No | Visible in Travel tab |

### Fires vs Matters
**A matter lives in one place only.** If any item in a matter is T1, the entire matter moves to Fires in the sidebar. It disappears from the Matters list. When all T1 items are resolved/dismissed, the matter drops back to Matters with its next-worst tier. No duplication.

**Demotion timing:** Matter demotion from Fires to Matters happens **immediately** when the last T1 item is dismissed or resolved. No waiting for next scan. This is a frontend query — the sidebar groups matters by their worst active tier on each render.

### Card Updates
When Baker scans again and finds new info about an existing item, it **updates the existing card** (adds new info, marks "Updated 10:45 AM"). No duplicate cards.

### Grouping
- Items grouped by **matter** (from matter_registry in DB)
- Within a matter: sorted by tier (worst first), then newest on top
- New items highlighted with blue background
- Matters in sidebar sorted by worst active tier, then alphabetical
- **Ungrouped section** for items Baker can't link to a matter

### Ungrouped Assignment
Each ungrouped card shows an assignment bar:
```
Assign to: [Hagenauer ▾]  or  [+ New Project]
```
Dropdown lists known matters. "New Project" creates a new matter + ClickUp project + Dropbox folder.

---

## Tab Specifications

### 1. Morning Brief (landing page)

**What it shows:**
- Greeting: "Good morning, Dimitry"
- **Narrative summary** (2-3 sentences, Baker voice): "Hagenauer insolvency is the top issue — filing deadline in 5 days. Cupial handover demand requires response today. 3 other matters have updates, nothing else urgent."
- **Stats row:** 4 cards — Fires count (red), Deadlines this week (amber), Processed overnight (blue), Actions completed (green)
- **Quick action buttons:** Morning Briefing, Draft Email, Legal Review, Research, Financial Analysis, IT Status
- **Top fires:** T1 alert cards, fully expanded with PCS + actions
- **Deadlines this week:** Compact list, color-coded dots, days remaining
- **Baker activity today:** Timeline of what Baker did (capability runs, emails processed, alerts generated)

**Backend:** New endpoint `GET /api/dashboard/morning-brief` returning:
- fire_count, deadline_count, processed_overnight, actions_completed
- narrative (generated by Haiku, cached 30 min)
- top_fires (T1 alerts with structured_actions)
- deadlines (next 7 days)
- activity (recent capability_runs + baker_actions)

### 2. Fires

**What it shows:** All matters that have at least one T1 item. Each matter's items displayed as cards, T1 first. Full PCS + actions + reply thread on each card.

**Backend:** `GET /api/alerts?tier=1` grouped by matter.

### 3. Matters

**What it shows:** Sidebar expands to show sub-list of all matters with dot color + item count + new count. Click a matter → right panel shows all its items, newest on top, grouped by tier. T1/T2 expanded, T3/T4 compact.

**View toggle:** List | Board (top-right of content area)

**Board view:** Kanban columns by tier — Fire | Important | Routine | All Others. Cards are draggable (future).

**Backend:** `GET /api/matters` (list all matters with counts), `GET /api/matters/{slug}/items` (items for a matter).

### 4. People

**What it shows:** List of VIP contacts and key people. Click a person → right panel shows recent interactions (emails, WhatsApp, meetings), related matters, communication history.

**Backend:** Existing contacts + vip_contacts tables. New endpoint `GET /api/people/{id}/activity`.

### 5. Deadlines

**What it shows:** All deadlines sorted by urgency. Color-coded dots. Days remaining. Link to related matter. Click → opens the matter context.

**Backend:** Existing `GET /api/deadlines` endpoint.

### 6. Tags

**What it shows:** List of available tags with item counts. Click a tag → right panel shows all items with that tag across all matters.

**Tag creation:** Baker auto-tags based on content (legal, finance, deadline, follow-up, waiting-response, contract, dispute). Director can add custom tags via `+tag` button on any card footer.

**Backend:** New `tags` column (JSONB array) on alerts table. New endpoint `GET /api/tags` (list with counts), `GET /api/alerts?tag=legal` (filter by tag).

### 7. Search

**What it shows:** Deep search page with filters. Search box + results list. Filters: by matter, by date range, by source (email, WhatsApp, ClickUp, meetings, RSS), by person.

**Backend:** Enhanced version of existing search, with filter parameters.

### 8. Ask Baker

**What it shows:** The Scan chat interface. Full conversation with Baker. Streaming responses. Same as current Scan but in the new layout.

**Backend:** Existing `/api/scan` endpoint. No changes.

### 9. Ask Specialist

**What it shows:** Capability picker → dedicated chat with a specific specialist. Director picks from: Legal, Finance, IT, Sales, Asset Management, Research, Communications, Investment Banking, Marketing, AI Development.

**Backend:** New endpoint `POST /api/scan/specialist` with `capability_slug` parameter that forces routing to a specific capability.

### 10. Travel

**What it shows:** Upcoming trips, bookings, "leave by" times, travel alerts. Items never expire — they persist until the travel date passes.

**Backend:** Travel items tagged in alerts or a dedicated travel collection. Future: detect flight/train bookings from email.

### 11. Media

**What it shows:** RSS feed items (Feedly), future Google Alerts. Market intelligence, industry news. Grouped by feed/source.

**Backend:** Existing RSS trigger data.

---

## Card Anatomy

Every alert card has the same structure, with sections shown/hidden based on tier:

```
┌─────────────────────────────────────────────────────────┐
│ [Tier badge]  Card title                    [new] time  │  ← always visible
│                                          Updated 10:45  │  ← if updated
├─────────────────────────────────────────────────────────┤
│ [Problem]          [Cause]            [Solution]        │  ← T1/T2 only
├─────────────────────────────────────────────────────────┤
│ BAKER RECOMMENDS                                        │  ← T1/T2 only
│ Part label                                              │
│ [Draft]  Draft evidence filing for E+H          [Run]   │
│ [Analyze] Brisen exposure under IO              [Run]   │
│                                                         │
│ [Something else...                              [Run]]  │
├─────────────────────────────────────────────────────────┤
│ MORE ACTIONS                                            │  ← all tiers
│ [Draft...] [Analyze...] [Plan...] [Summarize...] [Search...]│
├─────────────────────────────────────────────────────────┤
│ RESULT (expandable/collapsible)                         │
│ Baker's output with formatted markdown                  │
│ [Copy] [Word] [Email] [Save to Project] [Continue]     │
├─────────────────────────────────────────────────────────┤
│ REPLY THREAD                                            │  ← if Baker asked questions
│ Baker: "I need confirmation on..."                      │
│ You: "Send to both. Green light."                       │
│ Baker: "Understood. Drafting now."                      │
│ [Reply to Baker on this matter...              [Send]]  │
├─────────────────────────────────────────────────────────┤
│ [Run All]  [Create Task]  [Create Project]    Dismiss   │  ← footer
└─────────────────────────────────────────────────────────┘
```

**T3 cards:** Compact — title line only, expand on click to reveal actions.
**T4 cards:** Compact — title line only, expand on click. No PCS.

### Action Types (uniform badge style)

All action type badges are identical: muted gray background (#f1f5f9), dark gray text (#475569), same size, same padding. The label text differentiates them:

| Label | What it produces |
|-------|-----------------|
| Draft | Email, letter, memo, response |
| Analyze | Research, compare, review, assess (auto-routes to right specialist) |
| Plan | ClickUp tasks, timeline, milestones |
| Summarize | Condense information into a brief |
| Search | Deep search across all sources |

### "More Actions" Menu

Available on every card. When Director clicks one (e.g., "Draft..."), an input field appears:
```
Draft: [What should Baker draft?                    ] [Run]
```
Director types the instruction, clicks Run, Baker executes with the card's matter context.

### Reply Thread

Every result card has a reply field at the bottom. Baker maintains conversation context per matter. The thread shows:
- Baker's output (including questions)
- Director's reply
- Baker's follow-up response
- Reply input for continued conversation

**Backend:** New `card_thread` column (JSONB) on alerts table, or a new `alert_threads` table linking alert_id → conversation messages.

### Result Actions

Every result (Baker's output) has a toolbar:
| Button | What it does |
|--------|-------------|
| Copy | Copy raw markdown to clipboard |
| Word | Download as .docx |
| Email | Open email draft with result as body |
| Save to Project | Save to Dropbox project folder (`_BAKER_OUTPUTS/{matter}/`) |
| Continue in Scan | Open Ask Baker tab with this result as context |

---

## Artifact Storage

**Dropbox structure:**
```
_BAKER_OUTPUTS/
  Hagenauer/
  Cupial/
  MO_Vienna/
  Lilienmatt/
  BCOMM_M365/
  _Ungrouped/
```

Baker auto-creates folders matching matter_registry. Files saved as:
```
_BAKER_OUTPUTS/Hagenauer/2026-03-07_evidence_preservation_memo.md
```

**Backend:** New endpoint `POST /api/artifacts/save` with matter_slug, title, content. Writes to Dropbox via API or local filesystem.

---

## Command Bar

Persistent at top of right area (below sidebar logo level). Visible on every tab. **Replaces the v2 "Baker's Scan" button entirely.** Remove the floating Scan button from all pages — its function is now served by the Command Bar + Ask Baker tab.

- **Input field:** "Ask Baker anything..."
- **Keyboard shortcut:** Cmd+K focuses the input
- **Capability auto-detection:** As user types, Baker detects which capability matches (via trigger patterns in DB). Shows a small badge: "Legal detected" / "Finance detected"
- **Quick action buttons** (right side): Briefing, Draft, Legal, Research

**Backend:** New endpoint `GET /api/scan/detect?q=...` returns matched capability slug without executing. Lightweight — just runs trigger pattern matching.

---

## Backend Changes Required

### New Endpoints
| Endpoint | Purpose |
|----------|---------|
| `GET /api/dashboard/morning-brief` | Aggregated morning data + Haiku narrative |
| `GET /api/matters` | List matters with item counts and worst tier |
| `GET /api/matters/{slug}/items` | Items for a matter, sorted by tier then date |
| `GET /api/tags` | List tags with item counts |
| `GET /api/alerts?tag={tag}` | Filter alerts by tag |
| `GET /api/people/{id}/activity` | Person's recent interactions |
| `GET /api/activity` | Unified activity feed |
| `GET /api/scan/detect?q={query}` | Capability detection without execution |
| `POST /api/scan/specialist` | Force-route to specific capability |
| `POST /api/artifacts/save` | Save result to Dropbox project folder |
| `POST /api/alerts/{id}/reply` | Add reply to alert thread |
| `POST /api/alerts/{id}/assign` | Assign ungrouped alert to a matter |
| `POST /api/alerts/{id}/tag` | Add/remove tags on an alert |

### Schema Changes
| Table | Change |
|-------|--------|
| `alerts` | Add `matter_slug TEXT`, `tags JSONB DEFAULT '[]'`, `board_status TEXT DEFAULT 'new'` |
| `matter_registry` | Add `dropbox_path TEXT` for artifact storage |
| New: `alert_threads` | `id SERIAL, alert_id INTEGER REFERENCES alerts(id), role TEXT, content TEXT, created_at TIMESTAMPTZ DEFAULT NOW()` (see Architect Note #4) |
| New: `alert_artifacts` | `id, alert_id, matter_slug, title, content, file_path, created_at` |

**Note:** No `thread JSONB` on alerts table. Threads live in the separate `alert_threads` table (Architect Note #4).

### Alert Lifecycle
```
New → [Baker scans, creates alert, generates structured_actions]
  → Assigns matter_slug (auto by keyword match to matter_registry — see Note below)
  → Auto-tags (legal, finance, deadline, etc.)
  → If T1/T2: push to Slack sb-inbox

Visible → [Director sees card on dashboard]
  → Can Run actions, Reply, Create Task, Create Project
  → Can reassign matter, add tags
  → Can Dismiss

Updated → [Next scan finds new info]
  → Baker updates existing card, adds timestamp
  → New info highlighted

Expired → [3 days old, T2/T3/T4 only]
  → Auto-dismissed, removed from active views
  → Still searchable in Search tab

T1 special: never auto-expires. Travel special: expires only after date passes.
```

### Matter Auto-Assignment (required for Phase A2)
When Baker creates an alert, it must assign `matter_slug` automatically. Without this, all alerts land in "Ungrouped" and the Matters tab is useless.

**Implementation:** In `pipeline.py`, after creating an alert, run the alert title + body against `matter_registry` names and aliases using keyword matching (same trigger_pattern approach as capability routing). If a match is found, set `matter_slug`. If no match, leave NULL (goes to Ungrouped).

This is a **Phase A2 requirement**, not Phase C. The manual Ungrouped dropdown (Phase B) is a fallback for when auto-assignment fails, not the primary path.

---

## Architect Notes (gap repairs)

### 1. "More Actions" inline behavior
When Director clicks "Draft..." (or Analyze, Plan, Summarize, Search) from the More Actions row, an input field expands **inline on the card**, directly below the button row:
```
[Draft...] [Analyze...] [Plan...] [Summarize...] [Search...]

Draft: [What should Baker draft?                       ] [Run]
```
No modal, no popup. Same inline pattern as the freetext "Something else" row. The matter context is automatically included — Baker knows which alert and matter this relates to.

### 2. Morning narrative edge cases
The Haiku-generated narrative must handle:
- **Zero alerts:** "All clear. No fires overnight. 2 routine updates across MO Vienna and BCOMM."
- **All T1:** Lead with the count and top issue, then list others.
- **Weekend/holiday:** Adjust tone. "Weekend summary: Baker processed 42 emails since Friday..."

Narrative is cached for 30 minutes. Invalidated when a new T1 alert is created. **Mechanism:** Application-level. After any `INSERT INTO alerts WHERE tier = 1` in `store_back.py`, delete the in-memory cached narrative (use a module-level dict with timestamp, no Redis needed). Next `GET /api/dashboard/morning-brief` regenerates via Haiku.

### 3. Board view is read-only
Board view (kanban) in this brief is **display-only**. No drag-and-drop. No status changes by moving cards between columns. Cards are clickable (opens detail in right panel). Drag-and-drop is a Phase C+ feature if needed.

### 4. Reply thread — separate table
Do NOT store threads as JSONB on the alerts table. Use a separate table:
```sql
CREATE TABLE alert_threads (
    id SERIAL PRIMARY KEY,
    alert_id INTEGER REFERENCES alerts(id) NOT NULL,
    role TEXT NOT NULL,           -- 'baker' or 'director'
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_alert_threads_alert ON alert_threads(alert_id);
```
This keeps the alerts table lean and allows threads to grow without bloating the main query. When rendering a card, fetch threads with `SELECT * FROM alert_threads WHERE alert_id = ? ORDER BY created_at`.

When Director sends a reply (`POST /api/alerts/{id}/reply`), Baker receives the reply in context (alert title + body + structured_actions + thread history) and generates a response. Both messages are inserted into alert_threads.

### 5. Ask Specialist = same chat, different routing
Ask Baker and Ask Specialist use the **same chat UI component**. The only difference:
- **Ask Baker:** Routes via normal capability detection (auto-picks best match)
- **Ask Specialist:** Shows a capability picker at the top of the chat. Director selects a capability (Legal, Finance, IT...), then types. All messages force-route to that capability via `POST /api/scan/specialist?capability=legal`.

Do NOT build two separate chat interfaces. One component, one flag.

### 6. Phase A split for manageable delivery
Phase A is too large for a single Brisen sprint. Split into:

**Phase A1 — Layout + Navigation (ship first)**
1. Sidebar with all 11 tab labels (only Morning Brief, Fires, Matters, Deadlines functional)
2. Morning Brief landing page (narrative + stats + top fires + deadlines + activity)
3. Fires tab (filtered T1 matters view)
4. Command bar (basic — input field, no auto-detection yet)

**Phase A2 — Cards + Interaction**
5. Card redesign: one-click Run, PCS, Baker recommends + More actions menu
6. Matters tab with sub-list navigation and matter detail view
7. Reply thread on result cards
8. Result toolbar (Copy, Word, Email, Save to Project)
9. Deadlines tab (full view)

---

## Security Review

### Input Validation
- **Reply thread:** Director input via `POST /api/alerts/{id}/reply` must be sanitized. Max length 4000 chars. The `content` field is passed to Claude as user message — no raw HTML rendering. Store as plain text, render with `md()` (which escapes via `esc()` first).
- **"More Actions" custom prompt:** Same rules. Director's typed instruction is passed to Claude as a user message within the alert context. Max length 2000 chars. No server-side template injection risk because the prompt is a Claude API message, not evaluated code.
- **Tag creation:** Tags must be alphanumeric + hyphens only. Regex: `/^[a-z0-9-]{1,50}$/`. Reject anything else. Stored in JSONB array on alerts table.
- **Matter assignment:** Dropdown only offers existing matter_slugs from DB. "New Project" creates a slug from the user-provided name — slugify (lowercase, hyphens, strip special chars, max 50 chars).

### Authorization
- All new endpoints require `X-Baker-Key` header (existing `verify_api_key` dependency). No changes to auth model.
- **Alert thread replies:** Verify the alert_id exists before inserting. No user-to-user messaging — this is Director-to-Baker only.
- **Artifact save (`POST /api/artifacts/save`):** Write path is constrained to `_BAKER_OUTPUTS/` directory only. The `matter_slug` parameter must match a known matter in matter_registry, or `_Ungrouped`. **Path traversal protection:** Reject any slug containing `..`, `/`, `\`, or non-alphanumeric characters (except hyphens and underscores). Construct the full path server-side: `BAKER_OUTPUTS_ROOT / sanitized_slug / filename`. Never use user-provided paths directly.

### Data Exposure
- **Morning narrative:** Generated by Haiku from alert titles and bodies. These already contain business-sensitive information. The narrative endpoint must require auth (same as all /api/* routes). No public caching.
- **Capability detection (`GET /api/scan/detect`):** Returns only the matched capability slug (e.g., "legal"). Does not expose trigger patterns, system prompts, or internal routing logic.
- **Board view:** Shows alert titles and tier badges. No full body content in board cards — only shown when card is clicked/expanded. Reduces data exposure in screenshots.

### Rate Limiting
- **Reply thread:** Max 50 replies per alert (raised from 20 — complex matters like Hagenauer need extended dialogue). After 50, show "Continue in Ask Baker for extended conversation." The "Continue in Ask Baker" link pre-fills the Scan context with the alert + thread history so no context is lost.
- **Morning narrative generation:** Cached 30 min. At most 2 Haiku calls per hour. No abuse vector.
- **"More Actions" execution:** Each Run button triggers a `/api/scan` call. Existing capability timeout (90s) and iteration limits (8) apply. No additional rate limiting needed beyond existing cost controls.

### XSS Prevention
- All text rendering in the frontend must use `textContent` (for plain text) or `md()` (which calls `esc()` first, then applies markdown regex). **Never use `innerHTML` with raw user input or raw Baker output.** The existing `md()` function is safe — it escapes first, then converts markdown patterns to HTML.
- Reply thread messages: render with `md()` for Baker messages (may contain formatting), `esc()` for Director messages (plain text).
- Tag badges: render with `textContent` only. Tags are alphanumeric — no HTML possible.

### SQL Injection
- All new endpoints must use parameterized queries (existing pattern with `%s` placeholders in psycopg2). No string concatenation for SQL. This is already the codebase standard — Brisen must follow it.
- The `matter_slug` filter in queries must use parameterized `WHERE matter_slug = %s`, never `WHERE matter_slug = '{slug}'`.

---

## Build Sequence

This is a large brief. Recommended phasing:

### Phase A1 — Layout + Navigation (ship first)
1. Sidebar with all 11 tab labels (Morning Brief, Fires, Matters, Deadlines functional; others show "Coming soon" placeholder)
2. Morning Brief landing page (narrative + stats + top fires + deadlines + activity)
3. Fires tab (filtered T1 matters view)
4. Command bar (basic input field, quick action buttons, no auto-detection yet)

### Phase A2 — Cards + Interaction
5. **Matter auto-assignment** — keyword match alert title+body against matter_registry on creation (required for Matters tab to work)
6. Card redesign: one-click Run, PCS, Baker recommends + More actions menu (inline input)
7. Matters tab with sub-list navigation and matter detail view (list mode)
8. Reply thread on result cards (separate alert_threads table)
9. Result toolbar (Copy, Word, Email, Save to Project)
10. Deadlines tab (full view with color-coded dots)

### Phase B (extends functionality)
11. Tags system (auto-tagging + manual + tag tab view)
12. Board view toggle on Matters (read-only)
13. Ungrouped assignment (dropdown + New Project)
14. Ask Specialist tab (capability picker + same chat component as Ask Baker)
15. Command bar capability auto-detection badge
16. Artifact storage (Dropbox _BAKER_OUTPUTS, path traversal protection)

### Phase C (completes the vision)
17. People tab (contact-centric view + activity)
18. Search tab with filters (matter, date, source, person)
19. Travel tab (travel alerts, no expiry until date passes)
20. Media tab (RSS, future Google Alerts)
21. Alert auto-expiry (3-day rule for T2/T3/T4)

**Note:** Matter auto-assignment moved from Phase C to Phase A2 (item #5). Without it, the Matters tab would be empty.

---

## Reference

- **Prototype:** `_01_INBOX_FROM_CLAUDE/baker_cockpit_v3_final.html`
- **Director's process map:** `~/Desktop/DRAFT PROCESS .xlsx`
- **Current dashboard:** `outputs/static/index.html` + `outputs/static/app.js` + `outputs/static/style.css`
- **Inspiration:** Linear (task cards), Perplexity (AI output), Mercury (executive dashboard), Todoist (board view)
