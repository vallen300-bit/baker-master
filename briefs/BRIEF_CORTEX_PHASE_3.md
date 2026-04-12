# BRIEF: CORTEX-PHASE-3 — Wiki Lint + Intent Feed Dashboard

## Context
Cortex v2 Phases 0-2B-II are deployed. Events flow through the bus, semantic dedup runs in shadow mode, wiki pages load in agent context. But there's zero Director visibility — no way to see what Cortex is doing, what dedup decisions it's making, or whether wiki pages are stale/orphaned. Phase 3 adds the eyes: automated wiki lint + a dashboard card showing the event stream.

## Estimated time: ~5-6h
## Complexity: Medium
## Prerequisites: Phases 0-2B-II deployed (confirmed)

---

## Feature 1: `cortex_lint_results` Table + Lint Job

### Problem
14 wiki pages exist with no quality monitoring. No contradiction detection, no orphan detection, no staleness alerting. Karpathy pattern calls for periodic lint — Baker has nothing.

### Current State
- `wiki_pages` table: 14 pages (all `agent_knowledge`), `page_type`, `updated_at`, `backlinks`, `matter_slugs` columns available
- `cortex_events` table: events flowing (shadow dedup active)
- `vip_contacts` table: ~50+ contacts
- No `cortex_lint_results` table exists

### Implementation

#### 1a. Table creation in `memory/store_back.py`

Add in `_ensure_cortex_events_table()` (after the cortex_events CREATE, around line 2590):

```sql
CREATE TABLE IF NOT EXISTS cortex_lint_results (
    id          SERIAL PRIMARY KEY,
    finding_type TEXT NOT NULL,          -- 'stale_page', 'orphan_vip', 'generation_behind', 'broken_backlink', 'missing_index'
    severity    TEXT DEFAULT 'warning',  -- 'critical', 'warning', 'info'
    slug_or_ref TEXT NOT NULL,           -- wiki page slug or VIP name
    description TEXT NOT NULL,
    status      TEXT DEFAULT 'open',     -- 'open', 'resolved', 'dismissed'
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_lint_results_status
    ON cortex_lint_results (status, severity);
```

#### 1b. Lint function in `models/cortex.py`

Add after the `_auto_queue_insights` function (around line 340). This is the core lint logic:

```python
def run_wiki_lint() -> list[dict]:
    """
    Periodic wiki health check. Detects stale pages, orphan VIPs,
    generation mismatches, broken backlinks.
    Returns list of finding dicts.
    """
    findings = []
    conn = _get_conn()
    if not conn:
        logger.error("run_wiki_lint: no DB connection")
        return findings
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # ── 1. STALE PAGES — agent_knowledge not updated in 14+ days ──
        cur.execute("""
            SELECT slug, title, updated_at
            FROM wiki_pages
            WHERE page_type = 'agent_knowledge'
              AND updated_at < NOW() - INTERVAL '14 days'
            LIMIT 50
        """)
        for row in cur.fetchall():
            findings.append({
                "finding_type": "stale_page",
                "severity": "warning",
                "slug_or_ref": row["slug"],
                "description": f"Page '{row['title']}' last updated {row['updated_at'].strftime('%Y-%m-%d')} (>14 days ago)",
            })

        # ── 2. ORPHAN VIPs — contacts not mentioned in any wiki page ──
        # Get all wiki content concatenated
        cur.execute("SELECT string_agg(content, ' ') AS all_content FROM wiki_pages LIMIT 1")
        all_content_row = cur.fetchone()
        all_content = (all_content_row["all_content"] or "").lower() if all_content_row else ""

        cur.execute("SELECT name FROM vip_contacts WHERE name IS NOT NULL LIMIT 100")
        for row in cur.fetchall():
            name_lower = row["name"].lower()
            # Check if at least the last name appears
            parts = name_lower.split()
            last_name = parts[-1] if parts else name_lower
            if len(last_name) > 2 and last_name not in all_content:
                findings.append({
                    "finding_type": "orphan_vip",
                    "severity": "info",
                    "slug_or_ref": row["name"],
                    "description": f"VIP '{row['name']}' not mentioned in any wiki page",
                })

        # ── 3. GENERATION BEHIND — cortex events newer than compiled pages ──
        cur.execute("""
            SELECT wp.slug, wp.updated_at,
                   (SELECT MAX(ce.created_at) FROM cortex_events ce
                    WHERE ce.category = CASE
                        WHEN wp.slug LIKE 'deadlines%' THEN 'deadline'
                        WHEN wp.slug LIKE 'decisions%' THEN 'decision'
                        ELSE 'unknown'
                    END) AS latest_event_at
            FROM wiki_pages wp
            WHERE wp.page_type = 'compiled_state'
            LIMIT 20
        """)
        for row in cur.fetchall():
            if row["latest_event_at"] and row["latest_event_at"] > row["updated_at"]:
                findings.append({
                    "finding_type": "generation_behind",
                    "severity": "warning",
                    "slug_or_ref": row["slug"],
                    "description": f"Compiled page '{row['slug']}' is behind latest Cortex event ({row['latest_event_at'].strftime('%Y-%m-%d %H:%M')})",
                })

        # ── 4. BROKEN BACKLINKS — referenced slugs that don't exist ──
        cur.execute("SELECT slug, backlinks FROM wiki_pages WHERE backlinks IS NOT NULL LIMIT 100")
        # Also get all existing slugs
        cur.execute("SELECT slug FROM wiki_pages LIMIT 500")
        existing_slugs = {r["slug"] for r in cur.fetchall()}

        # Re-query for backlinks
        cur.execute("SELECT slug, backlinks FROM wiki_pages WHERE backlinks IS NOT NULL AND array_length(backlinks, 1) > 0 LIMIT 100")
        for row in cur.fetchall():
            for link in (row["backlinks"] or []):
                if link not in existing_slugs:
                    findings.append({
                        "finding_type": "broken_backlink",
                        "severity": "warning",
                        "slug_or_ref": row["slug"],
                        "description": f"Page '{row['slug']}' has backlink to non-existent '{link}'",
                    })

        # ── 5. MISSING INDEX — PM agents without an index page ──
        cur.execute("""
            SELECT DISTINCT agent_owner FROM wiki_pages
            WHERE agent_owner IS NOT NULL
            LIMIT 20
        """)
        for row in cur.fetchall():
            agent = row["agent_owner"]
            cur.execute("SELECT 1 FROM wiki_pages WHERE slug = %s LIMIT 1", (f"{agent}/index",))
            if not cur.fetchone():
                findings.append({
                    "finding_type": "missing_index",
                    "severity": "warning",
                    "slug_or_ref": agent,
                    "description": f"Agent '{agent}' has wiki pages but no index page at '{agent}/index'",
                })

        conn.commit()

        # ── Store findings (clear old open, insert new) ──
        cur.execute("DELETE FROM cortex_lint_results WHERE status = 'open'")
        for f in findings:
            cur.execute("""
                INSERT INTO cortex_lint_results (finding_type, severity, slug_or_ref, description)
                VALUES (%s, %s, %s, %s)
            """, (f["finding_type"], f["severity"], f["slug_or_ref"], f["description"]))
        conn.commit()
        cur.close()

        logger.info("wiki_lint: %d findings stored", len(findings))
        return findings

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("run_wiki_lint failed: %s", e)
        return findings
    finally:
        _put_conn(conn)
```

#### 1c. Scheduler job in `triggers/embedded_scheduler.py`

Add in `_register_all_jobs()` alongside existing health jobs:

```python
# Wiki lint — daily 06:30 UTC (before morning brief)
scheduler.add_job(
    _run_wiki_lint,
    trigger=CronTrigger(hour=6, minute=30, timezone="UTC"),
    id="wiki_lint",
    name="wiki_lint",
    replace_existing=True,
)
```

And the wrapper function (add near the other sentinel functions):

```python
async def _run_wiki_lint():
    """Run wiki lint and log results."""
    try:
        from models.cortex import run_wiki_lint
        findings = run_wiki_lint()
        logger.info("wiki_lint: completed with %d findings", len(findings))
        if findings:
            # Report to sentinel health for visibility
            from triggers.sentinel_health import report_success
            report_success("wiki_lint", {"findings_count": len(findings)})
    except Exception as e:
        logger.error("wiki_lint scheduler failed: %s", e)
```

### Key Constraints
- Lint must NOT modify wiki pages — read-only analysis
- `DELETE FROM cortex_lint_results WHERE status = 'open'` clears only unfixed findings. Dismissed/resolved findings are preserved for history
- `string_agg` for orphan VIP check is bounded by LIMIT on wiki_pages (14 pages today, max ~500)
- All queries have LIMIT clauses

---

## Feature 2: Intent Feed API Endpoints

### Problem
No API to query Cortex events or lint results. Dashboard can't show anything without endpoints.

### Current State
- `/api/dashboard/morning-brief` returns `activity` (capability_runs) but NOT cortex events
- `/api/dashboard/activity-feed` exists but returns capability_runs, not cortex data
- No cortex-specific endpoints exist

### Implementation

Add these 3 endpoints in `outputs/dashboard.py`. Place them after the existing `/api/dashboard/activity-feed` endpoint (around line 3740):

```python
@app.get("/api/cortex/events", tags=["cortex"], dependencies=[Depends(verify_api_key)])
async def get_cortex_events(
    event_type: str = None,
    category: str = None,
    source_agent: str = None,
    limit: int = 30,
):
    """Cortex event feed — filterable by type, category, agent."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        clauses = []
        params = []
        if event_type:
            clauses.append("event_type = %s")
            params.append(event_type)
        if category:
            clauses.append("category = %s")
            params.append(category)
        if source_agent:
            clauses.append("source_agent = %s")
            params.append(source_agent)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        safe_limit = min(max(limit, 1), 100)
        params.append(safe_limit)
        cur.execute(f"""
            SELECT id, event_type, category, source_agent, source_type,
                   source_ref, payload, refers_to, canonical_id, created_at
            FROM cortex_events
            {where}
            ORDER BY created_at DESC
            LIMIT %s
        """, params)
        events = [_serialize(dict(r)) for r in cur.fetchall()]
        cur.close()
        conn.commit()
        return {"events": events, "count": len(events)}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("get_cortex_events: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        store._put_conn(conn)


@app.get("/api/cortex/lint", tags=["cortex"], dependencies=[Depends(verify_api_key)])
async def get_cortex_lint(status: str = "open", limit: int = 50):
    """Lint results — wiki health findings."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        safe_limit = min(max(limit, 1), 100)
        cur.execute("""
            SELECT id, finding_type, severity, slug_or_ref, description, status, created_at
            FROM cortex_lint_results
            WHERE status = %s
            ORDER BY
                CASE severity WHEN 'critical' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END,
                created_at DESC
            LIMIT %s
        """, (status, safe_limit))
        results = [_serialize(dict(r)) for r in cur.fetchall()]
        cur.close()
        conn.commit()
        return {"lint_results": results, "count": len(results)}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("get_cortex_lint: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        store._put_conn(conn)


@app.post("/api/cortex/lint/run", tags=["cortex"], dependencies=[Depends(verify_api_key)])
async def run_cortex_lint_now():
    """Trigger wiki lint on demand."""
    try:
        from models.cortex import run_wiki_lint
        findings = run_wiki_lint()
        return {"findings": len(findings), "details": findings[:20]}
    except Exception as e:
        logger.error("run_cortex_lint_now: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/cortex/stats", tags=["cortex"], dependencies=[Depends(verify_api_key)])
async def get_cortex_stats():
    """Cortex summary stats for dashboard card header."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Event counts by type (last 7 days)
        cur.execute("""
            SELECT event_type, COUNT(*) as cnt
            FROM cortex_events
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY event_type
            ORDER BY cnt DESC
            LIMIT 20
        """)
        event_counts = {r["event_type"]: r["cnt"] for r in cur.fetchall()}

        # Total events
        cur.execute("SELECT COUNT(*) as cnt FROM cortex_events LIMIT 1")
        total_events = cur.fetchone()["cnt"]

        # Lint findings
        cur.execute("""
            SELECT severity, COUNT(*) as cnt
            FROM cortex_lint_results
            WHERE status = 'open'
            GROUP BY severity
            LIMIT 10
        """)
        lint_counts = {r["severity"]: r["cnt"] for r in cur.fetchall()}

        # Wiki pages
        cur.execute("""
            SELECT page_type, COUNT(*) as cnt
            FROM wiki_pages
            GROUP BY page_type
            LIMIT 10
        """)
        wiki_counts = {r["page_type"]: r["cnt"] for r in cur.fetchall()}

        # Dedup stats (shadow)
        cur.execute("""
            SELECT event_type, COUNT(*) as cnt
            FROM cortex_events
            WHERE event_type IN ('would_merge', 'review_needed', 'merged')
            GROUP BY event_type
            LIMIT 10
        """)
        dedup_counts = {r["event_type"]: r["cnt"] for r in cur.fetchall()}

        cur.close()
        conn.commit()
        return {
            "total_events": total_events,
            "events_7d": event_counts,
            "dedup": dedup_counts,
            "lint_open": lint_counts,
            "wiki_pages": wiki_counts,
        }
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("get_cortex_stats: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        store._put_conn(conn)
```

### Key Constraints
- All queries LIMIT-bounded
- All except blocks have `conn.rollback()`
- Uses existing `_serialize()` helper and `verify_api_key` dependency
- `f""` SQL is safe here — filter params are always `%s` parameterized, never interpolated. The only dynamic part is the WHERE clause construction from validated filter params
- No new endpoint shadows existing ones (verified: no `/api/cortex/*` routes exist)

---

## Feature 3: Intent Feed Dashboard Card

### Problem
Director has zero visibility into what Cortex is doing. Events accumulate in PostgreSQL with no UI.

### Current State
- 2x2 grid: Travel, Critical, Promised, Meetings
- `silentContactsCard` div below grid (hidden, can be repurposed for a different card or left)
- Card pattern: `.grid-cell` with `.grid-cell-header` + `.grid-cell-body`

### Implementation

#### 3a. HTML — Add full-width Intent Feed card below the grid

In `outputs/static/index.html`, after the closing `</div>` of `.landing-grid` (line 221) and before the `silentContactsCard` (line 223):

```html
<!-- Cortex Intent Feed (CORTEX-PHASE-3) -->
<div id="cortexFeedCard" class="cortex-feed-card" hidden>
    <div class="grid-cell-header grid-header-cortex">
        <span class="section-label" style="margin:0">Cortex</span>
        <span class="cortex-tabs">
            <button class="cortex-tab active" onclick="_cortexTab('events')" id="cortexTabEvents">Events</button>
            <button class="cortex-tab" onclick="_cortexTab('dedup')" id="cortexTabDedup">Dedup</button>
            <button class="cortex-tab" onclick="_cortexTab('lint')" id="cortexTabLint">Lint</button>
        </span>
        <span class="grid-cell-count" id="cortexCount"></span>
    </div>
    <div class="cortex-feed-body" id="cortexFeedBody">
        <div class="grid-empty">Loading Cortex data...</div>
    </div>
</div>
```

#### 3b. CSS — Add to `outputs/static/style.css`

Add at the end of the file (before any media queries):

```css
/* ── Cortex Intent Feed (CORTEX-PHASE-3) ── */
.cortex-feed-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: var(--shadow-sm);
    margin-top: 16px;
    max-height: 340px;
    display: flex;
    flex-direction: column;
}
.grid-header-cortex {
    background: rgba(100, 120, 180, 0.08);
    display: flex;
    align-items: center;
    gap: 12px;
}
.cortex-tabs {
    display: flex;
    gap: 4px;
    margin-left: auto;
}
.cortex-tab {
    background: none;
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 2px 10px;
    font-size: 11px;
    color: var(--text3);
    cursor: pointer;
    font-family: inherit;
}
.cortex-tab.active {
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
}
.cortex-feed-body {
    overflow-y: auto;
    padding: 8px 0;
    flex: 1;
}
.cortex-event-row {
    display: flex;
    align-items: baseline;
    padding: 6px 18px;
    font-size: 12px;
    border-bottom: 1px solid var(--border);
    gap: 10px;
}
.cortex-event-row:last-child { border-bottom: none; }
.cortex-event-type {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    min-width: 70px;
    flex-shrink: 0;
}
.cortex-type-accepted { color: var(--green, #5b9a6f); }
.cortex-type-would_merge { color: var(--amber, #d4a535); }
.cortex-type-review_needed { color: var(--fire, #c75050); }
.cortex-type-merged { color: var(--green, #5b9a6f); }
.cortex-event-agent {
    font-size: 10px;
    color: var(--text3);
    min-width: 60px;
    flex-shrink: 0;
}
.cortex-event-desc {
    flex: 1;
    color: var(--text1);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.cortex-event-time {
    font-size: 10px;
    color: var(--text3);
    flex-shrink: 0;
}
.cortex-lint-severity {
    font-size: 10px;
    font-weight: 600;
    min-width: 60px;
    flex-shrink: 0;
}
.cortex-lint-critical { color: var(--fire, #c75050); }
.cortex-lint-warning { color: var(--amber, #d4a535); }
.cortex-lint-info { color: var(--text3); }
```

**IMPORTANT:** Bump cache version on both CSS and JS links in `index.html`. Find the current `?v=` values and increment by 1.

#### 3c. JavaScript — Add to `outputs/static/app.js`

Add these functions at the end of the file (before any closing braces/IFE):

```javascript
/* ── Cortex Intent Feed (CORTEX-PHASE-3) ── */
let _cortexCurrentTab = 'events';
let _cortexData = { events: [], dedup: [], lint: [], stats: {} };

async function loadCortexFeed() {
    try {
        const [eventsRes, lintRes, statsRes] = await Promise.all([
            fetch('/api/cortex/events?limit=30', { headers: { 'X-Baker-Key': _bakerKey() } }),
            fetch('/api/cortex/lint?status=open&limit=20', { headers: { 'X-Baker-Key': _bakerKey() } }),
            fetch('/api/cortex/stats', { headers: { 'X-Baker-Key': _bakerKey() } }),
        ]);
        if (eventsRes.ok) {
            const d = await eventsRes.json();
            _cortexData.events = d.events || [];
            // Split dedup events
            _cortexData.dedup = _cortexData.events.filter(
                e => ['would_merge', 'review_needed', 'merged'].includes(e.event_type)
            );
        }
        if (lintRes.ok) {
            const d = await lintRes.json();
            _cortexData.lint = d.lint_results || [];
        }
        if (statsRes.ok) {
            _cortexData.stats = await statsRes.json();
        }

        const card = document.getElementById('cortexFeedCard');
        const total = (_cortexData.events.length || 0);
        const lintOpen = (_cortexData.lint.length || 0);
        if (total > 0 || lintOpen > 0) {
            card.hidden = false;
            document.getElementById('cortexCount').textContent =
                total + ' events' + (lintOpen > 0 ? ', ' + lintOpen + ' lint' : '');
        } else {
            card.hidden = true;
            return;
        }
        _renderCortexTab(_cortexCurrentTab);
    } catch (e) {
        console.warn('loadCortexFeed:', e);
    }
}

function _cortexTab(tab) {
    _cortexCurrentTab = tab;
    document.querySelectorAll('.cortex-tab').forEach(t => t.classList.remove('active'));
    document.getElementById('cortexTab' + tab.charAt(0).toUpperCase() + tab.slice(1)).classList.add('active');
    _renderCortexTab(tab);
}

function _renderCortexTab(tab) {
    const body = document.getElementById('cortexFeedBody');
    const items = tab === 'dedup' ? _cortexData.dedup :
                  tab === 'lint' ? _cortexData.lint :
                  _cortexData.events;

    if (!items || items.length === 0) {
        body.innerHTML = '<div class="grid-empty">No ' + tab + ' data yet.</div>';
        return;
    }

    if (tab === 'lint') {
        body.innerHTML = items.map(r => `
            <div class="cortex-event-row">
                <span class="cortex-lint-severity cortex-lint-${r.severity}">${r.severity}</span>
                <span class="cortex-event-type">${r.finding_type}</span>
                <span class="cortex-event-desc" title="${_escAttr(r.description)}">${_escText(r.description)}</span>
            </div>
        `).join('');
        return;
    }

    body.innerHTML = items.map(ev => {
        const payload = typeof ev.payload === 'string' ? JSON.parse(ev.payload) : (ev.payload || {});
        const desc = payload.description || payload.decision || JSON.stringify(payload).substring(0, 120);
        const time = ev.created_at ? new Date(ev.created_at).toLocaleString('en-GB', {
            day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'
        }) : '';
        return `
            <div class="cortex-event-row">
                <span class="cortex-event-type cortex-type-${ev.event_type}">${ev.event_type}</span>
                <span class="cortex-event-agent">${ev.source_agent || ''}</span>
                <span class="cortex-event-desc" title="${_escAttr(desc)}">${_escText(desc)}</span>
                <span class="cortex-event-time">${time}</span>
            </div>
        `;
    }).join('');
}

function _escAttr(s) { return (s || '').replace(/"/g, '&quot;').replace(/</g, '&lt;'); }
function _escText(s) { return (s || '').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
```

**Important:** Check if `_escAttr` / `_escText` helpers already exist in app.js. If so, use the existing ones. If similar helpers exist with different names (like `_escHtml`), use those instead.

#### 3d. Wire into `loadMorningBrief()`

In `app.js`, find `loadMorningBrief()` function (around line 941). At the end of this function, after all other data rendering, add:

```javascript
// Load Cortex Intent Feed
loadCortexFeed();
```

This ensures the feed loads alongside the morning brief data.

#### 3e. `_bakerKey()` helper

Check if a helper to get the API key for fetch headers already exists. Likely the existing code uses a hardcoded header or reads from a variable. Match the existing pattern — do NOT introduce a new auth mechanism. Look for patterns like `headers: {'X-Baker-Key': ...}` in existing fetch calls and replicate.

### Key Constraints
- Card stays `hidden` if zero events AND zero lint findings — no empty UI
- Tab state persists during session (variable, not URL)
- XSS protection: use `_escText` / `_escAttr` for all user-derived content
- No SSE or WebSocket — simple fetch on morning brief load + manual refresh
- Cache bust: increment `?v=` on both CSS and JS `<link>`/`<script>` tags

---

## Files Modified
- `memory/store_back.py` — `cortex_lint_results` table creation in `_ensure_cortex_events_table()`
- `models/cortex.py` — `run_wiki_lint()` function (~80 lines)
- `triggers/embedded_scheduler.py` — `wiki_lint` cron job (daily 06:30 UTC)
- `outputs/dashboard.py` — 4 new endpoints (`/api/cortex/events`, `/api/cortex/lint`, `/api/cortex/lint/run`, `/api/cortex/stats`)
- `outputs/static/index.html` — Cortex card HTML (after `.landing-grid` closing div)
- `outputs/static/style.css` — Cortex card styles (~60 lines)
- `outputs/static/app.js` — `loadCortexFeed()`, `_cortexTab()`, `_renderCortexTab()`, helpers

## Do NOT Touch
- `models/cortex.py` existing functions (`publish_event`, `check_dedup`, `cortex_create_deadline`, `cortex_store_decision`) — these are Phase 2 and working
- `orchestrator/agent.py` — tool router is stable
- `orchestrator/capability_runner.py` — context loading is stable
- `baker_mcp/baker_mcp_server.py` — MCP routing is stable
- The 2x2 grid structure in index.html — don't rearrange existing cards

## Quality Checkpoints
1. Syntax check all modified Python files: `python3 -c "import py_compile; py_compile.compile('FILE', doraise=True)"`
2. Verify `cortex_lint_results` table created after deploy: `SELECT column_name FROM information_schema.columns WHERE table_name = 'cortex_lint_results'`
3. Test lint on demand: `curl -s -X POST "https://baker-master.onrender.com/api/cortex/lint/run?key=bakerbhavanga"` — should return findings
4. Test events endpoint: `curl -s "https://baker-master.onrender.com/api/cortex/events?limit=5&key=bakerbhavanga"` — should return event list
5. Test stats endpoint: `curl -s "https://baker-master.onrender.com/api/cortex/stats?key=bakerbhavanga"` — should return counts
6. Load dashboard in browser — Cortex card should appear below the grid if events/lint exist
7. Click Events/Dedup/Lint tabs — should switch content
8. Verify CSS/JS cache version bumped — check `?v=` params in HTML source
9. Mobile check: card should be full-width and scrollable on small screens

## Verification SQL
```sql
-- Confirm table exists
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'cortex_lint_results' ORDER BY ordinal_position;

-- Check lint findings after first run
SELECT finding_type, severity, COUNT(*) FROM cortex_lint_results
WHERE status = 'open' GROUP BY finding_type, severity;

-- Cortex events flowing
SELECT event_type, category, source_agent, created_at
FROM cortex_events ORDER BY id DESC LIMIT 10;

-- Stats sanity
SELECT COUNT(*) FROM cortex_events;
SELECT COUNT(*) FROM cortex_lint_results WHERE status = 'open';
SELECT COUNT(*) FROM wiki_pages;
```
