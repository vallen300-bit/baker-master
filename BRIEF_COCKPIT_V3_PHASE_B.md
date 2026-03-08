# COCKPIT-V3 Phase B — Brief for Code Brisen

**Author:** Code 300 (architect)
**Date:** 2026-03-08
**Parent brief:** BRIEF_COCKPIT_V3.md v1.5
**Branch:** `feat/cockpit-v3-b` (create from `main`)
**Builds on:** Phase A1 + A2 (sidebar, Morning Brief, Fires, Deadlines, Ask Baker, command bar, matter auto-assignment, inline results, reply threads, result toolbar, enhanced deadlines)

---

## Overview

Phase B adds 6 features in 3 steps. Each step is one commit.

| Step | Items | Files touched |
|------|-------|---------------|
| **B1** | Tags system + Ungrouped assignment | `pipeline.py`, `store_back.py`, `dashboard.py`, `app.js`, `index.html` |
| **B2** | Ask Specialist + Command bar detection | `dashboard.py`, `app.js`, `index.html` |
| **B3** | Board view + Artifact storage | `store_back.py`, `dashboard.py`, `app.js`, `index.html`, `style.css` |

---

## Step 1 — Tags System + Ungrouped Assignment

### 1a. Auto-tagging alerts

**Where:** `orchestrator/pipeline.py`

When creating alerts, auto-assign tags based on content. Use simple keyword matching — same approach as `_match_matter_slug()`. Do NOT add a separate Haiku call for tagging.

**Tag list (fixed set):**
```
legal, finance, deadline, follow-up, waiting-response, contract, dispute,
compliance, meeting, travel, hr, it, marketing, sales, investor
```

**Implementation:** New function `_auto_tag(title: str, body: str) -> list[str]`:
- Combine title + body, lowercase
- Match against keyword groups:
  - `legal` → lawsuit, court, litigation, legal, attorney, lawyer, claim, dispute, evidence
  - `finance` → loan, interest, cashflow, cash flow, budget, invoice, payment, term sheet, LP
  - `deadline` → deadline, due date, expires, expiry, overdue, by end of
  - `follow-up` → follow up, follow-up, following up, check in, check-in
  - `waiting-response` → waiting for, awaiting, no response, pending response, haven't heard
  - `contract` → contract, agreement, lease, MOU, memorandum, signed, signature
  - `dispute` → dispute, arbitration, mediation, complaint, grievance
  - `compliance` → compliance, regulatory, regulation, audit, FINMA, license
  - `meeting` → meeting, call, session, workshop, conference
  - `travel` → flight, hotel, booking, travel, airport, train, itinerary
  - `hr` → employee, hiring, recruitment, termination, payroll, HR
  - `it` → IT, migration, M365, BYOD, security, infrastructure, server, cloud
  - `marketing` → marketing, PR, campaign, social media, branding, advertisement
  - `sales` → sales, buyer, prospect, pitch, showing, unit, pricing
  - `investor` → investor, LP, raise, fund, capital, equity, return
- Return all matching tags (an alert can have multiple)
- Maximum 5 tags per alert (take first 5 matches)

**Integration point:** In the alert creation loop (around line 348-370), after `_match_matter_slug()`:
```python
tags = _auto_tag(alert_title, alert_body)
```
Pass `tags` to `create_alert()`. The `create_alert` method already has the `tags` JSONB column in the INSERT statement — verify and add if missing.

### 1b. Tag endpoints

**Where:** `outputs/dashboard.py`

**Endpoint 1: `GET /api/tags`**
- Returns all distinct tags with item counts
- SQL: Query alerts table, unnest tags JSONB array, GROUP BY, COUNT
- Response: `{"tags": [{"name": "legal", "count": 12}, ...], "total": 45}`
- Only count `status = 'pending'` alerts

```sql
SELECT tag, COUNT(*) as count
FROM alerts, jsonb_array_elements_text(tags) AS tag
WHERE status = 'pending'
GROUP BY tag
ORDER BY count DESC
```

**Endpoint 2: `POST /api/alerts/{id}/tag`**
- Body: `{"action": "add"|"remove", "tag": "string"}`
- Validate tag is non-empty, max 30 chars, alphanumeric + hyphens only
- `add`: `UPDATE alerts SET tags = tags || to_jsonb(%s::text) WHERE id = %s AND NOT tags ? %s`
- `remove`: `UPDATE alerts SET tags = tags - %s WHERE id = %s`
- Response: `{"ok": true, "tags": [updated list]}`

### 1c. Ungrouped assignment

**Endpoint 3: `POST /api/alerts/{id}/assign`**
- Body: `{"matter_slug": "existing_slug"}` or `{"matter_slug": "_new", "new_name": "Project Name"}`
- If `matter_slug == "_new"`: slugify `new_name` (lowercase, replace spaces with `_`, strip special chars except hyphens/underscores, max 50 chars). INSERT into `matter_registry` with `status='active'`, then use the new slug.
- If existing slug: verify it exists in `matter_registry`
- UPDATE: `UPDATE alerts SET matter_slug = %s WHERE id = %s`
- Response: `{"ok": true, "matter_slug": "the_slug"}`

### 1d. Frontend — Tags tab

**Where:** `outputs/static/index.html`, `outputs/static/app.js`

**HTML:** Add a view container (same pattern as Matters):
```html
<!-- VIEW: Tags -->
<div class="view" id="viewTags">
    <div class="section-label">Tags</div>
    <div id="tagsContent"></div>
</div>
```

**JS: `loadTagsTab()`** — called from `switchTab('tags')`:
1. Fetch `GET /api/tags`
2. Render each tag as a compact card with name + count
3. Click a tag → fetch `GET /api/alerts?tag={tag}` → show filtered alert cards in the same container
4. Need new endpoint `GET /api/alerts?tag={tag}` — OR reuse: fetch all pending alerts and filter client-side by tag. **Decision: add a server-side endpoint** `GET /api/alerts/by-tag/{tag}` that returns alerts where `tags ? %s` (JSONB contains). Parameterized, no injection risk.

**Endpoint 4: `GET /api/alerts/by-tag/{tag}`**
- SQL: `SELECT * FROM alerts WHERE status = 'pending' AND tags ? %s ORDER BY tier, created_at DESC`
- Response: `{"items": [...], "count": N, "tag": "legal"}`

**Tag badges on cards:** In `renderAlertCard()`, after the card header, if `alert.tags` is non-empty, render small tag badges:
```html
<div class="card-tags">
    <span class="tag-badge">legal</span>
    <span class="tag-badge">deadline</span>
</div>
```

**+tag button on card footer:** Add a small "+" button next to Resolve/Dismiss. On click, show a dropdown with available tags (hardcoded list from 1a). Selecting a tag calls `POST /api/alerts/{id}/tag` with action `add`.

**Ungrouped assignment dropdown:** On cards where `alert.matter_slug` is null (ungrouped alerts), show a dropdown in the card header area. Options: all active matters from `GET /api/matters` + "New Project..." option. Selecting calls `POST /api/alerts/{id}/assign`.

### CSS additions

```css
.tag-badge {
    display: inline-block; padding: 2px 7px; margin: 0 3px 3px 0;
    background: #e8edf3; border-radius: 4px; font-size: 10px;
    font-family: var(--mono); color: var(--text2);
}
.card-tags { padding: 0 16px 6px; }
```

---

## Step 2 — Ask Specialist + Command Bar Detection

### 2a. Ask Specialist endpoint

**Where:** `outputs/dashboard.py`

**Endpoint: `POST /api/scan/specialist`**

Request model (new):
```python
class SpecialistScanRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    capability_slug: str = Field(..., min_length=1, max_length=50)
    history: list = Field(default_factory=list)
```

Implementation:
1. Look up the capability by slug: `CapabilityRegistry.get_instance().get_by_slug(req.capability_slug)`
2. If not found or not active → 404
3. Build a `RoutingPlan` with `mode="fast"` and the single capability
4. Call `_scan_chat_capability()` with this forced plan — same function used by normal scan when a capability matches
5. Return the SSE `StreamingResponse`

**CRITICAL: This MUST use the existing `_scan_chat_capability()` function. Do NOT create a separate Claude call. The only difference from normal `/api/scan` is that capability detection is bypassed — the capability is provided directly. The underlying execution (agentic RAG, tool use, memory search) is identical.**

Pseudocode:
```python
@app.post("/api/scan/specialist", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def scan_specialist(req: SpecialistScanRequest):
    start = time.time()
    from orchestrator.capability_registry import CapabilityRegistry
    from orchestrator.capability_router import RoutingPlan

    cap = CapabilityRegistry.get_instance().get_by_slug(req.capability_slug)
    if not cap or not cap.active:
        raise HTTPException(status_code=404, detail=f"Capability '{req.capability_slug}' not found")

    plan = RoutingPlan(mode="fast", capabilities=[cap])
    scan_req = ScanRequest(question=req.question, history=req.history)
    return _scan_chat_capability(scan_req, start, {"plan": plan})
```

### 2b. Capability detection endpoint

**Where:** `outputs/dashboard.py`

**Endpoint: `GET /api/scan/detect`**

Query param: `q` (the user's partial input)

Implementation:
1. Run `CapabilityRegistry.get_instance().match_trigger(q)` — existing method, regex match
2. If match found → return `{"detected": true, "capability_slug": "legal", "capability_name": "Legal/Claims"}`
3. If no match → return `{"detected": false}`
4. **Security:** Do NOT expose trigger patterns, system prompts, or internal routing logic. Only return slug and name.

```python
@app.get("/api/scan/detect", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def detect_capability(q: str = Query("", max_length=500)):
    if len(q.strip()) < 3:
        return {"detected": false}
    from orchestrator.capability_registry import CapabilityRegistry
    cap = CapabilityRegistry.get_instance().match_trigger(q)
    if cap:
        return {"detected": True, "capability_slug": cap.slug, "capability_name": cap.name}
    return {"detected": False}
```

### 2c. Frontend — Ask Specialist tab

**Where:** `outputs/static/index.html`, `outputs/static/app.js`

**HTML:** Replace the "Coming Soon" placeholder for ask-specialist with a real view. Reuse the same chat layout as Ask Baker, but with a capability picker at the top.

```html
<!-- VIEW: Ask Specialist -->
<div class="view" id="viewAskSpecialist">
    <div class="scan-view-header">
        <span class="scan-view-title">Ask Specialist</span>
    </div>
    <div style="padding:0 16px;">
        <select id="specialistPicker" class="specialist-picker">
            <option value="">Select a specialist...</option>
        </select>
    </div>
    <div class="scan-view-body">
        <div id="specialistMessages" class="scan-messages"></div>
        <form id="specialistForm" class="scan-form" autocomplete="off">
            <input id="specialistInput" type="text" class="scan-input" placeholder="Ask the specialist..." maxlength="4000" required disabled />
            <button type="submit" class="scan-send" id="specialistSendBtn" disabled>Send</button>
        </form>
    </div>
</div>
```

**JS:**

`loadSpecialistTab()` — called from `switchTab('ask-specialist')`:
1. Fetch `GET /api/capabilities` (existing endpoint) to populate the picker
2. Filter to `capability_type == "domain"` and `active == true`
3. Populate `<select>` options with slug as value, name as label
4. On select change: enable input, clear messages, set `_specialistSlug`

`sendSpecialistMessage(question)`:
1. Same SSE streaming pattern as `sendScanMessage()` in Ask Baker
2. POST to `/api/scan/specialist` with `{question, capability_slug: _specialistSlug, history: _specialistHistory}`
3. Render director message bubble, stream Baker response, add to `_specialistHistory`
4. Keep last 10 turns in history

**Key rule (Brief §5): Do NOT build two separate chat interfaces.** Reuse the same rendering functions (`renderUserMsg`, `renderBakerMsg` or equivalent). The ONLY difference is:
- Ask Baker sends to `/api/scan`
- Ask Specialist sends to `/api/scan/specialist` with capability_slug

If the existing code doesn't have reusable render functions, extract them first, then use in both.

### 2d. Command bar auto-detection badge

**Where:** `outputs/static/app.js`

On the command bar input (`#cmdInput`), add a debounced `input` event listener:
1. Wait 300ms after last keystroke (debounce)
2. If input length >= 3 chars, call `GET /api/scan/detect?q={input}`
3. If `detected == true`, show a small badge next to the input: `<span class="cmd-detect-badge">Legal detected</span>`
4. If `detected == false` or input cleared, hide badge

**HTML addition (index.html):** Add a badge container inside `.cmd-input-wrap`:
```html
<span class="cmd-detect-badge" id="cmdDetectBadge" hidden></span>
```

**CSS:**
```css
.cmd-detect-badge {
    position: absolute; right: 60px; top: 50%; transform: translateY(-50%);
    padding: 2px 8px; background: var(--blue); color: white;
    border-radius: 4px; font-size: 10px; font-family: var(--mono);
}
```

When the user submits from the command bar (existing behavior switches to Ask Baker tab and sends the message), clear the badge.

---

## Step 3 — Board View + Artifact Storage

### 3a. Board view toggle on Matters

**Where:** `outputs/static/app.js`, `outputs/static/style.css`

Add a List | Board toggle at the top of the Matters content area.

**In `loadMatterDetail(matterSlug)`:** Add toggle buttons above the card list:
```html
<div class="view-toggle">
    <button class="toggle-btn active" data-view="list">List</button>
    <button class="toggle-btn" data-view="board">Board</button>
</div>
```

**Board view rendering:** When "Board" is selected, render items as kanban columns:
```
| Fire (T1)     | Important (T2) | Routine (T3)  | Other (T4)    |
| card          | card           | card          | card          |
| card          |                | card          |               |
```

- Each column is a vertical stack of compact cards (title + matter + time only)
- No drag-and-drop (read-only — Brief §3)
- Cards are clickable — clicking opens the full expanded card in list view
- If a column is empty, show "No items"

**CSS:**
```css
.board-view { display: flex; gap: 12px; overflow-x: auto; }
.board-column { flex: 1; min-width: 200px; }
.board-column-header {
    font-family: var(--mono); font-size: 10px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.5px; color: var(--text3);
    padding: 8px 0; border-bottom: 2px solid var(--border);
}
.board-card {
    padding: 10px 12px; margin: 6px 0; background: white;
    border: 1px solid var(--border); border-radius: 6px;
    font-size: 12px; cursor: pointer;
}
.board-card:hover { border-color: var(--blue); }
```

**Also add board view to `loadMattersTab()` (the overview page):** Show toggle there too. In board mode, show all pending alerts grouped by tier across all matters, not grouped by matter.

### 3b. Artifact storage (PostgreSQL)

**Where:** `memory/store_back.py`, `outputs/dashboard.py`

**Schema: `alert_artifacts` table**

Add to `store_back.py` — new `_ensure_alert_artifacts_table()` method, called from `__init__`:

```sql
CREATE TABLE IF NOT EXISTS alert_artifacts (
    id          SERIAL PRIMARY KEY,
    alert_id    INTEGER REFERENCES alerts(id),
    matter_slug TEXT,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    format      TEXT DEFAULT 'md',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_alert_artifacts_matter ON alert_artifacts(matter_slug);
CREATE INDEX IF NOT EXISTS idx_alert_artifacts_alert ON alert_artifacts(alert_id);
```

**Endpoint: `POST /api/artifacts/save`**

Request model:
```python
class SaveArtifactRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=100000)
    title: str = Field("Baker Result", max_length=200)
    matter_slug: Optional[str] = None
    alert_id: Optional[int] = None
    format: str = Field("md", pattern="^(md|txt)$")
```

Implementation:
1. If `matter_slug` provided, validate it exists in `matter_registry` or equals `_ungrouped`
2. **Security:** Validate `matter_slug` contains only `[a-zA-Z0-9_-]` characters (no path traversal even though we're storing in DB — defense in depth for future Dropbox sync)
3. INSERT into `alert_artifacts`
4. Response: `{"ok": true, "artifact_id": 123}`

**Endpoint: `GET /api/artifacts`**

Query params: `matter_slug` (optional), `limit` (default 50, max 200)
- If `matter_slug` provided: filter by it
- Response: `{"artifacts": [...], "count": N}`

### 3c. Frontend — Save to Project button

**Where:** `outputs/static/app.js`

The result toolbar (added in Phase A2) currently has Copy, Word, Email buttons. Add a fourth: **Save**.

In `streamInlineResult()`, where the toolbar is built, add:
```javascript
'<button class="footer-btn" onclick="saveArtifact(this)">Save</button>'
```

`saveArtifact(btn)`:
1. Get the result text from `toolbar.dataset.resultText`
2. Get the alert's `matter_slug` from the card's dataset (add `data-matter` to the card in `renderAlertCard`)
3. POST to `/api/artifacts/save` with `{content, title: "Baker Analysis", matter_slug, alert_id}`
4. On success: change button text to "Saved" for 2 seconds
5. On failure: change button text to "Error" for 2 seconds

---

## CRITICAL Rules (same as A1/A2 — must be respected)

1. **Ask Specialist routes through existing agentic RAG pipeline.** `POST /api/scan/specialist` calls `_scan_chat_capability()` — the same function used by normal `/api/scan` when a capability matches. No separate Claude call path.

2. **Command bar detection is lightweight.** `GET /api/scan/detect` only runs `match_trigger()` (regex). No LLM call. No capability execution.

3. **Auto-tagging is keyword-based.** No additional Haiku call. Simple keyword matching like `_match_matter_slug()`.

4. **Board view is read-only.** No drag-and-drop. No status changes by moving cards. Cards are clickable to view detail. Drag-and-drop is Phase C+ if ever.

5. **All SQL is parameterized.** No string concatenation in queries.

6. **All dynamic text uses `esc()`.** Markdown content uses `md()` (which escapes first). Director input uses `textContent`. No raw innerHTML with user data.

7. **Artifact `matter_slug` validation:** Regex check `[a-zA-Z0-9_-]` only. Defense in depth for future filesystem sync.

---

## Existing Code Reference

| What | Where | Notes |
|------|-------|-------|
| `_match_matter_slug()` | `pipeline.py:25` | Pattern for auto-tagging — same keyword matching approach |
| `_generate_structured_actions()` | `pipeline.py:125` | Haiku call for T1/T2 alerts — do NOT piggyback on this for tags |
| `create_alert()` | `store_back.py:2444` | Already accepts `matter_slug`. Verify `tags` param exists, add if missing |
| `CapabilityRegistry.match_trigger()` | `capability_registry.py:143` | Regex match for detection endpoint |
| `CapabilityRegistry.get_by_slug()` | `capability_registry.py:122` | Lookup for specialist endpoint |
| `CapabilityRouter.route()` | `capability_router.py:37` | Normal routing — specialist bypasses this |
| `RoutingPlan` | `capability_router.py` | Import for building forced plan |
| `_scan_chat_capability()` | `dashboard.py:~1940` | The function specialist MUST call |
| `ScanRequest` | `dashboard.py:140` | Existing request model |
| `renderAlertCard()` | `app.js:~330` | Add tag badges + ungrouped dropdown here |
| `streamInlineResult()` | `app.js:~544` | Add Save button to toolbar here |
| `GET /api/capabilities` | `dashboard.py` | Existing — returns all capabilities for specialist picker |
| `GET /api/matters` | `dashboard.py` | Existing — returns matters for ungrouped dropdown |
| `tags JSONB` column | `alerts` table | Already exists (A1 schema). Default `'[]'` |
| `board_status` column | `alerts` table | Already exists (A1 schema). Default `'new'` |

---

## Schema Changes Summary

| Change | Type | Notes |
|--------|------|-------|
| `tags` param in `create_alert()` | Code change | Column exists in DB but NOT in method signature or INSERT. Must add `tags: list = None` param, `tags_json = _json.dumps(tags) if tags else '[]'`, and include in INSERT |
| `alert_artifacts` table | New table | Via `_ensure_alert_artifacts_table()` in store_back.py |
| No other schema migrations needed | — | `tags`, `board_status`, `exit_reason` already on alerts |

---

## Endpoints Summary (6 new)

| # | Endpoint | Method | Purpose |
|---|----------|--------|---------|
| 1 | `/api/tags` | GET | List tags with item counts |
| 2 | `/api/alerts/{id}/tag` | POST | Add/remove tag on alert |
| 3 | `/api/alerts/{id}/assign` | POST | Assign ungrouped alert to matter |
| 4 | `/api/alerts/by-tag/{tag}` | GET | Filter alerts by tag |
| 5 | `/api/scan/specialist` | POST | Force-route to specific capability |
| 6 | `/api/scan/detect` | GET | Lightweight capability detection |
| 7 | `/api/artifacts/save` | POST | Save result to DB |
| 8 | `/api/artifacts` | GET | List saved artifacts |

---

## Commit Plan

```
Step 1: feat: COCKPIT-V3 B1 -- tags system + ungrouped assignment
Step 2: feat: COCKPIT-V3 B2 -- ask specialist + command bar detection
Step 3: feat: COCKPIT-V3 B3 -- board view + artifact storage
```

3 commits on branch `feat/cockpit-v3-b`. Push to origin when complete. Code 300 will review before merge.

---

## Verification Report (Code 300, 2026-03-08)

All references, dependencies, and integration points verified against codebase. Results below.

### Gaps Brisen Must Address

| # | Gap | Where | What to do |
|---|-----|-------|------------|
| 1 | `create_alert()` has no `tags` param | `store_back.py:2444` | Add `tags: list = None` to signature. Add `tags` to INSERT columns + VALUES. Serialize: `tags_json = _json.dumps(tags) if tags else '[]'` |
| 2 | `pipeline.py` call to `create_alert` has no `tags=` | `pipeline.py:357` | After calling `_auto_tag()`, pass `tags=tags` to `create_alert()` |
| 3 | `switchTab()` routes 'tags' to "Coming soon" | `app.js:126-156` | Add `'tags'` to `FUNCTIONAL_TABS` set, add `'tags': 'viewTags'` to `TAB_VIEW_MAP`, add `else if (tabName === 'tags') loadTagsTab();` |
| 4 | `renderAlertCard()` has no tags rendering | `app.js:330` | Add tag badges after card header (see CSS in brief) |
| 5 | `renderAlertCard()` has no `data-matter` attribute | `app.js:338` | Add `data-matter="..."` to the card div — needed for Save button to know the matter |
| 6 | No debounce utility in `app.js` | — | Write a simple `debounce(fn, ms)` function for command bar detection |
| 7 | `switchTab()` routes 'ask-specialist' to "Coming soon" | `app.js` | Add to `FUNCTIONAL_TABS` + `TAB_VIEW_MAP`, implement `loadSpecialistTab()` |

### Verified OK (all exist and work)

| Item | Location | Status |
|------|----------|--------|
| `alerts.tags` JSONB column | `init_database.sql:154` | Exists, DEFAULT '[]' |
| `alerts.board_status` column | `init_database.sql:155` | Exists, DEFAULT 'new' |
| `matter_registry` table + schema | `store_back.py:1717` | Full schema + indexes + seed data |
| `get_matters(status)` method | `store_back.py:1880` | Returns list of dicts |
| `_scan_chat_capability()` function | `dashboard.py:1935` | Accepts `(req, start, {"plan": plan})` — exact signature specialist needs |
| `RoutingPlan` dataclass | `capability_router.py:24` | Has `mode`, `capabilities`, `sub_tasks` fields |
| `CapabilityRegistry.get_instance()` | `capability_registry.py:50` | Thread-safe singleton, 5-min cache |
| `CapabilityRegistry.match_trigger()` | `capability_registry.py:143` | Regex match, returns CapabilityDef or None |
| `CapabilityRegistry.get_by_slug()` | `capability_registry.py:122` | Returns CapabilityDef or None |
| `GET /api/capabilities` endpoint | `dashboard.py:578` | Returns `{capabilities, count}`, auth required |
| `#cmdInput` HTML element | `index.html:80` | maxlength=4000 |
| `.cmd-input-wrap` CSS | `style.css:91` | Has `position: relative` — ready for badge |
| `_ensure_alert_threads_table()` pattern | `store_back.py:2416` | Pattern for `_ensure_alert_artifacts_table()` |
| 25 `_ensure` calls in `__init__` | `store_back.py:53-113` | Add new ensure at line 114 |
| `loadMatterDetail()` function | `app.js:734` | Works, renders cards with `renderAlertCard()` |
| `streamInlineResult()` toolbar | `app.js:600-608` | 3 buttons (Copy/Word/Email), add Save after Email |
| `/api/scan/generate-document` endpoint | `dashboard.py:2433` | Word button target, exists and working |
| Command bar → Ask Baker flow | `app.js:925-937` | Enter → switchTab('ask-baker') → sendScanMessage(q) |

### _scan_chat_capability() Exact Signature

```python
def _scan_chat_capability(req, start: float, intent_or_plan: dict = None,
                          task_id: int = None, domain: str = None, mode: str = None):
```

For Ask Specialist, call as:
```python
plan = RoutingPlan(mode="fast", capabilities=[cap])
return _scan_chat_capability(scan_req, start, {"plan": plan})
```

The function checks `intent_or_plan.get("plan")` first. If a pre-built plan is passed, it skips the router entirely. This is exactly what specialist needs.
