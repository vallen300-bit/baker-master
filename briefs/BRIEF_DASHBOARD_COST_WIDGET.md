# BRIEF: Dashboard Cost & Metrics Widgets

**Author:** Code 300 (Session 14)
**Date:** 2026-03-08
**Status:** Ready for Code Brisen
**Branch:** `feat/dashboard-cost-widget`

---

## Context

Phase 4A shipped cost tracking (`api_cost_log` table) and agent observability (`agent_tool_calls` table) with 4 API endpoints. The data is flowing but invisible — the Director can't see it in the Cockpit. This brief adds visual widgets.

---

## Existing API Endpoints (DO NOT REBUILD)

| Endpoint | Returns |
|----------|---------|
| `GET /api/cost/today` | Today's cost breakdown by model + source, thresholds |
| `GET /api/cost/history?days=7` | Daily cost totals for last N days |
| `GET /api/agent-metrics?hours=24` | Tool call metrics (per-tool calls, latency, success/fail) |
| `GET /api/agent-metrics/errors?limit=20` | Recent tool call errors |
| `GET /api/capability-quality` | Per-capability feedback quality percentages |

All require `X-Baker-Key` header (use `bakerFetch()`).

---

## What to Build

A new **"System"** section at the bottom of the Morning Brief tab (the default landing page). It shows 3 compact widgets: cost today, tool performance, and capability quality.

### Why Morning Brief Tab (Not a New Tab)

The Director sees Morning Brief first every day. Putting system health below the briefing narrative means he sees it in context without clicking around. It's operational awareness, not a separate destination.

---

## Part 1: Cost Widget

### Layout

```
┌─────────────────────────────────────────────────┐
│  💰 API Cost Today                    €0.42     │
│  ┌─────────────────────────────────────┐        │
│  │ ████████░░░░░░░░░░░░ €0.42 / €15   │ bar    │
│  └─────────────────────────────────────┘        │
│  Haiku: €0.08 (23 calls) · Opus: €0.34 (2)     │
│  7-day trend: €0.38 → €0.51 → €0.42            │
└─────────────────────────────────────────────────┘
```

### Data Source

```javascript
const costData = await bakerFetch('/api/cost/today');
// costData = {
//   date, total_eur, total_input_tokens, total_output_tokens, call_count,
//   by_model: { "claude-opus-4-6": {cost, calls, tokens_in, tokens_out}, ... },
//   by_source: { "pipeline": {cost, calls}, "agent_loop": {cost, calls}, ... },
//   alert_threshold_eur, hard_stop_threshold_eur
// }

const historyData = await bakerFetch('/api/cost/history?days=7');
// historyData = { days, history: [{date, total_eur, calls, tokens_in, tokens_out}, ...] }
```

### Implementation

```javascript
async function renderCostWidget(container) {
    const [costData, historyData] = await Promise.all([
        bakerFetch('/api/cost/today').then(r => r.json()),
        bakerFetch('/api/cost/history?days=7').then(r => r.json()),
    ]);

    const total = costData.total_eur || 0;
    const threshold = costData.alert_threshold_eur || 15;
    const pct = Math.min((total / threshold) * 100, 100);
    const barColor = pct > 80 ? '#f44336' : pct > 50 ? '#ff9800' : '#4caf50';

    // Model breakdown
    const models = Object.entries(costData.by_model || {})
        .map(([m, d]) => {
            const shortName = m.includes('haiku') ? 'Haiku' : m.includes('sonnet') ? 'Sonnet' : 'Opus';
            return `${shortName}: €${Number(d.cost).toFixed(2)} (${d.calls})`;
        }).join(' · ') || 'No calls yet';

    // 7-day trend
    const trend = (historyData.history || [])
        .slice(0, 7).reverse()
        .map(d => '€' + Number(d.total_eur).toFixed(2))
        .join(' → ') || 'No history';

    const html = `
        <div class="system-widget">
            <div class="widget-header">
                <span>API Cost Today</span>
                <span class="widget-value">€${total.toFixed(2)}</span>
            </div>
            <div class="cost-bar-track">
                <div class="cost-bar-fill" style="width:${pct}%;background:${barColor}"></div>
            </div>
            <div class="widget-detail">€${total.toFixed(2)} / €${threshold} alert threshold</div>
            <div class="widget-detail">${models}</div>
            <div class="widget-detail">7-day: ${trend}</div>
        </div>
    `;
    container.insertAdjacentHTML('beforeend', html);
}
```

---

## Part 2: Agent Metrics Widget

### Layout

```
┌─────────────────────────────────────────────────┐
│  ⚡ Agent Performance (24h)        142 calls    │
│  search_memory    68 calls  avg 245ms   0 fail  │
│  search_emails    34 calls  avg 312ms   1 fail  │
│  web_search       22 calls  avg 890ms   0 fail  │
│  get_contact      18 calls  avg 120ms   0 fail  │
└─────────────────────────────────────────────────┘
```

### Data Source

```javascript
const metrics = await bakerFetch('/api/agent-metrics?hours=24');
// metrics = {
//   tool_metrics: { hours, tools: [{tool_name, calls, avg_latency_ms, max_latency_ms, successes, failures}], total_calls, avg_latency_ms },
//   source_metrics: { hours, sources: [{source, calls, avg_latency_ms, successes, failures}] }
// }
```

### Implementation

```javascript
async function renderMetricsWidget(container) {
    const data = await bakerFetch('/api/agent-metrics?hours=24').then(r => r.json());
    const tools = (data.tool_metrics?.tools || []).slice(0, 5); // Top 5
    const total = data.tool_metrics?.total_calls || 0;

    let rows = tools.map(t =>
        `<div class="metric-row">
            <span class="metric-name">${t.tool_name}</span>
            <span class="metric-val">${t.calls} calls</span>
            <span class="metric-val">avg ${t.avg_latency_ms}ms</span>
            <span class="metric-val ${t.failures > 0 ? 'metric-fail' : ''}">${t.failures} fail</span>
        </div>`
    ).join('');

    if (!rows) rows = '<div class="widget-detail">No tool calls in last 24h</div>';

    const html = `
        <div class="system-widget">
            <div class="widget-header">
                <span>Agent Performance (24h)</span>
                <span class="widget-value">${total} calls</span>
            </div>
            ${rows}
        </div>
    `;
    container.insertAdjacentHTML('beforeend', html);
}
```

---

## Part 3: Capability Quality Widget

### Layout

```
┌─────────────────────────────────────────────────┐
│  📊 Capability Quality                          │
│  finance       12 tasks   83% accepted          │
│  legal          8 tasks   75% accepted          │
│  research       5 tasks    — no feedback yet    │
└─────────────────────────────────────────────────┘
```

### Data Source

```javascript
const quality = await bakerFetch('/api/capability-quality');
// quality = { capabilities: [{slug, total_tasks, accepted, revised, rejected, no_feedback, quality_pct}] }
```

### Implementation

```javascript
async function renderQualityWidget(container) {
    const data = await bakerFetch('/api/capability-quality').then(r => r.json());
    const caps = (data.capabilities || []).slice(0, 6); // Top 6

    let rows = caps.map(c => {
        const quality = c.quality_pct !== null ? `${c.quality_pct}% accepted` : 'no feedback yet';
        const qClass = c.quality_pct === null ? '' : c.quality_pct >= 80 ? 'metric-good' : c.quality_pct >= 50 ? 'metric-warn' : 'metric-fail';
        return `<div class="metric-row">
            <span class="metric-name">${c.slug}</span>
            <span class="metric-val">${c.total_tasks} tasks</span>
            <span class="metric-val ${qClass}">${quality}</span>
        </div>`;
    }).join('');

    if (!rows) rows = '<div class="widget-detail">No capability tasks yet</div>';

    const html = `
        <div class="system-widget">
            <div class="widget-header">
                <span>Capability Quality</span>
            </div>
            ${rows}
        </div>
    `;
    container.insertAdjacentHTML('beforeend', html);
}
```

---

## Part 4: System Section Container + CSS

### Where to Insert in the DOM

Find where the Morning Brief content is rendered in `app.js`. After the briefing narrative and stats, add:

```javascript
// After Morning Brief content is rendered:
const systemSection = document.createElement('div');
systemSection.id = 'system-widgets';
systemSection.innerHTML = '<h3 class="system-section-title">System Health</h3>';
morningBriefContainer.appendChild(systemSection);

// Render all 3 widgets in parallel
await Promise.all([
    renderCostWidget(systemSection),
    renderMetricsWidget(systemSection),
    renderQualityWidget(systemSection),
]);
```

### CSS (add to app.js or index.html)

```css
.system-section-title {
    font-size: 14px; font-weight: 600; color: #666;
    text-transform: uppercase; letter-spacing: 0.5px;
    margin: 24px 0 12px; padding-top: 16px;
    border-top: 2px solid #eee;
}
.system-widget {
    background: #fafafa; border: 1px solid #eee; border-radius: 8px;
    padding: 12px 16px; margin-bottom: 12px;
}
.widget-header {
    display: flex; justify-content: space-between; align-items: center;
    font-size: 14px; font-weight: 600; margin-bottom: 8px;
}
.widget-value { font-size: 18px; font-weight: 700; }
.widget-detail { font-size: 12px; color: #888; margin-top: 4px; }
.cost-bar-track {
    height: 6px; background: #eee; border-radius: 3px;
    margin: 6px 0; overflow: hidden;
}
.cost-bar-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
.metric-row {
    display: flex; gap: 12px; font-size: 13px; padding: 3px 0;
    border-bottom: 1px solid #f0f0f0;
}
.metric-row:last-child { border-bottom: none; }
.metric-name { flex: 1; font-weight: 500; }
.metric-val { color: #666; white-space: nowrap; }
.metric-good { color: #4caf50; }
.metric-warn { color: #ff9800; }
.metric-fail { color: #f44336; }
```

---

## Files Summary

| Action | File | What |
|--------|------|------|
| **MODIFY** | `outputs/static/app.js` | 3 widget render functions + system section + CSS injection |

**This is a frontend-only change.** No backend modifications needed — all data already served by existing endpoints.

**Estimated: ~150 lines (JS + CSS)**

---

## Verification Checklist

- [ ] Morning Brief tab shows "System Health" section below the briefing narrative
- [ ] Cost widget shows today's EUR total with progress bar toward €15 threshold
- [ ] Cost widget shows model breakdown (Haiku/Opus with calls count)
- [ ] Cost widget shows 7-day trend
- [ ] Agent metrics widget shows top 5 tools by call count with avg latency + failures
- [ ] Capability quality widget shows per-capability acceptance rate
- [ ] All 3 widgets load in parallel (no sequential blocking)
- [ ] Widgets handle empty data gracefully ("No calls yet", "No feedback yet")
- [ ] `bakerFetch()` used for all API calls (auth wrapper)

---

## What NOT to Build

- No charts/graphs (text-based widgets are sufficient for v1)
- No historical drill-down (just today + 7-day trend)
- No separate System tab (widgets live inside Morning Brief)
- No real-time updates (refresh on page load is sufficient)

---

## Context for Brisen

- `bakerFetch(url, opts)` is the auth wrapper — always use it instead of raw `fetch()`
- Morning Brief tab rendering: search app.js for "morning" or "brief" to find the render function
- The Morning Brief narrative is cached (30 min) — widgets should load independently via their own API calls
- CSS can be injected via `<style>` tag in JS or added to index.html — either is fine
- The app.js file is ~2100 lines — search for the tab rendering section, don't read the whole file
