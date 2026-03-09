/* ============================================================
   Baker Cockpit v3 — app.js
   Split layout: sidebar navigation + command bar + content views

   SECURITY: All HTML rendering uses md() (which calls esc() first)
   or esc() for plain text. Never raw innerHTML with untrusted input.
   This follows the brief's XSS prevention rules and existing codebase patterns.
   ============================================================ */

// ═══ API CONFIG ═══
const BAKER_CONFIG = { apiKey: '' };

async function loadConfig() {
    try {
        const resp = await fetch('/api/client-config');
        if (resp.ok) {
            const data = await resp.json();
            BAKER_CONFIG.apiKey = data.apiKey;
        }
    } catch (e) {
        console.error('Failed to load client config:', e);
    }
}

async function bakerFetch(url, options = {}) {
    const headers = { ...(options.headers || {}), 'X-Baker-Key': BAKER_CONFIG.apiKey };
    return fetch(url, { ...options, headers });
}

// ═══ STATE ═══
let currentTab = 'morning-brief';
let scanHistory = [];
let scanStreaming = false;

// ═══ HELPERS ═══

/** Escape HTML entities — prevents XSS. Used by md() and all text rendering. */
function esc(str) {
    if (!str) return '';
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

/** Markdown-to-HTML converter. ALWAYS calls esc() first, then applies formatting. Safe for innerHTML. */
function md(text) {
    if (!text) return '';
    let h = esc(text); // XSS-safe: escapes all HTML entities first

    // Tables: detect markdown table blocks and convert to HTML tables
    h = h.replace(/((?:^\|.+\|$\n?)+)/gm, function(tableBlock) {
        var rows = tableBlock.trim().split('\n');
        if (rows.length < 2) return tableBlock;
        var html = '<table style="border-collapse:collapse;width:100%;font-size:12px;margin:8px 0;">';
        for (var ri = 0; ri < rows.length; ri++) {
            var row = rows[ri].trim();
            if (!row.startsWith('|')) continue;
            // Skip separator row (|---|---|)
            if (/^\|[\s\-:|]+\|$/.test(row)) continue;
            var cells = row.split('|').filter(function(c, i, a) { return i > 0 && i < a.length - 1; });
            var tag = ri === 0 ? 'th' : 'td';
            var bgStyle = ri === 0 ? 'background:var(--bg2);font-weight:600;' : '';
            html += '<tr>';
            for (var ci = 0; ci < cells.length; ci++) {
                html += '<' + tag + ' style="padding:4px 8px;border:1px solid var(--border);text-align:left;' + bgStyle + '">' + cells[ci].trim() + '</' + tag + '>';
            }
            html += '</tr>';
        }
        html += '</table>';
        return html;
    });

    h = h.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    h = h.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    h = h.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    h = h.replace(/\*(.+?)\*/g, '<em>$1</em>');
    h = h.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    h = h.replace(/^- (.+)$/gm, '<li>$1</li>');
    h = h.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
    h = h.replace(/\n/g, '<br>');
    return h;
}

function fmtDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
        + ' ' + d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
}

function fmtRelativeTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now - d;
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return diffMins + 'm ago';
    const diffHrs = Math.floor(diffMins / 60);
    if (diffHrs < 24) return diffHrs + 'h ago';
    const diffDays = Math.floor(diffHrs / 24);
    if (diffDays === 1) return 'Yesterday';
    return diffDays + ' days ago';
}

function fmtDeadlineDays(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    const now = new Date();
    now.setHours(0, 0, 0, 0);
    d.setHours(0, 0, 0, 0);
    const diff = Math.ceil((d - now) / 86400000);
    if (diff < 0) return Math.abs(diff) + ' days overdue';
    if (diff === 0) return 'Today';
    if (diff === 1) return 'Tomorrow';
    return diff + ' days';
}

function tierClass(tier) {
    if (tier === 1) return 'red';
    if (tier === 2) return 'amber';
    if (tier === 3) return 'slate';
    return 'lgray';
}

/** Set element text safely (no HTML) */
function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
}

/** Set element safe HTML (pre-escaped via md/esc) */
function setSafeHTML(el, safeHtml) {
    if (el) el.innerHTML = safeHtml; // SECURITY: caller must pass md() or esc() output only
}

// ═══ NAVIGATION ═══

const TAB_VIEW_MAP = {
    'morning-brief': 'viewMorningBrief',
    'fires': 'viewFires',
    'matters': 'viewMatters',
    'deadlines': 'viewDeadlines',
    'people': 'viewPeople',
    'tags': 'viewTags',
    'search': 'viewSearch',
    'ask-baker': 'viewAskBaker',
    'ask-specialist': 'viewAskSpecialist',
    'travel': 'viewTravel',
    'media': 'viewMedia',
    'commitments': 'viewCommitments',
    'browser': 'viewBrowser',
};

const FUNCTIONAL_TABS = new Set(['morning-brief', 'fires', 'matters', 'deadlines', 'people', 'tags', 'search', 'ask-baker', 'ask-specialist', 'travel', 'media', 'commitments', 'browser']);

function switchTab(tabName) {
    document.querySelectorAll('.nav-item[data-tab]').forEach(item => {
        item.classList.toggle('active', item.dataset.tab === tabName);
    });

    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));

    // All 11 tabs are functional — no "Coming soon" fallback needed
    var viewId = TAB_VIEW_MAP[tabName];
    if (viewId) {
        var el = document.getElementById(viewId);
        if (el) el.classList.add('active');
    }

    currentTab = tabName;

    if (tabName === 'morning-brief') loadMorningBrief();
    else if (tabName === 'fires') loadFires();
    else if (tabName === 'matters') loadMattersTab();
    else if (tabName === 'deadlines') loadDeadlinesTab();
    else if (tabName === 'people') loadPeopleTab();
    else if (tabName === 'tags') loadTagsTab();
    else if (tabName === 'search') loadSearchTab();
    else if (tabName === 'ask-baker') focusScanInput();
    else if (tabName === 'ask-specialist') loadSpecialistTab();
    else if (tabName === 'travel') loadTravelTab();
    else if (tabName === 'media') loadMediaTab();
    else if (tabName === 'commitments') loadCommitmentsTab();
    else if (tabName === 'browser') loadBrowserTab();
}

// ═══ MORNING BRIEF ═══

async function loadMorningBrief() {
    try {
        const resp = await bakerFetch('/api/dashboard/morning-brief');
        if (!resp.ok) return;
        const data = await resp.json();

        setText('statFires', data.fire_count || 0);
        setText('statDeadlines', data.deadline_count || 0);
        setText('statProcessed', data.processed_overnight || 0);
        setText('statActions', data.actions_completed || 0);

        const narEl = document.getElementById('briefNarrative');
        if (narEl && data.narrative) setSafeHTML(narEl, md(data.narrative));

        // Fires badge
        const firesBadge = document.getElementById('firesBadge');
        if (firesBadge) {
            if (data.fire_count > 0) {
                firesBadge.textContent = data.fire_count;
                firesBadge.hidden = false;
            } else {
                firesBadge.hidden = true;
            }
        }

        // Top fires
        const firesList = document.getElementById('topFiresList');
        if (firesList) {
            if (data.top_fires && data.top_fires.length > 0) {
                setSafeHTML(firesList, data.top_fires.map(function(a) { return renderAlertCard(a, true); }).join(''));
            } else {
                firesList.textContent = 'No active fires. All clear.';
                firesList.style.cssText = 'color:var(--text3);font-size:12px;';
            }
        }

        // Deadlines
        const dlList = document.getElementById('deadlinesList');
        if (dlList) {
            if (data.deadlines && data.deadlines.length > 0) {
                setSafeHTML(dlList, data.deadlines.map(renderDeadlineCompact).join(''));
            } else {
                dlList.textContent = 'No deadlines this week.';
                dlList.style.cssText = 'color:var(--text3);font-size:12px;';
            }
        }

        // Activity
        const actList = document.getElementById('activityList');
        if (actList) {
            if (data.activity && data.activity.length > 0) {
                setSafeHTML(actList, data.activity.map(renderActivityRow).join(''));
            } else {
                actList.textContent = 'No activity yet today.';
                actList.style.cssText = 'color:var(--text3);font-size:12px;';
            }
        }

        // Meetings today (Phase 3A)
        var meetingsLabel = document.getElementById('meetingsSectionLabel');
        var meetingsList = document.getElementById('meetingsTodayList');
        if (meetingsList) {
            if (data.meetings_today && data.meetings_today.length > 0) {
                if (meetingsLabel) meetingsLabel.style.display = '';
                setSafeHTML(meetingsList, data.meetings_today.map(renderMeetingCard).join(''));
            } else {
                if (meetingsLabel) meetingsLabel.style.display = 'none';
                meetingsList.textContent = '';
            }
        }

        // Update stats: add meeting count
        var statMeetings = document.getElementById('statMeetings');
        if (statMeetings) setText('statMeetings', data.meeting_count || 0);

        loadMattersSummary();

        // DASHBOARD-COST-WIDGET: Load system health widgets
        loadSystemWidgets();
    } catch (e) {
        console.error('loadMorningBrief failed:', e);
    }
}

// ═══ SYSTEM HEALTH WIDGETS (DASHBOARD-COST-WIDGET) ═══

function _injectSystemCSS() {
    if (document.getElementById('system-widget-css')) return;
    var s = document.createElement('style');
    s.id = 'system-widget-css';
    s.textContent = [
        '.system-section-title{font-size:14px;font-weight:600;color:#666;text-transform:uppercase;letter-spacing:0.5px;margin:24px 0 12px;padding-top:16px;border-top:2px solid #eee}',
        '.system-widget{background:#fafafa;border:1px solid #eee;border-radius:8px;padding:12px 16px;margin-bottom:12px}',
        '.widget-header{display:flex;justify-content:space-between;align-items:center;font-size:14px;font-weight:600;margin-bottom:8px}',
        '.widget-value{font-size:18px;font-weight:700}',
        '.widget-detail{font-size:12px;color:#888;margin-top:4px}',
        '.cost-bar-track{height:6px;background:#eee;border-radius:3px;margin:6px 0;overflow:hidden}',
        '.cost-bar-fill{height:100%;border-radius:3px;transition:width 0.3s}',
        '.metric-row{display:flex;gap:12px;font-size:13px;padding:3px 0;border-bottom:1px solid #f0f0f0}',
        '.metric-row:last-child{border-bottom:none}',
        '.metric-name{flex:1;font-weight:500}',
        '.metric-val{color:#666;white-space:nowrap}',
        '.metric-good{color:#4caf50}',
        '.metric-warn{color:#ff9800}',
        '.metric-fail{color:#f44336}',
    ].join('\n');
    document.head.appendChild(s);
}

async function loadSystemWidgets() {
    _injectSystemCSS();
    var container = document.getElementById('systemWidgets');
    if (!container) return;
    container.textContent = '';
    var title = document.createElement('h3');
    title.className = 'system-section-title';
    title.textContent = 'System Health';
    container.appendChild(title);

    await Promise.all([
        renderSentinelWidget(container),
        renderCostWidget(container),
        renderMetricsWidget(container),
        renderQualityWidget(container),
    ]);
}

async function renderSentinelWidget(container) {
    try {
        var resp = await bakerFetch('/api/sentinel-health');
        if (!resp.ok) return;
        var data = await resp.json();
        var sentinels = data.sentinels || [];
        var summary = data.summary || {};

        if (sentinels.length === 0) return;

        var card = document.createElement('div');
        card.className = 'system-widget';

        var header = document.createElement('div');
        header.className = 'system-widget-header';
        var title = document.createElement('span');
        title.textContent = 'Sentinel Status';
        header.appendChild(title);

        var badge = document.createElement('span');
        var downCount = summary.down || 0;
        var degradedCount = summary.degraded || 0;
        if (downCount > 0) {
            badge.textContent = downCount + ' down';
            badge.style.cssText = 'color:#f44336;font-weight:600;font-size:11px;';
        } else if (degradedCount > 0) {
            badge.textContent = degradedCount + ' degraded';
            badge.style.cssText = 'color:#ff9800;font-weight:600;font-size:11px;';
        } else {
            badge.textContent = 'All healthy';
            badge.style.cssText = 'color:#4caf50;font-weight:600;font-size:11px;';
        }
        header.appendChild(badge);
        card.appendChild(header);

        var grid = document.createElement('div');
        grid.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;';

        sentinels.forEach(function(s) {
            var dot = document.createElement('div');
            dot.style.cssText = 'display:flex;align-items:center;gap:4px;font-size:11px;color:var(--text2);';

            var circle = document.createElement('span');
            circle.style.cssText = 'display:inline-block;width:8px;height:8px;border-radius:50%;';
            var statusColors = {healthy:'#4caf50', degraded:'#ff9800', down:'#f44336', unknown:'#9e9e9e'};
            circle.style.backgroundColor = statusColors[s.status] || '#9e9e9e';
            if (s.status === 'down') {
                circle.style.animation = 'pulse 1.5s infinite';
            }
            dot.appendChild(circle);

            var label = document.createElement('span');
            label.textContent = esc(s.source);
            if (s.consecutive_failures > 0) {
                label.title = 'Failures: ' + s.consecutive_failures + (s.last_error ? '\n' + s.last_error : '');
            }
            dot.appendChild(label);
            grid.appendChild(dot);
        });

        card.appendChild(grid);
        container.appendChild(card);
    } catch (e) {
        console.error('renderSentinelWidget failed:', e);
    }
}

async function renderCostWidget(container) {
    try {
        var results = await Promise.all([
            bakerFetch('/api/cost/today').then(function(r) { return r.json(); }),
            bakerFetch('/api/cost/history?days=7').then(function(r) { return r.json(); }),
        ]);
        var costData = results[0];
        var historyData = results[1];

        var total = costData.total_eur || 0;
        var threshold = costData.alert_threshold_eur || 15;
        var pct = Math.min((total / threshold) * 100, 100);
        var barColor = pct > 80 ? '#f44336' : pct > 50 ? '#ff9800' : '#4caf50';

        var models = Object.entries(costData.by_model || {})
            .map(function(entry) {
                var m = entry[0], d = entry[1];
                var shortName = m.indexOf('haiku') >= 0 ? 'Haiku' : m.indexOf('sonnet') >= 0 ? 'Sonnet' : 'Opus';
                return esc(shortName) + ': \u20AC' + Number(d.cost).toFixed(2) + ' (' + d.calls + ')';
            }).join(' \u00B7 ') || 'No calls yet';

        var trend = (historyData.history || [])
            .slice(0, 7).reverse()
            .map(function(d) { return '\u20AC' + Number(d.total_eur).toFixed(2); })
            .join(' \u2192 ') || 'No history';

        var w = document.createElement('div');
        w.className = 'system-widget';

        var header = document.createElement('div');
        header.className = 'widget-header';
        var hLabel = document.createElement('span');
        hLabel.textContent = 'API Cost Today';
        var hVal = document.createElement('span');
        hVal.className = 'widget-value';
        hVal.textContent = '\u20AC' + total.toFixed(2);
        header.appendChild(hLabel);
        header.appendChild(hVal);
        w.appendChild(header);

        var track = document.createElement('div');
        track.className = 'cost-bar-track';
        var fill = document.createElement('div');
        fill.className = 'cost-bar-fill';
        fill.style.width = pct + '%';
        fill.style.background = barColor;
        track.appendChild(fill);
        w.appendChild(track);

        var details = [
            '\u20AC' + total.toFixed(2) + ' / \u20AC' + threshold + ' alert threshold',
            models,
            '7-day: ' + trend
        ];
        details.forEach(function(txt) {
            var d = document.createElement('div');
            d.className = 'widget-detail';
            d.textContent = txt;
            w.appendChild(d);
        });
        container.appendChild(w);
    } catch (e) { console.warn('Cost widget failed:', e); }
}

async function renderMetricsWidget(container) {
    try {
        var data = await bakerFetch('/api/agent-metrics?hours=24').then(function(r) { return r.json(); });
        var tools = (data.tool_metrics && data.tool_metrics.tools || []).slice(0, 5);
        var total = (data.tool_metrics && data.tool_metrics.total_calls) || 0;

        var w = document.createElement('div');
        w.className = 'system-widget';

        var header = document.createElement('div');
        header.className = 'widget-header';
        var hLabel = document.createElement('span');
        hLabel.textContent = 'Agent Performance (24h)';
        var hVal = document.createElement('span');
        hVal.className = 'widget-value';
        hVal.textContent = total + ' calls';
        header.appendChild(hLabel);
        header.appendChild(hVal);
        w.appendChild(header);

        if (tools.length === 0) {
            var empty = document.createElement('div');
            empty.className = 'widget-detail';
            empty.textContent = 'No tool calls in last 24h';
            w.appendChild(empty);
        } else {
            tools.forEach(function(t) {
                var row = document.createElement('div');
                row.className = 'metric-row';
                var name = document.createElement('span');
                name.className = 'metric-name';
                name.textContent = t.tool_name;
                var calls = document.createElement('span');
                calls.className = 'metric-val';
                calls.textContent = t.calls + ' calls';
                var latency = document.createElement('span');
                latency.className = 'metric-val';
                latency.textContent = 'avg ' + t.avg_latency_ms + 'ms';
                var fails = document.createElement('span');
                fails.className = 'metric-val' + (t.failures > 0 ? ' metric-fail' : '');
                fails.textContent = t.failures + ' fail';
                row.appendChild(name);
                row.appendChild(calls);
                row.appendChild(latency);
                row.appendChild(fails);
                w.appendChild(row);
            });
        }
        container.appendChild(w);
    } catch (e) { console.warn('Metrics widget failed:', e); }
}

async function renderQualityWidget(container) {
    try {
        var data = await bakerFetch('/api/capability-quality').then(function(r) { return r.json(); });
        var caps = (data.capabilities || []).slice(0, 6);

        var w = document.createElement('div');
        w.className = 'system-widget';

        var header = document.createElement('div');
        header.className = 'widget-header';
        var hLabel = document.createElement('span');
        hLabel.textContent = 'Capability Quality';
        header.appendChild(hLabel);
        w.appendChild(header);

        if (caps.length === 0) {
            var empty = document.createElement('div');
            empty.className = 'widget-detail';
            empty.textContent = 'No capability tasks yet';
            w.appendChild(empty);
        } else {
            caps.forEach(function(c) {
                var quality = c.quality_pct !== null ? c.quality_pct + '% accepted' : 'no feedback yet';
                var qClass = c.quality_pct === null ? '' : c.quality_pct >= 80 ? ' metric-good' : c.quality_pct >= 50 ? ' metric-warn' : ' metric-fail';
                var row = document.createElement('div');
                row.className = 'metric-row';
                var name = document.createElement('span');
                name.className = 'metric-name';
                name.textContent = c.slug;
                var tasks = document.createElement('span');
                tasks.className = 'metric-val';
                tasks.textContent = c.total_tasks + ' tasks';
                var q = document.createElement('span');
                q.className = 'metric-val' + qClass;
                q.textContent = quality;
                row.appendChild(name);
                row.appendChild(tasks);
                row.appendChild(q);
                w.appendChild(row);
            });
        }
        container.appendChild(w);
    } catch (e) { console.warn('Quality widget failed:', e); }
}

// ═══ MATTERS SUMMARY (sidebar) ═══

async function loadMattersSummary() {
    try {
        const resp = await bakerFetch('/api/dashboard/matters-summary');
        if (!resp.ok) return;
        const data = await resp.json();

        const subList = document.getElementById('mattersSubList');
        setText('mattersCount', data.count || '');

        if (subList && data.matters) {
            // Build sub-items using safe DOM methods
            subList.textContent = '';
            for (const m of data.matters) {
                const slug = m.matter_slug || '_ungrouped';
                const label = slug === '_ungrouped' ? 'Ungrouped' : slug.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
                const dotClass = (m.worst_tier && m.worst_tier <= 2) ? 'red' : 'slate';

                const item = document.createElement('div');
                item.className = 'nav-item';
                item.dataset.tab = 'matters';
                item.dataset.matter = slug;

                const dot = document.createElement('span');
                dot.className = 'nav-dot ' + dotClass;
                item.appendChild(dot);

                const lbl = document.createElement('span');
                lbl.className = 'nav-label';
                lbl.textContent = label;
                item.appendChild(lbl);

                const cnt = document.createElement('span');
                cnt.className = 'nav-count';
                cnt.textContent = m.item_count;
                item.appendChild(cnt);

                if (m.new_count > 0) {
                    const newBadge = document.createElement('span');
                    newBadge.className = 'nav-new';
                    newBadge.textContent = m.new_count + ' new';
                    item.appendChild(newBadge);
                }

                item.addEventListener('click', function() { switchTab('matters'); });
                subList.appendChild(item);
            }
        }
    } catch (e) {
        console.error('loadMattersSummary failed:', e);
    }
}

// ═══ FIRES TAB ═══

async function loadFires() {
    const container = document.getElementById('firesContent');
    if (!container) return;
    container.textContent = 'Loading...';

    try {
        // Upcoming: show T2+ only (T1s are on Dashboard)
        const resp = await bakerFetch('/api/alerts?min_tier=2');
        if (!resp.ok) return;
        const data = await resp.json();

        if (!data.alerts || data.alerts.length === 0) {
            container.textContent = 'No upcoming items.';
            container.style.cssText = 'color:var(--text3);font-size:13px;padding:20px 0;';
            return;
        }

        // Group by matter
        const groups = {};
        for (const a of data.alerts) {
            const key = a.matter_slug || '_ungrouped';
            if (!groups[key]) groups[key] = [];
            groups[key].push(a);
        }

        container.textContent = '';
        for (const [slug, alerts] of Object.entries(groups)) {
            const label = slug === '_ungrouped' ? 'Ungrouped' : slug.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });

            const sectionLabel = document.createElement('div');
            sectionLabel.className = 'section-label';
            sectionLabel.style.marginTop = '16px';
            sectionLabel.textContent = label;
            container.appendChild(sectionLabel);

            const cardsHtml = alerts.map(function(a) { return renderAlertCard(a, true); }).join('');
            const cardsDiv = document.createElement('div');
            setSafeHTML(cardsDiv, cardsHtml); // SECURITY: renderAlertCard uses esc() for all user data
            container.appendChild(cardsDiv);
        }
        populateAssignDropdowns();
    } catch (e) {
        container.textContent = 'Failed to load fires.';
        container.style.color = 'var(--red)';
    }
}

// ═══ DEADLINES TAB ═══

// ═══ CARD RENDERING ═══
// SECURITY: All dynamic text goes through esc(). Resulting HTML is safe for setSafeHTML().

function renderAlertCard(alert, expanded) {
    const tier = alert.tier || 3;
    const tierLabel = 'T' + tier;
    const isNew = isNewAlert(alert.created_at);
    const borderClass = tier === 1 ? ' t1-border' : tier === 2 ? ' t2-border' : '';
    const newClass = isNew ? ' new' : '';
    var aid = esc(String(alert.id));

    var matterAttr = alert.matter_slug ? ' data-matter="' + esc(alert.matter_slug) + '"' : '';
    var html = '<div class="card' + newClass + borderClass + '" data-alert-id="' + aid + '"' + matterAttr + '>';

    // Header
    html += '<div class="card-header">';
    html += '<span class="tier-badge t' + tier + '">' + esc(tierLabel) + '</span>';
    html += '<span class="card-title">' + esc(alert.title) + '</span>';
    if (isNew) html += '<span class="card-new-badge">new</span>';
    html += '<span class="card-time">' + esc(fmtRelativeTime(alert.created_at)) + '</span>';
    html += '</div>';

    // Tag badges
    var alertTags = alert.tags || [];
    if (typeof alertTags === 'string') { try { alertTags = JSON.parse(alertTags); } catch(e) { alertTags = []; } }
    if (alertTags.length > 0) {
        html += '<div class="card-tags">';
        for (var ti = 0; ti < alertTags.length; ti++) {
            html += '<span class="tag-badge">' + esc(alertTags[ti]) + '</span>';
        }
        html += '</div>';
    }

    // Ungrouped assignment dropdown
    if (!alert.matter_slug) {
        html += '<div class="assign-bar">';
        html += '<span style="font-size:10px;color:var(--amber);font-weight:600;">Assign to:</span>';
        html += '<select class="assign-select" onchange="assignAlert(' + alert.id + ',this.value)" data-alert="' + aid + '">';
        html += '<option value="">Select matter...</option>';
        html += '</select>';
        html += '</div>';
    }

    // PCS (for T1/T2 with structured_actions)
    if (expanded && (tier <= 2) && alert.structured_actions) {
        var sa = alert.structured_actions;
        if (typeof sa === 'string') { try { sa = JSON.parse(sa); } catch(e) { sa = {}; } }

        if (sa.problem || sa.cause || sa.solution) {
            html += '<div class="pcs">';
            html += '<div class="pcs-box"><div class="pcs-label">Problem</div><div class="pcs-text">' + esc(sa.problem || '') + '</div></div>';
            html += '<div class="pcs-box"><div class="pcs-label">Cause</div><div class="pcs-text">' + esc(sa.cause || '') + '</div></div>';
            html += '<div class="pcs-box"><div class="pcs-label">Solution</div><div class="pcs-text">' + esc(sa.solution || '') + '</div></div>';
            html += '</div>';
        }

        // Baker recommends
        if (sa.parts && sa.parts.length > 0) {
            html += '<div class="recommends"><div class="recommends-label">Baker recommends</div>';
            for (var pi = 0; pi < sa.parts.length; pi++) {
                var part = sa.parts[pi];
                html += '<div class="part-label">' + esc(part.label || '') + '</div>';
                if (part.actions) {
                    for (var ai = 0; ai < part.actions.length; ai++) {
                        var action = part.actions[ai];
                        var prompt = action.prompt || action.label || '';
                        html += '<div class="action-row">';
                        html += '<span class="action-type">' + esc((action.type || 'Analyze').charAt(0).toUpperCase() + (action.type || 'analyze').slice(1)) + '</span>';
                        html += '<span class="action-label">' + esc(action.label || action.description || '') + '</span>';
                        html += '<button class="run-btn" data-prompt="' + esc(prompt) + '" data-alert="' + aid + '" onclick="runCardAction(this)">Run</button>';
                        html += '</div>';
                        // Inline result container for this action
                        html += '<div class="card-result-area" id="result-' + aid + '-' + pi + '-' + ai + '" style="display:none;"></div>';
                    }
                }
            }
            html += '<div class="freetext"><input placeholder="Something else..." data-alert="' + aid + '" />';
            html += '<button class="run-btn" style="opacity:0.3;" data-alert="' + aid + '" onclick="runFreetext(this)">Run</button></div>';
            html += '</div>';
        }

        // More actions
        html += '<div class="more-actions"><div class="more-actions-label">More actions</div>';
        html += '<div class="more-actions-row">';
        var moreActions = ['Draft', 'Analyze', 'Plan', 'Summarize', 'Search'];
        for (var mi = 0; mi < moreActions.length; mi++) {
            html += '<button class="more-action-btn" data-action-type="' + esc(moreActions[mi]) + '" data-alert="' + aid + '" onclick="openMoreAction(this)">' + esc(moreActions[mi]) + '...</button>';
        }
        html += '</div></div>';
    }

    // Inline result area (for any action on the card)
    html += '<div class="card-result-area" id="card-result-' + aid + '" style="display:none;"></div>';

    // Reply thread area
    html += '<div class="card-reply-area" id="card-reply-' + aid + '" style="display:none;padding:0 16px 10px;">';
    html += '<div id="card-thread-' + aid + '"></div>';
    html += '<div style="display:flex;gap:8px;margin-top:6px;">';
    html += '<input class="reply-input" placeholder="Reply to Baker on this matter..." data-alert="' + aid + '" style="flex:1;padding:8px 10px;border:1px solid var(--border);border-radius:6px;font-size:12px;font-family:var(--font);outline:none;" maxlength="4000" />';
    html += '<button class="run-btn" onclick="sendCardReply(this)" data-alert="' + aid + '">Send</button>';
    html += '</div></div>';

    // Footer
    html += '<div class="card-footer">';
    html += '<button class="footer-btn primary" onclick="switchTab(\'ask-baker\')">Open in Scan</button>';
    html += '<button class="footer-resolve" data-alert="' + aid + '" onclick="resolveAlert(' + alert.id + ',this)">Resolve</button>';
    html += '<button class="footer-dismiss" data-alert="' + aid + '" onclick="dismissAlert(' + alert.id + ',this)">Dismiss</button>';
    html += '</div></div>';

    return html;
}

function renderMeetingCard(m) {
    var startTime = '';
    try {
        var d = new Date(m.start);
        startTime = d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
    } catch(e) { startTime = m.start || ''; }
    var attendeeStr = (m.attendees || []).slice(0, 3).map(esc).join(', ');
    if ((m.attendees || []).length > 3) attendeeStr += ' +' + ((m.attendees || []).length - 3);
    var dotClass = m.prepped ? 'green' : 'amber';
    var statusText = m.prepped ? 'Prepped' : 'Pending';
    return '<div class="card card-compact"><div class="card-header">' +
        '<span class="nav-dot ' + dotClass + '" style="margin-top:5px;"></span>' +
        '<span class="card-title">' + esc(m.title || '') + '</span>' +
        '<span class="card-time">' + esc(startTime) + '</span>' +
        '</div>' +
        '<div class="card-body" style="font-size:11px;color:var(--text3);padding:2px 0 4px 18px;">' +
        (attendeeStr ? esc(attendeeStr) + ' &middot; ' : '') +
        '<span style="color:var(--' + (m.prepped ? 'green' : 'amber') + ');">' + esc(statusText) + '</span>' +
        '</div></div>';
}

function renderDeadlineCompact(dl) {
    const daysText = fmtDeadlineDays(dl.due_date);
    const priority = (dl.priority || 'normal').toLowerCase();
    let dotClass = 'lgray';
    let timeStyle = '';
    if (priority === 'critical' || daysText === 'Today') { dotClass = 'red'; timeStyle = 'color:var(--red);font-weight:600;'; }
    else if (priority === 'high' || daysText === 'Tomorrow') { dotClass = 'amber'; }
    else if (daysText.includes('overdue')) { dotClass = 'red'; timeStyle = 'color:var(--red);font-weight:600;'; }

    return '<div class="card card-compact"><div class="card-header">' +
        '<span class="nav-dot ' + dotClass + '" style="margin-top:5px;"></span>' +
        '<span class="card-title">' + esc(dl.description || '') + '</span>' +
        '<span class="card-time" style="' + timeStyle + '">' + esc(daysText) + '</span>' +
        '</div></div>';
}

function renderActivityRow(item) {
    let dotColor = 'var(--text4)';
    let label = '';
    let time = '';

    if (item.type === 'capability_run') {
        dotColor = item.status === 'completed' ? 'var(--green)' : 'var(--amber)';
        label = '<strong>' + esc(item.label || 'Capability') + '</strong> ' + esc(item.status || '') +
            (item.iterations ? ' -- ' + esc(String(item.iterations)) + ' iterations' : '');
        time = esc(fmtRelativeTime(item.timestamp)) + (item.tool_calls_count ? ' -- ' + esc(String(item.tool_calls_count)) + ' tools' : '');
    } else if (item.type === 'alert_created') {
        dotColor = item.tier === 1 ? 'var(--red)' : item.tier === 2 ? 'var(--amber)' : 'var(--text4)';
        label = '<strong>Alert T' + esc(String(item.tier || '?')) + '</strong> ' + esc(item.label || '');
        time = esc(fmtRelativeTime(item.timestamp));
    }

    return '<div class="activity-row">' +
        '<span class="activity-dot" style="background:' + dotColor + ';"></span>' +
        '<div><div class="activity-text">' + label + '</div>' +
        '<div class="activity-time">' + time + '</div></div></div>';
}

function isNewAlert(createdAt) {
    if (!createdAt) return false;
    return (new Date() - new Date(createdAt)) < 86400000;
}

// ═══ CARD ACTIONS ═══

async function resolveAlert(alertId, btnEl) {
    try {
        await bakerFetch('/api/alerts/' + alertId + '/resolve', { method: 'POST' });
        var card = btnEl.closest('.card');
        if (card) { card.style.opacity = '0.3'; setTimeout(function() { card.remove(); }, 500); }
    } catch (e) { console.error('resolveAlert failed:', e); }
}

async function dismissAlert(alertId, btnEl) {
    try {
        await bakerFetch('/api/alerts/' + alertId + '/dismiss', { method: 'POST' });
        var card = btnEl.closest('.card');
        if (card) { card.style.opacity = '0.3'; setTimeout(function() { card.remove(); }, 500); }
    } catch (e) { console.error('dismissAlert failed:', e); }
}

/**
 * Run a card action — streams result INLINE into the card (not switching to Ask Baker).
 * CRITICAL: Routes through existing /api/scan pipeline (agentic RAG).
 */
function runCardAction(btnEl) {
    var prompt = btnEl.dataset.prompt;
    var alertId = btnEl.dataset.alert;
    if (!prompt || !alertId) return;

    // Find or create a result area right after the action row
    var actionRow = btnEl.closest('.action-row');
    var resultArea = actionRow ? actionRow.nextElementSibling : null;
    if (!resultArea || !resultArea.classList.contains('card-result-area')) {
        // Fallback: use the card-level result area
        resultArea = document.getElementById('card-result-' + alertId);
    }

    // Mark button as running
    btnEl.textContent = '...';
    btnEl.disabled = true;

    streamInlineResult(prompt, alertId, resultArea, btnEl);
}

function runFreetext(btn) {
    var input = btn.previousElementSibling;
    var alertId = btn.dataset.alert;
    if (!input || !input.value.trim()) return;
    var prompt = input.value.trim();
    input.value = '';

    var resultArea = document.getElementById('card-result-' + alertId);
    btn.textContent = '...';
    btn.disabled = true;
    streamInlineResult(prompt, alertId, resultArea, btn);
}

function openMoreAction(btn) {
    var actionType = btn.dataset.actionType;
    var alertId = btn.dataset.alert;
    var existing = btn.parentElement.querySelector('.more-action-inline');
    if (existing) { existing.remove(); return; }

    var inline = document.createElement('div');
    inline.className = 'more-action-inline';
    inline.style.cssText = 'display:flex;gap:8px;width:100%;margin-top:6px;';

    var inp = document.createElement('input');
    inp.style.cssText = 'flex:1;padding:7px 10px;border:1px solid var(--border);border-radius:6px;font-size:12px;font-family:var(--font);outline:none;';
    inp.placeholder = 'What should Baker ' + actionType.toLowerCase() + '?';
    inp.maxLength = 2000;

    var runBtn = document.createElement('button');
    runBtn.className = 'run-btn';
    runBtn.textContent = 'Run';
    runBtn.addEventListener('click', function() {
        if (!inp.value.trim()) return;
        var resultArea = document.getElementById('card-result-' + alertId);
        runBtn.textContent = '...';
        runBtn.disabled = true;
        streamInlineResult(inp.value.trim(), alertId, resultArea, runBtn);
    });

    inline.appendChild(inp);
    inline.appendChild(runBtn);
    btn.parentElement.appendChild(inline);
    inp.focus();
}

/**
 * Stream an SSE result from /api/scan into an inline result area on a card.
 * CRITICAL: Uses the SAME /api/scan pipeline as Ask Baker — agentic RAG, capability routing, full tool use.
 */
async function streamInlineResult(prompt, alertId, resultArea, triggerBtn) {
    if (!resultArea) return;
    resultArea.style.display = 'block';
    resultArea.style.cssText = 'display:block;margin:4px 16px;padding:12px 14px;background:#f8fafc;border:1px solid var(--border);border-radius:7px;font-size:12px;line-height:1.7;max-height:300px;overflow-y:auto;';
    resultArea.innerHTML = '<div class="thinking"><span class="thinking-dots"><span></span><span></span><span></span></span> Baker is thinking...</div>';

    var fullResponse = '';
    try {
        var resp = await bakerFetch('/api/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: prompt, history: [] }),
        });
        if (!resp.ok) throw new Error('Scan API returned ' + resp.status);

        var reader = resp.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';

        while (true) {
            var chunk = await reader.read();
            if (chunk.done) break;
            buffer += decoder.decode(chunk.value, { stream: true });
            var lines = buffer.split('\n');
            buffer = lines.pop();

            for (var i = 0; i < lines.length; i++) {
                if (!lines[i].startsWith('data: ')) continue;
                var payload = lines[i].slice(6).trim();
                if (payload === '[DONE]') continue;
                try {
                    var data = JSON.parse(payload);
                    if (data.token) {
                        if (!fullResponse) resultArea.textContent = '';
                        fullResponse += data.token;
                        resultArea.innerHTML = '<div class="md-content">' + md(fullResponse) + '</div>'; // SECURITY: md() escapes first
                    }
                    if (data.error) {
                        fullResponse += '\n[Error: ' + data.error + ']';
                        resultArea.innerHTML = '<div class="md-content">' + md(fullResponse) + '</div>';
                    }
                } catch (e) { /* skip */ }
            }
        }
    } catch (err) {
        fullResponse = 'Error: ' + err.message;
        resultArea.textContent = fullResponse;
    }

    // Add result toolbar
    if (fullResponse) {
        var toolbar = document.createElement('div');
        toolbar.style.cssText = 'display:flex;gap:5px;margin-top:8px;padding-top:8px;border-top:1px solid var(--border);';
        toolbar.innerHTML = '<button class="footer-btn" onclick="copyResult(this)">Copy</button>' +
            '<button class="footer-btn" onclick="downloadResultAsWord(this)">Word</button>' +
            '<button class="footer-btn" onclick="emailResult(this)">Email</button>' +
            '<button class="footer-btn" onclick="saveArtifact(this)">Save</button>';
        toolbar.dataset.resultText = fullResponse;
        resultArea.appendChild(toolbar);

        // Show reply thread area
        var replyArea = document.getElementById('card-reply-' + alertId);
        if (replyArea) replyArea.style.display = 'block';
    }

    // Restore button
    if (triggerBtn) {
        triggerBtn.textContent = 'Done';
        triggerBtn.classList.add('done');
        triggerBtn.disabled = false;
    }
}

/**
 * Send a reply on a card thread.
 * CRITICAL: Routes through existing agentic RAG pipeline via POST /api/alerts/{id}/reply.
 */
async function sendCardReply(btn) {
    var alertId = btn.dataset.alert;
    var input = btn.previousElementSibling;
    if (!input || !input.value.trim()) return;
    var content = input.value.trim();
    input.value = '';
    btn.disabled = true;

    var threadEl = document.getElementById('card-thread-' + alertId);
    if (!threadEl) return;

    // Show director message
    var dirMsg = document.createElement('div');
    dirMsg.style.cssText = 'padding:8px 10px;margin:4px 0;background:#eff6ff;border-radius:6px;font-size:11px;';
    dirMsg.innerHTML = '<div style="font-family:var(--mono);font-size:9px;font-weight:700;color:var(--text3);margin-bottom:2px;">YOU</div>';
    var dirText = document.createElement('span');
    dirText.textContent = content; // plain text — no HTML
    dirMsg.appendChild(dirText);
    threadEl.appendChild(dirMsg);

    // Show thinking indicator
    var thinkEl = document.createElement('div');
    thinkEl.style.cssText = 'padding:6px 10px;font-size:11px;color:var(--text3);';
    thinkEl.innerHTML = '<div class="thinking"><span class="thinking-dots"><span></span><span></span><span></span></span> Baker is thinking...</div>';
    threadEl.appendChild(thinkEl);

    // Stream reply via /api/alerts/{id}/reply (routes through /api/scan internally)
    var fullResponse = '';
    try {
        var resp = await bakerFetch('/api/alerts/' + alertId + '/reply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: content }),
        });
        if (!resp.ok) throw new Error('Reply API returned ' + resp.status);

        var reader = resp.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';

        // Replace thinking with baker message container
        thinkEl.innerHTML = '<div style="font-family:var(--mono);font-size:9px;font-weight:700;color:var(--text3);margin-bottom:2px;">BAKER</div><div class="md-content" id="reply-stream-' + alertId + '"></div>';
        var streamEl = document.getElementById('reply-stream-' + alertId);

        while (true) {
            var chunk = await reader.read();
            if (chunk.done) break;
            buffer += decoder.decode(chunk.value, { stream: true });
            var lines = buffer.split('\n');
            buffer = lines.pop();

            for (var i = 0; i < lines.length; i++) {
                if (!lines[i].startsWith('data: ')) continue;
                var payload = lines[i].slice(6).trim();
                if (payload === '[DONE]') continue;
                try {
                    var data = JSON.parse(payload);
                    if (data.token) {
                        fullResponse += data.token;
                        if (streamEl) streamEl.innerHTML = md(fullResponse); // SECURITY: md() escapes first
                    }
                } catch (e) { /* skip */ }
            }
        }
    } catch (err) {
        thinkEl.innerHTML = '<div style="color:var(--red);font-size:11px;">Reply failed: ' + esc(err.message) + '</div>';
    }

    btn.disabled = false;
}

// ═══ RESULT TOOLBAR ═══

function copyResult(btn) {
    var toolbar = btn.closest('[data-result-text]');
    if (!toolbar) return;
    navigator.clipboard.writeText(toolbar.dataset.resultText).then(function() {
        btn.textContent = 'Copied';
        setTimeout(function() { btn.textContent = 'Copy'; }, 2000);
    });
}

function downloadResultAsWord(btn) {
    var toolbar = btn.closest('[data-result-text]');
    if (!toolbar) return;
    bakerFetch('/api/scan/generate-document', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: toolbar.dataset.resultText, format: 'docx', title: 'Baker Result' }),
    }).then(function(resp) {
        if (resp.ok) return resp.json();
        throw new Error('Generation failed');
    }).then(function(data) {
        if (data.download_url) window.open(data.download_url, '_blank');
    }).catch(function(e) { console.error('Word download failed:', e); });
}

function emailResult(btn) {
    var toolbar = btn.closest('[data-result-text]');
    if (!toolbar) return;
    var text = toolbar.dataset.resultText || '';
    var subject = 'Baker Analysis';
    window.location.href = 'mailto:?subject=' + encodeURIComponent(subject) + '&body=' + encodeURIComponent(text);
}

function saveArtifact(btn) {
    var toolbar = btn.closest('[data-result-text]');
    if (!toolbar) return;
    var text = toolbar.dataset.resultText || '';
    // Get matter_slug from the card's data-matter attribute
    var card = btn.closest('.card');
    var matterSlug = card ? card.dataset.matter : null;
    var alertId = card ? parseInt(card.dataset.alertId) : null;

    btn.textContent = 'Saving...';
    btn.disabled = true;
    bakerFetch('/api/artifacts/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            content: text,
            title: 'Baker Analysis',
            matter_slug: matterSlug || null,
            alert_id: alertId || null,
            format: 'md',
        }),
    }).then(function(resp) {
        if (resp.ok) {
            btn.textContent = 'Saved';
            setTimeout(function() { btn.textContent = 'Save'; btn.disabled = false; }, 2000);
        } else {
            throw new Error('Save failed');
        }
    }).catch(function(e) {
        btn.textContent = 'Error';
        setTimeout(function() { btn.textContent = 'Save'; btn.disabled = false; }, 2000);
    });
}

// ═══ MATTERS DETAIL VIEW ═══

var _matterDetailItems = null;
var _matterDetailSlug = null;
var _matterViewMode = 'list';

async function loadMatterDetail(matterSlug) {
    var container = document.getElementById('mattersContent');
    if (!container) return;
    container.textContent = 'Loading...';
    _matterDetailSlug = matterSlug;

    try {
        var resp = await bakerFetch('/api/matters/' + encodeURIComponent(matterSlug) + '/items');
        if (!resp.ok) return;
        var data = await resp.json();

        if (!data.items || data.items.length === 0) {
            container.textContent = 'No items for this matter.';
            container.style.cssText = 'color:var(--text3);font-size:13px;';
            return;
        }

        _matterDetailItems = data.items;
        _matterViewMode = 'list';
        renderMatterView(container, matterSlug, data.items);
    } catch (e) {
        container.textContent = 'Failed to load matter.';
        container.style.color = 'var(--red)';
    }
}

function renderMatterView(container, slug, items) {
    var label = slug === '_ungrouped' ? 'Ungrouped' : slug.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
    container.textContent = '';

    // Header with toggle
    var headerRow = document.createElement('div');
    headerRow.style.cssText = 'display:flex;align-items:center;margin-bottom:12px;';

    var header = document.createElement('div');
    header.className = 'section-label';
    header.style.marginBottom = '0';
    header.textContent = label + ' (' + items.length + ' items)';
    headerRow.appendChild(header);

    // View toggle
    var toggle = document.createElement('div');
    toggle.style.cssText = 'display:flex;gap:0;margin-left:auto;border:1px solid var(--border);border-radius:6px;overflow:hidden;';
    var listBtn = document.createElement('button');
    listBtn.textContent = 'List';
    listBtn.style.cssText = 'padding:5px 12px;font-size:10px;font-weight:600;font-family:var(--mono);border:none;cursor:pointer;letter-spacing:0.3px;' + (_matterViewMode === 'list' ? 'background:var(--text);color:#fff;' : 'background:var(--card);color:var(--text3);');
    listBtn.addEventListener('click', function() { _matterViewMode = 'list'; renderMatterView(container, slug, items); });

    var boardBtn = document.createElement('button');
    boardBtn.textContent = 'Board';
    boardBtn.style.cssText = 'padding:5px 12px;font-size:10px;font-weight:600;font-family:var(--mono);border:none;cursor:pointer;letter-spacing:0.3px;' + (_matterViewMode === 'board' ? 'background:var(--text);color:#fff;' : 'background:var(--card);color:var(--text3);');
    boardBtn.addEventListener('click', function() { _matterViewMode = 'board'; renderMatterView(container, slug, items); });

    toggle.appendChild(listBtn);
    toggle.appendChild(boardBtn);
    headerRow.appendChild(toggle);
    container.appendChild(headerRow);

    if (_matterViewMode === 'list') {
        var cardsDiv = document.createElement('div');
        var cardsHtml = items.map(function(a) { return renderAlertCard(a, (a.tier || 3) <= 2); }).join('');
        setSafeHTML(cardsDiv, cardsHtml);
        container.appendChild(cardsDiv);
        populateAssignDropdowns();
    } else {
        renderBoardView(container, items);
    }
}

function renderBoardView(container, items) {
    var cols = { 1: [], 2: [], 3: [], 4: [] };
    for (var i = 0; i < items.length; i++) {
        var tier = items[i].tier || 4;
        if (tier > 4) tier = 4;
        cols[tier].push(items[i]);
    }

    var colLabels = { 1: 'Fire', 2: 'Important', 3: 'Routine', 4: 'Other' };
    var colDots = { 1: 'red', 2: 'amber', 3: 'slate', 4: 'lgray' };

    var board = document.createElement('div');
    board.className = 'board-view';

    for (var t = 1; t <= 4; t++) {
        var col = document.createElement('div');
        col.className = 'board-column';

        var colHeader = document.createElement('div');
        colHeader.className = 'board-column-header';
        colHeader.innerHTML = '<span class="nav-dot ' + colDots[t] + '"></span> ' + esc(colLabels[t]) + ' <span style="opacity:0.5;">(' + cols[t].length + ')</span>';
        col.appendChild(colHeader);

        if (cols[t].length === 0) {
            var empty = document.createElement('div');
            empty.style.cssText = 'color:var(--text4);font-size:11px;padding:8px 0;';
            empty.textContent = 'No items';
            col.appendChild(empty);
        } else {
            for (var ci = 0; ci < cols[t].length; ci++) {
                var item = cols[t][ci];
                var card = document.createElement('div');
                card.className = 'board-card';
                card.dataset.alertId = item.id;
                card.addEventListener('click', function() {
                    _matterViewMode = 'list';
                    renderMatterView(document.getElementById('mattersContent'), _matterDetailSlug, _matterDetailItems);
                });

                var titleEl = document.createElement('div');
                titleEl.style.cssText = 'font-size:12px;font-weight:500;line-height:1.4;margin-bottom:4px;';
                titleEl.textContent = item.title;
                card.appendChild(titleEl);

                var meta = document.createElement('div');
                meta.style.cssText = 'font-size:10px;color:var(--text3);';
                meta.textContent = 'T' + (item.tier || '?') + ' — ' + fmtRelativeTime(item.created_at);
                card.appendChild(meta);

                col.appendChild(card);
            }
        }
        board.appendChild(col);
    }
    container.appendChild(board);
}

// ═══ ASK BAKER (SCAN SSE) ═══

function focusScanInput() {
    const input = document.getElementById('scanInput');
    if (input) setTimeout(function() { input.focus(); }, 100);
}

function appendScanBubble(role, content, id) {
    const container = document.getElementById('scanMessages');
    if (!container) return;
    const div = document.createElement('div');
    div.className = 'scan-msg ' + (role === 'user' ? 'user' : 'baker');
    if (id) div.id = id;
    if (role === 'assistant' && !content) {
        // Thinking indicator — safe static HTML
        div.innerHTML = '<div class="thinking"><span class="thinking-dots"><span></span><span></span><span></span></span> Baker is thinking...</div>';
    } else if (role === 'assistant') {
        div.innerHTML = '<div class="md-content">' + md(content) + '</div>'; // SECURITY: md() calls esc() first
    } else {
        div.textContent = content; // User messages: plain text, no HTML
    }
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return div;
}

function _createDownloadCard(genData) {
    const ext = genData.filename.split('.').pop();
    const sizeKB = (genData.size_bytes / 1024).toFixed(1);
    const fmtLabels = { docx: 'Word', xlsx: 'Excel', pdf: 'PDF', pptx: 'PowerPoint' };

    const card = document.createElement('div');
    card.style.cssText = 'margin-top:8px;padding:8px 12px;background:var(--badge-bg);border-radius:8px;';

    const link = document.createElement('a');
    link.href = genData.download_url;
    link.download = genData.filename;
    link.style.cssText = 'display:flex;align-items:center;gap:8px;text-decoration:none;color:var(--text);font-size:12px;font-weight:500;';

    const nameSpan = document.createElement('span');
    nameSpan.textContent = genData.filename;
    link.appendChild(nameSpan);

    const metaSpan = document.createElement('span');
    metaSpan.style.cssText = 'color:var(--text3);font-size:10px;';
    metaSpan.textContent = (fmtLabels[ext] || ext) + ' | ' + sizeKB + ' KB';
    link.appendChild(metaSpan);

    const dlSpan = document.createElement('span');
    dlSpan.style.cssText = 'color:var(--blue);font-size:11px;font-weight:600;';
    dlSpan.textContent = 'Download';
    link.appendChild(dlSpan);

    card.appendChild(link);
    return card;
}

async function sendScanMessage(question) {
    if (scanStreaming || !question.trim()) return;
    scanStreaming = true;

    const sendBtn = document.getElementById('scanSendBtn');
    const input = document.getElementById('scanInput');
    if (sendBtn) sendBtn.disabled = true;
    if (input) { input.disabled = true; input.value = ''; }

    scanHistory.push({ role: 'user', content: question });
    appendScanBubble('user', question);

    const assistantId = 'scan-reply-' + Date.now();
    appendScanBubble('assistant', '', assistantId);
    const replyEl = document.getElementById(assistantId);
    if (replyEl) replyEl.innerHTML = '<div class="thinking"><span class="thinking-dots"><span></span><span></span><span></span></span> Baker is thinking...</div>';

    let fullResponse = '';
    try {
        const resp = await bakerFetch('/api/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: question, history: scanHistory.slice(-10) }),
        });

        if (!resp.ok) throw new Error('Scan API returned ' + resp.status);

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const payload = line.slice(6).trim();
                if (payload === '[DONE]') continue;
                try {
                    const data = JSON.parse(payload);
                    if (data.token) {
                        if (!fullResponse && replyEl) replyEl.textContent = ''; // clear thinking indicator
                        fullResponse += data.token;
                        // SECURITY: md() calls esc() first to sanitize HTML entities before formatting
                        if (replyEl) replyEl.innerHTML = '<div class="md-content">' + md(fullResponse) + '</div>';
                    }
                    if (data.task_id) {
                        window._lastScanTaskId = data.task_id; // LEARNING-LOOP: capture for feedback buttons
                    }
                    if (data.error) {
                        fullResponse += '\n[Error: ' + data.error + ']';
                        if (replyEl) replyEl.innerHTML = '<div class="md-content">' + md(fullResponse) + '</div>';
                    }
                } catch (e) { /* skip unparseable */ }
            }
        }
    } catch (err) {
        fullResponse = 'Connection error: ' + err.message;
        if (replyEl) replyEl.textContent = fullResponse;
    }

    // Document generation
    const docMatch = fullResponse.match(/```baker-document\s*\n([\s\S]*?)\n```/);
    if (docMatch && replyEl) {
        try {
            const docSpec = JSON.parse(docMatch[1]);
            const cleanResponse = fullResponse.replace(/```baker-document\s*\n[\s\S]*?\n```/, '').trim();
            if (cleanResponse) replyEl.innerHTML = '<div class="md-content">' + md(cleanResponse) + '</div>';
            const genRes = await bakerFetch('/api/scan/generate-document', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    content: typeof docSpec.content === 'string' ? docSpec.content : JSON.stringify(docSpec.content),
                    format: docSpec.format,
                    title: docSpec.title || 'Baker Document',
                }),
            });
            if (genRes.ok) {
                const genData = await genRes.json();
                replyEl.appendChild(_createDownloadCard(genData));
            }
        } catch (e) { console.warn('Document generation failed:', e); }
    }

    scanHistory.push({ role: 'assistant', content: fullResponse });
    if (scanHistory.length > 20) scanHistory = scanHistory.slice(-20);

    // Copy button for Ask Baker responses
    if (replyEl && fullResponse && !fullResponse.startsWith('Connection error:')) {
        var copyBar = document.createElement('div');
        copyBar.style.cssText = 'display:flex;gap:8px;margin-top:8px;';
        var cpBtn = document.createElement('button');
        cpBtn.textContent = 'Copy';
        cpBtn.style.cssText = 'font-size:11px;padding:3px 10px;border:1px solid var(--border);color:var(--text2);background:var(--bg1);border-radius:4px;cursor:pointer;';
        cpBtn.addEventListener('click', function() {
            navigator.clipboard.writeText(fullResponse).then(function() {
                cpBtn.textContent = 'Copied';
                setTimeout(function() { cpBtn.textContent = 'Copy'; }, 2000);
            });
        });
        copyBar.appendChild(cpBtn);
        replyEl.appendChild(copyBar);
    }

    // LEARNING-LOOP: Render feedback buttons if we got a task_id
    if (window._lastScanTaskId && replyEl) {
        renderFeedbackButtons(window._lastScanTaskId, replyEl);
        window._lastScanTaskId = null;
    }

    scanStreaming = false;
    if (sendBtn) sendBtn.disabled = false;
    if (input) { input.disabled = false; input.focus(); }

    const container = document.getElementById('scanMessages');
    if (container) container.scrollTop = container.scrollHeight;
}

// ═══ COMMAND BAR ═══

function setupCommandBar() {
    const cmdInput = document.getElementById('cmdInput');
    if (cmdInput) {
        cmdInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && cmdInput.value.trim()) {
                e.preventDefault();
                const q = cmdInput.value.trim();
                cmdInput.value = '';
                switchTab('ask-baker');
                setTimeout(function() { sendScanMessage(q); }, 100);
            }
        });
    }

    // Cmd+K shortcut
    document.addEventListener('keydown', function(e) {
        if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
            e.preventDefault();
            if (cmdInput) cmdInput.focus();
        }
    });

    // Quick action buttons (command bar)
    document.querySelectorAll('.cmd-quick').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var action = btn.dataset.action;
            var prompts = {
                'briefing': 'Give me a morning briefing -- what happened overnight, top fires, key deadlines.',
                'draft': 'Help me draft an email.',
                'legal': 'Give me a legal status update on active disputes.',
                'research': 'What market intelligence do you have from recent RSS feeds and emails?',
            };
            switchTab('ask-baker');
            setTimeout(function() { sendScanMessage(prompts[action] || action); }, 100);
        });
    });

    // Quick action buttons (morning brief)
    document.querySelectorAll('.quick-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var action = btn.dataset.action;
            var prompts = {
                'briefing': 'Give me a full morning briefing.',
                'draft': 'Help me draft an email.',
                'legal': 'Give me a legal review of all active disputes.',
                'research': 'What market intelligence do you have?',
                'finance': 'Give me a financial analysis update.',
                'it': 'Give me an IT infrastructure status update.',
            };
            switchTab('ask-baker');
            setTimeout(function() { sendScanMessage(prompts[action] || action); }, 100);
        });
    });
}

// ═══ MATTERS TAB ═══

var _currentMatterSlug = null;

async function loadMattersTab() {
    var container = document.getElementById('mattersContent');
    if (!container) return;

    // If a specific matter was selected, load its detail
    if (_currentMatterSlug) {
        loadMatterDetail(_currentMatterSlug);
        _currentMatterSlug = null;
        return;
    }

    // Otherwise show all matters overview
    container.textContent = 'Loading matters...';
    try {
        var resp = await bakerFetch('/api/dashboard/matters-summary');
        if (!resp.ok) return;
        var data = await resp.json();

        if (!data.matters || data.matters.length === 0) {
            container.textContent = 'No active matters.';
            container.style.cssText = 'color:var(--text3);font-size:13px;';
            return;
        }

        container.textContent = '';
        var header = document.createElement('div');
        header.className = 'section-label';
        header.textContent = 'All matters (' + data.matters.length + ')';
        container.appendChild(header);

        for (var i = 0; i < data.matters.length; i++) {
            var m = data.matters[i];
            var slug = m.matter_slug || '_ungrouped';
            var label = slug === '_ungrouped' ? 'Ungrouped' : slug.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
            var dotClass = tierClass(m.worst_tier);

            var card = document.createElement('div');
            card.className = 'card card-compact';
            card.style.cursor = 'pointer';
            card.dataset.matter = slug;
            card.addEventListener('click', function() {
                loadMatterDetail(this.dataset.matter);
            });

            var hdr = document.createElement('div');
            hdr.className = 'card-header';

            var dot = document.createElement('span');
            dot.className = 'nav-dot ' + dotClass;
            dot.style.marginTop = '5px';
            hdr.appendChild(dot);

            var title = document.createElement('span');
            title.className = 'card-title';
            title.textContent = label;
            hdr.appendChild(title);

            var count = document.createElement('span');
            count.className = 'card-time';
            count.textContent = m.item_count + ' items';
            hdr.appendChild(count);

            if (m.new_count > 0) {
                var newBadge = document.createElement('span');
                newBadge.className = 'card-new-badge';
                newBadge.textContent = m.new_count + ' new';
                hdr.appendChild(newBadge);
            }

            card.appendChild(hdr);
            container.appendChild(card);
        }
    } catch (e) {
        container.textContent = 'Failed to load matters.';
        container.style.color = 'var(--red)';
    }
}

// ═══ PEOPLE TAB ═══

// ═══ NETWORKING TAB (NETWORKING-PHASE-1) ═══

var _networkingFilter = 'all';

async function loadPeopleTab() {
    var container = document.getElementById('peopleContent');
    if (!container) return;
    container.textContent = 'Loading networking...';

    try {
        var results = await Promise.all([
            bakerFetch('/api/networking/contacts' + (_networkingFilter !== 'all' ? '?contact_type=' + _networkingFilter : '')).then(function(r) { return r.json(); }),
            bakerFetch('/api/networking/alerts').then(function(r) { return r.json(); }),
            bakerFetch('/api/networking/events').then(function(r) { return r.json(); }),
        ]);
        var contactsData = results[0];
        var alertsData = results[1];
        var eventsData = results[2];

        container.textContent = '';

        // A. Alert Strip
        var strip = document.createElement('div');
        strip.style.cssText = 'display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap;';

        if (alertsData.going_cold_count > 0) {
            var badge = document.createElement('span');
            badge.style.cssText = 'background:var(--red);color:#fff;padding:4px 10px;border-radius:12px;font-size:11px;font-weight:600;cursor:pointer;';
            badge.textContent = alertsData.going_cold_count + ' going cold';
            strip.appendChild(badge);
        }
        if (alertsData.unreciprocated_count > 0) {
            var badge2 = document.createElement('span');
            badge2.style.cssText = 'background:var(--amber);color:#fff;padding:4px 10px;border-radius:12px;font-size:11px;font-weight:600;';
            badge2.textContent = alertsData.unreciprocated_count + ' unreciprocated';
            strip.appendChild(badge2);
        }
        if (alertsData.upcoming_events_count > 0) {
            var badge3 = document.createElement('span');
            badge3.style.cssText = 'background:var(--blue);color:#fff;padding:4px 10px;border-radius:12px;font-size:11px;font-weight:600;';
            badge3.textContent = alertsData.upcoming_events_count + ' upcoming events';
            strip.appendChild(badge3);
        }
        if (strip.children.length === 0) {
            var allGood = document.createElement('span');
            allGood.style.cssText = 'color:var(--green);font-size:12px;font-weight:600;';
            allGood.textContent = 'All contacts healthy';
            strip.appendChild(allGood);
        }
        container.appendChild(strip);

        // B. Filter Buttons
        var filters = document.createElement('div');
        filters.style.cssText = 'display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap;';
        var types = ['all', 'principal', 'introducer', 'operator', 'institutional', 'connector'];
        types.forEach(function(t) {
            var btn = document.createElement('button');
            btn.className = _networkingFilter === t ? 'filter-tab active' : 'filter-tab';
            btn.textContent = t.charAt(0).toUpperCase() + t.slice(1);
            btn.addEventListener('click', function() { _networkingFilter = t; loadPeopleTab(); });
            filters.appendChild(btn);
        });
        container.appendChild(filters);

        // C. Contact List
        var contacts = contactsData.contacts || [];
        if (contacts.length === 0) {
            var empty = document.createElement('div');
            empty.textContent = 'No contacts found.';
            empty.style.cssText = 'color:var(--text3);font-size:12px;';
            container.appendChild(empty);
        }

        for (var i = 0; i < contacts.length; i++) {
            (function(c) {
                var card = document.createElement('div');
                card.className = 'card card-compact person-card';
                card.style.cursor = 'pointer';

                var hdr = document.createElement('div');
                hdr.className = 'card-header';
                hdr.style.cssText = 'display:flex;align-items:center;gap:8px;';

                // Tier badge
                if (c.tier) {
                    var tierBadge = document.createElement('span');
                    tierBadge.style.cssText = 'font-size:10px;font-weight:700;color:var(--text3);min-width:20px;';
                    tierBadge.textContent = 'T' + c.tier;
                    hdr.appendChild(tierBadge);
                }

                // Health dot
                var healthDot = document.createElement('span');
                healthDot.className = 'nav-dot';
                var hColors = {red: 'var(--red)', amber: 'var(--amber)', green: 'var(--green)', grey: 'var(--lgray)'};
                healthDot.style.cssText = 'width:8px;height:8px;border-radius:50;background:' + (hColors[c.health] || 'var(--lgray)') + ';flex-shrink:0;';
                hdr.appendChild(healthDot);

                // Name + type
                var nameWrap = document.createElement('div');
                nameWrap.style.cssText = 'flex:1;min-width:0;';
                var nm = document.createElement('div');
                nm.className = 'card-title';
                nm.textContent = c.name || '';
                nameWrap.appendChild(nm);
                var sub = document.createElement('div');
                sub.style.cssText = 'font-size:11px;color:var(--text3);';
                var subParts = [];
                if (c.contact_type) subParts.push(c.contact_type);
                if (c.role) subParts.push(c.role);
                sub.textContent = subParts.join(' \u00B7 ');
                nameWrap.appendChild(sub);
                hdr.appendChild(nameWrap);

                // Last contact
                if (c.last_contact_date) {
                    var lastC = document.createElement('span');
                    lastC.style.cssText = 'font-size:11px;color:var(--text3);white-space:nowrap;';
                    lastC.textContent = fmtRelativeTime(c.last_contact_date);
                    hdr.appendChild(lastC);
                }

                card.appendChild(hdr);

                // Matters badges
                if (c.matters && c.matters.length > 0) {
                    var mattersRow = document.createElement('div');
                    mattersRow.style.cssText = 'padding:4px 0 0;display:flex;gap:4px;flex-wrap:wrap;';
                    c.matters.forEach(function(m) {
                        var badge = document.createElement('span');
                        badge.className = 'tag-badge';
                        badge.textContent = m;
                        mattersRow.appendChild(badge);
                    });
                    card.appendChild(mattersRow);
                }

                // Expand area (hidden initially)
                var expandArea = document.createElement('div');
                expandArea.style.cssText = 'display:none;padding:10px 0 0;border-top:1px solid var(--border);margin-top:8px;';
                expandArea.dataset.contactId = c.id;
                card.appendChild(expandArea);

                // Click to expand/collapse
                hdr.addEventListener('click', function() {
                    if (expandArea.style.display === 'none') {
                        expandArea.style.display = '';
                        _loadContactExpand(expandArea, c);
                    } else {
                        expandArea.style.display = 'none';
                    }
                });

                container.appendChild(card);
            })(contacts[i]);
        }

        // D. Events Section
        var events = eventsData.events || [];
        if (events.length > 0) {
            var evLabel = document.createElement('div');
            evLabel.className = 'section-label';
            evLabel.textContent = 'Events of Interest';
            evLabel.style.marginTop = '16px';
            container.appendChild(evLabel);

            events.forEach(function(ev) {
                var row = document.createElement('div');
                row.className = 'card card-compact';
                var hdr = document.createElement('div');
                hdr.className = 'card-header';
                var title = document.createElement('span');
                title.className = 'card-title';
                title.textContent = ev.event_name || '';
                hdr.appendChild(title);
                var meta = document.createElement('span');
                meta.style.cssText = 'font-size:11px;color:var(--text3);';
                var parts = [];
                if (ev.dates_start) parts.push(ev.dates_start);
                if (ev.location) parts.push(ev.location);
                if (ev.category) parts.push(ev.category);
                meta.textContent = parts.join(' \u00B7 ');
                hdr.appendChild(meta);
                row.appendChild(hdr);
                container.appendChild(row);
            });
        }

    } catch (e) {
        console.error('loadPeopleTab (networking) failed:', e);
        container.textContent = 'Failed to load networking.';
    }
}

// Action buttons for contact expand
var _NETWORKING_ACTIONS = [
    {key: 'new_topic', label: 'New Topic'},
    {key: 'engaged_by_brisen', label: 'Engaged by Brisen'},
    {key: 'engaged_by_person', label: 'Engaged by Person'},
    {key: 'possible_connector', label: 'Possible Connector'},
    {key: 'possible_place', label: 'Possible Place'},
    {key: 'possible_date', label: 'Possible Date'},
];

async function _loadContactExpand(expandArea, contact) {
    expandArea.textContent = '';
    var cid = contact.id;

    // 1. Quick stats line
    var stats = document.createElement('div');
    stats.style.cssText = 'font-size:11px;color:var(--text2);margin-bottom:8px;';
    var statParts = [];
    if (contact.last_contact_date) statParts.push('Last: ' + fmtRelativeTime(contact.last_contact_date));
    if (contact.sentiment_trend) statParts.push('Sentiment: ' + contact.sentiment_trend);
    if (contact.relationship_score) statParts.push('Score: ' + contact.relationship_score);
    stats.textContent = statParts.join(' \u00B7 ') || 'No stats yet';
    expandArea.appendChild(stats);

    // 2. Recent interactions
    try {
        var resp = await bakerFetch('/api/networking/contact/' + cid + '/interactions');
        if (resp.ok) {
            var iData = await resp.json();
            if (iData.interactions && iData.interactions.length > 0) {
                var iLabel = document.createElement('div');
                iLabel.style.cssText = 'font-size:11px;font-weight:600;color:var(--text2);margin:6px 0 4px;';
                iLabel.textContent = 'Recent interactions';
                expandArea.appendChild(iLabel);
                iData.interactions.slice(0, 5).forEach(function(ix) {
                    var row = document.createElement('div');
                    row.style.cssText = 'font-size:11px;color:var(--text3);padding:2px 0;display:flex;gap:6px;';
                    var ch = document.createElement('span');
                    ch.style.fontWeight = '600';
                    ch.textContent = (ix.channel || '?').toUpperCase();
                    row.appendChild(ch);
                    var dir = document.createElement('span');
                    dir.textContent = ix.direction === 'inbound' ? '\u2190' : '\u2192';
                    row.appendChild(dir);
                    var subj = document.createElement('span');
                    subj.style.cssText = 'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
                    subj.textContent = ix.subject || '';
                    row.appendChild(subj);
                    if (ix.timestamp) {
                        var ts = document.createElement('span');
                        ts.textContent = fmtRelativeTime(ix.timestamp);
                        row.appendChild(ts);
                    }
                    expandArea.appendChild(row);
                });
            }
        }
    } catch (e) { /* non-fatal */ }

    // 3. Action buttons
    var btnRow = document.createElement('div');
    btnRow.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;margin-top:10px;';
    var responseArea = document.createElement('div');
    responseArea.style.cssText = 'margin-top:8px;font-size:12px;color:var(--text2);';

    _NETWORKING_ACTIONS.forEach(function(action) {
        var btn = document.createElement('button');
        btn.className = 'quick-btn';
        btn.style.cssText = 'font-size:11px;padding:4px 10px;';
        btn.textContent = action.label;
        btn.addEventListener('click', function() {
            _runNetworkingAction(cid, action.key, responseArea);
        });
        btnRow.appendChild(btn);
    });
    expandArea.appendChild(btnRow);
    expandArea.appendChild(responseArea);
}

async function _runNetworkingAction(contactId, actionKey, responseArea) {
    responseArea.innerHTML = '<div class="thinking"><span class="thinking-dots"><span></span><span></span><span></span></span> Baker is thinking...</div>';
    try {
        var resp = await bakerFetch('/api/networking/contact/' + contactId + '/action', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: actionKey}),
        });
        if (!resp.ok) {
            responseArea.textContent = 'Action failed.';
            return;
        }
        // SSE streaming response
        var reader = resp.body.getReader();
        var decoder = new TextDecoder();
        var text = '';
        responseArea.textContent = '';
        while (true) {
            var chunk = await reader.read();
            if (chunk.done) break;
            var raw = decoder.decode(chunk.value, {stream: true});
            // Parse SSE data lines
            var lines = raw.split('\n');
            for (var li = 0; li < lines.length; li++) {
                var line = lines[li];
                if (line.startsWith('data: ')) {
                    try {
                        var payload = JSON.parse(line.slice(6));
                        if (payload.token) text += payload.token;
                        if (payload.answer) text = payload.answer;
                    } catch (pe) {
                        // plain text token
                        text += line.slice(6);
                    }
                }
            }
            setSafeHTML(responseArea, md(text));
        }
        if (!text) responseArea.textContent = 'No response.';
    } catch (e) {
        console.error('Networking action failed:', e);
        responseArea.textContent = 'Action failed: ' + (e.message || 'unknown error');
    }
}

// Legacy alias — loadPersonDetail still called from old code paths
async function loadPersonDetail(name) {
    loadPeopleTab();
}

// ═══ SEARCH TAB ═══

var _searchInitialized = false;

function loadSearchTab() {
    if (_searchInitialized) return;
    _searchInitialized = true;
    var filtersEl = document.getElementById('searchFilters');
    if (!filtersEl) return;

    // Build filter bar using DOM methods
    filtersEl.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px;align-items:center;';

    var searchInput = document.createElement('input');
    searchInput.type = 'text';
    searchInput.placeholder = 'Search alerts...';
    searchInput.maxLength = 500;
    searchInput.style.cssText = 'flex:1;min-width:200px;padding:8px 12px;border:1px solid var(--border);border-radius:6px;font-size:12px;font-family:var(--font);outline:none;';
    searchInput.id = 'searchQueryInput';
    filtersEl.appendChild(searchInput);

    var matterSelect = document.createElement('select');
    matterSelect.style.cssText = 'padding:6px 10px;border:1px solid var(--border);border-radius:6px;font-size:11px;font-family:var(--font);';
    matterSelect.id = 'searchMatterFilter';
    matterSelect.innerHTML = '<option value="">All matters</option>';
    filtersEl.appendChild(matterSelect);

    var tagSelect = document.createElement('select');
    tagSelect.style.cssText = 'padding:6px 10px;border:1px solid var(--border);border-radius:6px;font-size:11px;font-family:var(--font);';
    tagSelect.id = 'searchTagFilter';
    tagSelect.innerHTML = '<option value="">All tags</option>';
    filtersEl.appendChild(tagSelect);

    var statusSelect = document.createElement('select');
    statusSelect.style.cssText = 'padding:6px 10px;border:1px solid var(--border);border-radius:6px;font-size:11px;font-family:var(--font);';
    statusSelect.id = 'searchStatusFilter';
    statusSelect.innerHTML = '<option value="">All status</option><option value="pending">Pending</option><option value="resolved">Resolved</option><option value="dismissed">Dismissed</option>';
    filtersEl.appendChild(statusSelect);

    var searchBtn = document.createElement('button');
    searchBtn.className = 'run-btn';
    searchBtn.textContent = 'Search';
    searchBtn.addEventListener('click', executeSearch);
    filtersEl.appendChild(searchBtn);

    // Debounced live search
    searchInput.addEventListener('input', debounce(function() {
        if (searchInput.value.trim().length >= 3) executeSearch();
    }, 300));

    // Populate dropdowns
    bakerFetch('/api/dashboard/matters-summary').then(function(r) { return r.json(); }).then(function(d) {
        if (d.matters) d.matters.forEach(function(m) {
            var opt = document.createElement('option');
            opt.value = m.matter_slug;
            opt.textContent = m.matter_slug === '_ungrouped' ? 'Ungrouped' : m.matter_slug;
            matterSelect.appendChild(opt);
        });
    }).catch(function() {});
    bakerFetch('/api/tags').then(function(r) { return r.json(); }).then(function(d) {
        if (d.tags) d.tags.forEach(function(t) {
            var opt = document.createElement('option');
            opt.value = t.tag || t.name;
            opt.textContent = (t.tag || t.name) + ' (' + t.count + ')';
            tagSelect.appendChild(opt);
        });
    }).catch(function() {});
}

async function executeSearch() {
    var results = document.getElementById('searchResults');
    if (!results) return;
    results.textContent = 'Searching...';

    var q = (document.getElementById('searchQueryInput') || {}).value || '';
    var matter = (document.getElementById('searchMatterFilter') || {}).value || '';
    var tag = (document.getElementById('searchTagFilter') || {}).value || '';
    var status = (document.getElementById('searchStatusFilter') || {}).value || '';

    var params = new URLSearchParams();
    if (q) params.set('q', q);
    if (matter) params.set('matter', matter);
    if (tag) params.set('tag', tag);
    if (status) params.set('status', status);
    params.set('limit', '50');

    try {
        var resp = await bakerFetch('/api/alerts/search?' + params.toString());
        if (!resp.ok) return;
        var data = await resp.json();

        results.textContent = '';
        var countEl = document.createElement('div');
        countEl.style.cssText = 'font-size:12px;color:var(--text3);margin-bottom:10px;';
        countEl.textContent = data.count + ' results';
        results.appendChild(countEl);

        if (data.items.length === 0) return;

        var cardsDiv = document.createElement('div');
        setSafeHTML(cardsDiv, data.items.map(function(a) {
            return renderAlertCard(a, (a.tier || 3) <= 2);
        }).join(''));
        results.appendChild(cardsDiv);
        populateAssignDropdowns();
    } catch (e) {
        results.textContent = 'Search failed.';
    }
}

// ═══ TAGS TAB ═══

async function loadTagsTab() {
    var container = document.getElementById('tagsContent');
    if (!container) return;
    container.textContent = 'Loading tags...';

    try {
        var resp = await bakerFetch('/api/tags');
        if (!resp.ok) return;
        var data = await resp.json();

        if (!data.tags || data.tags.length === 0) {
            container.textContent = 'No tags found.';
            container.style.cssText = 'color:var(--text3);font-size:13px;';
            return;
        }

        container.textContent = '';
        for (var i = 0; i < data.tags.length; i++) {
            var t = data.tags[i];
            var card = document.createElement('div');
            card.className = 'card card-compact';
            card.style.cursor = 'pointer';
            card.dataset.tag = t.tag || t.name;
            card.addEventListener('click', function() { loadTagItems(this.dataset.tag); });

            var hdr = document.createElement('div');
            hdr.className = 'card-header';

            var badge = document.createElement('span');
            badge.className = 'tag-badge';
            badge.textContent = t.tag || t.name;
            badge.style.marginTop = '3px';
            hdr.appendChild(badge);

            var title = document.createElement('span');
            title.className = 'card-title';
            title.textContent = '';
            hdr.appendChild(title);

            var count = document.createElement('span');
            count.className = 'card-time';
            count.textContent = t.count + ' items';
            hdr.appendChild(count);

            card.appendChild(hdr);
            container.appendChild(card);
        }
    } catch (e) {
        container.textContent = 'Failed to load tags.';
        container.style.color = 'var(--red)';
    }
}

async function loadTagItems(tag) {
    var container = document.getElementById('tagsContent');
    if (!container) return;
    container.textContent = 'Loading...';

    try {
        var resp = await bakerFetch('/api/alerts/by-tag/' + encodeURIComponent(tag));
        if (!resp.ok) return;
        var data = await resp.json();

        container.textContent = '';
        var back = document.createElement('button');
        back.className = 'footer-btn';
        back.textContent = 'Back to all tags';
        back.style.marginBottom = '12px';
        back.addEventListener('click', function() { loadTagsTab(); });
        container.appendChild(back);

        var header = document.createElement('div');
        header.className = 'section-label';
        header.textContent = tag + ' (' + data.count + ' items)';
        container.appendChild(header);

        if (data.items.length === 0) {
            var empty = document.createElement('div');
            empty.textContent = 'No items with this tag.';
            empty.style.cssText = 'color:var(--text3);font-size:13px;';
            container.appendChild(empty);
            return;
        }

        var cardsDiv = document.createElement('div');
        setSafeHTML(cardsDiv, data.items.map(function(a) {
            return renderAlertCard(a, (a.tier || 3) <= 2);
        }).join(''));
        container.appendChild(cardsDiv);
        populateAssignDropdowns();
    } catch (e) {
        container.textContent = 'Failed to load items.';
        container.style.color = 'var(--red)';
    }
}

// ═══ UNGROUPED ASSIGNMENT ═══

async function assignAlert(alertId, matterSlug) {
    if (!matterSlug) return;
    try {
        await bakerFetch('/api/alerts/' + alertId + '/assign', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ matter_slug: matterSlug }),
        });
        // Reload current view to reflect change
        if (currentTab === 'fires') loadFires();
        else if (currentTab === 'matters') loadMattersTab();
        else if (currentTab === 'morning-brief') loadMorningBrief();
    } catch (e) {
        console.error('assignAlert failed:', e);
    }
}

/** Populate all assign dropdowns with active matters. Called after rendering cards. */
async function populateAssignDropdowns() {
    var selects = document.querySelectorAll('.assign-select');
    if (selects.length === 0) return;
    try {
        var resp = await bakerFetch('/api/matters?status=active');
        if (!resp.ok) return;
        var data = await resp.json();
        selects.forEach(function(sel) {
            // Keep the first option
            while (sel.options.length > 1) sel.remove(1);
            if (data.matters) {
                for (var i = 0; i < data.matters.length; i++) {
                    var m = data.matters[i];
                    var opt = document.createElement('option');
                    opt.value = m.matter_name || m.slug;
                    opt.textContent = m.matter_name || m.slug;
                    sel.appendChild(opt);
                }
            }
        });
    } catch (e) {
        console.error('populateAssignDropdowns failed:', e);
    }
}

// ═══ ENHANCED DEADLINES TAB ═══

async function loadDeadlinesTab() {
    var container = document.getElementById('deadlinesContent');
    if (!container) return;
    container.textContent = 'Loading...';

    try {
        // Fetch both deadlines and commitments, merge into one list
        var [dlResp, cmResp] = await Promise.all([
            bakerFetch('/api/deadlines?limit=100'),
            bakerFetch('/api/commitments?status=active&limit=200'),
        ]);
        var allItems = [];

        if (dlResp.ok) {
            var dlData = await dlResp.json();
            (dlData.deadlines || []).forEach(function(d) {
                allItems.push({ type: 'deadline', id: d.id, description: d.description, due_date: d.due_date, source: d.source_type || 'deadline', matter: d.matter_slug, priority: d.priority, status: d.status });
            });
        }
        if (cmResp.ok) {
            var cmData = await cmResp.json();
            (cmData.commitments || []).forEach(function(c) {
                allItems.push({ type: 'commitment', id: c.id, description: c.description, due_date: c.due_date, source: c.source_type || c.source || 'commitment', matter: c.matter_slug, assigned_to: c.assigned_to, status: c.status });
            });
        }

        // Also fetch overdue commitments
        var ovResp = await bakerFetch('/api/commitments?status=overdue&limit=200');
        if (ovResp.ok) {
            var ovData = await ovResp.json();
            (ovData.commitments || []).forEach(function(c) {
                allItems.push({ type: 'commitment', id: c.id, description: c.description, due_date: c.due_date, source: c.source_type || c.source || 'commitment', matter: c.matter_slug, assigned_to: c.assigned_to, status: c.status });
            });
        }

        // Dedup by type+id
        var seen = {};
        allItems = allItems.filter(function(item) {
            var key = item.type + ':' + item.id;
            if (seen[key]) return false;
            seen[key] = true;
            return true;
        });

        // Sort by due_date (nulls last)
        allItems.sort(function(a, b) {
            var da = a.due_date || '9999-12-31';
            var db = b.due_date || '9999-12-31';
            return da < db ? -1 : da > db ? 1 : 0;
        });

        if (allItems.length === 0) {
            container.textContent = 'No active deadlines or commitments.';
            container.style.cssText = 'color:var(--text3);font-size:13px;';
            return;
        }

        // Group by urgency
        var overdue = [], today = [], thisWeek = [], later = [];
        for (var i = 0; i < allItems.length; i++) {
            var item = allItems[i];
            var daysText = fmtDeadlineDays(item.due_date);
            if (daysText.includes('overdue')) overdue.push(item);
            else if (daysText === 'Today') today.push(item);
            else if (daysText === 'Tomorrow' || (parseInt(daysText) > 0 && parseInt(daysText) <= 7)) thisWeek.push(item);
            else later.push(item);
        }

        container.textContent = '';

        var header = document.createElement('div');
        header.className = 'section-label';
        header.textContent = 'Deadlines & Commitments (' + allItems.length + ')';
        container.appendChild(header);

        function renderTimeGroup(label, items, isUrgent) {
            if (items.length === 0) return;
            var groupLabel = document.createElement('div');
            groupLabel.style.cssText = 'font-family:var(--mono);font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.6px;color:' + (isUrgent ? 'var(--red)' : 'var(--text3)') + ';margin:16px 0 6px;';
            groupLabel.textContent = label + ' (' + items.length + ')';
            container.appendChild(groupLabel);

            items.forEach(function(item) {
                var row = document.createElement('div');
                row.style.cssText = 'display:flex;gap:12px;padding:8px 10px;border-bottom:1px solid var(--border);cursor:pointer;transition:background 0.15s;';
                row.addEventListener('mouseenter', function() { row.style.background = 'var(--bg2)'; });
                row.addEventListener('mouseleave', function() { row.style.background = ''; });

                // LEFT: date
                var dateCol = document.createElement('div');
                dateCol.style.cssText = 'min-width:70px;font-size:11px;font-weight:600;color:' + (isUrgent ? 'var(--red)' : 'var(--text2)') + ';padding-top:2px;';
                var dueStr = item.due_date ? new Date(item.due_date).toLocaleDateString('en-GB', {day:'numeric', month:'short'}) : 'No date';
                dateCol.textContent = dueStr;
                row.appendChild(dateCol);

                // RIGHT: description + source tag
                var descCol = document.createElement('div');
                descCol.style.cssText = 'flex:1;font-size:13px;color:var(--text1);';
                descCol.textContent = item.description || '';
                if (item.matter) {
                    var tag = document.createElement('span');
                    tag.style.cssText = 'font-size:10px;color:var(--text3);margin-left:8px;';
                    tag.textContent = item.matter.replace(/_/g, ' ');
                    descCol.appendChild(tag);
                }
                row.appendChild(descCol);

                // Click to expand actions
                var actionsDiv = document.createElement('div');
                actionsDiv.style.cssText = 'display:none;padding:8px 10px 8px 82px;background:var(--bg2);border-bottom:1px solid var(--border);';
                var expanded = false;

                row.addEventListener('click', function() {
                    expanded = !expanded;
                    actionsDiv.style.display = expanded ? 'flex' : 'none';
                    actionsDiv.style.gap = '8px';
                });

                function makeBtn(label, color, onClick) {
                    var btn = document.createElement('button');
                    btn.textContent = label;
                    btn.style.cssText = 'font-size:11px;padding:4px 12px;border:1px solid ' + color + ';color:' + color + ';background:transparent;border-radius:4px;cursor:pointer;';
                    btn.addEventListener('click', function(e) { e.stopPropagation(); onClick(); });
                    return btn;
                }

                actionsDiv.appendChild(makeBtn('Dismiss', 'var(--text3)', function() {
                    var endpoint = item.type === 'deadline'
                        ? '/api/deadlines/' + item.id + '/dismiss'
                        : '/api/commitments/' + item.id + '/dismiss';
                    bakerFetch(endpoint, { method: 'POST' }).then(function() { loadDeadlinesTab(); });
                }));

                actionsDiv.appendChild(makeBtn('+1 Week', 'var(--amber)', function() {
                    var newDate = new Date(item.due_date || new Date());
                    newDate.setDate(newDate.getDate() + 7);
                    var endpoint = item.type === 'deadline'
                        ? '/api/deadlines/' + item.id + '/reschedule'
                        : '/api/commitments/' + item.id + '/reschedule';
                    bakerFetch(endpoint, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({due_date: newDate.toISOString()}) }).then(function() { loadDeadlinesTab(); });
                }));

                actionsDiv.appendChild(makeBtn('Ask Baker', 'var(--blue)', function() {
                    var input = document.getElementById('scanInput');
                    if (input) {
                        input.value = 'What should I do about: ' + (item.description || '');
                        switchTab('ask-baker');
                    }
                }));

                container.appendChild(row);
                container.appendChild(actionsDiv);
            });
        }

        renderTimeGroup('Overdue', overdue, true);
        renderTimeGroup('Today', today, true);
        renderTimeGroup('This Week', thisWeek, false);
        renderTimeGroup('Later', later, false);

    } catch (e) {
        container.textContent = 'Failed to load deadlines.';
        container.style.color = 'var(--red)';
        console.warn('Deadlines tab failed:', e);
    }
}

// ═══ TRAVEL TAB ═══

async function loadTravelTab() {
    var container = document.getElementById('travelContent');
    if (!container) return;
    container.textContent = 'Loading travel items...';
    try {
        var resp = await bakerFetch('/api/alerts/by-tag/travel');
        if (!resp.ok) return;
        var data = await resp.json();

        if (!data.items || data.items.length === 0) {
            container.textContent = 'No travel alerts. Travel-related emails and bookings will appear here when detected.';
            container.style.cssText = 'color:var(--text3);font-size:13px;';
            return;
        }

        // Split into upcoming and past
        var now = new Date();
        now.setHours(0, 0, 0, 0);
        var upcoming = [];
        var past = [];
        for (var i = 0; i < data.items.length; i++) {
            var item = data.items[i];
            if (item.travel_date) {
                var td = new Date(item.travel_date);
                if (td < now) { past.push(item); continue; }
            }
            upcoming.push(item);
        }

        container.textContent = '';

        if (upcoming.length > 0) {
            var upLabel = document.createElement('div');
            upLabel.style.cssText = 'font-family:var(--mono);font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.6px;color:var(--text3);margin:0 0 8px;';
            upLabel.textContent = 'Upcoming (' + upcoming.length + ')';
            container.appendChild(upLabel);
            var upDiv = document.createElement('div');
            setSafeHTML(upDiv, upcoming.map(function(a) { return renderAlertCard(a, false); }).join(''));
            container.appendChild(upDiv);
        }

        if (past.length > 0) {
            var pastLabel = document.createElement('div');
            pastLabel.style.cssText = 'font-family:var(--mono);font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.6px;color:var(--text4);margin:16px 0 8px;';
            pastLabel.textContent = 'Past (' + past.length + ')';
            container.appendChild(pastLabel);
            var pastDiv = document.createElement('div');
            pastDiv.style.opacity = '0.5';
            setSafeHTML(pastDiv, past.map(function(a) { return renderAlertCard(a, false); }).join(''));
            container.appendChild(pastDiv);
        }
    } catch (e) {
        container.textContent = 'Failed to load travel items.';
    }
}

// ═══ MEDIA TAB (RSS) ═══

async function loadMediaTab() {
    var container = document.getElementById('mediaContent');
    if (!container) return;
    container.textContent = 'Loading media...';
    try {
        // Fetch feeds for filter dropdown
        var feedsResp = await bakerFetch('/api/rss/feeds');
        var feedsData = feedsResp.ok ? await feedsResp.json() : { feeds: [] };

        // Fetch articles
        var articlesResp = await bakerFetch('/api/rss/articles?limit=50');
        if (!articlesResp.ok) return;
        var data = await articlesResp.json();

        container.textContent = '';

        // Category filter
        if (feedsData.feeds && feedsData.feeds.length > 0) {
            var filterRow = document.createElement('div');
            filterRow.style.cssText = 'margin-bottom:12px;';
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
            catSelect.addEventListener('change', async function() {
                var url = '/api/rss/articles?limit=50';
                if (catSelect.value) url += '&category=' + encodeURIComponent(catSelect.value);
                var r = await bakerFetch(url);
                if (r.ok) {
                    var d = await r.json();
                    renderArticles(container, d.articles, filterRow);
                }
            });
            filterRow.appendChild(catSelect);
            container.appendChild(filterRow);
        }

        if (!data.articles || data.articles.length === 0) {
            var empty = document.createElement('div');
            empty.textContent = 'No media items yet. RSS feeds are polled every hour.';
            empty.style.cssText = 'color:var(--text3);font-size:13px;';
            container.appendChild(empty);
            return;
        }

        var filterRow2 = container.querySelector('div');
        renderArticles(container, data.articles, filterRow2);
    } catch (e) {
        container.textContent = 'Failed to load media.';
    }
}

function renderArticles(container, articles, filterRow) {
    // Clear existing articles but keep filter row
    while (container.children.length > (filterRow ? 1 : 0)) {
        container.removeChild(container.lastChild);
    }

    // Group by date
    var today = new Date(); today.setHours(0,0,0,0);
    var yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1);
    var weekAgo = new Date(today); weekAgo.setDate(weekAgo.getDate() - 7);

    var groups = { 'Today': [], 'Yesterday': [], 'This Week': [], 'Older': [] };
    for (var i = 0; i < articles.length; i++) {
        var a = articles[i];
        var d = a.published_at ? new Date(a.published_at) : new Date(0);
        if (d >= today) groups['Today'].push(a);
        else if (d >= yesterday) groups['Yesterday'].push(a);
        else if (d >= weekAgo) groups['This Week'].push(a);
        else groups['Older'].push(a);
    }

    for (var group in groups) {
        if (groups[group].length === 0) continue;
        var label = document.createElement('div');
        label.style.cssText = 'font-family:var(--mono);font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.6px;color:var(--text3);margin:12px 0 6px;';
        label.textContent = group + ' (' + groups[group].length + ')';
        container.appendChild(label);

        for (var j = 0; j < groups[group].length; j++) {
            var art = groups[group][j];
            var card = document.createElement('div');
            card.className = 'article-card';

            var link = document.createElement('a');
            link.className = 'article-title';
            // Security: only allow http/https URLs — reject javascript:, data:, etc.
            var articleUrl = art.url || '#';
            if (articleUrl !== '#' && !/^https?:\/\//i.test(articleUrl)) articleUrl = '#';
            link.href = articleUrl;
            link.target = '_blank';
            link.rel = 'noopener';
            link.textContent = art.title || 'Untitled';
            card.appendChild(link);

            var meta = document.createElement('div');
            meta.className = 'article-meta';
            meta.textContent = [art.feed_title, art.category, art.published_at ? fmtRelativeTime(art.published_at) : ''].filter(Boolean).join(' | ');
            card.appendChild(meta);

            if (art.summary) {
                var summary = document.createElement('div');
                summary.className = 'article-summary';
                summary.textContent = (art.summary || '').substring(0, 200);
                card.appendChild(summary);
            }

            container.appendChild(card);
        }
    }
}

// ═══ ASK SPECIALIST ═══

var _specialistSlug = null;
var _specialistHistory = [];
var _specialistStreaming = false;

async function loadSpecialistTab() {
    var picker = document.getElementById('specialistPicker');
    if (!picker || picker.options.length > 1) return; // Already populated

    try {
        var resp = await bakerFetch('/api/capabilities');
        if (!resp.ok) return;
        var data = await resp.json();
        if (!data.capabilities) return;

        for (var i = 0; i < data.capabilities.length; i++) {
            var cap = data.capabilities[i];
            if (cap.capability_type === 'domain' && cap.active) {
                var opt = document.createElement('option');
                opt.value = cap.slug;
                opt.textContent = cap.name;
                picker.appendChild(opt);
            }
        }
    } catch (e) {
        console.error('loadSpecialistTab failed:', e);
    }
}

async function sendSpecialistMessage(question) {
    if (_specialistStreaming || !question.trim() || !_specialistSlug) return;
    _specialistStreaming = true;

    var sendBtn = document.getElementById('specialistSendBtn');
    var input = document.getElementById('specialistInput');
    if (sendBtn) sendBtn.disabled = true;
    if (input) { input.disabled = true; input.value = ''; }

    _specialistHistory.push({ role: 'user', content: question });
    appendSpecialistBubble('user', question);

    var replyId = 'specialist-reply-' + Date.now();
    appendSpecialistBubble('assistant', '', replyId);
    var replyEl = document.getElementById(replyId);
    if (replyEl) replyEl.innerHTML = '<div class="thinking"><span class="thinking-dots"><span></span><span></span><span></span></span> Baker is thinking...</div>';

    var fullResponse = '';
    try {
        var resp = await bakerFetch('/api/scan/specialist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question: question,
                capability_slug: _specialistSlug,
                history: _specialistHistory.slice(-30),
            }),
        });
        if (!resp.ok) throw new Error('Specialist API returned ' + resp.status);

        var reader = resp.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';

        while (true) {
            var chunk = await reader.read();
            if (chunk.done) break;
            buffer += decoder.decode(chunk.value, { stream: true });
            var lines = buffer.split('\n');
            buffer = lines.pop();
            for (var li = 0; li < lines.length; li++) {
                if (!lines[li].startsWith('data: ')) continue;
                var payload = lines[li].slice(6).trim();
                if (payload === '[DONE]') continue;
                try {
                    var data = JSON.parse(payload);
                    if (data.token) {
                        if (!fullResponse && replyEl) replyEl.textContent = '';
                        fullResponse += data.token;
                        if (replyEl) replyEl.innerHTML = '<div class="md-content">' + md(fullResponse) + '</div>';
                    }
                } catch (e) { /* skip */ }
            }
        }
    } catch (err) {
        fullResponse = 'Error: ' + err.message;
        if (replyEl) replyEl.textContent = fullResponse;
    }

    _specialistHistory.push({ role: 'assistant', content: fullResponse });
    if (_specialistHistory.length > 30) _specialistHistory = _specialistHistory.slice(-30);

    // Add copy button after response
    if (replyEl && fullResponse && !fullResponse.startsWith('Error:')) {
        var toolbar = document.createElement('div');
        toolbar.style.cssText = 'display:flex;gap:8px;margin-top:8px;';

        var copyBtn = document.createElement('button');
        copyBtn.textContent = 'Copy';
        copyBtn.style.cssText = 'font-size:11px;padding:3px 10px;border:1px solid var(--border);color:var(--text2);background:var(--bg1);border-radius:4px;cursor:pointer;';
        copyBtn.addEventListener('click', function() {
            navigator.clipboard.writeText(fullResponse).then(function() {
                copyBtn.textContent = 'Copied';
                setTimeout(function() { copyBtn.textContent = 'Copy'; }, 2000);
            });
        });
        toolbar.appendChild(copyBtn);

        var saveBtn = document.createElement('button');
        saveBtn.textContent = 'Save to Memory';
        saveBtn.style.cssText = 'font-size:11px;padding:3px 10px;border:1px solid var(--blue);color:var(--blue);background:transparent;border-radius:4px;cursor:pointer;';
        saveBtn.addEventListener('click', function() {
            bakerFetch('/api/artifacts/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    content: fullResponse,
                    title: 'Specialist: ' + (_specialistSlug || 'analysis'),
                    source: 'specialist_' + (_specialistSlug || 'unknown'),
                }),
            }).then(function(r) {
                if (r.ok) { saveBtn.textContent = 'Saved'; saveBtn.disabled = true; }
                else { saveBtn.textContent = 'Failed'; }
            });
        });
        toolbar.appendChild(saveBtn);

        replyEl.appendChild(toolbar);
    }

    _specialistStreaming = false;
    if (sendBtn) sendBtn.disabled = false;
    if (input) { input.disabled = false; input.focus(); }

    var container = document.getElementById('specialistMessages');
    if (container) container.scrollTop = container.scrollHeight;
}

function appendSpecialistBubble(role, content, id) {
    var container = document.getElementById('specialistMessages');
    if (!container) return;
    var div = document.createElement('div');
    div.className = 'scan-msg ' + (role === 'user' ? 'user' : 'baker');
    if (id) div.id = id;
    if (role === 'assistant' && !content) {
        div.innerHTML = '<div class="thinking"><span class="thinking-dots"><span></span><span></span><span></span></span> Specialist is thinking...</div>';
    } else if (role === 'assistant') {
        div.innerHTML = '<div class="md-content">' + md(content) + '</div>';
    } else {
        div.textContent = content;
    }
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return div;
}

// ═══ DEBOUNCE + COMMAND BAR DETECTION ═══

function debounce(fn, ms) {
    var timer;
    return function() {
        var args = arguments;
        var ctx = this;
        clearTimeout(timer);
        timer = setTimeout(function() { fn.apply(ctx, args); }, ms);
    };
}

function setupDetectionBadge() {
    var cmdInput = document.getElementById('cmdInput');
    var badge = document.getElementById('cmdDetectBadge');
    if (!cmdInput || !badge) return;

    var detect = debounce(async function() {
        var q = cmdInput.value.trim();
        if (q.length < 3) { badge.hidden = true; return; }
        try {
            var resp = await bakerFetch('/api/scan/detect?q=' + encodeURIComponent(q));
            if (!resp.ok) { badge.hidden = true; return; }
            var data = await resp.json();
            if (data.detected) {
                badge.textContent = data.capability_name + ' detected';
                badge.hidden = false;
            } else {
                badge.hidden = true;
            }
        } catch (e) { badge.hidden = true; }
    }, 300);

    cmdInput.addEventListener('input', detect);
    cmdInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') badge.hidden = true;
    });
}

// ═══ INIT ═══

async function init() {
    await loadConfig();

    // Greeting
    var hour = new Date().getHours();
    var greet = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
    var greetEl = document.getElementById('briefGreeting');
    if (greetEl) {
        var now = new Date();
        var dateStr = now.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
        var timeStr = now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
        greetEl.innerHTML = '<span>' + esc(greet + ', Dimitry') + '</span><span style="font-size:14px;color:var(--text3);font-weight:400;">' + esc(dateStr + ' \u00B7 ' + timeStr) + '</span>';
    }

    // Sidebar navigation (static items)
    document.querySelectorAll('.nav-item[data-tab]').forEach(function(item) {
        item.addEventListener('click', function() {
            // If clicking a matters sub-item, set the matter slug
            if (item.dataset.matter) {
                _currentMatterSlug = item.dataset.matter;
            }
            switchTab(item.dataset.tab);
        });
    });

    // Matters sub-list (delegated — items added dynamically by loadMattersSummary)
    var mattersSubList = document.getElementById('mattersSubList');
    if (mattersSubList) {
        mattersSubList.addEventListener('click', function(e) {
            var item = e.target.closest('.nav-item');
            if (item && item.dataset.matter) {
                _currentMatterSlug = item.dataset.matter;
                switchTab('matters');
            }
        });
    }

    // Scan form
    var scanForm = document.getElementById('scanForm');
    if (scanForm) {
        scanForm.addEventListener('submit', function(e) {
            e.preventDefault();
            var input = document.getElementById('scanInput');
            if (input && input.value.trim()) sendScanMessage(input.value.trim());
        });
    }

    // Command bar
    setupCommandBar();
    setupDetectionBadge();

    // Specialist form
    var specialistForm = document.getElementById('specialistForm');
    if (specialistForm) {
        specialistForm.addEventListener('submit', function(e) {
            e.preventDefault();
            var input = document.getElementById('specialistInput');
            if (input && input.value.trim()) sendSpecialistMessage(input.value.trim());
        });
    }
    var specialistPicker = document.getElementById('specialistPicker');
    if (specialistPicker) {
        specialistPicker.addEventListener('change', function() {
            _specialistSlug = specialistPicker.value || null;
            var input = document.getElementById('specialistInput');
            var sendBtn = document.getElementById('specialistSendBtn');
            if (input) input.disabled = !_specialistSlug;
            if (sendBtn) sendBtn.disabled = !_specialistSlug;
            // Clear messages on capability change
            _specialistHistory = [];
            var container = document.getElementById('specialistMessages');
            if (container) container.textContent = '';
            if (_specialistSlug && input) input.focus();
        });
    }

    // Load morning brief
    loadMorningBrief();
}

document.addEventListener('DOMContentLoaded', init);

// ═══ DASHBOARD-DATA-LAYER: COMMITMENTS + BROWSER TABS ═══

function _injectDataLayerCSS() {
    if (document.getElementById('data-layer-css')) return;
    var s = document.createElement('style');
    s.id = 'data-layer-css';
    s.textContent = [
        '.commitment-card{background:white;border:1px solid #e8e8e8;border-radius:8px;padding:12px 16px;margin-bottom:8px}',
        '.commitment-card.overdue{border-left:3px solid #f44336}',
        '.commitment-desc{font-size:14px;font-weight:500;margin-bottom:4px}',
        '.commitment-meta{font-size:12px;color:#888}',
        '.overdue-badge{background:#f44336;color:white;font-size:11px;padding:1px 6px;border-radius:3px;font-weight:600}',
        '.filter-tabs{display:flex;gap:4px;margin:12px 0}',
        '.filter-tab{border:1px solid #ddd;background:white;border-radius:4px;padding:4px 12px;font-size:13px;cursor:pointer}',
        '.filter-tab.active{background:#333;color:white;border-color:#333}',
        '.tab-header{display:flex;justify-content:flex-end;margin-bottom:8px}',
        '.tab-count{font-size:13px;color:#888}',
        '.empty-state{text-align:center;color:#aaa;padding:32px;font-size:14px}',
        '.browser-card{background:white;border:1px solid #e8e8e8;border-radius:8px;padding:12px 16px;margin-bottom:8px}',
        '.browser-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}',
        '.browser-name{font-size:14px;font-weight:600}',
        '.browser-meta{font-size:12px;color:#888;margin-top:2px}',
        '.browser-warn{color:#f44336}',
        '.browser-result{margin-top:8px;padding-top:8px;border-top:1px solid #f0f0f0}',
        '.result-label{font-size:11px;color:#888;text-transform:uppercase;margin-bottom:4px}',
        '.result-snippet{font-size:13px;color:#555;line-height:1.4}',
        '.run-btn{border:1px solid #2196f3;color:#2196f3;background:white;border-radius:4px;padding:4px 10px;font-size:12px;cursor:pointer}',
        '.run-btn:hover{background:#2196f3;color:white}',
        '.run-btn:disabled{opacity:0.5;cursor:not-allowed}',
    ].join('\n');
    document.head.appendChild(s);
}

// --- Commitments Tab ---

var _commitmentsFilter = 'active';

async function loadCommitmentsTab() {
    _injectDataLayerCSS();
    var container = document.getElementById('commitmentsContent');
    if (!container) return;
    container.textContent = 'Loading...';

    try {
        var url = '/api/commitments';
        if (_commitmentsFilter) url += '?status=' + _commitmentsFilter;
        var data = await bakerFetch(url).then(function(r) { return r.json(); });
        var items = data.commitments || [];
        var overdue = data.overdue_count || 0;
        var total = data.total || items.length;

        var wrapper = document.createElement('div');

        // Header
        var header = document.createElement('div');
        header.className = 'tab-header';
        var count = document.createElement('span');
        count.className = 'tab-count';
        count.textContent = overdue + ' overdue / ' + total + ' total';
        header.appendChild(count);
        wrapper.appendChild(header);

        // Filter tabs
        var filters = document.createElement('div');
        filters.className = 'filter-tabs';
        ['active', 'overdue', 'completed', ''].forEach(function(f) {
            var label = f || 'all';
            var btn = document.createElement('button');
            btn.className = _commitmentsFilter === f ? 'filter-tab active' : 'filter-tab';
            btn.textContent = label.charAt(0).toUpperCase() + label.slice(1);
            btn.addEventListener('click', function() { _commitmentsFilter = f; loadCommitmentsTab(); });
            filters.appendChild(btn);
        });
        wrapper.appendChild(filters);

        // Cards
        if (items.length === 0) {
            var empty = document.createElement('div');
            empty.className = 'empty-state';
            empty.textContent = 'No commitments with status "' + (_commitmentsFilter || 'all') + '"';
            wrapper.appendChild(empty);
        } else {
            items.forEach(function(c) {
                var isOverdue = c.status === 'overdue' || (c.due_date && new Date(c.due_date) < new Date() && c.status === 'active');
                var card = document.createElement('div');
                card.className = isOverdue ? 'commitment-card overdue' : 'commitment-card';

                var desc = document.createElement('div');
                desc.className = 'commitment-desc';
                if (isOverdue) {
                    var badge = document.createElement('span');
                    badge.className = 'overdue-badge';
                    badge.textContent = 'OVERDUE';
                    desc.appendChild(badge);
                    desc.appendChild(document.createTextNode(' '));
                }
                desc.appendChild(document.createTextNode(c.description || ''));
                card.appendChild(desc);

                var meta = document.createElement('div');
                meta.className = 'commitment-meta';
                var dueStr = c.due_date ? new Date(c.due_date).toLocaleDateString('en-GB', {month: 'short', day: 'numeric'}) : 'No date';
                var metaText = 'Due: ' + dueStr + ' \u00B7 Source: ' + (c.source || '?');
                if (c.assigned_to) metaText += ' \u00B7 Assigned: ' + c.assigned_to;
                meta.textContent = metaText;
                card.appendChild(meta);

                wrapper.appendChild(card);
            });
        }

        container.textContent = '';
        container.appendChild(wrapper);
    } catch (e) {
        container.textContent = 'Failed to load commitments.';
        console.warn('Commitments load failed:', e);
    }
}

// --- Browser Monitor Tab ---

function _timeAgo(date) {
    var seconds = Math.floor((new Date() - date) / 1000);
    if (seconds < 60) return seconds + 's ago';
    var minutes = Math.floor(seconds / 60);
    if (minutes < 60) return minutes + ' min ago';
    var hours = Math.floor(minutes / 60);
    if (hours < 24) return hours + 'h ago';
    return Math.floor(hours / 24) + 'd ago';
}

async function loadBrowserTab() {
    _injectDataLayerCSS();
    var container = document.getElementById('browserContent');
    if (!container) return;
    container.textContent = 'Loading...';

    try {
        var data = await bakerFetch('/api/browser/tasks').then(function(r) { return r.json(); });
        var tasks = data.tasks || [];

        var wrapper = document.createElement('div');

        var header = document.createElement('div');
        header.className = 'tab-header';
        var count = document.createElement('span');
        count.className = 'tab-count';
        count.textContent = tasks.length + ' tasks';
        header.appendChild(count);
        wrapper.appendChild(header);

        if (tasks.length === 0) {
            var empty = document.createElement('div');
            empty.className = 'empty-state';
            empty.textContent = 'No browser monitoring tasks configured';
            wrapper.appendChild(empty);
        } else {
            tasks.forEach(function(t) {
                var card = document.createElement('div');
                card.className = 'browser-card';

                var hdr = document.createElement('div');
                hdr.className = 'browser-header';
                var name = document.createElement('span');
                name.className = 'browser-name';
                name.textContent = t.name;
                var runBtn = document.createElement('button');
                runBtn.className = 'run-btn';
                runBtn.textContent = 'Run Now';
                runBtn.addEventListener('click', function() { _runBrowserTask(t.id, runBtn); });
                hdr.appendChild(name);
                hdr.appendChild(runBtn);
                card.appendChild(hdr);

                var meta1 = document.createElement('div');
                meta1.className = 'browser-meta';
                meta1.textContent = 'Mode: ' + t.mode + ' \u00B7 Category: ' + (t.category || '\u2014');
                card.appendChild(meta1);

                var lastPolled = t.last_polled ? _timeAgo(new Date(t.last_polled)) : 'never';
                var failures = t.consecutive_failures || 0;
                var meta2 = document.createElement('div');
                meta2.className = 'browser-meta' + (failures > 0 ? ' browser-warn' : '');
                meta2.textContent = 'Last polled: ' + lastPolled + ' \u00B7 ' + failures + ' failures';
                card.appendChild(meta2);

                if (t.latest_result) {
                    var snippet = (t.latest_result.content || '').substring(0, 200).replace(/\n/g, ' ');
                    var resultDiv = document.createElement('div');
                    resultDiv.className = 'browser-result';
                    var label = document.createElement('div');
                    label.className = 'result-label';
                    label.textContent = 'Latest result:';
                    var snipDiv = document.createElement('div');
                    snipDiv.className = 'result-snippet';
                    snipDiv.textContent = snippet;
                    resultDiv.appendChild(label);
                    resultDiv.appendChild(snipDiv);
                    card.appendChild(resultDiv);
                }

                wrapper.appendChild(card);
            });
        }

        container.textContent = '';
        container.appendChild(wrapper);
    } catch (e) {
        container.textContent = 'Failed to load browser tasks.';
        console.warn('Browser tab load failed:', e);
    }
}

async function _runBrowserTask(taskId, btn) {
    btn.disabled = true;
    btn.textContent = 'Running...';
    try {
        await bakerFetch('/api/browser/tasks/' + taskId + '/run', { method: 'POST' });
        btn.textContent = 'Done';
        setTimeout(function() { btn.textContent = 'Run Now'; btn.disabled = false; }, 5000);
    } catch (e) {
        btn.textContent = 'Failed';
        setTimeout(function() { btn.textContent = 'Run Now'; btn.disabled = false; }, 3000);
    }
}

// ═══ LEARNING-LOOP: FEEDBACK BUTTONS ═══

function renderFeedbackButtons(taskId, container) {
    var fb = document.createElement('div');
    fb.className = 'feedback-bar';
    fb.style.cssText = 'margin-top:12px;padding:8px 0;border-top:1px solid #eee;';
    var label = document.createElement('span');
    label.textContent = 'Was this helpful? ';
    label.style.cssText = 'font-size:13px;color:#888;margin-right:8px;';
    fb.appendChild(label);

    var btns = [
        { text: '\u2713', feedback: 'accepted', color: '#4caf50', title: 'Good' },
        { text: '\u270E', feedback: 'revised', color: '#ff9800', title: 'Needs revision' },
        { text: '\u2717', feedback: 'rejected', color: '#f44336', title: 'Wrong' },
    ];
    btns.forEach(function(b) {
        var btn = document.createElement('button');
        btn.textContent = b.text;
        btn.title = b.title;
        btn.style.cssText = 'border:1px solid #ddd;background:white;border-radius:4px;padding:4px 10px;cursor:pointer;font-size:14px;margin-right:4px;';
        btn.addEventListener('mouseenter', function() { btn.style.borderColor = b.color; btn.style.color = b.color; });
        btn.addEventListener('mouseleave', function() { btn.style.borderColor = '#ddd'; btn.style.color = ''; });
        btn.addEventListener('click', function() { submitFeedback(taskId, b.feedback, fb); });
        fb.appendChild(btn);
    });
    container.appendChild(fb);
}

async function submitFeedback(taskId, feedback, barEl) {
    var comment = null;
    if (feedback !== 'accepted') {
        comment = prompt('What should Baker do differently?');
        if (comment === null) return;
    }
    var body = { feedback: feedback };
    if (comment) body.comment = comment;

    try {
        await bakerFetch('/api/tasks/' + taskId + '/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        barEl.textContent = '';
        var done = document.createElement('span');
        done.textContent = 'Feedback recorded: ' + feedback;
        done.style.cssText = 'font-size:13px;color:#4caf50;';
        barEl.appendChild(done);
    } catch (e) {
        console.warn('Feedback submission failed:', e);
    }
}
