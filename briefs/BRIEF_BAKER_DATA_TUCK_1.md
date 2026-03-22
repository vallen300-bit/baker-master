# Brief: BAKER-DATA-TUCK-1 — Move System Widgets into Baker Data Tab

**Author:** AI Head (Session 21, Director request)
**For:** Code 300
**Priority:** HIGH — Director wants operational data out of the main view

---

## Problem

The landing page currently shows 4 system widgets (Sentinel Status, API Cost Today, Agent Performance, Capability Quality) below the fires and deadlines. These are operational/engineering metrics that clutter the Director's view. The Director wants them tucked into the **Baker Data** sidebar tab.

## Current State

- `index.html:130` — `<div id="systemWidgets"></div>` sits on the landing page
- `app.js:629` — `loadSystemWidgets()` is called from `loadMorningBrief()` (landing page load)
- `app.js:675-919` — 5 functions: `loadSystemWidgets()`, `renderSentinelWidget()`, `renderCostWidget()`, `renderMetricsWidget()`, `renderQualityWidget()`
- `app.js:1962-2046` — `loadBakerData()` currently shows Activity (24h) + Recent Capability Runs

## What to Build

### Step 1: Remove widgets from landing page

**`outputs/static/index.html`:**
Remove or comment out the `systemWidgets` div (line 130):
```html
<!-- Removed: system widgets moved to Baker Data tab -->
```

**`outputs/static/app.js`:**
Remove the `loadSystemWidgets()` call from `loadMorningBrief()` (line 629).

### Step 2: Add widgets to Baker Data tab

**`outputs/static/app.js` — modify `loadBakerData()`:**

After the existing Activity (24h) and Recent Capability Runs sections, add:

```javascript
// ── System Health section ──
var sysContainer = document.createElement('div');
sysContainer.style.cssText = 'margin-top:24px;';
container.appendChild(sysContainer);

// Reuse existing widget renderers
await Promise.all([
    renderSentinelWidget(sysContainer),
    renderCostWidget(sysContainer),
    renderMetricsWidget(sysContainer),
    renderQualityWidget(sysContainer),
]);
```

The widget functions (`renderSentinelWidget`, `renderCostWidget`, etc.) already accept a container parameter — they don't depend on `#systemWidgets`. Just pass the Baker Data container instead.

### Step 3: Add section header

Before the system widgets in Baker Data, add a section label:

```javascript
var sysLabel = document.createElement('div');
sysLabel.style.cssText = 'font-size:11px;font-weight:700;color:var(--text3);font-family:var(--mono);letter-spacing:0.3px;margin-bottom:8px;margin-top:24px;';
sysLabel.textContent = 'SYSTEM HEALTH';
container.appendChild(sysLabel);
```

## Result

**Landing page:** Clean — greeting, stats, fires, deadlines. No engineering metrics.
**Baker Data tab:** Activity (24h) + Capability Runs + System Health + API Cost + Agent Performance + Capability Quality.

## Files to Modify

| File | Change |
|------|--------|
| `outputs/static/index.html` | Remove `<div id="systemWidgets"></div>` (line 130) |
| `outputs/static/app.js` | Remove `loadSystemWidgets()` call from `loadMorningBrief()` (line 629) |
| `outputs/static/app.js` | Add widget rendering to `loadBakerData()` after existing content |

## Verification

1. Landing page loads without system widgets
2. Baker Data tab shows: Activity → Capability Runs → System Health → API Cost → Agent Performance → Capability Quality
3. All 4 widget types render correctly in Baker Data (sentinel dots, cost bar, tool metrics, capability quality)
4. No console errors

## What NOT to Do

- Don't delete the widget functions — they're reused, just called from a different location
- Don't change the widget styling — they should look the same, just in a different tab
