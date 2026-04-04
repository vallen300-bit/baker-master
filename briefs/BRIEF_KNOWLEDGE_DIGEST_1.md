# BRIEF: KNOWLEDGE-DIGEST-1 — LLM-Compiled Knowledge Base from RSS Articles

## Context
Inspired by Karpathy's approach: instead of showing raw RSS feeds, use LLMs to **compile** incoming articles into structured, per-topic knowledge files. The knowledge base becomes the product — always current, concise, high-signal. Raw articles remain available as drill-down.

Baker already ingests ~116 articles/week across 12 feeds, scores relevance with Gemini Flash, and stores summaries. What's missing is the compilation layer that turns raw articles into maintained knowledge pages.

## Estimated time: ~4-5h (backend + frontend + testing)
## Complexity: Medium
## Prerequisites: None (builds on existing RSS pipeline)

---

## Feature 1: Knowledge Digest DB Table + Compilation Engine

### Problem
RSS articles are stored individually. No synthesis. The Media tab is a raw feed — useful for scanning but not for answering "what's happening in branded residences this week?"

### Current State
- `rss_articles` stores title, url, summary (HTML, 1-9KB), published_at
- `rss_feeds` has category field (AI Technology, Market Intelligence, etc.)
- `run_rss_poll()` in `triggers/rss_trigger.py` runs every 60 min
- Articles already scored for relevance via `_check_article_relevance()` (Gemini Flash)
- `deep_analyses` table exists but is for ad-hoc research, not recurring digests

### Implementation

#### 1a. New DB table: `knowledge_digests`

Add to `memory/store_back.py` in `_ensure_tables()` (near line ~200):

```sql
CREATE TABLE IF NOT EXISTS knowledge_digests (
    id SERIAL PRIMARY KEY,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    digest_md TEXT NOT NULL,
    source_article_ids INTEGER[] DEFAULT '{}',
    article_count INTEGER DEFAULT 0,
    last_compiled TIMESTAMPTZ DEFAULT NOW(),
    period_start TIMESTAMPTZ,
    period_end TIMESTAMPTZ,
    model_used TEXT DEFAULT 'gemini-flash',
    token_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_digests_cat_period
    ON knowledge_digests(category, period_start);
```

Schema rationale:
- `category` — matches `rss_feeds.category` (e.g., "AI Technology", "Market Intelligence")
- `digest_md` — compiled markdown: structured summary with sections
- `source_article_ids` — links back to `rss_articles.id` for drill-down
- `period_start/end` — the time window this digest covers (e.g., weekly)
- Unique index prevents duplicate digests for the same category+period

#### 1b. Compilation function: `compile_knowledge_digest()`

Add to `triggers/rss_trigger.py` (after `_check_article_relevance()`):

```python
def compile_knowledge_digest(category: str, days: int = 7):
    """Compile recent articles in a category into a structured knowledge digest."""
    from memory.store_back import BakerStore
    from llm.gemini_client import call_flash
    import json

    store = BakerStore()
    conn = store._get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT a.id, a.title, a.url, a.summary, a.published_at,
                   f.title AS feed_title
            FROM rss_articles a JOIN rss_feeds f ON a.feed_id = f.id
            WHERE f.category = %s AND f.is_active = true
              AND a.published_at > NOW() - make_interval(days => %s)
            ORDER BY a.published_at DESC LIMIT 50
        """, (category, days))
        articles = [dict(r) for r in cur.fetchall()]
        cur.close()
        if not articles:
            return None

        # Strip HTML from summaries for cleaner LLM input
        import re
        def strip_html(text):
            if not text:
                return ''
            return re.sub(r'<[^>]+>', '', text)[:2000]

        # Build article digest for LLM
        article_texts = []
        for a in articles:
            article_texts.append(
                f"**{a['title']}** ({a['feed_title']}, {str(a['published_at'])[:10]})\n"
                f"{strip_html(a['summary'])[:800]}\n"
                f"URL: {a['url']}"
            )
        articles_block = "\n---\n".join(article_texts)

        prompt = f"""You are an intelligence analyst compiling a weekly knowledge digest for a luxury hospitality investor and CEO.

Category: {category}
Period: Last {days} days
Articles: {len(articles)}

Compile these articles into a structured intelligence brief using this format:

## Executive Summary
2-3 sentence overview of what happened this week in this space.

## Key Developments
Numbered list of the 3-5 most important developments. Each: one bold headline, 2-3 sentences of context, source link.

## Signals & Trends
What patterns or shifts are emerging? What should the Director watch?

## People & Companies to Watch
Names mentioned that are relevant — new appointments, acquisitions, strategic moves.

## Relevance to Portfolio
How does this connect to luxury hospitality, branded residences, or wellness investments?

Rules:
- Be concise. Total output under 1500 words.
- Use markdown formatting.
- Include source URLs as inline links.
- Focus on signal, not noise. Skip press releases with no strategic value.
- If fewer than 3 articles have real substance, say so — don't pad.

Articles:
{articles_block}"""

        digest_md = call_flash(prompt, system="You compile structured intelligence digests. Be concise and analytical.")
        if not digest_md:
            return None

        # Store the digest
        article_ids = [a['id'] for a in articles]
        now = datetime.utcnow()
        period_start = now - timedelta(days=days)

        conn2 = store._get_conn()
        if not conn2:
            return None
        try:
            cur2 = conn2.cursor()
            cur2.execute("""
                INSERT INTO knowledge_digests
                    (category, title, digest_md, source_article_ids,
                     article_count, period_start, period_end, model_used)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'gemini-flash')
                ON CONFLICT (category, period_start)
                DO UPDATE SET digest_md = EXCLUDED.digest_md,
                    source_article_ids = EXCLUDED.source_article_ids,
                    article_count = EXCLUDED.article_count,
                    last_compiled = NOW()
                RETURNING id
            """, (category, f"{category} — Week of {period_start.strftime('%b %d')}",
                  digest_md, article_ids, len(articles), period_start, now))
            conn2.commit()
            result = cur2.fetchone()
            cur2.close()
            logger.info(f"Knowledge digest compiled: {category}, {len(articles)} articles")
            return result[0] if result else None
        except Exception as e:
            conn2.rollback()
            logger.error(f"Failed to store knowledge digest: {e}")
            return None
        finally:
            store._put_conn(conn2)
    except Exception as e:
        conn.rollback()
        logger.error(f"compile_knowledge_digest failed for {category}: {e}")
        return None
    finally:
        store._put_conn(conn)
```

#### 1c. Trigger compilation after RSS poll

In `run_rss_poll()` (at the end, after all feeds processed), add:

```python
# Compile knowledge digests if articles were ingested
if total_new > 0:
    try:
        conn_cat = store._get_conn()
        if conn_cat:
            cur_cat = conn_cat.cursor()
            cur_cat.execute("""
                SELECT DISTINCT category FROM rss_feeds
                WHERE is_active = true AND category IS NOT NULL
            """)
            categories = [r[0] for r in cur_cat.fetchall()]
            cur_cat.close()
            store._put_conn(conn_cat)

            for cat in categories:
                # Only recompile if last digest is >6h old
                conn_check = store._get_conn()
                if conn_check:
                    cur_check = conn_check.cursor()
                    cur_check.execute("""
                        SELECT last_compiled FROM knowledge_digests
                        WHERE category = %s
                        ORDER BY last_compiled DESC LIMIT 1
                    """, (cat,))
                    row = cur_check.fetchone()
                    cur_check.close()
                    store._put_conn(conn_check)

                    if row and row[0] and (datetime.utcnow() - row[0].replace(tzinfo=None)).total_seconds() < 21600:
                        continue  # Skip — compiled less than 6h ago

                compile_knowledge_digest(cat)
    except Exception as e:
        logger.error(f"Knowledge digest compilation failed: {e}")
```

### Key Constraints
- **6-hour cooldown** between recompilations per category (avoid burning tokens)
- **50-article cap** per digest (Gemini Flash context is sufficient)
- **HTML stripped** before LLM input (summaries are raw HTML)
- **Upsert** — same category+period overwrites, no duplicates
- **Fault-tolerant** — compilation failure doesn't block RSS poll
- `call_flash()` requires `system=` parameter (known pattern from MEMORY.md)

### Cost Estimate
- ~5 categories × 1 Flash call × ~4K input tokens × ~1.5K output = ~28K tokens/compilation
- At $0.15/1M input + $0.60/1M output: ~$0.005 per full compilation cycle
- Max 4 cycles/day = **~$0.02/day**, negligible

---

## Feature 2: Knowledge Digest API Endpoint

### Problem
Frontend needs to fetch compiled digests to display in the Media tab.

### Current State
`/api/rss/articles` returns raw articles. No digest endpoint exists.

### Implementation

Add to `outputs/dashboard.py` (after `/api/rss/category-counts`):

```python
@app.get("/api/rss/knowledge-digests", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_knowledge_digests(category: Optional[str] = None):
    """Get compiled knowledge digests, optionally filtered by category."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"digests": []}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if category:
                cur.execute("""
                    SELECT id, category, title, digest_md, article_count,
                           last_compiled, period_start, period_end
                    FROM knowledge_digests
                    WHERE category = %s
                    ORDER BY last_compiled DESC LIMIT 5
                """, (category,))
            else:
                cur.execute("""
                    SELECT DISTINCT ON (category)
                        id, category, title, digest_md, article_count,
                        last_compiled, period_start, period_end
                    FROM knowledge_digests
                    ORDER BY category, last_compiled DESC
                """)
            digests = [_serialize(dict(r)) for r in cur.fetchall()]
            cur.close()
            return {"digests": digests}
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"GET /api/rss/knowledge-digests failed: {e}")
        return {"digests": []}
```

### Verification
```sql
SELECT category, title, article_count, last_compiled,
       LEFT(digest_md, 200) AS preview
FROM knowledge_digests ORDER BY last_compiled DESC LIMIT 10;
```

---

## Feature 3: Media Tab — Knowledge Digest View

### Problem
Media tab shows raw article list. Should show compiled knowledge digests with option to drill into raw articles.

### Current State
- `loadMediaTab()` in `app.js` (~line 5665) fetches `/api/rss/articles` and renders article cards
- Category dropdown already exists
- Sidebar categories with click-to-filter already wired (MEDIA-SIDEBAR feature)

### Implementation

#### 3a. Add digest panel to Media tab (app.js)

Modify `loadMediaTab()` to fetch digests first, then articles as drill-down:

```javascript
async function loadMediaTab() {
    var container = document.getElementById('mediaContent');
    if (!container) return;
    showLoading(container, 'Loading media');

    // MEDIA-SIDEBAR: Consume pre-filter from sidebar click
    var preFilter = window._mediaFilterCategory;
    window._mediaFilterCategory = undefined;

    try {
        // Fetch knowledge digests
        var digestUrl = '/api/rss/knowledge-digests';
        if (preFilter) digestUrl += '?category=' + encodeURIComponent(preFilter);
        var digestResp = await bakerFetch(digestUrl);
        var digestData = digestResp.ok ? await digestResp.json() : { digests: [] };

        // Fetch feeds for filter dropdown
        var feedsResp = await bakerFetch('/api/rss/feeds');
        var feedsData = feedsResp.ok ? await feedsResp.json() : { feeds: [] };

        container.textContent = '';

        // Category filter dropdown (same as before)
        if (feedsData.feeds && feedsData.feeds.length > 0) {
            var filterRow = document.createElement('div');
            filterRow.style.cssText = 'margin-bottom:12px;display:flex;align-items:center;gap:12px;';
            var catSelect = document.createElement('select');
            catSelect.style.cssText = 'padding:6px 10px;border:1px solid var(--border);border-radius:6px;font-size:11px;font-family:var(--font);';
            catSelect.innerHTML = '<option value="">All categories</option>';
            var categories = {};
            feedsData.feeds.forEach(function(f) {
                if (f.category && !categories[f.category]) {
                    categories[f.category] = true;
                    var opt = document.createElement('option');
                    opt.value = f.category;
                    opt.textContent = f.category;
                    catSelect.appendChild(opt);
                }
            });
            if (preFilter) catSelect.value = preFilter;

            // View toggle: Digest / Raw
            var viewToggle = document.createElement('button');
            viewToggle.textContent = 'Show Raw Articles';
            viewToggle.style.cssText = 'padding:4px 10px;border:1px solid var(--border);border-radius:6px;font-size:10px;font-family:var(--mono);cursor:pointer;background:transparent;color:var(--text2);';
            viewToggle.dataset.mode = 'digest';

            catSelect.addEventListener('change', function() {
                if (viewToggle.dataset.mode === 'digest') {
                    _renderDigests(container, filterRow, catSelect.value);
                } else {
                    _renderRawArticles(container, filterRow, catSelect.value);
                }
            });

            viewToggle.addEventListener('click', function() {
                if (viewToggle.dataset.mode === 'digest') {
                    viewToggle.dataset.mode = 'raw';
                    viewToggle.textContent = 'Show Intelligence Digest';
                    _renderRawArticles(container, filterRow, catSelect.value);
                } else {
                    viewToggle.dataset.mode = 'digest';
                    viewToggle.textContent = 'Show Raw Articles';
                    _renderDigests(container, filterRow, catSelect.value);
                }
            });

            filterRow.appendChild(catSelect);
            filterRow.appendChild(viewToggle);
            container.appendChild(filterRow);
        }

        // Render digests (default view)
        if (digestData.digests && digestData.digests.length > 0) {
            _showDigests(container, digestData.digests);
        } else {
            // Fallback to raw articles if no digests exist yet
            _renderRawArticles(container, container.querySelector('div'), preFilter || '');
        }
    } catch (e) {
        container.textContent = 'Failed to load media.';
    }
}
```

#### 3b. New helper: `_showDigests()`

```javascript
function _showDigests(container, digests) {
    // Clear existing content except filter row
    while (container.children.length > 1) {
        container.removeChild(container.lastChild);
    }
    for (var i = 0; i < digests.length; i++) {
        var d = digests[i];
        var card = document.createElement('div');
        card.style.cssText = 'background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:12px;';

        var header = document.createElement('div');
        header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;';

        var catLabel = document.createElement('span');
        catLabel.style.cssText = 'font-family:var(--mono);font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.6px;color:var(--accent);';
        catLabel.textContent = d.category;
        header.appendChild(catLabel);

        var meta = document.createElement('span');
        meta.style.cssText = 'font-size:10px;color:var(--text3);';
        meta.textContent = (d.article_count || 0) + ' articles · compiled ' + _timeAgo(d.last_compiled);
        header.appendChild(meta);

        card.appendChild(header);

        // Render markdown as HTML (simple conversion)
        var body = document.createElement('div');
        body.style.cssText = 'font-size:13px;line-height:1.6;color:var(--text1);';
        body.className = 'digest-content';
        setSafeHTML(body, _simpleMarkdown(d.digest_md || ''));
        card.appendChild(body);

        container.appendChild(card);
    }
}
```

#### 3c. New helper: `_renderDigests()` and `_renderRawArticles()`

```javascript
async function _renderDigests(container, filterRow, category) {
    // Clear and show loading
    while (container.children.length > 1) {
        container.removeChild(container.lastChild);
    }
    var url = '/api/rss/knowledge-digests';
    if (category) url += '?category=' + encodeURIComponent(category);
    var resp = await bakerFetch(url);
    if (resp.ok) {
        var data = await resp.json();
        if (data.digests && data.digests.length > 0) {
            _showDigests(container, data.digests);
        } else {
            var empty = document.createElement('div');
            empty.textContent = 'No digest yet for this category. Digests compile automatically after the next RSS poll.';
            empty.style.cssText = 'color:var(--text3);font-size:13px;padding:20px 0;';
            container.appendChild(empty);
        }
    }
}

async function _renderRawArticles(container, filterRow, category) {
    while (container.children.length > 1) {
        container.removeChild(container.lastChild);
    }
    var url = '/api/rss/articles?limit=50';
    if (category) url += '&category=' + encodeURIComponent(category);
    var resp = await bakerFetch(url);
    if (resp.ok) {
        var data = await resp.json();
        renderArticles(container, data.articles || [], filterRow);
    }
}
```

#### 3d. Simple markdown renderer (add near utility functions)

```javascript
function _simpleMarkdown(md) {
    if (!md) return '';
    // Escape HTML first
    var html = md.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    // Headers
    html = html.replace(/^### (.+)$/gm, '<h4 style="margin:12px 0 4px;font-size:12px;color:var(--text2);">$1</h4>');
    html = html.replace(/^## (.+)$/gm, '<h3 style="margin:16px 0 6px;font-size:13px;font-weight:700;color:var(--text1);">$1</h3>');
    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Links
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" style="color:var(--accent);">$1</a>');
    // Numbered lists
    html = html.replace(/^\d+\. (.+)$/gm, '<li style="margin:2px 0;margin-left:16px;">$1</li>');
    // Bullet lists
    html = html.replace(/^- (.+)$/gm, '<li style="margin:2px 0;margin-left:16px;">$1</li>');
    // Paragraphs
    html = html.replace(/\n\n/g, '</p><p style="margin:8px 0;">');
    html = '<p style="margin:8px 0;">' + html + '</p>';
    return html;
}
```

### Key Constraints
- **Digest is default view** — raw articles available via toggle button
- **Digest view is read-only** — no editing, just display
- Use `setSafeHTML()` (existing XSS-safe function) for rendering
- `_simpleMarkdown()` is intentionally minimal — no full parser needed
- Keep `renderArticles()` untouched — it's the raw view, already working
- Cache bust: bump `app.js?v=97`

### Verification
1. Hard refresh → Media tab shows digest cards instead of raw articles
2. Each digest card shows: category label, article count, compilation time, structured markdown
3. "Show Raw Articles" button switches to the old raw article view
4. Category dropdown filters both digest and raw views
5. Sidebar category clicks pre-filter digest view correctly
6. If no digests exist yet, falls back to raw articles gracefully

---

## Files Modified
- `memory/store_back.py` — `knowledge_digests` table in `_ensure_tables()`
- `triggers/rss_trigger.py` — `compile_knowledge_digest()` function + trigger at end of `run_rss_poll()`
- `outputs/dashboard.py` — `/api/rss/knowledge-digests` endpoint
- `outputs/static/app.js` — Rewrite `loadMediaTab()`, add `_showDigests()`, `_renderDigests()`, `_renderRawArticles()`, `_simpleMarkdown()`
- `outputs/static/index.html` — Cache bust `app.js?v=97`

## Do NOT Touch
- `outputs/static/style.css` — all styling done inline (matches existing pattern)
- `triggers/rss_client.py` — RSS client is working fine
- `orchestrator/weekly_digest.py` — separate feature, don't conflate
- `orchestrator/memory_consolidator.py` — different pipeline, keep independent
- Existing `renderArticles()` function — used by raw view toggle, must stay intact

## Quality Checkpoints
1. Table created on deploy: `SELECT * FROM knowledge_digests LIMIT 1;` (no error)
2. After RSS poll runs, digests appear: `SELECT category, article_count, LEFT(digest_md, 100) FROM knowledge_digests;`
3. API responds: `curl /api/rss/knowledge-digests` returns digests
4. Frontend shows digest cards on Media tab
5. Toggle button switches between digest and raw views
6. Category filter works for both views
7. Sidebar click pre-filters digest view
8. No compilation happens within 6h of last compilation (check logs)
9. Syntax check: `python3 -c "import py_compile; py_compile.compile('triggers/rss_trigger.py', doraise=True)"`

## Verification SQL
```sql
-- Check digests exist and are fresh
SELECT category, title, article_count,
       last_compiled, LEFT(digest_md, 200) AS preview
FROM knowledge_digests
ORDER BY last_compiled DESC LIMIT 10;

-- Check compilation frequency (should be max 4/day per category)
SELECT category, COUNT(*), MAX(last_compiled)
FROM knowledge_digests
GROUP BY category;
```

## Manual Trigger (for testing before first RSS poll)
If you want to test immediately without waiting for the hourly RSS poll, add a temporary endpoint or run in Python shell:
```python
from triggers.rss_trigger import compile_knowledge_digest
compile_knowledge_digest('AI Technology', days=7)
compile_knowledge_digest('Market Intelligence', days=7)
```
