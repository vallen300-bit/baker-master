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
    'ask-baker': 'viewAskBaker',
};

const FUNCTIONAL_TABS = new Set(['morning-brief', 'fires', 'matters', 'deadlines', 'ask-baker']);

function switchTab(tabName) {
    document.querySelectorAll('.nav-item[data-tab]').forEach(item => {
        item.classList.toggle('active', item.dataset.tab === tabName);
    });

    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));

    if (FUNCTIONAL_TABS.has(tabName)) {
        const viewId = TAB_VIEW_MAP[tabName];
        if (viewId) {
            const el = document.getElementById(viewId);
            if (el) el.classList.add('active');
        }
    } else {
        const cs = document.getElementById('viewComingSoon');
        if (cs) cs.classList.add('active');
        const labels = {
            'people': 'People', 'tags': 'Tags', 'search': 'Search',
            'ask-specialist': 'Ask Specialist', 'travel': 'Travel', 'media': 'Media'
        };
        setText('comingSoonTitle', (labels[tabName] || tabName) + ' -- Coming soon');
    }

    currentTab = tabName;

    if (tabName === 'morning-brief') loadMorningBrief();
    else if (tabName === 'fires') loadFires();
    else if (tabName === 'matters') loadMattersTab();
    else if (tabName === 'deadlines') loadDeadlinesTab();
    else if (tabName === 'ask-baker') focusScanInput();
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

    var html = '<div class="card' + newClass + borderClass + '" data-alert-id="' + aid + '">';

    // Header
    html += '<div class="card-header">';
    html += '<span class="tier-badge t' + tier + '">' + esc(tierLabel) + '</span>';
    html += '<span class="card-title">' + esc(alert.title) + '</span>';
    if (isNew) html += '<span class="card-new-badge">new</span>';
    html += '<span class="card-time">' + esc(fmtRelativeTime(alert.created_at)) + '</span>';
    html += '</div>';

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
            '<button class="footer-btn" onclick="emailResult(this)">Email</button>';
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

// ═══ MATTERS DETAIL VIEW ═══

async function loadMatterDetail(matterSlug) {
    var container = document.getElementById('mattersContent');
    if (!container) return;
    container.textContent = 'Loading...';

    try {
        var resp = await bakerFetch('/api/matters/' + encodeURIComponent(matterSlug) + '/items');
        if (!resp.ok) return;
        var data = await resp.json();

        if (!data.items || data.items.length === 0) {
            container.textContent = 'No items for this matter.';
            container.style.cssText = 'color:var(--text3);font-size:13px;';
            return;
        }

        var label = matterSlug === '_ungrouped' ? 'Ungrouped' : matterSlug.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });

        container.textContent = '';
        var header = document.createElement('div');
        header.className = 'section-label';
        header.textContent = label + ' (' + data.items.length + ' items)';
        container.appendChild(header);

        var cardsDiv = document.createElement('div');
        var cardsHtml = data.items.map(function(a) {
            var expanded = (a.tier || 3) <= 2;
            return renderAlertCard(a, expanded);
        }).join('');
        setSafeHTML(cardsDiv, cardsHtml);
        container.appendChild(cardsDiv);
    } catch (e) {
        container.textContent = 'Failed to load matter.';
        container.style.color = 'var(--red)';
    }
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
                        if (replyEl) replyEl.innerHTML = '<div class="md-content">' + md(fullResponse) + '</div>'; // SECURITY: md() escapes first
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

// ═══ INIT ═══

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

    // Load morning brief
    loadMorningBrief();
}

document.addEventListener('DOMContentLoaded', init);
