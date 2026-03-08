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
};

const FUNCTIONAL_TABS = new Set(['morning-brief', 'fires', 'matters', 'deadlines', 'people', 'tags', 'search', 'ask-baker', 'ask-specialist', 'travel', 'media']);

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
    } catch (e) {
        console.error('loadMorningBrief failed:', e);
    }
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
                const dotClass = tierClass(m.worst_tier);

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
    container.textContent = 'Loading fires...';

    try {
        const resp = await bakerFetch('/api/alerts?tier=1');
        if (!resp.ok) return;
        const data = await resp.json();

        if (!data.alerts || data.alerts.length === 0) {
            container.textContent = 'No active fires. All clear.';
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

async function loadPeopleTab() {
    var container = document.getElementById('peopleContent');
    if (!container) return;
    container.textContent = 'Loading people...';
    try {
        var resp = await bakerFetch('/api/people');
        if (!resp.ok) return;
        var data = await resp.json();
        if (!data.people || data.people.length === 0) {
            container.textContent = 'No contacts found.';
            return;
        }
        container.textContent = '';
        for (var i = 0; i < data.people.length; i++) {
            var p = data.people[i];
            var card = document.createElement('div');
            card.className = 'card card-compact person-card';
            card.style.cursor = 'pointer';
            card.dataset.personName = p.name || '';
            card.addEventListener('click', function() { loadPersonDetail(this.dataset.personName); });
            var hdr = document.createElement('div');
            hdr.className = 'card-header';
            if (p.is_vip) {
                var vip = document.createElement('span');
                vip.className = 'vip-badge';
                vip.textContent = 'VIP';
                hdr.appendChild(vip);
            }
            if (p.tier) {
                var dot = document.createElement('span');
                dot.className = 'nav-dot ' + tierClass(p.tier);
                dot.style.marginTop = '5px';
                hdr.appendChild(dot);
            }
            var nm = document.createElement('span');
            nm.className = 'card-title';
            nm.textContent = p.name || '';
            hdr.appendChild(nm);
            var role = document.createElement('span');
            role.className = 'card-time';
            role.textContent = [p.role, p.company].filter(Boolean).join(' — ');
            hdr.appendChild(role);
            card.appendChild(hdr);
            container.appendChild(card);
        }
    } catch (e) {
        container.textContent = 'Failed to load people.';
    }
}

async function loadPersonDetail(name) {
    var container = document.getElementById('peopleContent');
    if (!container) return;
    container.textContent = 'Loading...';
    try {
        var resp = await bakerFetch('/api/people/' + encodeURIComponent(name) + '/activity');
        if (!resp.ok) return;
        var data = await resp.json();
        container.textContent = '';

        var back = document.createElement('button');
        back.className = 'footer-btn';
        back.textContent = 'Back to all people';
        back.style.marginBottom = '12px';
        back.addEventListener('click', function() { loadPeopleTab(); });
        container.appendChild(back);

        var header = document.createElement('div');
        header.className = 'section-label';
        header.textContent = name;
        container.appendChild(header);

        // Related matters
        if (data.matters && data.matters.length > 0) {
            var mattersDiv = document.createElement('div');
            mattersDiv.style.cssText = 'padding:0 0 10px;';
            for (var mi = 0; mi < data.matters.length; mi++) {
                var badge = document.createElement('span');
                badge.className = 'tag-badge';
                badge.textContent = data.matters[mi];
                mattersDiv.appendChild(badge);
            }
            container.appendChild(mattersDiv);
        }

        // Activity feed
        if (!data.activity || data.activity.length === 0) {
            var empty = document.createElement('div');
            empty.textContent = 'No recent activity found.';
            empty.style.cssText = 'color:var(--text3);font-size:12px;';
            container.appendChild(empty);
            return;
        }
        for (var ai = 0; ai < data.activity.length; ai++) {
            var item = data.activity[ai];
            var row = document.createElement('div');
            row.className = 'activity-row';
            var typeBadge = document.createElement('span');
            typeBadge.className = 'activity-type ' + (item.type || '');
            typeBadge.textContent = (item.type || '').charAt(0).toUpperCase() + (item.type || '').slice(1);
            row.appendChild(typeBadge);
            var info = document.createElement('div');
            var titleEl = document.createElement('div');
            titleEl.className = 'activity-text';
            titleEl.textContent = item.title || '';
            info.appendChild(titleEl);
            if (item.preview) {
                var prevEl = document.createElement('div');
                prevEl.style.cssText = 'font-size:11px;color:var(--text3);margin-top:2px;';
                prevEl.textContent = item.preview;
                info.appendChild(prevEl);
            }
            var dateEl = document.createElement('div');
            dateEl.className = 'activity-time';
            dateEl.textContent = item.date ? fmtRelativeTime(item.date) : '';
            info.appendChild(dateEl);
            row.appendChild(info);
            container.appendChild(row);
        }
    } catch (e) {
        container.textContent = 'Failed to load person details.';
    }
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
    container.textContent = 'Loading deadlines...';

    try {
        var resp = await bakerFetch('/api/deadlines');
        if (!resp.ok) return;
        var data = await resp.json();

        if (!data.deadlines || data.deadlines.length === 0) {
            container.textContent = 'No active deadlines.';
            container.style.cssText = 'color:var(--text3);font-size:13px;';
            return;
        }

        container.textContent = '';
        var header = document.createElement('div');
        header.className = 'section-label';
        header.textContent = 'Active deadlines (' + data.deadlines.length + ')';
        container.appendChild(header);

        // Group by urgency: overdue/today, this week, later
        var overdue = [], thisWeek = [], later = [];
        for (var i = 0; i < data.deadlines.length; i++) {
            var dl = data.deadlines[i];
            var daysText = fmtDeadlineDays(dl.due_date);
            if (daysText.includes('overdue') || daysText === 'Today') overdue.push(dl);
            else if (daysText === 'Tomorrow' || parseInt(daysText) <= 7) thisWeek.push(dl);
            else later.push(dl);
        }

        function renderGroup(label, items) {
            if (items.length === 0) return;
            var groupLabel = document.createElement('div');
            groupLabel.style.cssText = 'font-family:var(--mono);font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.6px;color:var(--text3);margin:12px 0 6px;';
            groupLabel.textContent = label;
            container.appendChild(groupLabel);
            var groupDiv = document.createElement('div');
            setSafeHTML(groupDiv, items.map(renderDeadlineCompact).join(''));
            container.appendChild(groupDiv);
        }

        renderGroup('Overdue / Today', overdue);
        renderGroup('This week', thisWeek);
        renderGroup('Later', later);

    } catch (e) {
        container.textContent = 'Failed to load deadlines.';
        container.style.color = 'var(--red)';
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

    var fullResponse = '';
    try {
        var resp = await bakerFetch('/api/scan/specialist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question: question,
                capability_slug: _specialistSlug,
                history: _specialistHistory.slice(-10),
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
    if (_specialistHistory.length > 20) _specialistHistory = _specialistHistory.slice(-20);

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
    setText('briefGreeting', greet + ', Dimitry');

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
