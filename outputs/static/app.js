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
    var headers = { ...(options.headers || {}), 'X-Baker-Key': BAKER_CONFIG.apiKey };
    var timeoutMs = options.timeout || 30000;
    var controller = new AbortController();
    var timer = setTimeout(function() { controller.abort(); }, timeoutMs);
    try {
        return await fetch(url, { ...options, headers: headers, signal: controller.signal });
    } finally {
        clearTimeout(timer);
    }
}

// ═══ STATE ═══
let currentTab = 'morning-brief';
var _scanHistories = {};   // keyed by context: 'global', 'matter:oskolkov-rg7', etc.
var _scanCurrentContext = 'global';
let scanStreaming = false;

// ═══ ARTIFACT PANEL ═══
var _toolLabels = {
    search_emails: ['Emails', '\u2709\uFE0F'],
    search_meetings: ['Meetings', '\uD83D\uDCCB'],
    search_memory: ['Memory', '\uD83E\uDDE0'],
    search_whatsapp: ['WhatsApp', '\uD83D\uDCAC'],
    search_contacts: ['Contacts', '\uD83D\uDC64'],
    search_deadlines: ['Deadlines', '\u23F0'],
    search_clickup: ['ClickUp', '\u2705'],
    search_deals: ['Deals', '\uD83D\uDCBC'],
    search_matters: ['Matters', '\uD83D\uDCC1'],
    web_search: ['Web', '\uD83C\uDF10'],
    read_document: ['Documents', '\uD83D\uDCC4'],
    search_documents: ['Documents', '\uD83D\uDCC4'],
};
var _capLabels = {
    sales: 'Sales', finance: 'Finance', legal: 'Legal',
    asset_management: 'Asset Management', it: 'IT',
    profiling: 'Profiling', research: 'Research',
    communications: 'Communications', pr_branding: 'PR & Branding',
    marketing: 'Marketing', ai_dev: 'AI Dev',
};

function _artifactPanel(panelId) {
    return document.getElementById(panelId);
}

function _artifactItems(itemsId) {
    return document.getElementById(itemsId);
}

function clearArtifactPanel(panelId, itemsId) {
    var panel = _artifactPanel(panelId);
    var items = _artifactItems(itemsId);
    if (items) items.textContent = '';
    if (panel) panel.classList.remove('open');
}

function openArtifactPanel(panelId) {
    var panel = _artifactPanel(panelId);
    if (panel && !panel.classList.contains('open')) {
        panel.classList.add('open');
    }
}

function addArtifactCapability(itemsId, panelId, slugs) {
    var items = _artifactItems(itemsId);
    if (!items) return;
    openArtifactPanel(panelId);

    var section = document.createElement('div');
    var label = document.createElement('div');
    label.className = 'artifact-section-label';
    label.textContent = 'Capability';
    section.appendChild(label);

    for (var i = 0; i < slugs.length; i++) {
        var badge = document.createElement('span');
        badge.className = 'artifact-capability';
        badge.id = 'artifact-cap-' + slugs[i];
        var dot = document.createElement('span');
        dot.className = 'artifact-cap-dot';
        badge.appendChild(dot);
        badge.appendChild(document.createTextNode(_capLabels[slugs[i]] || slugs[i]));
        section.appendChild(badge);
    }
    items.appendChild(section);

    // Add sources section (populated by tool calls)
    var srcSection = document.createElement('div');
    srcSection.id = itemsId + '-sources';
    var srcLabel = document.createElement('div');
    srcLabel.className = 'artifact-section-label';
    srcLabel.textContent = 'Sources searched';
    srcSection.appendChild(srcLabel);
    items.appendChild(srcSection);
}

function addArtifactSource(itemsId, panelId, toolName) {
    var srcSection = document.getElementById(itemsId + '-sources');
    if (!srcSection) {
        // No capability was set — create sources section directly
        var items = _artifactItems(itemsId);
        if (!items) return;
        openArtifactPanel(panelId);
        srcSection = document.createElement('div');
        srcSection.id = itemsId + '-sources';
        var srcLabel = document.createElement('div');
        srcLabel.className = 'artifact-section-label';
        srcLabel.textContent = 'Sources searched';
        srcSection.appendChild(srcLabel);
        items.appendChild(srcSection);
    }

    // Avoid duplicate source entries
    if (document.getElementById('artifact-src-' + toolName)) return;

    openArtifactPanel(panelId);
    var info = _toolLabels[toolName];
    if (!info) return; // unknown tool — skip

    var row = document.createElement('div');
    row.className = 'artifact-source';
    row.id = 'artifact-src-' + toolName;

    var icon = document.createElement('span');
    icon.className = 'artifact-source-icon';
    icon.textContent = info[1];
    row.appendChild(icon);

    var lbl = document.createElement('span');
    lbl.className = 'artifact-source-label';
    lbl.textContent = info[0];
    row.appendChild(lbl);

    var check = document.createElement('span');
    check.className = 'artifact-source-check';
    check.textContent = '\u2713';
    row.appendChild(check);

    srcSection.appendChild(row);
}

function addArtifactDownload(itemsId, panelId, genData) {
    var items = _artifactItems(itemsId);
    if (!items) return;
    openArtifactPanel(panelId);

    // Add downloads section if not present
    var dlSection = document.getElementById(itemsId + '-downloads');
    if (!dlSection) {
        dlSection = document.createElement('div');
        dlSection.id = itemsId + '-downloads';
        var dlLabel = document.createElement('div');
        dlLabel.className = 'artifact-section-label';
        dlLabel.textContent = 'Generated files';
        dlSection.appendChild(dlLabel);
        items.appendChild(dlSection);
    }

    var ext = genData.filename.split('.').pop();
    var sizeKB = (genData.size_bytes / 1024).toFixed(1);
    var fmtLabels = { docx: 'Word', xlsx: 'Excel', pdf: 'PDF', pptx: 'PowerPoint' };
    var fmtIcons = { docx: '\uD83D\uDCC3', xlsx: '\uD83D\uDCCA', pdf: '\uD83D\uDCC4', pptx: '\uD83D\uDCCA' };

    var link = document.createElement('a');
    link.className = 'artifact-download';
    link.href = genData.download_url;
    link.download = genData.filename;

    var ic = document.createElement('span');
    ic.className = 'artifact-download-icon';
    ic.textContent = fmtIcons[ext] || '\uD83D\uDCC4';
    link.appendChild(ic);

    var info = document.createElement('div');
    info.className = 'artifact-download-info';
    var name = document.createElement('div');
    name.className = 'artifact-download-name';
    name.textContent = genData.filename;
    info.appendChild(name);
    var meta = document.createElement('div');
    meta.className = 'artifact-download-meta';
    meta.textContent = (fmtLabels[ext] || ext.toUpperCase()) + ' \u00B7 ' + sizeKB + ' KB';
    info.appendChild(meta);
    link.appendChild(info);

    dlSection.appendChild(link);
}

function finalizeArtifactPanel(itemsId, startTime) {
    // Stop capability dot animation
    var items = _artifactItems(itemsId);
    if (!items) return;
    var caps = items.querySelectorAll('.artifact-capability');
    for (var i = 0; i < caps.length; i++) caps[i].classList.add('done');

    // Add timing metadata
    if (startTime) {
        var elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
        var metaDiv = document.createElement('div');
        metaDiv.className = 'artifact-meta';
        metaDiv.textContent = elapsed + 's';
        items.appendChild(metaDiv);
    }
}

function getScanHistory() {
    if (!_scanHistories[_scanCurrentContext]) _scanHistories[_scanCurrentContext] = [];
    return _scanHistories[_scanCurrentContext];
}

function openMatterScan(matterSlug) {
    if (matterSlug) {
        _scanCurrentContext = 'matter:' + matterSlug;
    } else {
        _scanCurrentContext = 'global';
    }
    renderScanHistory();
    switchTab('ask-baker');
    var input = document.getElementById('scanInput');
    if (input && matterSlug) {
        input.placeholder = 'Ask about ' + matterSlug.replace(/[-_]/g, ' ') + '...';
    } else if (input) {
        input.placeholder = 'Ask Baker...';
    }
}

function renderScanHistory() {
    var container = document.getElementById('scanMessages');
    if (!container) return;
    container.textContent = '';
    var history = getScanHistory();
    // Render oldest first — prepend puts each on top, so oldest ends at bottom
    for (var i = history.length - 1; i >= 0; i--) {
        appendScanBubble(history[i].role, history[i].content);
    }
    // Update context badge
    updateScanContextBadge();
}

function updateScanContextBadge() {
    var header = document.querySelector('.scan-view-header');
    if (!header) return;
    var existing = document.getElementById('scanContextBadge');
    if (existing) existing.remove();
    if (_scanCurrentContext === 'global') return;
    var slug = _scanCurrentContext.replace('matter:', '');
    var label = slug.replace(/[-_]/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
    var badge = document.createElement('span');
    badge.id = 'scanContextBadge';
    badge.style.cssText = 'display:inline-flex;align-items:center;gap:6px;margin-left:12px;padding:3px 10px;background:var(--blue);color:#fff;border-radius:12px;font-size:11px;font-weight:600;font-family:var(--mono);letter-spacing:0.3px;cursor:default;';
    badge.textContent = label;
    var closeBtn = document.createElement('span');
    closeBtn.textContent = '\u00D7';
    closeBtn.style.cssText = 'cursor:pointer;font-size:14px;line-height:1;opacity:0.8;';
    closeBtn.addEventListener('click', function() {
        _scanCurrentContext = 'global';
        renderScanHistory();
        var input = document.getElementById('scanInput');
        if (input) input.placeholder = 'Ask Baker...';
    });
    badge.appendChild(closeBtn);
    header.appendChild(badge);
}

// ═══ HELPERS ═══

/** Show animated thinking dots inside a container element. */
function showLoading(el, label) {
    el.innerHTML = '<div class="thinking"><span class="thinking-dots">' +
        '<span></span><span></span><span></span></span> ' +
        esc(label || 'Loading') + '...</div>';
}

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
    // SPECIALIST-THINKING-1: Render citation badges [Source: label]
    h = h.replace(/\[Source: ([^\]]+)\]/g, '<span class="citation" title="$1">$1</span>');
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
    'documents': 'viewDocuments',
    'dossiers': 'viewDossiers',
    'browser': 'viewBrowser',
    'baker-data': 'viewBakerData',
};

const FUNCTIONAL_TABS = new Set(['morning-brief', 'fires', 'matters', 'deadlines', 'people', 'tags', 'search', 'ask-baker', 'ask-specialist', 'travel', 'media', 'documents', 'dossiers', 'browser', 'baker-data']);

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

    // Show/hide back button (hidden on Dashboard)
    var backBtn = document.getElementById('cmdBack');
    if (backBtn) backBtn.hidden = (tabName === 'morning-brief');

    if (tabName === 'morning-brief') loadMorningBrief();
    else if (tabName === 'fires') loadFires();
    else if (tabName === 'matters') loadMattersTab();
    else if (tabName === 'deadlines') loadDeadlinesTab();
    else if (tabName === 'people') loadPeopleTab();
    else if (tabName === 'tags') loadTagsTab();
    else if (tabName === 'search') loadSearchTab();
    else if (tabName === 'ask-baker') { updateScanContextBadge(); focusScanInput(); }
    else if (tabName === 'ask-specialist') loadSpecialistTab();
    else if (tabName === 'travel') loadTravelTab();
    else if (tabName === 'media') loadMediaTab();
    else if (tabName === 'documents') loadDocumentsTab();
    else if (tabName === 'dossiers') loadDossiersTab();
    else if (tabName === 'browser') loadBrowserTab();
    else if (tabName === 'baker-data') loadBakerData();
}

// ═══ WEEKLY PRIORITIES WIDGET ═══

function _renderPrioritiesWidget(priorities) {
    var widget = document.getElementById('prioritiesWidget');
    var list = document.getElementById('prioritiesList');
    if (!widget || !list) return;

    // Always show the widget (empty state has "No priorities set" + add button)
    widget.hidden = false;
    list.textContent = '';

    if (!priorities || priorities.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'priorities-empty';
        empty.textContent = 'No priorities set this week. Click + to add.';
        list.appendChild(empty);
        return;
    }

    priorities.forEach(function(p) {
        var item = document.createElement('div');
        item.className = 'priority-item';
        item.dataset.id = p.id;

        var rank = document.createElement('span');
        rank.className = 'priority-rank';
        rank.textContent = p.rank + '.';
        item.appendChild(rank);

        var text = document.createElement('span');
        text.className = 'priority-text';
        text.textContent = p.priority_text;
        item.appendChild(text);

        if (p.matter_slug) {
            var matter = document.createElement('span');
            matter.className = 'priority-matter';
            matter.textContent = p.matter_slug;
            item.appendChild(matter);
        }

        var doneBtn = document.createElement('button');
        doneBtn.className = 'priority-done-btn';
        doneBtn.title = 'Mark completed';
        doneBtn.textContent = '\u2713';
        doneBtn.addEventListener('click', function() { _completePriority(p.id, item); });
        item.appendChild(doneBtn);

        list.appendChild(item);
    });
}

function _completePriority(id, itemEl) {
    bakerFetch('/api/priorities/' + id, { method: 'DELETE' }).then(function(resp) {
        if (resp.ok) {
            itemEl.style.opacity = '0.4';
            itemEl.style.textDecoration = 'line-through';
            setTimeout(function() { itemEl.remove(); }, 600);
        }
    });
}

(function _initPrioritiesForm() {
    document.addEventListener('DOMContentLoaded', function() {
        var addBtn = document.getElementById('prioritiesAddBtn');
        var form = document.getElementById('prioritiesForm');
        var input = document.getElementById('priorityInput');
        var matterInput = document.getElementById('priorityMatterInput');
        var saveBtn = document.getElementById('prioritySaveBtn');
        var cancelBtn = document.getElementById('priorityCancelBtn');

        if (!addBtn || !form) return;

        addBtn.addEventListener('click', function() {
            form.hidden = !form.hidden;
            if (!form.hidden && input) input.focus();
        });

        if (cancelBtn) cancelBtn.addEventListener('click', function() {
            form.hidden = true;
            if (input) input.value = '';
            if (matterInput) matterInput.value = '';
        });

        if (saveBtn) saveBtn.addEventListener('click', _savePriority);
        if (input) input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') _savePriority();
        });

        function _savePriority() {
            var text = (input ? input.value.trim() : '');
            if (!text) return;
            var matter = matterInput ? matterInput.value.trim() : '';

            saveBtn.disabled = true;
            saveBtn.textContent = '...';

            // Fetch current priorities, append new one, re-set all
            bakerFetch('/api/priorities').then(function(r) { return r.json(); }).then(function(d) {
                var existing = (d.priorities || []).map(function(p) {
                    return { text: p.priority_text, matter: p.matter_slug };
                });
                existing.push({ text: text, matter: matter || null });

                return bakerFetch('/api/priorities', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ priorities: existing }),
                });
            }).then(function(resp) {
                if (resp.ok) {
                    form.hidden = true;
                    if (input) input.value = '';
                    if (matterInput) matterInput.value = '';
                    // Reload the widget
                    return resp.json().then(function(d) {
                        _renderPrioritiesWidget(d.priorities || []);
                    });
                }
            }).catch(function(err) {
                console.error('Save priority failed:', err);
            }).finally(function() {
                saveBtn.disabled = false;
                saveBtn.textContent = 'Save';
            });
        }
    });
})();


// ═══ PROPOSED ACTIONS WIDGET ═══

var _sourceColors = {
    email: '#0a6fdb', whatsapp: '#25d366', meeting: '#8b5cf6',
    calendar: '#f59e0b', deadline: '#ef4444', cadence: '#06b6d4'
};

function _renderActionsWidget(actions, researchProposals) {
    var widget = document.getElementById('actionsWidget');
    var list = document.getElementById('desktopActionsList');
    var countEl = document.getElementById('desktopActionCount');
    if (!widget || !list) return;

    var proposals = researchProposals || [];
    var totalCount = (actions ? actions.length : 0) + proposals.length;

    if (totalCount === 0) {
        widget.hidden = true;
        return;
    }

    widget.hidden = false;
    list.textContent = '';
    if (countEl) countEl.textContent = totalCount;

    // Research proposals first
    proposals.forEach(function(proposal) {
        var card = document.createElement('div');
        card.className = 'action-card';
        card.style.borderLeftColor = '#8b5cf6';

        var header = document.createElement('div');
        header.className = 'action-card-header';
        var badge = document.createElement('span');
        badge.className = 'action-source-badge';
        badge.style.background = '#8b5cf6';
        badge.textContent = 'RESEARCH';
        header.appendChild(badge);
        var typeLabel = document.createElement('span');
        typeLabel.className = 'action-due';
        typeLabel.textContent = (proposal.subject_type || 'person').replace(/_/g, ' ');
        header.appendChild(typeLabel);
        card.appendChild(header);

        var title = document.createElement('div');
        title.className = 'action-card-title';
        title.textContent = 'Run dossier: ' + (proposal.subject_name || 'Unknown');
        card.appendChild(title);

        if (proposal.context) {
            var desc = document.createElement('div');
            desc.className = 'action-card-desc';
            desc.textContent = proposal.context;
            card.appendChild(desc);
        }

        var specialists = proposal.specialists || [];
        if (typeof specialists === 'string') { try { specialists = JSON.parse(specialists); } catch(e) { specialists = []; } }
        if (specialists.length > 0) {
            var specNames = { research: 'Research', legal: 'Legal', profiling: 'People Intel', pr_branding: 'PR & Branding' };
            var suggest = document.createElement('div');
            suggest.className = 'action-card-suggest';
            suggest.textContent = 'Specialists: ' + specialists.map(function(s) { return specNames[s] || s; }).join(', ');
            card.appendChild(suggest);
        }

        var btns = document.createElement('div');
        btns.className = 'action-card-btns';
        var runBtn = document.createElement('button');
        runBtn.className = 'action-btn approve';
        runBtn.textContent = 'Run Dossier';
        runBtn.addEventListener('click', function() { _respondDesktopResearch(proposal.id, 'approved', card); });
        btns.appendChild(runBtn);
        var skipBtn = document.createElement('button');
        skipBtn.className = 'action-btn skip';
        skipBtn.textContent = 'Skip';
        skipBtn.addEventListener('click', function() { _respondDesktopResearch(proposal.id, 'skipped', card); });
        btns.appendChild(skipBtn);
        card.appendChild(btns);

        list.appendChild(card);
    });

    actions.forEach(function(action) {
        var card = document.createElement('div');
        card.className = 'action-card';
        var prio = action.priority_rank || 2;
        if (prio === 1) card.classList.add('urgent');

        var srcColor = _sourceColors[action.source_type] || '#888';
        card.style.borderLeftColor = srcColor;

        // Header: source badge + due date
        var header = document.createElement('div');
        header.className = 'action-card-header';

        var badge = document.createElement('span');
        badge.className = 'action-source-badge';
        badge.style.background = srcColor;
        badge.textContent = (action.source_type || 'task').replace(/_/g, ' ');
        header.appendChild(badge);

        if (action.due_date) {
            var due = document.createElement('span');
            due.className = 'action-due';
            var dueDate = new Date(action.due_date + 'T00:00:00');
            var today = new Date(); today.setHours(0,0,0,0);
            if (dueDate < today) due.classList.add('overdue');
            due.textContent = action.due_date;
            header.appendChild(due);
        }

        card.appendChild(header);

        // Title
        var title = document.createElement('div');
        title.className = 'action-card-title';
        title.textContent = action.title || '';
        card.appendChild(title);

        // Description (truncated)
        if (action.description) {
            var desc = document.createElement('div');
            desc.className = 'action-card-desc';
            desc.textContent = action.description.length > 120
                ? action.description.substring(0, 120) + '...'
                : action.description;
            card.appendChild(desc);
        }

        // Suggested action
        if (action.suggested_action) {
            var suggest = document.createElement('div');
            suggest.className = 'action-card-suggest';
            suggest.textContent = action.suggested_action;
            card.appendChild(suggest);
        }

        // Buttons
        var btns = document.createElement('div');
        btns.className = 'action-card-btns';

        var approveBtn = document.createElement('button');
        approveBtn.className = 'action-btn approve';
        approveBtn.textContent = 'Approve';
        approveBtn.addEventListener('click', function() { _respondDesktopAction(action.id, 'approved', card); });
        btns.appendChild(approveBtn);

        var doneBtn = document.createElement('button');
        doneBtn.className = 'action-btn done';
        doneBtn.textContent = 'Done';
        doneBtn.addEventListener('click', function() { _respondDesktopAction(action.id, 'done', card); });
        btns.appendChild(doneBtn);

        var skipBtn = document.createElement('button');
        skipBtn.className = 'action-btn skip';
        skipBtn.textContent = 'Skip';
        skipBtn.addEventListener('click', function() { _respondDesktopAction(action.id, 'dismissed', card); });
        btns.appendChild(skipBtn);

        card.appendChild(btns);
        list.appendChild(card);
    });
}

function _respondDesktopResearch(proposalId, response, cardEl) {
    if (response === 'approved' && cardEl) {
        // Show running state with spinner
        var btns = cardEl.querySelector('.action-card-btns');
        if (btns) {
            btns.textContent = '';
            var spinner = document.createElement('div');
            spinner.className = 'dossier-progress';
            var spinEl = document.createElement('span');
            spinEl.className = 'dossier-spinner';
            spinner.appendChild(spinEl);
            var textSpan = document.createElement('span');
            textSpan.className = 'dossier-progress-text';
            textSpan.textContent = ' Running specialists...';
            spinner.appendChild(textSpan);
            btns.appendChild(spinner);
        }
        cardEl.style.opacity = '0.85';
        cardEl.style.pointerEvents = 'none';
        cardEl.classList.add('running');
    } else if (cardEl) {
        cardEl.style.opacity = '0.4';
        cardEl.style.pointerEvents = 'none';
    }

    bakerFetch('/api/research-proposals/' + proposalId + '/respond', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ response: response }),
    }).then(function(r) {
        if (!r.ok) throw new Error('API ' + r.status);
        if (response === 'approved') {
            _pollDossierStatus(proposalId, cardEl);
        } else if (cardEl) {
            cardEl.style.transition = 'opacity 0.3s, max-height 0.3s';
            cardEl.style.opacity = '0';
            cardEl.style.maxHeight = '0';
            cardEl.style.overflow = 'hidden';
            cardEl.style.margin = '0';
            cardEl.style.padding = '0';
            setTimeout(function() { cardEl.remove(); }, 300);
        }
    }).catch(function(e) {
        console.error('Research respond failed:', e);
        if (cardEl) { cardEl.style.opacity = '1'; cardEl.style.pointerEvents = ''; }
    });
}

function _pollDossierStatus(proposalId, cardEl) {
    var pollCount = 0;
    var maxPolls = 60;
    var labels = ['Running specialists...', 'Analyzing...', 'Combining results...', 'Generating document...'];

    var interval = setInterval(function() {
        pollCount++;
        var textEl = cardEl ? cardEl.querySelector('.dossier-progress-text') : null;
        if (textEl) {
            var labelIdx = Math.min(Math.floor(pollCount / 5), labels.length - 1);
            textEl.textContent = ' ' + labels[labelIdx];
        }
        if (pollCount >= maxPolls) {
            clearInterval(interval);
            if (textEl) textEl.textContent = ' Taking longer than expected — check back shortly.';
            return;
        }
        bakerFetch('/api/research-proposals/' + proposalId + '/status').then(function(r) {
            if (!r.ok) return;
            return r.json();
        }).then(function(data) {
            if (!data) return;
            if (data.status === 'completed') {
                clearInterval(interval);
                _showDossierComplete(proposalId, data.subject_name, cardEl);
            } else if (data.status === 'failed') {
                clearInterval(interval);
                _showDossierFailed(data.error_message || 'Dossier generation failed', cardEl);
            }
        }).catch(function() {});
    }, 5000);
}

function _showDossierFailed(errorMsg, cardEl) {
    if (!cardEl) return;
    cardEl.style.opacity = '1';
    cardEl.classList.remove('running');
    cardEl.style.borderLeftColor = 'var(--red)';
    var btns = cardEl.querySelector('.action-card-btns');
    if (btns) {
        btns.textContent = '';
        var errDiv = document.createElement('div');
        errDiv.style.cssText = 'font-size:11px;color:var(--red);padding:4px 0;';
        errDiv.textContent = errorMsg;
        btns.appendChild(errDiv);
    }
}

function _showDossierComplete(proposalId, subjectName, cardEl) {
    if (!cardEl) return;
    cardEl.style.opacity = '1';
    cardEl.classList.remove('running');
    cardEl.style.borderLeftColor = '#22c55e';

    var title = cardEl.querySelector('.action-card-title');
    if (title) title.textContent = 'Dossier ready: ' + (subjectName || 'Research');

    var desc = cardEl.querySelector('.action-card-desc');
    if (desc) desc.textContent = 'Research dossier completed. Download or check Dropbox.';

    var suggest = cardEl.querySelector('.action-card-suggest');
    if (suggest) suggest.remove();

    var progress = cardEl.querySelector('.dossier-progress');
    if (progress) {
        progress.textContent = '';
        var dlBtn = document.createElement('a');
        dlBtn.href = '/api/research-proposals/' + proposalId + '/download?key=' + encodeURIComponent(BAKER.apiKey);
        dlBtn.className = 'action-btn approve';
        dlBtn.style.cssText = 'text-decoration:none;display:inline-block;text-align:center;';
        dlBtn.textContent = 'Download .docx';
        dlBtn.target = '_blank';
        progress.appendChild(dlBtn);
    }
    cardEl.style.pointerEvents = '';
}

function _respondDesktopAction(actionId, response, cardEl) {
    if (cardEl) {
        cardEl.style.opacity = '0.4';
        cardEl.style.pointerEvents = 'none';
    }
    bakerFetch('/api/proposed-actions/' + actionId + '/respond', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ response: response }),
    }).then(function(r) {
        if (!r.ok) throw new Error('API ' + r.status);
        if (cardEl) {
            cardEl.style.transition = 'opacity 0.3s, max-height 0.3s';
            cardEl.style.opacity = '0';
            cardEl.style.maxHeight = '0';
            cardEl.style.overflow = 'hidden';
            cardEl.style.margin = '0';
            cardEl.style.padding = '0';
            setTimeout(function() { cardEl.remove(); }, 300);
        }
        // Update count
        var countEl = document.getElementById('desktopActionCount');
        if (countEl) {
            var remaining = document.querySelectorAll('.action-card').length - 1;
            if (remaining <= 0) {
                document.getElementById('actionsWidget').hidden = true;
            } else {
                countEl.textContent = remaining;
            }
        }
    }).catch(function(e) {
        console.error('Action respond failed:', e);
        if (cardEl) { cardEl.style.opacity = '1'; cardEl.style.pointerEvents = ''; }
    });
}


// ═══ MORNING BRIEF ═══

function _inferProposalType(label, instruction) {
    var t = (label + ' ' + instruction).toLowerCase();
    if (/\bdraft\b|\bwrite an?\b|\bfollow.?up\b|\bsend .* email\b/.test(t)) return 'draft';
    if (/\bdismiss\b|\bclean\b|\bclear\b|\bremove\b/.test(t)) return 'dismiss';
    if (/\bspecialist\b/.test(t)) return 'specialist';
    if (/\bcall\b|\bphone\b|\bring\b/.test(t)) return 'call';
    return 'analyze';
}

function _proposalMeta(actionType) {
    var map = {
        analyze:    { icon: '\uD83D\uDD0D', btnLabel: 'Go \u2192',      color: 'blue' },
        draft:      { icon: '\u2709\uFE0F',  btnLabel: 'Draft \u2192',   color: 'amber' },
        dismiss:    { icon: '\uD83E\uDDF9',  btnLabel: 'Do it \u2192',   color: 'green' },
        specialist: { icon: '\uD83E\uDDE0',  btnLabel: 'Ask \u2192',     color: 'purple' },
        call:       { icon: '\uD83D\uDCDE',  btnLabel: 'Details \u2192', color: 'blue' }
    };
    return map[actionType] || map.analyze;
}

function _makeProposalHandler(actionType, instruction, proposal, btn, card) {
    return async function() {
        if (btn.disabled) return;
        btn.disabled = true;

        if (actionType === 'dismiss' && proposal.params && proposal.params.tier) {
            // Inline bulk dismiss
            btn.textContent = 'Working...';
            try {
                var r = await bakerFetch('/api/alerts/bulk-dismiss', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tier: proposal.params.tier }),
                });
                if (!r.ok) throw new Error('API returned ' + r.status);
                btn.textContent = '\u2713 Done';
                btn.className = 'proposal-btn is-done';
                card.classList.add('done');
                refreshFiresBadge();
            } catch (e) {
                btn.textContent = 'Failed';
                btn.disabled = false;
                console.error('Proposal dismiss failed:', e);
            }
            return;
        }

        if (actionType === 'specialist' && proposal.params && proposal.params.capability_slug) {
            // Open specialist tab with pre-filled question
            btn.textContent = '\u2713 Sent';
            btn.className = 'proposal-btn is-done';
            card.classList.add('done');
            switchTab('ask-specialist');
            setTimeout(function() {
                var picker = document.getElementById('specialistPicker');
                if (picker) {
                    picker.value = proposal.params.capability_slug;
                    picker.dispatchEvent(new Event('change'));
                }
                setTimeout(function() {
                    sendSpecialistMessage(instruction);
                }, 150);
            }, 100);
            return;
        }

        // Default: open chat tab and auto-send (analyze, draft, call, or dismiss without params)
        btn.textContent = '\u2713 Sent';
        btn.className = 'proposal-btn is-done';
        card.classList.add('done');
        switchTab('ask-baker');
        setTimeout(function() { sendScanMessage(instruction); }, 100);
    };
}

async function loadMorningBrief() {
    try {
        var resp = await bakerFetch('/api/dashboard/morning-brief', { timeout: 25000 });
        if (!resp.ok) {
            _showBriefingUnavailable('Server returned ' + resp.status);
            return;
        }
        var data = await resp.json();

        // Unanswered badge in greeting line
        var uBadge = document.getElementById('unansweredBadge');
        if (uBadge) {
            var uCount = data.unanswered_count || 0;
            if (uCount > 0) {
                uBadge.textContent = uCount + ' awaiting reply';
                uBadge.className = 'unanswered-badge has-items';
                uBadge.hidden = false;
            } else {
                uBadge.hidden = true;
            }
        }

        var narEl = document.getElementById('briefNarrative');
        if (narEl && data.narrative) setSafeHTML(narEl, md(data.narrative));

        // Render actionable proposal cards (D7 Morning Brief v2)
        var proposalsEl = document.getElementById('briefProposals');
        if (!proposalsEl) {
            proposalsEl = document.createElement('div');
            proposalsEl.id = 'briefProposals';
            if (narEl) narEl.parentNode.insertBefore(proposalsEl, narEl.nextSibling);
        }
        proposalsEl.textContent = '';
        if (data.proposals && data.proposals.length > 0) {
            var pLabel = document.createElement('div');
            pLabel.style.cssText = 'font-size:11px;font-weight:700;color:var(--text2);font-family:var(--mono);letter-spacing:0.3px;margin-bottom:6px;';
            pLabel.textContent = 'RECOMMENDED ACTIONS';
            proposalsEl.appendChild(pLabel);

            var strip = document.createElement('div');
            strip.className = 'proposal-strip';
            proposalsEl.appendChild(strip);

            data.proposals.slice(0, 5).forEach(function(p) {
                var instruction = p.instruction || (p.params && p.params.question) || p.label;
                var actionType = p.action || _inferProposalType(p.label, instruction);
                var meta = _proposalMeta(actionType);

                var card = document.createElement('div');
                card.className = 'proposal-card type-' + actionType;

                var body = document.createElement('div');
                body.className = 'proposal-body';

                var icon = document.createElement('span');
                icon.className = 'proposal-icon';
                icon.textContent = meta.icon;
                body.appendChild(icon);

                var text = document.createElement('div');
                text.className = 'proposal-text';
                var lbl = document.createElement('div');
                lbl.className = 'proposal-label';
                lbl.textContent = p.label;
                text.appendChild(lbl);
                var sub = document.createElement('div');
                sub.className = 'proposal-sub';
                sub.textContent = instruction.length > 80 ? instruction.slice(0, 77) + '...' : instruction;
                text.appendChild(sub);
                body.appendChild(text);

                var btn = document.createElement('button');
                btn.className = 'proposal-btn color-' + meta.color;
                btn.textContent = meta.btnLabel;
                btn.addEventListener('click', _makeProposalHandler(actionType, instruction, p, btn, card));
                body.appendChild(btn);

                card.appendChild(body);
                strip.appendChild(card);
            });
        }

        // Weekly Priorities Widget
        _renderPrioritiesWidget(data.weekly_priorities || []);

        // Proposed Actions Widget
        _renderActionsWidget(data.proposed_actions || [], data.research_proposals || []);

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

        // LANDING-GRID-1: Populate 2x2 grid cells

        // Grid: Travel (top-left) — trips + today's travel events
        var gridTravel = document.getElementById('gridTravel');
        var gridTravelCount = document.getElementById('gridTravelCount');
        if (gridTravel) {
            var allTravel = [];

            // 1. Active trips (primary content)
            var trips = data.trips || [];
            for (var ti = 0; ti < trips.length; ti++) {
                var trip = trips[ti];
                var statusColor = _tripStatusColors[trip.status] || 'var(--text3)';
                var catLabel = _tripCategoryLabels[trip.category] || '';
                var dateStr = trip.start_date || '';
                if (trip.end_date && trip.end_date !== trip.start_date) dateStr += ' \u2014 ' + trip.end_date;
                allTravel.push(
                    '<div class="card card-compact" onclick="showTripView(' + trip.id + ')" style="cursor:pointer;"><div class="card-header">' +
                    '<span class="nav-dot" style="margin-top:5px;background:' + statusColor + ';"></span>' +
                    '<span class="card-title">' + esc(trip.event_name || trip.destination || 'Trip') +
                    (catLabel ? ' <span style="font-size:9px;font-weight:600;color:var(--text3);background:var(--bg2);padding:1px 4px;border-radius:3px;margin-left:6px;">' + esc(catLabel) + '</span>' : '') +
                    ' <span style="font-size:10px;color:var(--text3);margin-left:4px;">&#9656;</span></span>' +
                    '<span class="card-time">' + esc(dateStr) + '</span>' +
                    '</div></div>'
                );
            }

            // 2. Today's calendar travel events (flights not yet linked to trips)
            var travelEvents = (data.travel_today || []);
            var tripDests = trips.map(function(t) { return (t.destination || '').toLowerCase(); });
            for (var ei = 0; ei < travelEvents.length; ei++) {
                var ev = travelEvents[ei];
                // Skip if already covered by a trip card
                var evTitle = (ev.title || '').toLowerCase();
                var covered = tripDests.some(function(d) { return d && evTitle.indexOf(d) >= 0; });
                if (!covered) allTravel.push(renderTravelCard(ev));
            }

            if (allTravel.length > 0) {
                setSafeHTML(gridTravel, allTravel.join(''));
            } else {
                setSafeHTML(gridTravel, '<div class="grid-empty">No travel today.</div>');
            }
            if (gridTravelCount) gridTravelCount.textContent = allTravel.length > 0 ? allTravel.length : '';
        }

        // Grid: Fires (top-right)
        var gridFires = document.getElementById('gridFires');
        var gridFiresCount = document.getElementById('gridFiresCount');
        if (gridFires) {
            // TRAVEL-FIX-1: travel alerts now served separately, no need to filter from fires
            var fireItems = (data.top_fires || []);
            if (fireItems.length > 0) {
                setSafeHTML(gridFires, fireItems.map(function(a) { return renderFireCompact(a); }).join(''));
            } else {
                gridFires.innerHTML = '<div class="grid-empty">No active fires. All clear.</div>';
            }
            if (gridFiresCount) gridFiresCount.textContent = fireItems.length > 0 ? fireItems.length : '';
        }

        // Grid: Deadlines (bottom-left)
        var gridDeadlines = document.getElementById('gridDeadlines');
        var gridDeadlinesCount = document.getElementById('gridDeadlinesCount');
        if (gridDeadlines) {
            if (data.deadlines && data.deadlines.length > 0) {
                setSafeHTML(gridDeadlines, data.deadlines.map(renderDeadlineCompact).join(''));
            } else {
                gridDeadlines.innerHTML = '<div class="grid-empty">No deadlines this week.</div>';
            }
            if (gridDeadlinesCount) gridDeadlinesCount.textContent = (data.deadlines || []).length || '';
        }

        // Grid: Meetings (bottom-right) — TRAVEL-FIX-2: meetings separated from travel
        var gridMeetings = document.getElementById('gridMeetings');
        var gridMeetingsCount = document.getElementById('gridMeetingsCount');
        if (gridMeetings) {
            var meetingItems = (data.meetings_today || []).filter(function(m) {
                return !(m.title || '').startsWith('[Baker Prep]');
            }).map(renderMeetingCard);
            if (meetingItems.length > 0) {
                setSafeHTML(gridMeetings, meetingItems.join(''));
            } else {
                setSafeHTML(gridMeetings, '<div class="grid-empty">No meetings today.</div>');
            }
            if (gridMeetingsCount) gridMeetingsCount.textContent = meetingItems.length > 0 ? meetingItems.length : '';
        }

        // Update stats: show travel + meeting counts
        var statMeetings = document.getElementById('statMeetings');
        if (statMeetings) {
            var totalEvents = (data.travel_today || []).length + (data.meetings_today || []).length;
            setText('statMeetings', totalEvents || 0);
        }

        // SILENT-CONTACTS-CARD-1: Render relationship cooling warnings
        var silentCard = document.getElementById('silentContactsCard');
        if (silentCard) {
            var silentContacts = data.silent_contacts || [];
            if (silentContacts.length > 0) {
                silentCard.hidden = false;
                silentCard.textContent = '';
                silentCard.style.cssText = 'margin-top:16px;border:1px solid var(--border);border-left:3px solid var(--amber);border-radius:var(--radius-sm);padding:12px 16px;background:var(--card);';

                var scLabel = document.createElement('div');
                scLabel.style.cssText = 'font-size:11px;font-weight:700;color:var(--amber);font-family:var(--mono);letter-spacing:0.3px;margin-bottom:8px;';
                scLabel.textContent = 'RELATIONSHIPS COOLING';
                silentCard.appendChild(scLabel);

                for (var sci = 0; sci < silentContacts.length; sci++) {
                    var sc = silentContacts[sci];
                    var row = document.createElement('div');
                    row.style.cssText = 'display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid var(--border-light);';

                    var nameSpan = document.createElement('span');
                    nameSpan.style.cssText = 'flex:1;font-size:13px;font-weight:500;color:var(--text);';
                    nameSpan.textContent = sc.name || '';
                    row.appendChild(nameSpan);

                    var daysSpan = document.createElement('span');
                    daysSpan.style.cssText = 'font-size:11px;color:var(--amber);font-weight:600;flex-shrink:0;';
                    daysSpan.textContent = (sc.days_silent || 0) + 'd silent';
                    row.appendChild(daysSpan);

                    var reachBtn = document.createElement('button');
                    reachBtn.className = 'run-btn';
                    reachBtn.style.cssText = 'font-size:11px;padding:3px 10px;';
                    reachBtn.textContent = 'Reach out';
                    reachBtn.dataset.name = sc.name || '';
                    reachBtn.addEventListener('click', function() {
                        var name = this.dataset.name;
                        switchTab('ask-baker');
                        var input = document.getElementById('scanInput') || document.getElementById('cmdInput');
                        if (input) {
                            input.value = 'Draft an email to ' + name;
                            input.focus();
                        }
                    });
                    row.appendChild(reachBtn);

                    silentCard.appendChild(row);
                }
            } else {
                silentCard.hidden = true;
            }
        }

        loadMattersSummary();

        // System widgets moved to Baker Data tab (BAKER-DATA-TUCK-1)
    } catch (e) {
        console.error('loadMorningBrief failed:', e);
        _showBriefingUnavailable(e.name === 'AbortError' ? 'Request timed out' : String(e));
    }
}

function _showBriefingUnavailable(reason) {
    var narEl = document.getElementById('briefNarrative');
    if (!narEl) return;
    var retryBtn = document.createElement('button');
    retryBtn.textContent = 'Retry';
    retryBtn.style.cssText = 'margin-left:8px;padding:2px 10px;border-radius:4px;border:1px solid var(--border);background:var(--bg2);color:var(--text1);cursor:pointer;font-size:12px;';
    retryBtn.onclick = function() {
        showLoading(narEl, 'Retrying');
        loadMorningBrief();
    };
    narEl.textContent = 'Briefing unavailable (' + reason + '). ';
    narEl.appendChild(retryBtn);
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
                item.title = label + ' (' + m.item_count + ')';
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

                // Click handled by delegated handler on mattersSubList (line ~2742)
                subList.appendChild(item);
            }
        }
    } catch (e) {
        console.error('loadMattersSummary failed:', e);
    }
}

// ═══ QUICK ADD (Upcoming tab) ═══

function toggleQuickAdd() {
    var form = document.getElementById('quickAddForm');
    if (!form) return;
    form.style.display = form.style.display === 'none' ? 'block' : 'none';
    if (form.style.display === 'block') document.getElementById('quickAddInput').focus();
}

async function submitQuickAdd(e) {
    e.preventDefault();
    var input = document.getElementById('quickAddInput');
    var btn = document.getElementById('quickAddSubmit');
    var title = (input.value || '').trim();
    if (!title) return;

    btn.disabled = true;
    btn.textContent = 'Adding...';
    try {
        var resp = await bakerFetch('/api/alerts/quick-add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: title }),
        });
        if (resp.ok) {
            input.value = '';
            document.getElementById('quickAddForm').style.display = 'none';
            loadFires();  // refresh list
        }
    } catch (err) {
        console.error('Quick add failed:', err);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Add';
    }
}

// ═══ FIRES TAB ═══

var _firesAllAlerts = []; // cached for filtering
var _firesSourceFilter = ''; // active source filter

async function loadFires() {
    const container = document.getElementById('firesContent');
    if (!container) return;
    showLoading(container, 'Loading alerts');

    try {
        const resp = await bakerFetch('/api/alerts');
        if (!resp.ok) return;
        const data = await resp.json();

        _firesAllAlerts = data.alerts || [];

        if (_firesAllAlerts.length === 0) {
            container.textContent = 'No pending alerts.';
            container.style.cssText = 'color:var(--text3);font-size:13px;padding:20px 0;';
            _buildFiresToolbar([]);
            return;
        }

        // Build toolbar (source filter + bulk actions)
        _buildFiresToolbar(_firesAllAlerts);

        // Render with current filter
        _renderFiresFiltered();
        populateAssignDropdowns();
    } catch (e) {
        container.textContent = 'Failed to load fires.';
        container.style.color = 'var(--red)';
    }
}

function _buildFiresToolbar(alerts) {
    var toolbar = document.getElementById('firesToolbar');
    if (!toolbar) return;
    toolbar.textContent = '';
    toolbar.style.display = alerts.length > 0 ? 'flex' : 'none';

    if (alerts.length === 0) return;

    // Source filter
    var sources = {};
    for (var i = 0; i < alerts.length; i++) {
        var src = alerts[i].source || 'unknown';
        sources[src] = (sources[src] || 0) + 1;
    }

    var select = document.createElement('select');
    select.style.cssText = 'font-size:12px;padding:4px 8px;border:1px solid var(--border);border-radius:6px;background:var(--bg1);color:var(--text);font-family:var(--font);';
    var allOpt = document.createElement('option');
    allOpt.value = '';
    allOpt.textContent = 'All sources (' + alerts.length + ')';
    select.appendChild(allOpt);
    var sortedSources = Object.keys(sources).sort();
    for (var si = 0; si < sortedSources.length; si++) {
        var opt = document.createElement('option');
        opt.value = sortedSources[si];
        opt.textContent = sortedSources[si].replace(/_/g, ' ') + ' (' + sources[sortedSources[si]] + ')';
        select.appendChild(opt);
    }
    select.value = _firesSourceFilter;
    select.addEventListener('change', function() {
        _firesSourceFilter = select.value;
        _renderFiresFiltered();
    });
    toolbar.appendChild(select);

    // Select all checkbox
    var selAll = document.createElement('label');
    selAll.style.cssText = 'display:flex;align-items:center;gap:4px;font-size:11px;color:var(--text2);cursor:pointer;margin-left:8px;';
    var cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.id = 'firesSelectAll';
    cb.addEventListener('change', function() {
        var boxes = document.querySelectorAll('.fire-check');
        for (var bi = 0; bi < boxes.length; bi++) boxes[bi].checked = cb.checked;
    });
    selAll.appendChild(cb);
    selAll.appendChild(document.createTextNode('Select all'));
    toolbar.appendChild(selAll);

    // Dismiss selected
    var dismissBtn = document.createElement('button');
    dismissBtn.style.cssText = 'font-size:11px;padding:4px 10px;border:1px solid var(--border);color:var(--text2);background:var(--bg1);border-radius:6px;cursor:pointer;';
    dismissBtn.textContent = 'Dismiss selected';
    dismissBtn.addEventListener('click', bulkDismissSelected);
    toolbar.appendChild(dismissBtn);

    // Dismiss all T3
    var t3Count = 0;
    for (var ti = 0; ti < alerts.length; ti++) { if (alerts[ti].tier >= 3) t3Count++; }
    if (t3Count > 0) {
        var t3Btn = document.createElement('button');
        t3Btn.style.cssText = 'font-size:11px;padding:4px 10px;border:1px solid var(--amber);color:var(--amber);background:transparent;border-radius:6px;cursor:pointer;';
        t3Btn.textContent = 'Dismiss all T3+ (' + t3Count + ')';
        t3Btn.addEventListener('click', function() { bulkDismissByTier(3); });
        toolbar.appendChild(t3Btn);
    }
}

function _renderFiresFiltered() {
    var container = document.getElementById('firesContent');
    if (!container) return;

    var filtered = _firesAllAlerts;
    if (_firesSourceFilter) {
        filtered = _firesAllAlerts.filter(function(a) { return (a.source || 'unknown') === _firesSourceFilter; });
    }

    if (filtered.length === 0) {
        container.textContent = 'No alerts matching filter.';
        container.style.cssText = 'color:var(--text3);font-size:13px;padding:20px 0;';
        return;
    }

    // Group by matter
    var groups = {};
    for (var i = 0; i < filtered.length; i++) {
        var key = filtered[i].matter_slug || '_ungrouped';
        if (!groups[key]) groups[key] = [];
        groups[key].push(filtered[i]);
    }

    container.textContent = '';
    container.style.cssText = '';
    var keys = Object.keys(groups);
    for (var gi = 0; gi < keys.length; gi++) {
        var slug = keys[gi];
        var alerts = groups[slug];
        var label = slug === '_ungrouped' ? 'Ungrouped' : slug.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });

        var sectionLabel = document.createElement('div');
        sectionLabel.className = 'section-label';
        sectionLabel.style.marginTop = '16px';
        sectionLabel.textContent = label + ' (' + alerts.length + ')';
        container.appendChild(sectionLabel);

        for (var ai = 0; ai < alerts.length; ai++) {
            var cardHtml = renderAlertCard(alerts[ai], true);
            // Wrap with checkbox
            var wrapper = document.createElement('div');
            wrapper.style.cssText = 'display:flex;align-items:flex-start;gap:6px;';

            var checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'fire-check';
            checkbox.dataset.alertId = alerts[ai].id;
            checkbox.style.cssText = 'margin-top:14px;flex-shrink:0;cursor:pointer;';
            wrapper.appendChild(checkbox);

            var cardDiv = document.createElement('div');
            cardDiv.style.cssText = 'flex:1;min-width:0;';
            setSafeHTML(cardDiv, cardHtml);
            wrapper.appendChild(cardDiv);

            container.appendChild(wrapper);
        }
    }
    populateAssignDropdowns();
}

async function bulkDismissSelected() {
    var boxes = document.querySelectorAll('.fire-check:checked');
    if (boxes.length === 0) return;
    var ids = [];
    for (var i = 0; i < boxes.length; i++) ids.push(parseInt(boxes[i].dataset.alertId));

    try {
        var r = await bakerFetch('/api/alerts/bulk-dismiss', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ alert_ids: ids }),
        });
        if (!r.ok) throw new Error('API returned ' + r.status);
        var data = await r.json();
        // Remove dismissed from cached list
        _firesAllAlerts = _firesAllAlerts.filter(function(a) { return ids.indexOf(a.id) === -1; });
        _buildFiresToolbar(_firesAllAlerts);
        _renderFiresFiltered();
        refreshFiresBadge();
    } catch (e) { console.error('bulkDismissSelected failed:', e); }
}

async function bulkDismissByTier(tier) {
    try {
        var r = await bakerFetch('/api/alerts/bulk-dismiss', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tier: tier }),
        });
        if (!r.ok) throw new Error('API returned ' + r.status);
        var data = await r.json();
        // Remove dismissed from cached list
        _firesAllAlerts = _firesAllAlerts.filter(function(a) { return a.tier < tier; });
        _buildFiresToolbar(_firesAllAlerts);
        _renderFiresFiltered();
        refreshFiresBadge();
    } catch (e) { console.error('bulkDismissByTier failed:', e); }
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
    html += '<span class="card-title" id="alert-title-' + aid + '">' + esc(alert.title) + '</span>';
    if (isNew) html += '<span class="card-new-badge">new</span>';
    html += '<span class="card-time">' + esc(fmtRelativeTime(alert.created_at)) + '</span>';
    html += '<button class="alert-edit-btn" data-alert-id="' + aid + '" onclick="event.stopPropagation();toggleAlertEdit(' + alert.id + ')" title="Edit">&#9998;</button>';
    html += '</div>';

    // D5: Inline edit panel (hidden by default)
    html += '<div class="alert-edit-panel" id="alert-edit-' + aid + '" style="display:none;">';
    html += '<div style="display:flex;flex-direction:column;gap:8px;padding:8px 0;">';
    html += '<input class="alert-edit-input" id="alert-edit-title-' + aid + '" value="' + esc(alert.title || '') + '" placeholder="Title" />';
    html += '<div style="display:flex;gap:8px;align-items:center;">';
    html += '<select class="alert-edit-select" id="alert-edit-matter-' + aid + '"><option value="">No matter</option></select>';
    html += '<select class="alert-edit-select" id="alert-edit-tier-' + aid + '"><option value="1"' + (tier===1?' selected':'') + '>T1</option><option value="2"' + (tier===2?' selected':'') + '>T2</option><option value="3"' + (tier===3?' selected':'') + '>T3</option></select>';
    html += '</div>';
    html += '<div style="display:flex;gap:8px;">';
    html += '<button class="alert-edit-save" onclick="saveAlertEdit(' + alert.id + ')">Save</button>';
    html += '<button class="alert-edit-cancel" onclick="cancelAlertEdit(' + alert.id + ')">Cancel</button>';
    html += '</div>';
    html += '</div></div>';

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
    html += '<button class="footer-btn primary" onclick="openMatterScan(\'' + esc(alert.matter_slug || '') + '\')">Open in Scan</button>';
    html += '<button class="footer-resolve" data-alert="' + aid + '" onclick="resolveAlert(' + alert.id + ',this)">Resolve</button>';
    html += '<button class="footer-dismiss" data-alert="' + aid + '" onclick="dismissAlert(' + alert.id + ',this)">Dismiss</button>';
    html += '</div></div>';

    return html;
}

// TRAVEL-FIX-2 + TRIP-INTELLIGENCE-1: Route card for flights/travel events
var _CATEGORY_LABELS = { meeting: 'MTG', event: 'EVT', personal: 'PER' };

function renderTravelCard(t) {
    var startTime = '';
    var endTime = '';
    var duration = '';
    try {
        var ds = new Date(t.start);
        startTime = ds.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
        if (t.end) {
            var de = new Date(t.end);
            endTime = de.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
            var diffMs = de - ds;
            if (diffMs > 0) {
                var hrs = Math.floor(diffMs / 3600000);
                var mins = Math.round((diffMs % 3600000) / 60000);
                duration = hrs > 0 ? hrs + 'h' + (mins > 0 ? String(mins).padStart(2, '0') : '') : mins + 'min';
            }
        }
    } catch(e) { startTime = t.start || ''; }

    // Parse route from title: "Flight to San Francisco (LH 454)" or "Flight to Frankfurt am Main (OS 201)"
    var title = t.title || '';
    var flightNum = '';
    var destination = title;
    var fnMatch = title.match(/\(([A-Z]{2}\s?\d{2,4})\)/);
    if (fnMatch) {
        flightNum = fnMatch[1];
        destination = title.replace(fnMatch[0], '').trim();
    }
    // Extract "to <place>" pattern
    var toMatch = destination.match(/(?:flight|flug)\s+to\s+(.+)/i);
    if (toMatch) destination = toMatch[1].trim();

    // Origin from location field (e.g. "Vienna VIE" or "Frankfurt am Main FRA")
    var origin = '';
    var loc = t.location || '';
    var iataMatch = loc.match(/\b([A-Z]{3})\b/);
    if (iataMatch) origin = iataMatch[1];
    // Also check destination for IATA
    var destIata = '';
    var destIataMatch = destination.match(/\b([A-Z]{3})\b/);
    if (destIataMatch) destIata = destIataMatch[1];

    // TRIP-INTELLIGENCE-1: Trip status dot overrides time-based dot
    var dotClass = 'lgray';
    if (t.trip_status) {
        if (t.trip_status === 'planned') dotClass = 'blue';
        else if (t.trip_status === 'confirmed') dotClass = 'green';
        else if (t.trip_status === 'discarded') dotClass = 'red';
        else if (t.trip_status === 'completed') dotClass = 'amber';
    } else {
        // Time-based dot: green=past, amber=in progress, gray=upcoming
        var now = new Date();
        try {
            var evStart = new Date(t.start);
            var evEnd = t.end ? new Date(t.end) : null;
            if (evEnd && now > evEnd) dotClass = 'green';
            else if (now >= evStart) dotClass = 'amber';
        } catch(e) {}
    }

    // Route display
    var routeStr = '';
    if (origin && destIata && origin !== destIata) {
        routeStr = origin + ' &rarr; ' + destIata;
    } else if (origin) {
        routeStr = origin + ' &rarr; ' + esc(destination);
    } else if (destIata) {
        routeStr = '&rarr; ' + destIata;
    } else {
        routeStr = esc(destination);
    }

    // TRIP-INTELLIGENCE-1: Category badge
    var catBadge = '';
    if (t.trip_category && _CATEGORY_LABELS[t.trip_category]) {
        catBadge = ' <span style="font-size:9px;font-weight:600;color:var(--text3);background:var(--bg2);padding:1px 4px;border-radius:3px;margin-left:6px;">' + _CATEGORY_LABELS[t.trip_category] + '</span>';
    }

    // Detail line: flight number, airline hint, duration
    var detailParts = [];
    if (flightNum) detailParts.push(esc(flightNum));
    if (duration) detailParts.push(duration);
    if (endTime && dotClass !== 'green') detailParts.push('arr ' + endTime);
    var detailStr = detailParts.join(' &middot; ');

    // TRIP-INTELLIGENCE-1: Click → trip view if trip exists, else toggle notes
    var hasNotes = t.prep_notes && t.prep_notes.trim().length > 0;
    var clickAttr = '';
    var chevron = '';
    if (t.trip_id) {
        clickAttr = ' onclick="showTripView(' + t.trip_id + ')" style="cursor:pointer;"';
        chevron = ' <span style="font-size:10px;color:var(--text3);margin-left:4px;">&#9656;</span>';
    } else if (hasNotes) {
        clickAttr = ' onclick="var n=this.querySelector(\'.prep-notes\');n.style.display=n.style.display===\'none\'?\'block\':\'none\'" style="cursor:pointer;"';
        chevron = ' <span style="font-size:10px;color:var(--text3);margin-left:4px;">&#9662;</span>';
    }
    var notesHtml = hasNotes && !t.trip_id
        ? '<div class="prep-notes" style="display:none;font-size:12px;color:var(--text2);padding:8px 18px 12px 18px;line-height:1.5;white-space:pre-wrap;border-top:1px solid var(--border-light);margin-top:4px;">' + esc(t.prep_notes).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>') + '</div>'
        : '';

    return '<div class="card card-compact"' + clickAttr + '><div class="card-header">' +
        '<span class="nav-dot ' + dotClass + '" style="margin-top:5px;"></span>' +
        '<span class="card-title">' + routeStr + catBadge + chevron + '</span>' +
        '<span class="card-time">' + esc(startTime) + '</span>' +
        '</div>' +
        (detailStr ? '<div class="card-body" style="font-size:11px;color:var(--text3);padding:2px 0 4px 18px;">' + detailStr + '</div>' : '') +
        notesHtml +
        '</div>';
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
    var hasNotes = m.prep_notes && m.prep_notes.trim().length > 0;
    var clickAttr = hasNotes ? ' onclick="var n=this.querySelector(\'.prep-notes\');n.style.display=n.style.display===\'none\'?\'block\':\'none\'" style="cursor:pointer;"' : '';
    var chevron = hasNotes ? ' <span style="font-size:10px;color:var(--text3);margin-left:4px;">&#9662;</span>' : '';
    var notesHtml = hasNotes
        ? '<div class="prep-notes" style="display:none;font-size:12px;color:var(--text2);padding:8px 18px 12px 18px;line-height:1.5;white-space:pre-wrap;border-top:1px solid var(--border-light);margin-top:4px;">' + esc(m.prep_notes).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>') + '</div>'
        : '';
    return '<div class="card card-compact"' + clickAttr + '><div class="card-header">' +
        '<span class="nav-dot ' + dotClass + '" style="margin-top:5px;"></span>' +
        '<span class="card-title">' + esc(m.title || '') + chevron + '</span>' +
        '<span class="card-time">' + esc(startTime) + '</span>' +
        '</div>' +
        '<div class="card-body" style="font-size:11px;color:var(--text3);padding:2px 0 4px 18px;">' +
        (attendeeStr ? esc(attendeeStr) + ' &middot; ' : '') +
        '<span style="color:var(--' + (m.prepped ? 'green' : 'amber') + ');">' + esc(statusText) + '</span>' +
        '</div>' +
        notesHtml +
        '</div>';
}

function renderDeadlineCompact(dl) {
    const daysText = fmtDeadlineDays(dl.due_date);
    const priority = (dl.priority || 'normal').toLowerCase();
    let dotClass = 'lgray';
    let timeStyle = '';
    if (priority === 'critical' || daysText === 'Today') { dotClass = 'red'; timeStyle = 'color:var(--red);font-weight:600;'; }
    else if (priority === 'high' || daysText === 'Tomorrow') { dotClass = 'amber'; }
    else if (daysText.includes('overdue')) { dotClass = 'red'; timeStyle = 'color:var(--red);font-weight:600;'; }

    var hasSnippet = dl.source_snippet && dl.source_snippet.trim().length > 0;
    var clickAttr = hasSnippet ? ' onclick="var n=this.querySelector(\'.dl-detail\');n.style.display=n.style.display===\'none\'?\'block\':\'none\'" style="cursor:pointer;"' : '';
    var chevron = hasSnippet ? ' <span style="font-size:10px;color:var(--text3);margin-left:4px;">&#9662;</span>' : '';
    var detailHtml = hasSnippet
        ? '<div class="dl-detail" style="display:none;font-size:12px;color:var(--text2);padding:6px 18px 10px 18px;line-height:1.5;border-top:1px solid var(--border-light);white-space:pre-wrap;">' + esc(dl.source_snippet) + '</div>'
        : '';

    return '<div class="card card-compact"' + clickAttr + '><div class="card-header">' +
        '<span class="nav-dot ' + dotClass + '" style="margin-top:5px;"></span>' +
        '<span class="card-title">' + esc(dl.description || '') + chevron + '</span>' +
        '<span class="card-time" style="' + timeStyle + '">' + esc(daysText) + '</span>' +
        '</div>' + detailHtml + '</div>';
}

function renderFireCompact(alert) {
    var tier = alert.tier || 1;
    var dotClass = tier === 1 ? 'red' : 'amber';
    var body = (alert.body || '').trim();
    var hasBody = body.length > 0;
    var truncBody = body.length > 500 ? body.substring(0, 500) + '...' : body;
    var clickAttr = hasBody ? ' onclick="var n=this.querySelector(\'.fire-detail\');n.style.display=n.style.display===\'none\'?\'block\':\'none\'" style="cursor:pointer;"' : '';
    var chevron = hasBody ? ' <span style="font-size:10px;color:var(--text3);margin-left:4px;">&#9662;</span>' : '';
    var detailHtml = hasBody
        ? '<div class="fire-detail" style="display:none;font-size:12px;color:var(--text2);padding:6px 18px 10px 18px;line-height:1.5;border-top:1px solid var(--border-light);white-space:pre-wrap;">' +
          esc(truncBody) +
          (body.length > 500 ? ' <a href="#" onclick="event.stopPropagation();switchTab(\'fires\');return false;" style="color:var(--blue);font-weight:600;text-decoration:none;">See full &rarr;</a>' : '') +
          '</div>'
        : '';
    return '<div class="card card-compact"' + clickAttr + '><div class="card-header">' +
        '<span class="nav-dot ' + dotClass + '" style="margin-top:5px;"></span>' +
        '<span class="card-title">' + esc(alert.title || '') + chevron + '</span>' +
        '<span class="card-time">' + esc(fmtRelativeTime(alert.created_at)) + '</span>' +
        '</div>' + detailHtml + '</div>';
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
            timeout: 180000, // 3 min — SSE stream
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
            timeout: 180000, // 3 min — SSE stream
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
    if (!container) { console.error('mattersContent container not found'); return; }
    showLoading(container, 'Loading ' + matterSlug);
    _matterDetailSlug = matterSlug;

    try {
        var resp = await bakerFetch('/api/matters/' + encodeURIComponent(matterSlug) + '/items');
        if (!resp.ok) {
            container.textContent = 'Error loading matter (HTTP ' + resp.status + ')';
            container.style.color = 'var(--red)';
            return;
        }
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
        // Thinking indicator — safe static HTML (no user input)
        var dots = document.createElement('div');
        dots.className = 'thinking';
        var span = document.createElement('span');
        span.className = 'thinking-dots';
        for (var i = 0; i < 3; i++) span.appendChild(document.createElement('span'));
        dots.appendChild(span);
        dots.appendChild(document.createTextNode(' Baker is thinking...'));
        div.appendChild(dots);
    } else if (role === 'assistant') {
        // SECURITY: md() calls esc() first to sanitize HTML entities before formatting
        var mdDiv = document.createElement('div');
        mdDiv.className = 'md-content';
        setSafeHTML(mdDiv, md(content));
        div.appendChild(mdDiv);
    } else {
        div.textContent = content; // User messages: plain text, no HTML
    }
    // Newest messages at top (Cowork style — input is at top)
    container.prepend(div);
    container.scrollTop = 0;
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

    var _panelId = 'scanArtifactPanel';
    var _itemsId = 'scanArtifactItems';
    clearArtifactPanel(_panelId, _itemsId);
    var _scanStart = Date.now();

    const sendBtn = document.getElementById('scanSendBtn');
    const input = document.getElementById('scanInput');
    if (sendBtn) sendBtn.disabled = true;
    if (input) { input.disabled = true; input.value = ''; }

    getScanHistory().push({ role: 'user', content: question });
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
            timeout: 180000, // 3 min — SSE streams need time for retrieval + generation
            body: JSON.stringify({
                question: question,
                history: getScanHistory(),
                project: _scanCurrentContext.startsWith('matter:') ? _scanCurrentContext.replace('matter:', '') : null
            }),
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
                    // THINKING-DOTS-FIX: Update thinking label on status events
                    if (data.status && !fullResponse && replyEl) {
                        var _statusLabels = {
                            'retrieving': 'Searching memory...',
                            'thinking': 'Analyzing context...',
                            'generating': 'Writing response...'
                        };
                        var _label = _statusLabels[data.status];
                        if (_label) {
                            var _thinkDiv = replyEl.querySelector('.thinking');
                            if (_thinkDiv) {
                                // Replace text node only — preserve dots animation
                                var _nodes = _thinkDiv.childNodes;
                                for (var _ni = _nodes.length - 1; _ni >= 0; _ni--) {
                                    if (_nodes[_ni].nodeType === 3) _thinkDiv.removeChild(_nodes[_ni]);
                                }
                                _thinkDiv.appendChild(document.createTextNode(' ' + _label));
                            }
                        }
                    }
                    if (data.token) {
                        if (!fullResponse && replyEl) replyEl.textContent = ''; // clear thinking indicator
                        fullResponse += data.token;
                        // SECURITY: md() calls esc() first to sanitize HTML entities before formatting
                        if (replyEl) setSafeHTML(replyEl, '<div class="md-content">' + md(fullResponse) + '</div>');
                    }
                    if (data.capabilities) {
                        addArtifactCapability(_itemsId, _panelId, data.capabilities);
                    }
                    if (data.tool_call) {
                        addArtifactSource(_itemsId, _panelId, data.tool_call);
                    }
                    if (data.task_id) {
                        window._lastScanTaskId = data.task_id; // LEARNING-LOOP: capture for feedback buttons
                    }
                    if (data.error) {
                        fullResponse += '\n[Error: ' + data.error + ']';
                        if (replyEl) setSafeHTML(replyEl, '<div class="md-content">' + md(fullResponse) + '</div>');
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
            if (cleanResponse) setSafeHTML(replyEl, '<div class="md-content">' + md(cleanResponse) + '</div>');
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
                addArtifactDownload(_itemsId, _panelId, genData);
            }
        } catch (e) { console.warn('Document generation failed:', e); }
    }

    finalizeArtifactPanel(_itemsId, _scanStart);

    getScanHistory().push({ role: 'assistant', content: fullResponse });

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

    // FOLLOWUP-SUGGESTIONS-1: Show follow-up questions after substantive responses
    if (fullResponse && fullResponse.length > 100 && !fullResponse.startsWith('Error:') && replyEl) {
        _fetchFollowups(replyEl, question, fullResponse, 'scan');
    }

    scanStreaming = false;
    if (sendBtn) sendBtn.disabled = false;
    if (input) { input.disabled = false; input.focus(); }

    const container = document.getElementById('scanMessages');
    if (container) container.scrollTop = 0;
}

// ═══ FOLLOW-UP SUGGESTIONS ═══

async function _fetchFollowups(replyEl, question, answer, source) {
    try {
        var resp = await bakerFetch('/api/scan/followups', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question: question.substring(0, 300),
                answer: answer.substring(0, 1500),
            }),
        });
        if (!resp.ok) return;
        var data = await resp.json();
        if (!data.suggestions || data.suggestions.length === 0) return;

        var bar = document.createElement('div');
        bar.className = 'followup-bar';

        for (var i = 0; i < data.suggestions.length; i++) {
            var btn = document.createElement('button');
            btn.className = 'followup-btn';
            btn.textContent = data.suggestions[i];
            btn.addEventListener('click', (function(text, src) {
                return function() {
                    if (src === 'specialist') sendSpecialistMessage(text);
                    else sendScanMessage(text);
                };
            })(data.suggestions[i], source));
            bar.appendChild(btn);
        }

        replyEl.appendChild(bar);
        var container = replyEl.closest('.scan-messages, #specialistMessages, #scanMessages');
        if (container) container.scrollTop = container.scrollHeight;
    } catch (e) {
        // Non-fatal — just don't show suggestions
    }
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

// ═══ BAKER DATA TAB ═══

async function loadBakerData() {
    var container = document.getElementById('bakerDataContent');
    if (!container) return;
    showLoading(container, 'Loading Baker Data');

    try {
        var resp = await bakerFetch('/api/dashboard/morning-brief', { timeout: 20000 });
        if (!resp.ok) { container.textContent = 'Failed to load.'; return; }
        var data = await resp.json();

        container.textContent = '';

        // Activity Today
        var actLabel = document.createElement('div');
        actLabel.style.cssText = 'font-size:11px;font-weight:700;color:var(--text3);font-family:var(--mono);letter-spacing:0.3px;margin-bottom:8px;';
        actLabel.textContent = 'ACTIVITY (24H)';
        container.appendChild(actLabel);

        var actGrid = document.createElement('div');
        actGrid.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:20px;';

        var procBox = document.createElement('div');
        procBox.style.cssText = 'background:var(--card);border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px;';
        var procNum = document.createElement('div');
        procNum.style.cssText = 'font-size:20px;font-weight:700;color:var(--text);';
        procNum.textContent = data.processed_overnight || 0;
        procBox.appendChild(procNum);
        var procLbl = document.createElement('div');
        procLbl.style.cssText = 'font-size:12px;color:var(--text3);';
        procLbl.textContent = 'Processed';
        procBox.appendChild(procLbl);
        actGrid.appendChild(procBox);

        var actBox = document.createElement('div');
        actBox.style.cssText = 'background:var(--card);border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px;';
        var actNum = document.createElement('div');
        actNum.style.cssText = 'font-size:20px;font-weight:700;color:var(--text);';
        actNum.textContent = data.actions_completed || 0;
        actBox.appendChild(actNum);
        var actLbl = document.createElement('div');
        actLbl.style.cssText = 'font-size:12px;color:var(--text3);';
        actLbl.textContent = 'Actions completed';
        actBox.appendChild(actLbl);
        actGrid.appendChild(actBox);

        container.appendChild(actGrid);

        // Recent Capability Runs
        if (data.activity && data.activity.length > 0) {
            var capLabel = document.createElement('div');
            capLabel.style.cssText = 'font-size:11px;font-weight:700;color:var(--text3);font-family:var(--mono);letter-spacing:0.3px;margin-bottom:8px;';
            capLabel.textContent = 'RECENT CAPABILITY RUNS';
            container.appendChild(capLabel);

            for (var i = 0; i < data.activity.length; i++) {
                var run = data.activity[i];
                var row = document.createElement('div');
                row.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--border-light);font-size:12px;';

                var slug = document.createElement('span');
                slug.style.cssText = 'font-weight:500;color:var(--text);';
                slug.textContent = run.capability_slug || '?';
                row.appendChild(slug);

                var meta = document.createElement('span');
                meta.style.cssText = 'color:var(--text3);font-family:var(--mono);font-size:11px;';
                var status = run.status || '?';
                var iter = run.iterations || '?';
                var time = run.created_at ? new Date(run.created_at).toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit'}) : '';
                meta.textContent = status + ' | ' + iter + ' iter | ' + time;
                row.appendChild(meta);

                container.appendChild(row);
            }
        } else {
            var empty = document.createElement('div');
            empty.style.cssText = 'color:var(--text3);font-size:13px;padding:12px 0;';
            empty.textContent = 'No capability runs in the last 24 hours.';
            container.appendChild(empty);
        }

        // BAKER-DATA-TUCK-1: System health widgets (moved from landing page)
        var sysLabel = document.createElement('div');
        sysLabel.style.cssText = 'font-size:11px;font-weight:700;color:var(--text3);font-family:var(--mono);letter-spacing:0.3px;margin-bottom:8px;margin-top:24px;';
        sysLabel.textContent = 'SYSTEM HEALTH';
        container.appendChild(sysLabel);

        await Promise.all([
            renderSentinelWidget(container),
            renderCostWidget(container),
            renderMetricsWidget(container),
            renderQualityWidget(container),
        ]);

    } catch (e) {
        container.textContent = 'Failed to load Baker Data.';
    }
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
    showLoading(container, 'Loading matters');
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
var _networkingSort = 'tier'; // 'tier' or 'health'

async function loadPeopleTab() {
    var container = document.getElementById('peopleContent');
    if (!container) return;
    showLoading(container, 'Loading networking');

    try {
        var results = await Promise.all([
            bakerFetch('/api/networking/contacts' + (_networkingFilter !== 'all' ? '?contact_type=' + _networkingFilter : '')).then(function(r) { return r.json(); }),
            bakerFetch('/api/networking/alerts').then(function(r) { return r.json(); }),
            bakerFetch('/api/networking/events').then(function(r) { return r.json(); }),
            bakerFetch('/api/contacts/cadence').then(function(r) { return r.json(); }).catch(function() { return {contacts: []}; }),
        ]);
        var contactsData = results[0];
        var alertsData = results[1];
        var eventsData = results[2];
        var cadenceData = results[3];

        // Build cadence map by lowercase name
        var cadenceMap = {};
        var cadenceContacts = cadenceData.contacts || [];
        for (var ci = 0; ci < cadenceContacts.length; ci++) {
            var cc = cadenceContacts[ci];
            cadenceMap[(cc.name || '').toLowerCase()] = cc;
        }

        // Merge cadence data into contacts
        var contacts = contactsData.contacts || [];

        // If networking contacts empty but cadence has data, use cadence contacts directly
        if (contacts.length === 0 && cadenceContacts.length > 0) {
            contacts = cadenceContacts.map(function(cc) {
                return {
                    name: cc.name, tier: cc.tier, health: 'grey',
                    avg_inbound_gap_days: cc.avg_inbound_gap_days,
                    days_silent: cc.days_silent,
                    deviation: cc.deviation,
                    last_inbound_at: cc.last_inbound_at,
                    _hasCadence: true
                };
            });
        } else {
            for (var mi = 0; mi < contacts.length; mi++) {
                var cName = (contacts[mi].name || '').toLowerCase();
                if (cadenceMap[cName]) {
                    contacts[mi].avg_inbound_gap_days = cadenceMap[cName].avg_inbound_gap_days;
                    contacts[mi].days_silent = cadenceMap[cName].days_silent;
                    contacts[mi].deviation = cadenceMap[cName].deviation;
                    contacts[mi].last_inbound_at = cadenceMap[cName].last_inbound_at;
                    contacts[mi]._hasCadence = true;
                }
            }
        }

        // Compute cadence-relative health for each contact
        var healthCounts = {healthy: 0, cooling: 0, cold: 0, unknown: 0};
        for (var hi = 0; hi < contacts.length; hi++) {
            var co = contacts[hi];
            if (co._hasCadence && co.deviation !== undefined) {
                var dev = parseFloat(co.deviation);
                if (dev <= 1.0) { co._healthStatus = 'healthy'; healthCounts.healthy++; }
                else if (dev <= 2.0) { co._healthStatus = 'cooling'; healthCounts.cooling++; }
                else { co._healthStatus = 'cold'; healthCounts.cold++; }
            } else {
                co._healthStatus = 'unknown';
                healthCounts.unknown++;
            }
        }

        // Sort
        if (_networkingSort === 'health') {
            var healthOrder = {cold: 0, cooling: 1, healthy: 2, unknown: 3};
            contacts.sort(function(a, b) {
                var ha = healthOrder[a._healthStatus] || 3;
                var hb = healthOrder[b._healthStatus] || 3;
                if (ha !== hb) return ha - hb;
                return (parseFloat(b.deviation) || 0) - (parseFloat(a.deviation) || 0);
            });
        }

        container.textContent = '';

        // A. Health Summary Bar (C2)
        var tracked = healthCounts.healthy + healthCounts.cooling + healthCounts.cold;
        if (tracked > 0) {
            var healthBar = document.createElement('div');
            healthBar.style.cssText = 'display:flex;align-items:center;gap:12px;padding:10px 14px;background:var(--bg2);border-radius:8px;margin-bottom:12px;font-size:12px;';

            var trackLabel = document.createElement('span');
            trackLabel.style.cssText = 'font-weight:600;color:var(--text1);';
            trackLabel.textContent = tracked + ' tracked:';
            healthBar.appendChild(trackLabel);

            function _addHealthBadge(parent, count, color, label) {
                if (count === 0) return;
                var badge = document.createElement('span');
                badge.style.cssText = 'display:flex;align-items:center;gap:4px;';
                var dot = document.createElement('span');
                dot.style.cssText = 'width:8px;height:8px;border-radius:50%;background:' + color + ';flex-shrink:0;';
                badge.appendChild(dot);
                var text = document.createElement('span');
                text.style.color = 'var(--text2)';
                text.textContent = count + ' ' + label;
                badge.appendChild(text);
                parent.appendChild(badge);
            }
            _addHealthBadge(healthBar, healthCounts.healthy, 'var(--green)', 'healthy');
            _addHealthBadge(healthBar, healthCounts.cooling, 'var(--amber)', 'cooling');
            _addHealthBadge(healthBar, healthCounts.cold, 'var(--red)', 'at risk');

            container.appendChild(healthBar);
        }

        // B. Alert Strip
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
        if (strip.children.length === 0 && tracked === 0) {
            var allGood = document.createElement('span');
            allGood.style.cssText = 'color:var(--green);font-size:12px;font-weight:600;';
            allGood.textContent = 'All contacts healthy';
            strip.appendChild(allGood);
        }
        if (strip.children.length > 0) container.appendChild(strip);

        // C. Filter + Sort Bar
        var filters = document.createElement('div');
        filters.style.cssText = 'display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap;align-items:center;';
        var types = ['all', 'principal', 'introducer', 'operator', 'institutional', 'connector'];
        types.forEach(function(t) {
            var btn = document.createElement('button');
            btn.className = _networkingFilter === t ? 'filter-tab active' : 'filter-tab';
            btn.textContent = t.charAt(0).toUpperCase() + t.slice(1);
            btn.addEventListener('click', function() { _networkingFilter = t; loadPeopleTab(); });
            filters.appendChild(btn);
        });

        // Sort separator + sort buttons
        var sep = document.createElement('span');
        sep.style.cssText = 'width:1px;height:16px;background:var(--border);margin:0 4px;';
        filters.appendChild(sep);
        var sorts = [{key:'tier', label:'By Tier'}, {key:'health', label:'By Health'}];
        sorts.forEach(function(s) {
            var btn = document.createElement('button');
            btn.className = _networkingSort === s.key ? 'filter-tab active' : 'filter-tab';
            btn.textContent = s.label;
            btn.addEventListener('click', function() { _networkingSort = s.key; loadPeopleTab(); });
            filters.appendChild(btn);
        });

        container.appendChild(filters);

        // D. Contact List
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

                // Health dot (C2: cadence-relative)
                var healthDot = document.createElement('span');
                var healthColors = {healthy: 'var(--green)', cooling: 'var(--amber)', cold: 'var(--red)', unknown: 'var(--lgray, #ccc)'};
                healthDot.style.cssText = 'width:8px;height:8px;border-radius:50%;background:' + (healthColors[c._healthStatus] || 'var(--lgray, #ccc)') + ';flex-shrink:0;cursor:help;';

                // C2: Hover tooltip with cadence detail
                if (c._hasCadence) {
                    var gapStr = parseFloat(c.avg_inbound_gap_days).toFixed(1);
                    var silentStr = Math.round(parseFloat(c.days_silent));
                    var devStr = parseFloat(c.deviation).toFixed(1);
                    var statusLabel = c._healthStatus === 'healthy' ? 'Healthy' : c._healthStatus === 'cooling' ? 'Cooling (' + devStr + 'x normal gap)' : 'At Risk (' + devStr + 'x normal gap)';
                    healthDot.title = 'Avg contact every ' + gapStr + ' days\nLast heard: ' + silentStr + ' days ago\nStatus: ' + statusLabel;
                } else {
                    healthDot.title = 'No cadence data (insufficient interactions)';
                }
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

                // Last contact / days silent
                var lastLabel = '';
                if (c._hasCadence && c.days_silent) {
                    lastLabel = Math.round(parseFloat(c.days_silent)) + 'd ago';
                } else if (c.last_contact_date) {
                    lastLabel = fmtRelativeTime(c.last_contact_date);
                }
                if (lastLabel) {
                    var lastC = document.createElement('span');
                    lastC.style.cssText = 'font-size:11px;color:var(--text3);white-space:nowrap;';
                    lastC.textContent = lastLabel;
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

        // E. Events Section
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

// ═══ SEARCH TAB (D6: Knowledge Base) ═══

var _kbSearchQuery = '';
var _kbSourceFilter = '';
var _kbResults = [];
var _kbSearchInitialized = false;

var _KB_SOURCES = [
    { key: '', label: 'All', color: 'var(--blue)' },
    { key: 'emails', label: 'Emails', color: '#2563eb' },
    { key: 'meetings', label: 'Meetings', color: '#7c3aed' },
    { key: 'documents', label: 'Documents', color: '#16a34a' },
    { key: 'whatsapp', label: 'WhatsApp', color: '#0d9488' },
    { key: 'conversations', label: 'Conversations', color: 'rgba(0,0,0,0.45)' },
];

var _KB_BADGE_MAP = {
    emails: { text: 'EMAIL', cls: 'kb-source-emails' },
    meetings: { text: 'MEETING', cls: 'kb-source-meetings' },
    document: { text: 'DOC', cls: 'kb-source-document' },
    whatsapp: { text: 'WHATSAPP', cls: 'kb-source-whatsapp' },
    conversation: { text: 'MEMORY', cls: 'kb-source-conversation' },
};

function loadSearchTab() {
    var filtersEl = document.getElementById('searchFilters');
    if (!filtersEl) return;

    if (!_kbSearchInitialized) {
        _kbSearchInitialized = true;
        filtersEl.textContent = '';

        // Search bar row
        var barRow = document.createElement('div');
        barRow.style.cssText = 'display:flex;gap:8px;margin-bottom:10px;';

        var searchInput = document.createElement('input');
        searchInput.type = 'text';
        searchInput.id = 'kbSearchInput';
        searchInput.placeholder = 'Search across all Baker content...';
        searchInput.maxLength = 500;
        searchInput.style.cssText = 'flex:1;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;font-family:var(--font);background:var(--bg);outline:none;';
        searchInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                _kbSearchQuery = searchInput.value;
                executeKBSearch();
            }
        });
        barRow.appendChild(searchInput);

        var searchBtn = document.createElement('button');
        searchBtn.className = 'run-btn';
        searchBtn.textContent = 'Search';
        searchBtn.addEventListener('click', function() {
            _kbSearchQuery = searchInput.value;
            executeKBSearch();
        });
        barRow.appendChild(searchBtn);
        filtersEl.appendChild(barRow);

        // Source filter chips
        var chipRow = document.createElement('div');
        chipRow.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;';
        chipRow.id = 'kbChipRow';

        _KB_SOURCES.forEach(function(src) {
            var chip = document.createElement('button');
            chip.className = src.key === _kbSourceFilter ? 'kb-chip active' : 'kb-chip';
            chip.textContent = src.label;
            chip.dataset.source = src.key;
            if (src.key === _kbSourceFilter) {
                chip.style.background = src.color;
                chip.style.borderColor = 'transparent';
            }
            chip.addEventListener('click', function() {
                _kbSourceFilter = src.key;
                _updateKBChips();
                if (_kbSearchQuery.trim().length >= 2) executeKBSearch();
            });
            chipRow.appendChild(chip);
        });
        filtersEl.appendChild(chipRow);

        // Show empty state
        _showKBEmptyState();
    }

    // Focus input on tab switch
    var inp = document.getElementById('kbSearchInput');
    if (inp) setTimeout(function() { inp.focus(); }, 50);
}

function _updateKBChips() {
    var chips = document.querySelectorAll('#kbChipRow .kb-chip');
    for (var i = 0; i < chips.length; i++) {
        var chip = chips[i];
        var srcKey = chip.dataset.source;
        var isActive = srcKey === _kbSourceFilter;
        chip.className = isActive ? 'kb-chip active' : 'kb-chip';
        if (isActive) {
            var srcColor = 'var(--blue)';
            for (var j = 0; j < _KB_SOURCES.length; j++) {
                if (_KB_SOURCES[j].key === srcKey) { srcColor = _KB_SOURCES[j].color; break; }
            }
            chip.style.background = srcColor;
            chip.style.borderColor = 'transparent';
        } else {
            chip.style.background = '';
            chip.style.borderColor = '';
        }
    }
}

function _showKBEmptyState() {
    var results = document.getElementById('searchResults');
    if (!results) return;
    results.textContent = '';
    var empty = document.createElement('div');
    empty.style.cssText = 'text-align:center;padding:80px 20px;color:var(--text3);';
    var icon = document.createElement('div');
    icon.style.cssText = 'font-size:48px;margin-bottom:16px;opacity:0.4;';
    icon.textContent = '\uD83D\uDD0D';
    empty.appendChild(icon);
    var title = document.createElement('div');
    title.style.cssText = 'font-size:16px;font-weight:600;color:var(--text2);margin-bottom:8px;';
    title.textContent = "Search Baker's Knowledge Base";
    empty.appendChild(title);
    var desc = document.createElement('div');
    desc.style.cssText = 'font-size:13px;line-height:1.6;';
    desc.textContent = 'Find anything across emails, meetings, documents, WhatsApp messages, and past conversations.';
    empty.appendChild(desc);
    results.appendChild(empty);
}

function _kbExtractTitle(r) {
    var m = r.metadata || {};
    switch (r.source) {
        case 'emails': return m.subject || m.label || (r.content || '').split('\n')[0].slice(0, 80) || 'Email';
        case 'meetings': return m.title || m.label || 'Meeting transcript';
        case 'document': return m.filename || m.label || 'Document';
        case 'whatsapp': return m.sender_name || m.chat || 'WhatsApp message';
        case 'conversation': return m.label || 'Past conversation';
        default: return m.label || r.source || 'Result';
    }
}

function _kbExtractDate(r) {
    var m = r.metadata || {};
    var raw = m.date || m.received_at || m.timestamp || m.ingested_at;
    if (!raw) return '';
    return _formatRelativeDate(raw);
}

function _formatRelativeDate(dateStr) {
    try {
        var d = new Date(dateStr);
        if (isNaN(d.getTime())) return dateStr;
        var diff = Date.now() - d.getTime();
        var mins = Math.floor(diff / 60000);
        if (mins < 60) return mins + 'm ago';
        var hrs = Math.floor(mins / 60);
        if (hrs < 24) return hrs + 'h ago';
        var days = Math.floor(hrs / 24);
        if (days < 7) return days + 'd ago';
        return d.toLocaleDateString('en-GB', { month: 'short', day: 'numeric', year: 'numeric' });
    } catch (e) { return dateStr; }
}

function _kbExtractMeta(r) {
    var m = r.metadata || {};
    var parts = [];
    if (m.sender) parts.push(m.sender);
    if (m.sender_name && !m.sender) parts.push(m.sender_name);
    if (m.filename && r.source !== 'document') parts.push(m.filename);
    if (m.chat) parts.push(m.chat);
    return parts.join(' \u00B7 ');
}

async function executeKBSearch() {
    var q = _kbSearchQuery.trim();
    if (q.length < 2) return;

    var results = document.getElementById('searchResults');
    showLoading(results, 'Searching');

    var params = new URLSearchParams();
    params.set('q', q);
    params.set('limit', '30');
    if (_kbSourceFilter) params.set('sources', _kbSourceFilter);

    try {
        var resp = await bakerFetch('/api/search/unified?' + params.toString());
        if (!resp.ok) throw new Error('API ' + resp.status);
        var data = await resp.json();
        _kbResults = data.results || [];
        _renderKBResults(data);
    } catch (e) {
        results.textContent = '';
        var err = document.createElement('div');
        err.style.cssText = 'color:var(--text3);font-size:13px;padding:20px;';
        err.textContent = 'Search failed. Try again.';
        results.appendChild(err);
    }
}

function _renderKBResults(data) {
    var results = document.getElementById('searchResults');
    if (!results) return;
    results.textContent = '';

    var items = data.results || [];

    // Count header
    var countEl = document.createElement('div');
    countEl.style.cssText = 'font-size:12px;color:var(--text3);margin:12px 0 8px;';
    if (items.length === 0) {
        countEl.textContent = 'No results found for \u201c' + (data.query || _kbSearchQuery) + '\u201d';
        results.appendChild(countEl);
        return;
    }
    var srcList = (data.sources_searched || []).join(', ');
    countEl.textContent = data.total + ' result' + (data.total !== 1 ? 's' : '') + (srcList ? ' across ' + srcList : '');
    results.appendChild(countEl);

    // Render cards
    var html = '';
    for (var i = 0; i < items.length; i++) {
        var r = items[i];
        var badge = _KB_BADGE_MAP[r.source] || { text: r.source, cls: 'kb-source-conversation' };
        var title = _kbExtractTitle(r);
        var dateStr = _kbExtractDate(r);
        var score = r.score ? Math.round(r.score * 100) + '%' : '';
        var preview = (r.content || '').slice(0, 200);
        var full = r.content || '';
        var meta = _kbExtractMeta(r);

        html += '<div class="kb-result" data-index="' + i + '">' +
            '<div class="kb-result-header">' +
                '<span class="kb-source-badge ' + esc(badge.cls) + '">' + esc(badge.text) + '</span>' +
                '<span class="kb-result-title">' + esc(title) + '</span>' +
                (score ? '<span class="kb-result-score">' + esc(score) + '</span>' : '') +
                (dateStr ? '<span class="kb-result-date">' + esc(dateStr) + '</span>' : '') +
            '</div>' +
            '<div class="kb-result-body">' + esc(preview) + '</div>' +
            '<div class="kb-result-full" style="display:none">' + esc(full) + '</div>' +
            (meta ? '<div class="kb-result-meta">' + esc(meta) + '</div>' : '') +
        '</div>';
    }

    var cardsDiv = document.createElement('div');
    setSafeHTML(cardsDiv, html);
    results.appendChild(cardsDiv);

    // Click to expand/collapse
    cardsDiv.addEventListener('click', function(e) {
        var card = e.target.closest('.kb-result');
        if (!card) return;
        var body = card.querySelector('.kb-result-body');
        var full = card.querySelector('.kb-result-full');
        if (!body || !full) return;
        var expanded = card.classList.toggle('kb-result-expanded');
        body.style.display = expanded ? 'none' : '';
        full.style.display = expanded ? '' : 'none';
    });
}

// ═══ TAGS TAB ═══

async function loadTagsTab() {
    var container = document.getElementById('tagsContent');
    if (!container) return;
    showLoading(container, 'Loading tags');

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
    showLoading(container, 'Loading tag items');

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

// ═══ D5: INLINE ALERT EDITING ═══

function toggleAlertEdit(alertId) {
    var panel = document.getElementById('alert-edit-' + alertId);
    if (!panel) return;
    var isHidden = panel.style.display === 'none';
    panel.style.display = isHidden ? '' : 'none';
    if (isHidden) _populateAlertEditMatters(alertId);
}

function cancelAlertEdit(alertId) {
    var panel = document.getElementById('alert-edit-' + alertId);
    if (panel) panel.style.display = 'none';
}

async function _populateAlertEditMatters(alertId) {
    var sel = document.getElementById('alert-edit-matter-' + alertId);
    if (!sel || sel.options.length > 1) return;
    try {
        var resp = await bakerFetch('/api/matters?status=active');
        if (!resp.ok) return;
        var data = await resp.json();
        if (data.matters) {
            for (var i = 0; i < data.matters.length; i++) {
                var m = data.matters[i];
                var opt = document.createElement('option');
                opt.value = m.matter_name || m.slug;
                opt.textContent = m.matter_name || m.slug;
                sel.appendChild(opt);
            }
        }
        // Pre-select current matter
        var card = sel.closest('[data-matter]');
        if (card) sel.value = card.dataset.matter || '';
    } catch (e) { /* silent */ }
}

async function saveAlertEdit(alertId) {
    var titleInput = document.getElementById('alert-edit-title-' + alertId);
    var matterSel = document.getElementById('alert-edit-matter-' + alertId);
    var tierSel = document.getElementById('alert-edit-tier-' + alertId);
    if (!titleInput) return;

    var body = {};
    var newTitle = titleInput.value.trim();
    if (newTitle) body.title = newTitle;
    if (matterSel) body.matter_slug = matterSel.value || null;
    if (tierSel) body.tier = parseInt(tierSel.value);

    // Optimistic update
    var titleEl = document.getElementById('alert-title-' + alertId);
    var origTitle = titleEl ? titleEl.textContent : '';
    if (titleEl && newTitle) titleEl.textContent = newTitle;
    cancelAlertEdit(alertId);

    try {
        var resp = await bakerFetch('/api/alerts/' + alertId, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body),
        });
        if (!resp.ok) throw new Error('API ' + resp.status);
        // Refresh to show matter/tier changes
        if (body.matter_slug !== undefined || body.tier) {
            if (typeof loadFires === 'function') loadFires();
        }
    } catch (e) {
        console.error('saveAlertEdit failed:', e);
        // Revert on error
        if (titleEl) titleEl.textContent = origTitle;
        alert('Failed to save: ' + e.message);
    }
}

// ═══ ENHANCED DEADLINES TAB ═══

async function loadDeadlinesTab() {
    var container = document.getElementById('deadlinesContent');
    if (!container) return;
    showLoading(container, 'Loading deadlines');

    try {
        // Fetch deadlines (commitments migrated to deadlines in OBLIGATIONS-UNIFY-1)
        var dlResp = await bakerFetch('/api/deadlines?limit=100');
        var allItems = [];

        if (dlResp.ok) {
            var dlData = await dlResp.json();
            (dlData.deadlines || []).forEach(function(d) {
                allItems.push({ type: 'deadline', id: d.id, description: d.description, due_date: d.due_date, source: d.source_type || 'deadline', matter: d.matter_slug, priority: d.priority, status: d.status, severity: d.severity, obligation_type: d.obligation_type, assigned_to: d.assigned_to });
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
            container.textContent = 'No active obligations.';
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
        header.textContent = 'Obligations (' + allItems.length + ')';
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

                // SEVERITY badge
                if (item.severity) {
                    var sevBadge = document.createElement('span');
                    var sevColors = { hard: 'var(--red)', firm: 'var(--amber)', soft: 'var(--blue)' };
                    var sevCol = sevColors[item.severity] || 'var(--text3)';
                    sevBadge.style.cssText = 'font-size:9px;font-weight:600;color:' + sevCol + ';border:1px solid ' + sevCol + ';padding:1px 5px;border-radius:3px;min-width:32px;text-align:center;margin-top:2px;';
                    sevBadge.textContent = item.severity.toUpperCase();
                    row.appendChild(sevBadge);
                }

                // RIGHT: description + source tag + assigned_to
                var descCol = document.createElement('div');
                descCol.style.cssText = 'flex:1;font-size:13px;color:var(--text1);';
                descCol.textContent = item.description || '';
                if (item.assigned_to) {
                    var aTag = document.createElement('span');
                    aTag.style.cssText = 'font-size:10px;color:var(--blue);margin-left:8px;';
                    aTag.textContent = '\u2192 ' + item.assigned_to;
                    descCol.appendChild(aTag);
                }
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
                    bakerFetch('/api/deadlines/' + item.id + '/dismiss', { method: 'POST' }).then(function() { loadDeadlinesTab(); });
                }));

                actionsDiv.appendChild(makeBtn('+1 Week', 'var(--amber)', function() {
                    var newDate = new Date(item.due_date || new Date());
                    newDate.setDate(newDate.getDate() + 7);
                    bakerFetch('/api/deadlines/' + item.id + '/reschedule', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({due_date: newDate.toISOString()}) }).then(function() { loadDeadlinesTab(); });
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

        // D3: Triage button
        if (allItems.length > 0) {
            var triageBtnWrap = document.createElement('div');
            triageBtnWrap.style.cssText = 'margin:16px 0 0;text-align:center;';
            var triageBtn = document.createElement('button');
            triageBtn.style.cssText = 'padding:8px 20px;border:1px solid var(--blue);color:var(--blue);background:transparent;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;font-family:var(--font);';
            triageBtn.textContent = 'Triage (' + allItems.length + ' pending)';
            triageBtn.addEventListener('click', function() { _openTriageDeck(allItems); });
            triageBtnWrap.appendChild(triageBtn);
            container.appendChild(triageBtnWrap);
        }

    } catch (e) {
        container.textContent = 'Failed to load deadlines.';
        container.style.color = 'var(--red)';
        console.warn('Deadlines tab failed:', e);
    }
}

// ═══ D3: TRIAGE CARD DECK ═══
var _triageItems = [];
var _triageIndex = 0;
var _triageUndo = null; // {index, item, previousState}

function _openTriageDeck(items) {
    _triageItems = items.slice(); // copy
    _triageIndex = 0;
    _triageUndo = null;

    var overlay = document.getElementById('triageOverlay');
    overlay.style.display = 'flex';

    document.getElementById('triageCloseBtn').onclick = function() { _closeTriageDeck(); };
    document.getElementById('triageUndoBtn').onclick = function() { _undoTriageAction(); };

    _buildTriageActions();
    _renderTriageCard();
}

function _closeTriageDeck() {
    document.getElementById('triageOverlay').style.display = 'none';
    loadDeadlinesTab(); // Refresh
}

function _renderTriageCard() {
    var area = document.getElementById('triageCardArea');
    var counter = document.getElementById('triageCounter');
    area.textContent = '';

    counter.textContent = (_triageIndex + 1) + ' of ' + _triageItems.length;

    if (_triageIndex >= _triageItems.length) {
        var done = document.createElement('div');
        done.style.cssText = 'text-align:center;';
        var doneIcon = document.createElement('div');
        doneIcon.style.cssText = 'font-size:48px;margin-bottom:16px;';
        doneIcon.textContent = '\u2705';
        done.appendChild(doneIcon);
        var doneText = document.createElement('div');
        doneText.style.cssText = 'font-size:18px;font-weight:600;color:var(--text1);margin-bottom:8px;';
        doneText.textContent = 'All reviewed!';
        done.appendChild(doneText);
        var doneBtn = document.createElement('button');
        doneBtn.style.cssText = 'padding:10px 24px;background:var(--blue);color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;margin-top:12px;';
        doneBtn.textContent = 'Back to Obligations';
        doneBtn.addEventListener('click', function() { _closeTriageDeck(); });
        done.appendChild(doneBtn);
        area.appendChild(done);
        counter.textContent = 'Done';
        document.getElementById('triageActions').style.display = 'none';
        return;
    }

    document.getElementById('triageActions').style.display = 'flex';
    var item = _triageItems[_triageIndex];

    var card = document.createElement('div');
    card.style.cssText = 'width:100%;max-width:500px;padding:24px;background:var(--bg2);border-radius:12px;border:1px solid var(--border);transition:transform 0.3s,opacity 0.3s;';

    // Priority strip
    var prioColors = {critical: 'var(--red)', high: 'var(--amber)', normal: 'var(--blue)', low: 'var(--text3)'};
    var prioColor = prioColors[item.priority] || 'var(--text3)';
    card.style.borderLeftWidth = '4px';
    card.style.borderLeftColor = prioColor;

    // Priority + severity badges
    var badges = document.createElement('div');
    badges.style.cssText = 'display:flex;gap:6px;margin-bottom:12px;';
    if (item.priority) {
        var prioBadge = document.createElement('span');
        prioBadge.style.cssText = 'font-size:10px;font-weight:700;color:' + prioColor + ';border:1px solid ' + prioColor + ';padding:2px 8px;border-radius:4px;text-transform:uppercase;';
        prioBadge.textContent = item.priority;
        badges.appendChild(prioBadge);
    }
    if (item.severity) {
        var sevColors = {hard: 'var(--red)', firm: 'var(--amber)', soft: 'var(--blue)'};
        var sevCol = sevColors[item.severity] || 'var(--text3)';
        var sevBadge = document.createElement('span');
        sevBadge.style.cssText = 'font-size:10px;font-weight:700;color:' + sevCol + ';border:1px solid ' + sevCol + ';padding:2px 8px;border-radius:4px;text-transform:uppercase;';
        sevBadge.textContent = item.severity;
        badges.appendChild(sevBadge);
    }
    card.appendChild(badges);

    // Description
    var desc = document.createElement('div');
    desc.style.cssText = 'font-size:15px;line-height:1.6;color:var(--text1);margin-bottom:16px;';
    desc.textContent = item.description || 'No description';
    card.appendChild(desc);

    // Due date
    if (item.due_date) {
        var dueDiv = document.createElement('div');
        dueDiv.style.cssText = 'font-size:12px;color:var(--text3);margin-bottom:4px;';
        var dueDate = new Date(item.due_date);
        dueDiv.textContent = 'Due: ' + dueDate.toLocaleDateString('en-GB', {day: 'numeric', month: 'short', year: 'numeric'});
        var daysText = fmtDeadlineDays(item.due_date);
        if (daysText) dueDiv.textContent += ' (' + daysText + ')';
        card.appendChild(dueDiv);
    }

    // Source + matter
    var meta = document.createElement('div');
    meta.style.cssText = 'font-size:11px;color:var(--text3);';
    var metaParts = [];
    if (item.source) metaParts.push(item.source);
    if (item.matter) metaParts.push(item.matter.replace(/_/g, ' '));
    if (item.assigned_to) metaParts.push('\u2192 ' + item.assigned_to);
    meta.textContent = metaParts.join(' \u00B7 ');
    card.appendChild(meta);

    // Touch swipe support
    _setupTriageSwipe(card);

    area.appendChild(card);
}

function _setupTriageSwipe(card) {
    var startX = 0, startY = 0, currentX = 0, currentY = 0, swiping = false;

    card.addEventListener('touchstart', function(e) {
        startX = e.touches[0].clientX;
        startY = e.touches[0].clientY;
        swiping = true;
    }, {passive: true});

    card.addEventListener('touchmove', function(e) {
        if (!swiping) return;
        currentX = e.touches[0].clientX - startX;
        currentY = e.touches[0].clientY - startY;
        // Horizontal swipe dominates
        if (Math.abs(currentX) > Math.abs(currentY)) {
            card.style.transform = 'translateX(' + currentX + 'px) rotate(' + (currentX * 0.05) + 'deg)';
            card.style.opacity = Math.max(1 - Math.abs(currentX) / 300, 0.3);
        } else if (currentY < -30) {
            card.style.transform = 'translateY(' + currentY + 'px)';
            card.style.opacity = Math.max(1 - Math.abs(currentY) / 300, 0.3);
        }
    }, {passive: true});

    card.addEventListener('touchend', function() {
        if (!swiping) return;
        swiping = false;
        if (currentX > 100) {
            // Swipe right = Keep
            card.style.transform = 'translateX(120%)';
            card.style.opacity = '0';
            setTimeout(function() { _triageAction('keep'); }, 200);
        } else if (currentX < -100) {
            // Swipe left = Dismiss
            card.style.transform = 'translateX(-120%)';
            card.style.opacity = '0';
            setTimeout(function() { _triageAction('dismiss'); }, 200);
        } else if (currentY < -80) {
            // Swipe up = Escalate
            card.style.transform = 'translateY(-120%)';
            card.style.opacity = '0';
            setTimeout(function() { _triageAction('escalate'); }, 200);
        } else {
            card.style.transform = '';
            card.style.opacity = '';
        }
        currentX = 0;
        currentY = 0;
    });
}

function _buildTriageActions() {
    var actionsDiv = document.getElementById('triageActions');
    actionsDiv.textContent = '';

    function _makeTriageBtn(label, color, bgColor, action) {
        var btn = document.createElement('button');
        btn.style.cssText = 'padding:10px 20px;border:2px solid ' + color + ';color:' + color + ';background:' + (bgColor || 'transparent') + ';border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;min-width:80px;';
        btn.textContent = label;
        btn.addEventListener('click', function() { _triageAction(action); });
        return btn;
    }

    actionsDiv.appendChild(_makeTriageBtn('Dismiss', 'var(--text3)', '', 'dismiss'));
    actionsDiv.appendChild(_makeTriageBtn('Keep', 'var(--green)', '', 'keep'));
    actionsDiv.appendChild(_makeTriageBtn('Escalate', 'var(--amber)', '', 'escalate'));
    actionsDiv.appendChild(_makeTriageBtn('Done', 'var(--blue)', 'var(--blue)', 'done'));
    // Make Done button white text
    actionsDiv.lastChild.style.color = '#fff';
}

function _triageAction(action) {
    if (_triageIndex >= _triageItems.length) return;
    var item = _triageItems[_triageIndex];
    var previousState = {priority: item.priority, status: item.status};

    // Save undo state
    _triageUndo = {index: _triageIndex, item: item, previousState: previousState, action: action};
    document.getElementById('triageUndo').style.display = '';

    // API call based on action
    if (action === 'dismiss') {
        bakerFetch('/api/deadlines/' + item.id, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({status: 'dismissed'})
        }).catch(function(e) { console.error('Triage dismiss failed:', e); });
    } else if (action === 'escalate') {
        bakerFetch('/api/deadlines/' + item.id, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({priority: 'high'})
        }).catch(function(e) { console.error('Triage escalate failed:', e); });
    } else if (action === 'done') {
        bakerFetch('/api/deadlines/' + item.id, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({status: 'completed'})
        }).catch(function(e) { console.error('Triage complete failed:', e); });
    }
    // 'keep' = no API call, just advance

    _triageIndex++;
    _renderTriageCard();
}

function _undoTriageAction() {
    if (!_triageUndo) return;
    var undo = _triageUndo;

    // Revert API change
    if (undo.action === 'dismiss') {
        bakerFetch('/api/deadlines/' + undo.item.id, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({status: 'active'})
        }).catch(function(e) { console.error('Triage undo dismiss failed:', e); });
    } else if (undo.action === 'escalate') {
        bakerFetch('/api/deadlines/' + undo.item.id, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({priority: undo.previousState.priority || 'normal'})
        }).catch(function(e) { console.error('Triage undo escalate failed:', e); });
    } else if (undo.action === 'done') {
        bakerFetch('/api/deadlines/' + undo.item.id, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({status: 'active'})
        }).catch(function(e) { console.error('Triage undo complete failed:', e); });
    }

    _triageIndex = undo.index;
    _triageUndo = null;
    document.getElementById('triageUndo').style.display = 'none';
    _renderTriageCard();
}

// ═══ TRAVEL TAB ═══

async function loadTravelTab() {
    var container = document.getElementById('travelContent');
    if (!container) return;
    showLoading(container, 'Loading travel items');
    try {
        // Fetch trips and alerts in parallel
        var [tripsResp, alertsResp] = await Promise.all([
            bakerFetch('/api/trips'),
            bakerFetch('/api/alerts/by-tag/travel'),
        ]);

        container.textContent = '';
        var hasContent = false;

        // TRIP-INTELLIGENCE-1: Show trips section
        if (tripsResp.ok) {
            var tripsData = await tripsResp.json();
            var trips = tripsData.trips || [];
            if (trips.length > 0) {
                hasContent = true;
                var tripsLabel = document.createElement('div');
                tripsLabel.style.cssText = 'font-family:var(--mono);font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.6px;color:var(--text3);margin:0 0 8px;';
                tripsLabel.textContent = 'Trips (' + trips.length + ')';
                container.appendChild(tripsLabel);

                var tripsDiv = document.createElement('div');
                var tripsHtml = trips.map(function(trip) {
                    var statusColor = _tripStatusColors[trip.status] || 'var(--text3)';
                    var catLabel = _tripCategoryLabels[trip.category] || '';
                    var dateStr = trip.start_date || '';
                    if (trip.end_date && trip.end_date !== trip.start_date) dateStr += ' — ' + trip.end_date;
                    return '<div class="card card-compact" onclick="showTripView(' + trip.id + ')" style="cursor:pointer;"><div class="card-header">' +
                        '<span class="nav-dot" style="margin-top:5px;background:' + statusColor + ';"></span>' +
                        '<span class="card-title">' + esc(trip.destination || 'Trip') +
                        (catLabel ? ' <span style="font-size:9px;font-weight:600;color:var(--text3);background:var(--bg2);padding:1px 4px;border-radius:3px;margin-left:6px;">' + esc(catLabel) + '</span>' : '') +
                        ' <span style="font-size:10px;color:var(--text3);margin-left:4px;">&#9656;</span></span>' +
                        '<span class="card-time">' + esc(dateStr) + '</span>' +
                        '</div>' +
                        (trip.origin ? '<div class="card-body" style="font-size:11px;color:var(--text3);padding:2px 0 4px 18px;">From: ' + esc(trip.origin) + '</div>' : '') +
                        '</div>';
                }).join('');
                setSafeHTML(tripsDiv, tripsHtml);
                container.appendChild(tripsDiv);
            }
        }

        // Show travel alerts
        if (alertsResp.ok) {
            var data = await alertsResp.json();
            var items = data.items || [];
            if (items.length > 0) {
                hasContent = true;
                var now = new Date();
                now.setHours(0, 0, 0, 0);
                var upcoming = [];
                var past = [];
                for (var i = 0; i < items.length; i++) {
                    var item = items[i];
                    if (item.travel_date) {
                        var td = new Date(item.travel_date);
                        if (td < now) { past.push(item); continue; }
                    }
                    upcoming.push(item);
                }

                if (upcoming.length > 0) {
                    var upLabel = document.createElement('div');
                    upLabel.style.cssText = 'font-family:var(--mono);font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.6px;color:var(--text3);margin:16px 0 8px;';
                    upLabel.textContent = 'Travel Alerts — Upcoming (' + upcoming.length + ')';
                    container.appendChild(upLabel);
                    var upDiv = document.createElement('div');
                    setSafeHTML(upDiv, upcoming.map(function(a) { return renderFireCompact(a); }).join(''));
                    container.appendChild(upDiv);
                }

                if (past.length > 0) {
                    var pastLabel = document.createElement('div');
                    pastLabel.style.cssText = 'font-family:var(--mono);font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.6px;color:var(--text4);margin:16px 0 8px;';
                    pastLabel.textContent = 'Travel Alerts — Past (' + past.length + ')';
                    container.appendChild(pastLabel);
                    var pastDiv = document.createElement('div');
                    pastDiv.style.opacity = '0.5';
                    setSafeHTML(pastDiv, past.map(function(a) { return renderFireCompact(a); }).join(''));
                    container.appendChild(pastDiv);
                }
            }
        }

        if (!hasContent) {
            container.textContent = 'No trips or travel alerts. Travel-related items will appear here when detected.';
            container.style.cssText = 'color:var(--text3);font-size:13px;';
        }
    } catch (e) {
        container.textContent = 'Failed to load travel items.';
    }
}

// ═══ MEDIA TAB (RSS) ═══

async function loadMediaTab() {
    var container = document.getElementById('mediaContent');
    if (!container) return;
    showLoading(container, 'Loading media');
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
var _specialistHistories = {};   // keyed by 'global' or 'matter:<slug>' + ':' + capSlug
var _specialistStreaming = false;
var _specialistContext = 'global'; // active matter context for specialist

function _specialistContextKey() {
    return (_specialistContext || 'global') + ':' + (_specialistSlug || '');
}

function _getSpecialistHistory() {
    var key = _specialistContextKey();
    if (!_specialistHistories[key]) _specialistHistories[key] = [];
    return _specialistHistories[key];
}

async function loadSpecialistTab() {
    // Capture matter context if navigating from a matter
    if (_currentMatterSlug) {
        _specialistContext = 'matter:' + _currentMatterSlug;
    }

    var picker = document.getElementById('specialistPicker');
    if (!picker) return;

    // Only populate once — check for data attribute flag
    if (picker.dataset.loaded) return;

    try {
        var resp = await bakerFetch('/api/capabilities');
        if (!resp.ok) return;
        var data = await resp.json();
        if (!data.capabilities) return;

        // Clear existing options except the placeholder
        while (picker.options.length > 1) picker.remove(1);

        var seen = {};
        for (var i = 0; i < data.capabilities.length; i++) {
            var cap = data.capabilities[i];
            if (cap.capability_type === 'domain' && cap.active && !seen[cap.slug]) {
                seen[cap.slug] = true;
                var opt = document.createElement('option');
                opt.value = cap.slug;
                opt.textContent = cap.name;
                picker.appendChild(opt);
            }
        }
        picker.dataset.loaded = 'true';
    } catch (e) {
        console.error('loadSpecialistTab failed:', e);
    }
}

async function sendSpecialistMessage(question) {
    if (_specialistStreaming || !question.trim() || !_specialistSlug) return;
    _specialistStreaming = true;

    var _panelId = 'specialistArtifactPanel';
    var _itemsId = 'specialistArtifactItems';
    clearArtifactPanel(_panelId, _itemsId);
    var _specStart = Date.now();

    // Pre-populate capability badge from selected specialist
    addArtifactCapability(_itemsId, _panelId, [_specialistSlug]);

    var sendBtn = document.getElementById('specialistSendBtn');
    var input = document.getElementById('specialistInput');
    if (sendBtn) sendBtn.disabled = true;
    if (input) { input.disabled = true; input.value = ''; }

    _getSpecialistHistory().push({ role: 'user', content: question });
    appendSpecialistBubble('user', question);

    var replyId = 'specialist-reply-' + Date.now();
    appendSpecialistBubble('assistant', '', replyId);
    var replyEl = document.getElementById(replyId);
    if (replyEl) setSafeHTML(replyEl, '<div class="thinking"><span class="thinking-dots"><span></span><span></span><span></span></span> Specialist is thinking...</div>');

    var fullResponse = '';
    try {
        var resp = await bakerFetch('/api/scan/specialist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            timeout: 180000, // 3 min — SSE stream
            body: JSON.stringify({
                question: question,
                capability_slug: _specialistSlug,
                history: _getSpecialistHistory().slice(-30),
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
                    // THINKING-DOTS-FIX: Update thinking label on status events
                    if (data.status && !fullResponse && replyEl) {
                        var _sLabels = {
                            'retrieving': 'Searching memory...',
                            'thinking': 'Analyzing context...',
                            'generating': 'Writing response...'
                        };
                        var _sLabel = _sLabels[data.status];
                        if (_sLabel) {
                            var _sThink = replyEl.querySelector('.thinking');
                            if (_sThink) {
                                var _sNodes = _sThink.childNodes;
                                for (var _si = _sNodes.length - 1; _si >= 0; _si--) {
                                    if (_sNodes[_si].nodeType === 3) _sThink.removeChild(_sNodes[_si]);
                                }
                                _sThink.appendChild(document.createTextNode(' ' + _sLabel));
                            }
                        }
                    }
                    if (data.token) {
                        if (!fullResponse && replyEl) replyEl.textContent = '';
                        fullResponse += data.token;
                        if (replyEl) setSafeHTML(replyEl, '<div class="md-content">' + md(fullResponse) + '</div>');
                    }
                    if (data.capabilities) {
                        // capabilities already set from picker — skip
                    }
                    if (data.tool_call) {
                        addArtifactSource(_itemsId, _panelId, data.tool_call);
                    }
                } catch (e) { /* skip */ }
            }
        }
    } catch (err) {
        fullResponse = 'Error: ' + err.message;
        if (replyEl) replyEl.textContent = fullResponse;
    }

    finalizeArtifactPanel(_itemsId, _specStart);

    var hist = _getSpecialistHistory();
    hist.push({ role: 'assistant', content: fullResponse });
    if (hist.length > 30) {
        var key = _specialistContextKey();
        _specialistHistories[key] = hist.slice(-30);
    }

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

    // FOLLOWUP-SUGGESTIONS-1: Show follow-up questions after specialist responses
    if (fullResponse && fullResponse.length > 100 && !fullResponse.startsWith('Error:') && replyEl) {
        _fetchFollowups(replyEl, question, fullResponse, 'specialist');
    }

    _specialistStreaming = false;
    if (sendBtn) sendBtn.disabled = false;
    if (input) { input.disabled = false; input.focus(); }

    var container = document.getElementById('specialistMessages');
    if (container) container.scrollTop = 0;
}

function appendSpecialistBubble(role, content, id) {
    var container = document.getElementById('specialistMessages');
    if (!container) return;
    var div = document.createElement('div');
    div.className = 'scan-msg ' + (role === 'user' ? 'user' : 'baker');
    if (id) div.id = id;
    if (role === 'assistant' && !content) {
        var dots = document.createElement('div');
        dots.className = 'thinking';
        var span = document.createElement('span');
        span.className = 'thinking-dots';
        for (var i = 0; i < 3; i++) span.appendChild(document.createElement('span'));
        dots.appendChild(span);
        dots.appendChild(document.createTextNode(' Specialist is thinking...'));
        div.appendChild(dots);
    } else if (role === 'assistant') {
        var mdDiv = document.createElement('div');
        mdDiv.className = 'md-content';
        setSafeHTML(mdDiv, md(content));
        div.appendChild(mdDiv);
    } else {
        div.textContent = content;
    }
    container.prepend(div);
    container.scrollTop = 0;
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
        if (q.length < 8) { badge.hidden = true; return; }
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

    // REALTIME-PUSH-1: Store API key for EventSource + request notification permission
    window._bakerApiKey = BAKER_CONFIG.apiKey || '';
    if (window.Notification && Notification.permission === 'default') {
        Notification.requestPermission();
    }
    _connectAlertStream();

    // E3: Register service worker + subscribe to Web Push
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/static/sw.js').then(function(reg) {
            console.log('SW registered:', reg.scope);
            return reg.pushManager.getSubscription().then(function(sub) {
                if (sub) return sub;
                return fetch('/api/push/vapid-key').then(function(r) { return r.json(); }).then(function(d) {
                    if (!d.public_key) return null;
                    var raw = atob(d.public_key.replace(/-/g, '+').replace(/_/g, '/'));
                    var arr = new Uint8Array(raw.length);
                    for (var i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
                    return reg.pushManager.subscribe({
                        userVisibleOnly: true,
                        applicationServerKey: arr,
                    });
                });
            });
        }).then(function(sub) {
            if (sub) {
                bakerFetch('/api/push/subscribe', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(sub.toJSON()),
                });
            }
        }).catch(function(e) {
            console.warn('Push subscription failed (non-fatal):', e);
        });
    }

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

    // D4: Apply saved tab order, then setup drag-drop
    _applyTabOrder();
    _setupTabDragDrop();

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

    // File upload handlers (Ask Baker + Ask Specialist)
    setupDocumentUpload('scanFile', 'scanUploadStatus', 'viewAskBaker');
    setupDocumentUpload('specialistFile', 'specialistUploadStatus', 'viewAskSpecialist');

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
            // Restore per-context history for this slug+matter combo
            var container = document.getElementById('specialistMessages');
            if (container) {
                container.textContent = '';
                var existing = _getSpecialistHistory();
                for (var i = 0; i < existing.length; i++) {
                    appendSpecialistBubble(existing[i].role, existing[i].content);
                }
            }
            if (_specialistSlug && input) input.focus();
        });
    }

    // Load morning brief
    loadMorningBrief();

    // Alert badge auto-refresh every 5 min (T1+T2 count on sidebar)
    setInterval(refreshFiresBadge, 5 * 60 * 1000);
}

/** Refresh sidebar fires badge independently (T1+T2 pending count). */
async function refreshFiresBadge() {
    try {
        var r = await bakerFetch('/api/alerts');
        if (!r.ok) return;
        var data = await r.json();
        var alerts = data.alerts || [];
        var count = 0;
        for (var i = 0; i < alerts.length; i++) {
            if (alerts[i].tier <= 2) count++;
        }
        var badge = document.getElementById('firesBadge');
        if (!badge) return;
        if (count > 0) {
            badge.textContent = count;
            badge.hidden = false;
        } else {
            badge.hidden = true;
        }
    } catch (e) { /* silent */ }
}

// ═══ REALTIME-PUSH-1: Live alert stream ═══
var _alertsMuted = false;

function _playT1Beep() {
    if (_alertsMuted) return;
    try {
        var ctx = new (window.AudioContext || window.webkitAudioContext)();
        var osc = ctx.createOscillator();
        var gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.frequency.value = 880;
        osc.type = 'sine';
        gain.gain.value = 0.3;
        osc.start();
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
        osc.stop(ctx.currentTime + 0.4);
    } catch (e) { /* no audio support */ }
}

function _showAlertToast(alert) {
    var isT1 = alert.tier === 1;
    var toast = document.createElement('div');
    toast.style.cssText = 'position:fixed;top:12px;right:12px;z-index:9999;max-width:400px;padding:12px 16px;border-radius:10px;font-size:13px;font-family:var(--font);color:#fff;cursor:pointer;box-shadow:0 4px 20px rgba(0,0,0,0.25);transition:opacity 0.3s;'
        + (isT1 ? 'background:#dc2626;' : 'background:#0a6fdb;');

    var tierSpan = document.createElement('span');
    tierSpan.style.cssText = 'font-weight:700;margin-right:8px;';
    tierSpan.textContent = 'T' + alert.tier;
    toast.appendChild(tierSpan);

    var titleSpan = document.createElement('span');
    titleSpan.textContent = (alert.title || '').substring(0, 80);
    toast.appendChild(titleSpan);

    toast.addEventListener('click', function() {
        toast.remove();
        // Navigate to Fires tab
        var firesTab = document.querySelector('[data-tab="fires"]');
        if (firesTab) firesTab.click();
    });

    document.body.appendChild(toast);

    // Auto-dismiss: T1 sticky (30s), T2 quick (15s)
    var dismissMs = isT1 ? 30000 : 15000;
    setTimeout(function() {
        toast.style.opacity = '0';
        setTimeout(function() { toast.remove(); }, 300);
    }, dismissMs);
}

function _sendBrowserNotification(alert) {
    if (!window.Notification || Notification.permission !== 'granted') return;
    try {
        var n = new Notification('Baker T' + alert.tier + ' Alert', {
            body: (alert.title || '').substring(0, 100),
            icon: '/static/baker-face-green.svg',
            tag: 'baker-alert-' + alert.id,
        });
        n.onclick = function() {
            window.focus();
            var firesTab = document.querySelector('[data-tab="fires"]');
            if (firesTab) firesTab.click();
            n.close();
        };
    } catch (e) { /* silent */ }
}

function _connectAlertStream() {
    var key = (window._bakerApiKey || '');
    if (!key) {
        // Retry after config loads
        setTimeout(_connectAlertStream, 3000);
        return;
    }
    var url = '/api/alerts/stream?key=' + encodeURIComponent(key);
    var es = new EventSource(url);

    es.onmessage = function(event) {
        try {
            var data = JSON.parse(event.data);
            if (data.type === 'new_alert' && data.tier <= 2) {
                _showAlertToast(data);
                _sendBrowserNotification(data);
                refreshFiresBadge();
                if (data.tier === 1) _playT1Beep();
            }
        } catch (e) { /* skip */ }
    };

    es.onerror = function() {
        es.close();
        // Reconnect after 30s
        setTimeout(_connectAlertStream, 30000);
    };
}

function toggleMute(btn) {
    _alertsMuted = !_alertsMuted;
    if (btn) btn.textContent = _alertsMuted ? '\uD83D\uDD15' : '\uD83D\uDD14';
    if (btn) btn.title = _alertsMuted ? 'Unmute alert sounds' : 'Mute alert sounds';
}

// ═══ D4: TAB CUSTOMIZATION (drag-to-reorder, pin/hide, localStorage) ═══
var _tabConfig = null; // {order: [...], pinned: [...], hidden: [...]}
var _TAB_CONFIG_KEY = 'baker_tab_order';

function _loadTabConfig() {
    try {
        var stored = localStorage.getItem(_TAB_CONFIG_KEY);
        if (stored) _tabConfig = JSON.parse(stored);
    } catch(e) {}
    if (!_tabConfig) _tabConfig = {order: [], pinned: [], hidden: []};
}

function _saveTabConfig() {
    try { localStorage.setItem(_TAB_CONFIG_KEY, JSON.stringify(_tabConfig)); } catch(e) {}
}

function _applyTabOrder() {
    _loadTabConfig();
    var nav = document.querySelector('.sidebar-nav');
    if (!nav) return;

    var items = Array.from(nav.querySelectorAll('.nav-item[data-tab]'));
    if (items.length === 0) return;

    // Get all non-tab elements (dividers, sub-lists) to preserve
    var dividers = Array.from(nav.querySelectorAll('.nav-divider, .nav-sub'));

    // Sort tabs by stored order (pinned first, then ordered, then rest)
    if (_tabConfig.order.length > 0) {
        var orderMap = {};
        for (var oi = 0; oi < _tabConfig.order.length; oi++) {
            orderMap[_tabConfig.order[oi]] = oi;
        }
        items.sort(function(a, b) {
            var aPin = _tabConfig.pinned.indexOf(a.dataset.tab) >= 0 ? 0 : 1;
            var bPin = _tabConfig.pinned.indexOf(b.dataset.tab) >= 0 ? 0 : 1;
            if (aPin !== bPin) return aPin - bPin;
            var aOrd = orderMap[a.dataset.tab] !== undefined ? orderMap[a.dataset.tab] : 999;
            var bOrd = orderMap[b.dataset.tab] !== undefined ? orderMap[b.dataset.tab] : 999;
            return aOrd - bOrd;
        });
    }

    // Hide/show based on config
    items.forEach(function(item) {
        var isHidden = _tabConfig.hidden.indexOf(item.dataset.tab) >= 0;
        item.style.display = isHidden ? 'none' : '';
        item.draggable = true;
        if (_tabConfig.pinned.indexOf(item.dataset.tab) >= 0) {
            item.classList.add('pinned');
        }
    });

    // Re-insert items in order (before first divider or at end)
    var firstDivider = nav.querySelector('.nav-divider');
    items.forEach(function(item) {
        nav.insertBefore(item, firstDivider);
    });
    // Re-insert dividers after tabs
    dividers.forEach(function(d) { nav.appendChild(d); });

    // Add overflow button if tabs are hidden
    _updateTabOverflow(nav, items);
}

function _updateTabOverflow(nav, items) {
    var existing = nav.querySelector('.nav-overflow');
    if (existing) existing.remove();

    var hiddenTabs = _tabConfig.hidden || [];
    if (hiddenTabs.length === 0) return;

    var overflowBtn = document.createElement('button');
    overflowBtn.className = 'nav-overflow';
    overflowBtn.textContent = '\u2026';
    overflowBtn.title = hiddenTabs.length + ' hidden tab(s)';
    overflowBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        _showTabOverflowMenu(overflowBtn, hiddenTabs);
    });
    nav.appendChild(overflowBtn);
}

function _showTabOverflowMenu(anchor, hiddenTabs) {
    _closeTabCtxMenu();
    var menu = document.createElement('div');
    menu.className = 'tab-ctx-menu';
    menu.id = 'tabOverflowMenu';

    hiddenTabs.forEach(function(tabName) {
        var item = document.createElement('button');
        item.className = 'tab-ctx-item';
        item.textContent = 'Show: ' + tabName.replace(/-/g, ' ');
        item.addEventListener('click', function() {
            _tabConfig.hidden = _tabConfig.hidden.filter(function(t) { return t !== tabName; });
            _saveTabConfig();
            _applyTabOrder();
            _closeTabCtxMenu();
        });
        menu.appendChild(item);
    });

    // Reset option
    var sep = document.createElement('div');
    sep.className = 'tab-ctx-sep';
    menu.appendChild(sep);
    var reset = document.createElement('button');
    reset.className = 'tab-ctx-item';
    reset.textContent = 'Reset layout';
    reset.style.color = 'var(--red)';
    reset.addEventListener('click', function() {
        localStorage.removeItem(_TAB_CONFIG_KEY);
        _tabConfig = {order: [], pinned: [], hidden: []};
        _applyTabOrder();
        _closeTabCtxMenu();
        location.reload();
    });
    menu.appendChild(reset);

    var rect = anchor.getBoundingClientRect();
    menu.style.left = rect.left + 'px';
    menu.style.top = (rect.bottom + 4) + 'px';
    document.body.appendChild(menu);

    setTimeout(function() {
        document.addEventListener('click', _closeTabCtxMenu, {once: true});
    }, 10);
}

function _setupTabDragDrop() {
    var nav = document.querySelector('.sidebar-nav');
    if (!nav) return;

    var dragItem = null;

    nav.addEventListener('dragstart', function(e) {
        var item = e.target.closest('.nav-item[data-tab]');
        if (!item) return;
        dragItem = item;
        item.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', item.dataset.tab);
    });

    nav.addEventListener('dragover', function(e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        var target = e.target.closest('.nav-item[data-tab]');
        nav.querySelectorAll('.nav-item').forEach(function(i) { i.classList.remove('drag-over'); });
        if (target && target !== dragItem) target.classList.add('drag-over');
    });

    nav.addEventListener('drop', function(e) {
        e.preventDefault();
        var target = e.target.closest('.nav-item[data-tab]');
        nav.querySelectorAll('.nav-item').forEach(function(i) { i.classList.remove('drag-over'); });
        if (!target || !dragItem || target === dragItem) return;

        // Reorder in DOM
        var items = Array.from(nav.querySelectorAll('.nav-item[data-tab]'));
        var dragIdx = items.indexOf(dragItem);
        var targetIdx = items.indexOf(target);
        if (dragIdx < targetIdx) {
            target.parentNode.insertBefore(dragItem, target.nextSibling);
        } else {
            target.parentNode.insertBefore(dragItem, target);
        }

        // Save new order
        var newItems = Array.from(nav.querySelectorAll('.nav-item[data-tab]'));
        _tabConfig.order = newItems.map(function(i) { return i.dataset.tab; });
        _saveTabConfig();
    });

    nav.addEventListener('dragend', function() {
        if (dragItem) dragItem.classList.remove('dragging');
        dragItem = null;
        nav.querySelectorAll('.nav-item').forEach(function(i) { i.classList.remove('drag-over'); });
    });

    // Context menu on right-click
    nav.addEventListener('contextmenu', function(e) {
        var item = e.target.closest('.nav-item[data-tab]');
        if (!item) return;
        e.preventDefault();
        _showTabCtxMenu(e.clientX, e.clientY, item.dataset.tab);
    });
}

function _showTabCtxMenu(x, y, tabName) {
    _closeTabCtxMenu();
    var menu = document.createElement('div');
    menu.className = 'tab-ctx-menu';
    menu.id = 'tabCtxMenu';

    var isPinned = _tabConfig.pinned.indexOf(tabName) >= 0;

    // Pin/Unpin
    var pinItem = document.createElement('button');
    pinItem.className = 'tab-ctx-item';
    pinItem.textContent = isPinned ? 'Unpin' : 'Pin to top';
    pinItem.addEventListener('click', function() {
        if (isPinned) {
            _tabConfig.pinned = _tabConfig.pinned.filter(function(t) { return t !== tabName; });
        } else {
            _tabConfig.pinned.push(tabName);
        }
        _saveTabConfig();
        _applyTabOrder();
        _closeTabCtxMenu();
    });
    menu.appendChild(pinItem);

    // Hide (don't allow hiding Dashboard)
    if (tabName !== 'morning-brief') {
        var hideItem = document.createElement('button');
        hideItem.className = 'tab-ctx-item';
        hideItem.textContent = 'Hide tab';
        hideItem.addEventListener('click', function() {
            if (_tabConfig.hidden.indexOf(tabName) < 0) _tabConfig.hidden.push(tabName);
            _saveTabConfig();
            _applyTabOrder();
            _closeTabCtxMenu();
        });
        menu.appendChild(hideItem);
    }

    // Reset
    var sep = document.createElement('div');
    sep.className = 'tab-ctx-sep';
    menu.appendChild(sep);
    var resetItem = document.createElement('button');
    resetItem.className = 'tab-ctx-item';
    resetItem.textContent = 'Reset layout';
    resetItem.style.color = 'var(--red)';
    resetItem.addEventListener('click', function() {
        localStorage.removeItem(_TAB_CONFIG_KEY);
        _tabConfig = {order: [], pinned: [], hidden: []};
        _applyTabOrder();
        _closeTabCtxMenu();
        location.reload();
    });
    menu.appendChild(resetItem);

    menu.style.left = x + 'px';
    menu.style.top = y + 'px';
    document.body.appendChild(menu);

    // Ensure menu stays within viewport
    var rect = menu.getBoundingClientRect();
    if (rect.right > window.innerWidth) menu.style.left = (window.innerWidth - rect.width - 8) + 'px';
    if (rect.bottom > window.innerHeight) menu.style.top = (window.innerHeight - rect.height - 8) + 'px';

    setTimeout(function() {
        document.addEventListener('click', _closeTabCtxMenu, {once: true});
    }, 10);
}

function _closeTabCtxMenu() {
    var m = document.getElementById('tabCtxMenu');
    if (m) m.remove();
    var m2 = document.getElementById('tabOverflowMenu');
    if (m2) m2.remove();
}

document.addEventListener('DOMContentLoaded', init);

// ═══ DASHBOARD-DATA-LAYER: COMMITMENTS + BROWSER TABS ═══

function _injectDataLayerCSS() {
    if (document.getElementById('data-layer-css')) return;
    var s = document.createElement('style');
    s.id = 'data-layer-css';
    s.textContent = [
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

// ═══ DOCUMENTS TAB ═══

var _docsSearch = '';
var _docsTypeFilter = '';
var _docsMatterFilter = '';
var _docsOffset = 0;
var _docsDebounceTimer = null;

async function loadDocumentsTab() {
    _docsOffset = 0;
    _buildDocsToolbar();
    await _fetchDocs();
}

function _buildDocsToolbar() {
    var toolbar = document.getElementById('docsToolbar');
    if (!toolbar) return;
    toolbar.textContent = '';

    // Search input
    var searchInput = document.createElement('input');
    searchInput.type = 'text';
    searchInput.placeholder = 'Search documents...';
    searchInput.value = _docsSearch;
    searchInput.style.cssText = 'flex:1;min-width:200px;padding:6px 10px;border:1px solid var(--border);border-radius:6px;font-size:12px;font-family:var(--font);outline:none;background:var(--bg1);color:var(--text);';
    searchInput.addEventListener('input', function() {
        clearTimeout(_docsDebounceTimer);
        _docsDebounceTimer = setTimeout(function() {
            _docsSearch = searchInput.value;
            _docsOffset = 0;
            _fetchDocs();
        }, 300);
    });
    toolbar.appendChild(searchInput);

    // Type filter
    var typeSelect = document.createElement('select');
    typeSelect.style.cssText = 'font-size:11px;padding:5px 8px;border:1px solid var(--border);border-radius:6px;background:var(--bg1);color:var(--text);font-family:var(--font);';
    var typeDefault = document.createElement('option');
    typeDefault.value = '';
    typeDefault.textContent = 'All types';
    typeSelect.appendChild(typeDefault);
    var types = ['contract', 'invoice', 'correspondence', 'report', 'proposal', 'legal', 'financial', 'presentation', 'minutes', 'agreement', 'certificate', 'receipt', 'travel_booking', 'other'];
    for (var ti = 0; ti < types.length; ti++) {
        var opt = document.createElement('option');
        opt.value = types[ti];
        opt.textContent = types[ti].replace(/_/g, ' ');
        if (types[ti] === _docsTypeFilter) opt.selected = true;
        typeSelect.appendChild(opt);
    }
    typeSelect.addEventListener('change', function() {
        _docsTypeFilter = typeSelect.value;
        _docsOffset = 0;
        _fetchDocs();
    });
    toolbar.appendChild(typeSelect);

    // Matter filter
    var matterSelect = document.createElement('select');
    matterSelect.style.cssText = 'font-size:11px;padding:5px 8px;border:1px solid var(--border);border-radius:6px;background:var(--bg1);color:var(--text);font-family:var(--font);';
    var matterDefault = document.createElement('option');
    matterDefault.value = '';
    matterDefault.textContent = 'All matters';
    matterSelect.appendChild(matterDefault);
    matterSelect.addEventListener('change', function() {
        _docsMatterFilter = matterSelect.value;
        _docsOffset = 0;
        _fetchDocs();
    });
    // Populate matters from existing sidebar matters list
    var matterItems = document.querySelectorAll('.nav-sub .nav-item[data-tab]');
    matterItems.forEach(function(item) {
        var slug = (item.dataset.tab || '').replace('matter-', '');
        if (slug) {
            var opt = document.createElement('option');
            opt.value = slug;
            opt.textContent = slug.replace(/_/g, ' ');
            if (slug === _docsMatterFilter) opt.selected = true;
            matterSelect.appendChild(opt);
        }
    });
    toolbar.appendChild(matterSelect);
}

async function _fetchDocs() {
    var container = document.getElementById('docsContent');
    if (!container) return;

    if (_docsOffset === 0) {
        showLoading(container, 'Loading documents');
    }

    var params = new URLSearchParams();
    if (_docsSearch) params.set('search', _docsSearch);
    if (_docsTypeFilter) params.set('doc_type', _docsTypeFilter);
    if (_docsMatterFilter) params.set('matter_slug', _docsMatterFilter);
    params.set('limit', '20');
    params.set('offset', String(_docsOffset));

    try {
        var r = await bakerFetch('/api/documents?' + params.toString());
        if (!r.ok) throw new Error('API ' + r.status);
        var data = await r.json();

        // Stats header
        if (data.stats && _docsOffset === 0) {
            var statsEl = document.getElementById('docsStats');
            if (statsEl) {
                statsEl.textContent = (data.stats.total_docs || 0) + ' documents | '
                    + (data.stats.type_count || 0) + ' types'
                    + (data.stats.top_matter ? ' | Top matter: ' + data.stats.top_matter : '');
            }
            var countEl = document.getElementById('docsCount');
            if (countEl) countEl.textContent = data.stats.total_docs || '';
        }

        if (_docsOffset === 0) container.textContent = '';

        var docs = data.documents || [];
        if (docs.length === 0 && _docsOffset === 0) {
            container.textContent = '';
            var empty = document.createElement('div');
            empty.style.cssText = 'color:var(--text3);font-size:13px;padding:20px 0;';
            empty.textContent = _docsSearch ? 'No documents matching "' + _docsSearch + '".' : 'No documents found.';
            container.appendChild(empty);
            return;
        }

        for (var i = 0; i < docs.length; i++) {
            container.appendChild(_createDocCard(docs[i]));
        }

        // Load more button
        var existingMore = container.querySelector('.load-more-btn');
        if (existingMore) existingMore.remove();

        if (data.total > _docsOffset + docs.length) {
            var moreBtn = document.createElement('button');
            moreBtn.className = 'load-more-btn';
            moreBtn.style.cssText = 'display:block;margin:12px auto;padding:8px 20px;font-size:12px;border:1px solid var(--border);border-radius:6px;background:var(--bg1);color:var(--text2);cursor:pointer;font-family:var(--font);';
            moreBtn.textContent = 'Load more (' + (data.total - _docsOffset - docs.length) + ' remaining)';
            moreBtn.addEventListener('click', function() {
                _docsOffset += 20;
                _fetchDocs();
            });
            container.appendChild(moreBtn);
        }
    } catch (e) {
        if (_docsOffset === 0) {
            container.textContent = '';
            var err = document.createElement('div');
            err.style.cssText = 'color:var(--red);font-size:13px;';
            err.textContent = 'Failed to load documents.';
            container.appendChild(err);
        }
    }
}

function _createDocCard(doc) {
    var card = document.createElement('div');
    card.className = 'card';
    card.style.cssText = 'margin-bottom:8px;cursor:pointer;';

    // Header
    var header = document.createElement('div');
    header.className = 'card-header';
    header.style.cssText = 'display:flex;align-items:center;gap:8px;';

    // Type badge
    if (doc.doc_type) {
        var typeBadge = document.createElement('span');
        typeBadge.style.cssText = 'font-size:9px;font-weight:600;padding:2px 6px;border-radius:4px;background:var(--blue-bg);color:var(--blue);text-transform:uppercase;flex-shrink:0;';
        typeBadge.textContent = doc.doc_type.replace(/_/g, ' ');
        header.appendChild(typeBadge);
    }

    // Filename
    var fname = document.createElement('span');
    fname.style.cssText = 'font-size:12px;font-weight:500;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;';
    fname.textContent = doc.filename || 'Untitled';
    header.appendChild(fname);

    // Date
    if (doc.ingested_at) {
        var dateSpan = document.createElement('span');
        dateSpan.style.cssText = 'font-size:10px;color:var(--text3);flex-shrink:0;';
        try {
            var d = new Date(doc.ingested_at);
            dateSpan.textContent = d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
        } catch (e) { dateSpan.textContent = ''; }
        header.appendChild(dateSpan);
    }

    card.appendChild(header);

    // Matter tag
    if (doc.matter_slug) {
        var matterTag = document.createElement('div');
        matterTag.style.cssText = 'font-size:10px;color:var(--text3);margin-top:2px;';
        matterTag.textContent = doc.matter_slug.replace(/_/g, ' ');
        card.appendChild(matterTag);
    }

    // Preview (collapsed by default)
    var previewDiv = document.createElement('div');
    previewDiv.style.cssText = 'display:none;font-size:11px;color:var(--text2);margin-top:6px;line-height:1.5;border-top:1px solid var(--border-light);padding-top:6px;white-space:pre-wrap;max-height:200px;overflow-y:auto;';
    previewDiv.textContent = doc.text_preview || '';
    card.appendChild(previewDiv);

    // Click to expand/collapse
    card.addEventListener('click', function() {
        var showing = previewDiv.style.display !== 'none';
        previewDiv.style.display = showing ? 'none' : 'block';
    });

    return card;
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

// ═══ DOSSIERS TAB ═══

async function loadDossiersTab() {
    var container = document.getElementById('dossiersContent');
    if (!container) return;
    showLoading(container, 'Loading dossiers');

    try {
        var data = await bakerFetch('/api/research-proposals?days=90').then(function(r) { return r.json(); });
        var proposals = data.proposals || [];

        // Update badge
        var completedCount = proposals.filter(function(p) { return p.status === 'completed'; }).length;
        var badge = document.getElementById('dossiersCount');
        if (badge) badge.textContent = completedCount || '';

        if (proposals.length === 0) {
            container.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text3);">No research dossiers yet. Baker auto-proposes dossiers when VIPs forward intelligence.</div>';
            return;
        }

        var wrapper = document.createElement('div');
        wrapper.style.cssText = 'display:flex;flex-direction:column;gap:8px;';

        for (var i = 0; i < proposals.length; i++) {
            var p = proposals[i];
            wrapper.appendChild(_renderDossierCard(p));
        }

        container.textContent = '';
        container.appendChild(wrapper);

    } catch (err) {
        container.innerHTML = '<div style="padding:20px;color:var(--red);">Failed to load dossiers: ' + esc(err.message) + '</div>';
    }
}

function _renderDossierCard(p) {
    var card = document.createElement('div');
    card.className = 'dossier-card';

    var statusColors = {
        completed: 'var(--green)',
        failed: 'var(--red)',
        running: 'var(--amber)',
        approved: 'var(--amber)',
        proposed: 'var(--blue)',
        skipped: 'var(--text3)'
    };
    var statusLabels = {
        completed: 'Completed',
        failed: 'Failed',
        running: 'Running...',
        approved: 'Approved',
        proposed: 'Proposed',
        skipped: 'Skipped'
    };

    var color = statusColors[p.status] || 'var(--text3)';
    var label = statusLabels[p.status] || p.status;

    // Header row: subject + status badge
    var header = document.createElement('div');
    header.style.cssText = 'display:flex;align-items:center;justify-content:space-between;gap:12px;';

    var title = document.createElement('div');
    title.style.cssText = 'font-weight:600;font-size:14px;color:var(--text);';
    title.textContent = p.subject_name || 'Unknown';
    header.appendChild(title);

    var badge = document.createElement('span');
    badge.style.cssText = 'font-size:11px;font-weight:600;padding:3px 10px;border-radius:12px;white-space:nowrap;color:#fff;background:' + color + ';';
    badge.textContent = label;
    header.appendChild(badge);

    card.appendChild(header);

    // Meta row: type, date, specialists
    var meta = document.createElement('div');
    meta.style.cssText = 'font-size:12px;color:var(--text2);margin-top:4px;display:flex;gap:16px;flex-wrap:wrap;';

    if (p.subject_type) {
        var typeSpan = document.createElement('span');
        typeSpan.textContent = p.subject_type;
        meta.appendChild(typeSpan);
    }

    var dateStr = p.completed_at || p.approved_at || p.created_at || '';
    if (dateStr) {
        var dateSpan = document.createElement('span');
        dateSpan.textContent = dateStr.substring(0, 10);
        meta.appendChild(dateSpan);
    }

    if (p.specialists) {
        var specs = typeof p.specialists === 'string' ? JSON.parse(p.specialists) : p.specialists;
        if (specs && specs.length) {
            var specSpan = document.createElement('span');
            specSpan.style.color = 'var(--text3)';
            specSpan.textContent = specs.join(', ');
            meta.appendChild(specSpan);
        }
    }

    card.appendChild(meta);

    // Error message for failed
    if (p.status === 'failed' && p.error_message) {
        var errDiv = document.createElement('div');
        errDiv.style.cssText = 'font-size:11px;color:var(--red);margin-top:6px;padding:6px 10px;background:rgba(220,49,48,0.06);border-radius:6px;';
        errDiv.textContent = p.error_message;
        card.appendChild(errDiv);
    }

    // Action buttons
    var actions = document.createElement('div');
    actions.style.cssText = 'display:flex;gap:8px;margin-top:8px;';

    if (p.status === 'completed') {
        var dlBtn = document.createElement('button');
        dlBtn.className = 'dossier-btn dossier-btn-primary';
        dlBtn.textContent = 'Download .docx';
        dlBtn.onclick = function() {
            window.open('/api/research-proposals/' + p.id + '/download?key=' + encodeURIComponent(BAKER_CONFIG.apiKey), '_blank');
        };
        actions.appendChild(dlBtn);
    }

    if (p.status === 'failed' || p.status === 'completed') {
        var retryBtn = document.createElement('button');
        retryBtn.className = 'dossier-btn';
        retryBtn.textContent = p.status === 'failed' ? 'Retry' : 'Regenerate';
        retryBtn.onclick = function() {
            _retryDossier(p.id, retryBtn);
        };
        actions.appendChild(retryBtn);
    }

    if (p.status === 'proposed') {
        var runBtn = document.createElement('button');
        runBtn.className = 'dossier-btn dossier-btn-primary';
        runBtn.textContent = 'Run Dossier';
        runBtn.onclick = function() {
            _respondDossier(p.id, 'approved', runBtn);
        };
        actions.appendChild(runBtn);

        var skipBtn = document.createElement('button');
        skipBtn.className = 'dossier-btn';
        skipBtn.textContent = 'Skip';
        skipBtn.onclick = function() {
            _respondDossier(p.id, 'skipped', skipBtn);
        };
        actions.appendChild(skipBtn);
    }

    if (p.status === 'running') {
        var spinDiv = document.createElement('div');
        spinDiv.style.cssText = 'font-size:12px;color:var(--amber);';
        spinDiv.textContent = 'Generating dossier...';
        actions.appendChild(spinDiv);
        // Auto-poll for completion
        _pollDossierTabStatus(p.id);
    }

    card.appendChild(actions);
    return card;
}

async function _retryDossier(proposalId, btn) {
    btn.disabled = true;
    btn.textContent = 'Retrying...';
    try {
        var resp = await bakerFetch('/api/research-proposals/' + proposalId + '/retry', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        if (resp.ok) {
            setTimeout(function() { loadDossiersTab(); }, 1000);
        } else {
            var err = await resp.json();
            alert('Retry failed: ' + (err.detail || 'Unknown error'));
            btn.disabled = false;
            btn.textContent = 'Retry';
        }
    } catch (e) {
        alert('Retry failed: ' + e.message);
        btn.disabled = false;
        btn.textContent = 'Retry';
    }
}

async function _respondDossier(proposalId, response, btn) {
    btn.disabled = true;
    btn.textContent = response === 'approved' ? 'Starting...' : 'Skipping...';
    try {
        var resp = await bakerFetch('/api/research-proposals/' + proposalId + '/respond', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ response: response }),
        });
        if (resp.ok) {
            setTimeout(function() { loadDossiersTab(); }, 1000);
        } else {
            var err = await resp.json();
            alert('Action failed: ' + (err.detail || 'Unknown error'));
            btn.disabled = false;
        }
    } catch (e) {
        alert('Action failed: ' + e.message);
        btn.disabled = false;
    }
}

function _pollDossierTabStatus(proposalId) {
    var interval = setInterval(async function() {
        try {
            var resp = await bakerFetch('/api/research-proposals/' + proposalId + '/status');
            if (!resp.ok) { clearInterval(interval); return; }
            var data = await resp.json();
            if (data.status === 'completed' || data.status === 'failed') {
                clearInterval(interval);
                loadDossiersTab();
            }
        } catch (e) {
            clearInterval(interval);
        }
    }, 5000);
    // Stop polling after 5 minutes
    setTimeout(function() { clearInterval(interval); }, 300000);
}

async function loadBrowserTab() {
    _injectDataLayerCSS();
    var container = document.getElementById('browserContent');
    if (!container) return;
    showLoading(container, 'Loading browser monitor');

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

// ═══ DOCUMENT UPLOAD (SPECIALIST-UPGRADE-1B) ═══

function setupDocumentUpload(fileInputId, statusId, viewId) {
    var fileInput = document.getElementById(fileInputId);
    if (!fileInput) return;

    // File picker change handler
    fileInput.addEventListener('change', function() {
        if (fileInput.files.length > 0) {
            uploadDocument(fileInput.files[0], statusId);
            fileInput.value = '';
        }
    });

    // Drag-and-drop on the view body
    var viewEl = document.getElementById(viewId);
    if (!viewEl) return;
    var body = viewEl.querySelector('.scan-view-body');
    if (!body) return;

    body.addEventListener('dragover', function(e) {
        e.preventDefault();
        body.classList.add('drag-over');
    });
    body.addEventListener('dragleave', function() {
        body.classList.remove('drag-over');
    });
    body.addEventListener('drop', function(e) {
        e.preventDefault();
        body.classList.remove('drag-over');
        if (e.dataTransfer.files.length > 0) {
            uploadDocument(e.dataTransfer.files[0], statusId);
        }
    });
}

async function uploadDocument(file, statusId) {
    var statusEl = document.getElementById(statusId);
    if (!statusEl) return;

    // Validate extension
    var ext = file.name.split('.').pop().toLowerCase();
    var allowed = ['pdf', 'docx', 'xlsx', 'csv', 'txt', 'png', 'jpg'];
    if (allowed.indexOf(ext) === -1) {
        showUploadStatus(statusEl, 'error', 'Unsupported file type: .' + ext);
        return;
    }

    // Show uploading state
    showUploadStatus(statusEl, 'uploading', 'Uploading ' + file.name + '...');

    try {
        var formData = new FormData();
        formData.append('file', file);

        // Update status through stages
        showUploadStatus(statusEl, 'uploading', 'Extracting text from ' + file.name + '...');

        var resp = await fetch('/api/documents/upload', {
            method: 'POST',
            headers: { 'X-Baker-Key': BAKER_CONFIG.apiKey },
            body: formData,
        });

        if (!resp.ok) {
            var err = await resp.json().catch(function() { return { detail: 'Upload failed' }; });
            showUploadStatus(statusEl, 'error', err.detail || 'Upload failed (HTTP ' + resp.status + ')');
            return;
        }

        var data = await resp.json();
        var summary = 'Uploaded: ' + data.filename;
        if (data.document_type) summary += ' — ' + data.document_type;
        if (data.matter_slug) summary += ', matter: ' + data.matter_slug;
        if (data.parties && data.parties.length > 0) summary += ', parties: ' + data.parties.join(', ');

        showUploadStatus(statusEl, 'success', summary);

        // Auto-hide after 10s
        setTimeout(function() {
            statusEl.hidden = true;
        }, 10000);

    } catch (e) {
        showUploadStatus(statusEl, 'error', 'Upload failed: ' + e.message);
    }
}

function showUploadStatus(el, state, message) {
    el.hidden = false;
    el.className = 'upload-status ' + state;
    el.textContent = message;
}

// ═══ TRIP-INTELLIGENCE-1: Full-screen Trip View ═══
// All user-provided values escaped via esc() (DOM-based HTML escaper at line 299)

var _tripStatusColors = { planned: 'var(--blue, #0a6fdb)', confirmed: 'var(--green, #22c55e)', discarded: 'var(--red, #ef4444)', completed: 'var(--amber, #f59e0b)' };
var _tripCategoryLabels = { meeting: 'Meeting', event: 'Event', personal: 'Personal' };
var _currentTripId = null;

async function showTripView(tripId) {
    _currentTripId = tripId;
    var container = document.getElementById('tripDetailContent');
    var tripView = document.getElementById('viewTripDetail');
    if (!container || !tripView) return;

    // Hide all views, show trip view
    document.querySelectorAll('.view').forEach(function(v) { v.classList.remove('active'); v.style.display = ''; });
    tripView.classList.add('active');
    container.textContent = 'Loading trip...';

    // Show back button
    var backBtn = document.getElementById('cmdBack');
    if (backBtn) backBtn.hidden = false;

    try {
        var resp = await bakerFetch('/api/trips/' + tripId);
        if (!resp.ok) {
            container.textContent = 'Trip not found.';
            return;
        }
        var trip = await resp.json();
        setSafeHTML(container, renderTripView(trip));
        // Batch 2: Load trip card data async
        loadTripCards(trip.id);
    } catch (e) {
        container.textContent = 'Failed to load trip: ' + e.message;
    }
}

function hideTripView() {
    var tripView = document.getElementById('viewTripDetail');
    if (tripView) {
        tripView.style.display = '';
        tripView.classList.remove('active');
    }
    switchTab('morning-brief');
}

function renderTripView(trip) {
    var statusColor = _tripStatusColors[trip.status] || 'var(--text3)';
    var startStr = trip.start_date || '';
    var endStr = trip.end_date || '';
    var dateRange = startStr;
    if (endStr && endStr !== startStr) dateRange += ' — ' + endStr;

    var html = '';

    // Back button
    html += '<div style="margin-bottom:16px;">';
    html += '<button onclick="hideTripView()" style="background:none;border:none;color:var(--blue);cursor:pointer;font-size:13px;font-family:var(--font);padding:0;">&larr; Back to Dashboard</button>';
    html += '</div>';

    // Header
    html += '<div style="margin-bottom:24px;">';
    html += '<div style="display:flex;align-items:baseline;gap:12px;margin-bottom:8px;">';
    html += '<h2 style="margin:0;font-size:22px;font-weight:700;">' + esc(trip.destination || 'Trip') + '</h2>';
    html += '<span style="color:' + statusColor + ';font-size:13px;font-weight:600;text-transform:capitalize;">' + esc(trip.status || 'planned') + '</span>';
    html += '</div>';
    if (dateRange) html += '<div style="font-size:13px;color:var(--text3);margin-bottom:4px;">' + esc(dateRange) + '</div>';
    if (trip.origin) html += '<div style="font-size:13px;color:var(--text3);">From: ' + esc(trip.origin) + '</div>';
    if (trip.event_name) html += '<div style="font-size:13px;color:var(--text2);margin-top:4px;">' + esc(trip.event_name) + '</div>';
    html += '</div>';

    // Status + Category controls
    html += '<div style="display:flex;gap:24px;margin-bottom:24px;flex-wrap:wrap;">';

    // Status buttons
    html += '<div><span style="font-size:11px;color:var(--text3);text-transform:uppercase;letter-spacing:0.5px;">Status</span><div style="display:flex;gap:6px;margin-top:6px;">';
    ['planned', 'confirmed', 'completed', 'discarded'].forEach(function(s) {
        var active = trip.status === s;
        var col = _tripStatusColors[s];
        html += '<button onclick="updateTripField(' + trip.id + ',\'' + s + '\',\'status\')" style="font-size:12px;font-family:var(--font);padding:4px 10px;border-radius:4px;cursor:pointer;border:1px solid ' + (active ? col : 'var(--border)') + ';background:' + (active ? col : 'transparent') + ';color:' + (active ? '#fff' : 'var(--text2)') + ';">' + s.charAt(0).toUpperCase() + s.slice(1) + '</button>';
    });
    html += '</div></div>';

    // Category buttons
    html += '<div><span style="font-size:11px;color:var(--text3);text-transform:uppercase;letter-spacing:0.5px;">Category</span><div style="display:flex;gap:6px;margin-top:6px;">';
    ['meeting', 'event', 'personal'].forEach(function(c) {
        var active = trip.category === c;
        html += '<button onclick="updateTripField(' + trip.id + ',\'' + c + '\',\'category\')" style="font-size:12px;font-family:var(--font);padding:4px 10px;border-radius:4px;cursor:pointer;border:1px solid ' + (active ? 'var(--blue)' : 'var(--border)') + ';background:' + (active ? 'var(--blue)' : 'transparent') + ';color:' + (active ? '#fff' : 'var(--text2)') + ';">' + esc(_tripCategoryLabels[c]) + '</button>';
    });
    html += '</div></div>';
    html += '</div>';

    // Strategic objective
    html += '<div style="margin-bottom:24px;">';
    html += '<div style="font-size:11px;color:var(--text3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">Strategic Objective</div>';
    html += '<div id="tripObjective" style="font-size:13px;color:var(--text2);padding:10px 12px;background:var(--bg2);border-radius:6px;min-height:36px;cursor:pointer;" onclick="editTripObjective(' + trip.id + ')" title="Click to edit">';
    html += trip.strategic_objective ? esc(trip.strategic_objective) : '<span style="color:var(--text3);font-style:italic;">Click to add objective...</span>';
    html += '</div></div>';

    // TRIP-INTELLIGENCE-1 Batch 2: Trip cards (loaded async)
    html += '<div id="tripCards-' + trip.id + '" style="margin-bottom:24px;">';
    html += '<div style="font-size:11px;color:var(--text3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;">Trip Intelligence</div>';
    html += '<div style="color:var(--text3);font-size:12px;">Loading trip cards...</div>';
    html += '</div>';

    // Notes section
    html += '<div style="margin-bottom:24px;">';
    html += '<div style="font-size:11px;color:var(--text3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">Notes</div>';
    var notes = trip.notes || [];
    if (notes.length > 0) {
        notes.forEach(function(n) {
            var ts = n.timestamp ? new Date(n.timestamp).toLocaleDateString() : '';
            html += '<div style="padding:8px 12px;background:var(--bg2);border-radius:6px;margin-bottom:6px;font-size:13px;">';
            html += '<div style="color:var(--text1);">' + esc(n.text || '') + '</div>';
            if (ts || n.source) html += '<div style="font-size:11px;color:var(--text3);margin-top:2px;">' + esc(ts) + (n.source ? ' · ' + esc(n.source) : '') + '</div>';
            html += '</div>';
        });
    }
    html += '<form onsubmit="addTripNote(event,' + trip.id + ')" style="display:flex;gap:8px;margin-top:8px;">';
    html += '<input id="tripNoteInput" type="text" placeholder="Add a note..." style="flex:1;padding:8px 12px;border:1px solid var(--border);border-radius:6px;font-size:13px;font-family:var(--font);outline:none;background:var(--bg1);color:var(--text1);" />';
    html += '<button type="submit" style="padding:6px 14px;background:var(--blue);color:#fff;border:none;border-radius:6px;font-size:12px;font-family:var(--font);cursor:pointer;">Add</button>';
    html += '</form>';
    html += '</div>';

    // Trip Contacts section removed — now shown in People to Meet card (Batch 3)

    return html;
}

async function updateTripField(tripId, value, field) {
    try {
        var body = {};
        body[field] = value;
        var resp = await bakerFetch('/api/trips/' + tripId, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (resp.ok) showTripView(tripId);  // Refresh
    } catch (e) {
        console.error('Failed to update trip:', e);
    }
}

async function addTripNote(event, tripId) {
    event.preventDefault();
    var input = document.getElementById('tripNoteInput');
    if (!input || !input.value.trim()) return;
    try {
        var resp = await bakerFetch('/api/trips/' + tripId + '/note', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: input.value.trim() }),
        });
        if (resp.ok) {
            input.value = '';
            showTripView(tripId);  // Refresh
        }
    } catch (e) {
        console.error('Failed to add note:', e);
    }
}

async function editTripObjective(tripId) {
    var el = document.getElementById('tripObjective');
    if (!el) return;
    var current = el.textContent.trim();
    if (current === 'Click to add objective...') current = '';
    var newVal = prompt('Strategic objective for this trip:', current);
    if (newVal === null) return;
    try {
        var resp = await bakerFetch('/api/trips/' + tripId, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ strategic_objective: newVal }),
        });
        if (resp.ok) showTripView(tripId);
    } catch (e) {
        console.error('Failed to update objective:', e);
    }
}

// ═══ TRIP-INTELLIGENCE-1 Batch 2: Trip Card Renderers ═══
// All user content escaped via esc()

async function loadTripCards(tripId) {
    var container = document.getElementById('tripCards-' + tripId);
    if (!container) return;
    try {
        var resp = await bakerFetch('/api/trips/' + tripId + '/cards');
        if (!resp.ok) {
            container.textContent = 'Failed to load trip cards.';
            return;
        }
        var cards = await resp.json();
        var html = '';
        html += renderTripCardSection('Logistics & Comms', renderLogisticsCard(cards.logistics || {}));
        html += renderTripCardSection('Daily Agenda', renderAgendaCard(cards.agenda || {}));
        html += renderTripCardSection('People to Meet (' + (cards.people || []).length + ')', renderPeopleCard(cards.people || []));
        html += renderTripCardSection('Flight Reading', renderReadingCard(cards.reading || {}));
        html += renderTripCardSection('Opportunistic Radar', renderRadarCard(cards.radar || {}));
        html += renderTripCardSection('Europe While You Sleep', renderTimezoneCard(cards.timezone || {}));
        html += renderTripCardSection('Outreach', renderOutreachCard(cards.people || []));
        html += renderTripCardSection('Trip Outcomes', '<div style="font-size:12px;color:var(--text3);">Coming in Batch 4</div>');
        setSafeHTML(container, '<div style="font-size:11px;color:var(--text3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;">Trip Intelligence</div>' + html);
    } catch (e) {
        container.textContent = 'Failed to load trip cards.';
        console.error('Trip cards error:', e);
    }
}

function renderTripCardSection(title, content) {
    return '<div style="margin-bottom:12px;background:var(--bg2);border-radius:8px;border:1px solid var(--border);overflow:hidden;">' +
        '<div style="padding:12px 16px;font-size:13px;font-weight:600;color:var(--text1);border-bottom:1px solid var(--border);cursor:pointer;" onclick="var b=this.nextElementSibling;b.style.display=b.style.display===\'none\'?\'block\':\'none\'">' +
        esc(title) + ' <span style="font-size:10px;color:var(--text3);float:right;">&#9662;</span></div>' +
        '<div style="padding:12px 16px;">' + content + '</div></div>';
}

function renderLogisticsCard(data) {
    var html = '';
    // Timezone info
    var tz = data.timezone || {};
    if (tz.diff) {
        html += '<div style="font-size:12px;color:var(--text2);margin-bottom:12px;padding:8px 10px;background:var(--bg1);border-radius:6px;">';
        html += 'Local time: <strong>' + esc(tz.local_now || '?') + '</strong>';
        html += ' &middot; Home (Zurich): ' + esc(tz.home_now || '?');
        html += ' &middot; Diff: <strong>' + esc(tz.diff) + '</strong>';
        html += '</div>';
    }
    // Emails
    var emails = data.emails || [];
    if (emails.length > 0) {
        html += '<div style="font-size:10px;color:var(--text3);text-transform:uppercase;margin-bottom:6px;">Emails (' + emails.length + ')</div>';
        emails.forEach(function(e) {
            html += '<div style="font-size:12px;margin-bottom:6px;padding:6px 0;border-bottom:1px solid var(--border-light);">';
            html += '<div style="font-weight:500;color:var(--text1);">' + esc(e.subject || 'No subject') + '</div>';
            html += '<div style="color:var(--text3);font-size:11px;">' + esc(e.sender_name || '') + ' &middot; ' + (e.received_date ? new Date(e.received_date).toLocaleDateString() : '') + '</div>';
            html += '</div>';
        });
    }
    // WhatsApp
    var wa = data.whatsapp || [];
    if (wa.length > 0) {
        html += '<div style="font-size:10px;color:var(--text3);text-transform:uppercase;margin:12px 0 6px;">WhatsApp (' + wa.length + ')</div>';
        wa.forEach(function(m) {
            html += '<div style="font-size:12px;margin-bottom:6px;padding:6px 0;border-bottom:1px solid var(--border-light);">';
            html += '<strong style="color:var(--text2);">' + esc(m.sender_name || '') + '</strong> ';
            html += '<span style="color:var(--text3);">' + esc(m.snippet || '').substring(0, 150) + '</span>';
            html += '</div>';
        });
    }
    if (!emails.length && !wa.length) html += '<div style="font-size:12px;color:var(--text3);">No logistics messages found for this destination.</div>';
    return html;
}

function renderAgendaCard(data) {
    var days = data.days || [];
    if (days.length === 0) return '<div style="font-size:12px;color:var(--text3);">No calendar events for this trip period.</div>';
    var html = '';
    days.forEach(function(day) {
        html += '<div style="font-size:11px;font-weight:600;color:var(--text3);text-transform:uppercase;margin:10px 0 6px;">' + esc(day.date) + '</div>';
        (day.events || []).forEach(function(ev) {
            var startTime = '';
            try { startTime = new Date(ev.start).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}); } catch(e) {}
            html += '<div style="display:flex;gap:8px;margin-bottom:6px;font-size:12px;">';
            html += '<span style="color:var(--text3);min-width:50px;">' + esc(startTime) + '</span>';
            html += '<span style="color:var(--text1);">' + esc(ev.title || '') + '</span>';
            if (ev.location) html += ' <span style="color:var(--text3);">@ ' + esc(ev.location) + '</span>';
            html += '</div>';
        });
    });
    return html;
}

function renderReadingCard(data) {
    var docs = data.documents || [];
    if (docs.length === 0) return '<div style="font-size:12px;color:var(--text3);">No priority documents found.</div>';
    var html = '';
    var typeColors = { legal_opinion: 'var(--red)', financial_model: 'var(--blue)', report: 'var(--green)', proposal: 'var(--amber)', contract: 'var(--text3)' };
    docs.forEach(function(d) {
        var col = typeColors[d.document_type] || 'var(--text3)';
        html += '<div style="font-size:12px;margin-bottom:8px;padding:8px 0;border-bottom:1px solid var(--border-light);">';
        html += '<span style="font-size:9px;font-weight:600;color:' + col + ';background:var(--bg1);padding:1px 5px;border-radius:3px;margin-right:6px;">' + esc((d.document_type || '').replace(/_/g, ' ').toUpperCase()) + '</span>';
        html += '<span style="color:var(--text1);font-weight:500;">' + esc(d.filename || 'Document') + '</span>';
        if (d.ingested_at) html += '<div style="font-size:11px;color:var(--text3);margin-top:2px;">' + new Date(d.ingested_at).toLocaleDateString() + '</div>';
        html += '</div>';
    });
    return html;
}

function renderRadarCard(data) {
    var contacts = data.dormant_contacts || [];
    if (contacts.length === 0) return '<div style="font-size:12px;color:var(--text3);">No dormant contacts found in this destination.</div>';
    var html = '';
    contacts.forEach(function(c) {
        var daysStr = c.days_since_contact ? c.days_since_contact + ' days ago' : 'Never contacted';
        var dotClass = c.days_since_contact && c.days_since_contact < 60 ? 'amber' : 'red';
        html += '<div style="display:flex;align-items:center;gap:8px;font-size:12px;margin-bottom:6px;padding:6px 0;border-bottom:1px solid var(--border-light);">';
        html += '<span class="nav-dot ' + dotClass + '" style="margin-top:1px;"></span>';
        html += '<span style="color:var(--text1);font-weight:500;">' + esc(c.name || '') + '</span>';
        if (c.role) html += '<span style="color:var(--text3);">(' + esc(c.role) + ')</span>';
        html += '<span style="color:var(--text3);margin-left:auto;font-size:11px;">' + esc(daysStr) + '</span>';
        html += '</div>';
    });
    return html;
}

function renderTimezoneCard(data) {
    var html = '';
    var tz = data.timezone || {};
    if (tz.diff) {
        html += '<div style="font-size:12px;color:var(--text2);margin-bottom:12px;padding:8px 10px;background:var(--bg1);border-radius:6px;">';
        html += 'Destination: <strong>' + esc(tz.local_now || '?') + '</strong>';
        html += ' &middot; Zurich: ' + esc(tz.home_now || '?');
        html += ' &middot; ' + esc(tz.diff) + ' from home';
        html += '</div>';
    }
    // VIP messages
    var msgs = data.vip_messages || [];
    if (msgs.length > 0) {
        html += '<div style="font-size:10px;color:var(--text3);text-transform:uppercase;margin-bottom:6px;">VIP Messages (last 24h)</div>';
        msgs.forEach(function(m) {
            html += '<div style="font-size:12px;margin-bottom:4px;"><strong>' + esc(m.sender_name || '') + ':</strong> ' + esc(m.snippet || '').substring(0, 120) + '</div>';
        });
    }
    // Urgent alerts
    var alerts = data.urgent_alerts || [];
    if (alerts.length > 0) {
        html += '<div style="font-size:10px;color:var(--text3);text-transform:uppercase;margin:10px 0 6px;">Urgent Alerts</div>';
        alerts.forEach(function(a) {
            html += '<div style="font-size:12px;margin-bottom:4px;color:var(--text1);">' + esc(a.title || '') + '</div>';
        });
    }
    // Deadlines
    var dls = data.deadlines || [];
    if (dls.length > 0) {
        html += '<div style="font-size:10px;color:var(--text3);text-transform:uppercase;margin:10px 0 6px;">Upcoming Deadlines</div>';
        dls.forEach(function(d) {
            html += '<div style="font-size:12px;margin-bottom:4px;">' + esc(d.description || '') + ' <span style="color:var(--text3);">(' + esc(d.due_date || '') + ')</span></div>';
        });
    }
    if (!msgs.length && !alerts.length && !dls.length) {
        html += '<div style="font-size:12px;color:var(--text3);">All quiet. No urgent items.</div>';
    }
    return html;
}

// ═══ TRIP-INTELLIGENCE-1 Batch 3: Card 4 — People to Meet ═══

function renderPeopleCard(people) {
    var html = '';
    if (!people || people.length === 0) {
        html += '<div style="font-size:12px;color:var(--text3);margin-bottom:8px;">No contacts linked to this trip yet.</div>';
    } else {
        people.forEach(function(p, idx) {
            var roiBg = (p.roi_score || 0) >= 8 ? 'var(--green, #22c55e)' : (p.roi_score || 0) >= 5 ? 'var(--amber, #f59e0b)' : 'var(--text3)';
            var tierDot = p.tier === 1 ? 'green' : p.tier === 2 ? 'amber' : 'gray';
            var panelId = 'people-detail-' + idx;

            // Header row (always visible)
            html += '<div style="border:1px solid var(--border);border-radius:6px;margin-bottom:8px;overflow:hidden;">';
            html += '<div onclick="var el=document.getElementById(\'' + panelId + '\');el.style.display=el.style.display===\'none\'?\'block\':\'none\'" style="display:flex;align-items:center;gap:8px;padding:10px 12px;cursor:pointer;background:var(--bg1);">';
            // Tier dot
            html += '<span class="nav-dot ' + tierDot + '" style="margin-top:1px;flex-shrink:0;"></span>';
            // Name
            html += '<span style="font-size:13px;font-weight:600;color:var(--text1);">' + esc(p.name) + '</span>';
            // Role
            if (p.role) html += '<span style="font-size:11px;color:var(--text3);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(p.role) + '</span>';
            // ROI badge
            if (p.roi_score) {
                html += '<span style="font-size:10px;font-weight:700;color:#fff;background:' + roiBg + ';padding:2px 7px;border-radius:10px;flex-shrink:0;">ROI ' + p.roi_score + '</span>';
            }
            // Outreach status pill
            if (p.outreach_status && p.outreach_status !== 'none') {
                var oCol = p.outreach_status === 'confirmed' ? 'var(--green)' : p.outreach_status === 'sent' ? 'var(--amber)' : 'var(--text3)';
                html += '<span style="font-size:10px;color:' + oCol + ';border:1px solid ' + oCol + ';padding:1px 6px;border-radius:8px;flex-shrink:0;">' + esc(p.outreach_status) + '</span>';
            }
            html += '<span style="font-size:10px;color:var(--text3);flex-shrink:0;">&#9662;</span>';
            html += '</div>';

            // Expandable detail panel (hidden by default)
            html += '<div id="' + panelId + '" style="display:none;padding:10px 12px;border-top:1px solid var(--border);">';

            // Notes / context
            if (p.notes) {
                html += '<div style="font-size:12px;color:var(--text2);margin-bottom:10px;padding:8px;background:var(--bg2);border-radius:4px;">' + esc(p.notes) + '</div>';
            }

            // Role context + Expertise
            if (p.role_context || p.expertise) {
                html += '<div style="display:flex;gap:16px;margin-bottom:10px;flex-wrap:wrap;">';
                if (p.role_context) {
                    html += '<div style="flex:1;min-width:140px;"><div style="font-size:10px;color:var(--text3);text-transform:uppercase;margin-bottom:3px;">Context</div>';
                    html += '<div style="font-size:12px;color:var(--text2);">' + esc(p.role_context) + '</div></div>';
                }
                if (p.expertise) {
                    html += '<div style="flex:1;min-width:140px;"><div style="font-size:10px;color:var(--text3);text-transform:uppercase;margin-bottom:3px;">Expertise</div>';
                    html += '<div style="font-size:12px;color:var(--text2);">' + esc(p.expertise) + '</div></div>';
                }
                html += '</div>';
            }

            // Interactions
            var interactions = p.interactions || [];
            if (interactions.length > 0) {
                html += '<div style="font-size:10px;color:var(--text3);text-transform:uppercase;margin-bottom:4px;">Recent Interactions (' + interactions.length + ')</div>';
                interactions.forEach(function(i) {
                    var chIcon = i.channel === 'email' ? '&#9993;' : i.channel === 'whatsapp' ? '&#128172;' : i.channel === 'meeting' ? '&#128100;' : '&#8226;';
                    var dirArrow = i.direction === 'outbound' ? '&rarr;' : i.direction === 'inbound' ? '&larr;' : '&harr;';
                    html += '<div style="font-size:11px;color:var(--text2);margin-bottom:3px;display:flex;gap:6px;">';
                    html += '<span>' + chIcon + '</span>';
                    html += '<span>' + dirArrow + '</span>';
                    html += '<span style="flex:1;">' + esc(i.subject || i.channel || '') + '</span>';
                    if (i.timestamp) html += '<span style="color:var(--text3);font-size:10px;">' + new Date(i.timestamp).toLocaleDateString() + '</span>';
                    html += '</div>';
                });
                html += '<div style="height:8px;"></div>';
            }

            // Obligations
            var obls = p.obligations || [];
            if (obls.length > 0) {
                html += '<div style="font-size:10px;color:var(--text3);text-transform:uppercase;margin-bottom:4px;">Mutual Obligations (' + obls.length + ')</div>';
                obls.forEach(function(o) {
                    var sevCol = o.severity === 'hard' ? 'var(--red)' : o.severity === 'firm' ? 'var(--amber)' : 'var(--text3)';
                    html += '<div style="font-size:11px;color:var(--text2);margin-bottom:3px;">';
                    if (o.severity) html += '<span style="font-size:9px;font-weight:700;color:' + sevCol + ';margin-right:4px;">' + esc(o.severity.toUpperCase()) + '</span>';
                    html += esc(o.description || '');
                    if (o.due_date) html += ' <span style="color:var(--text3);">(' + esc(o.due_date) + ')</span>';
                    html += '</div>';
                });
                html += '<div style="height:8px;"></div>';
            }

            // Emails
            var emails = p.emails || [];
            if (emails.length > 0) {
                html += '<div style="font-size:10px;color:var(--text3);text-transform:uppercase;margin-bottom:4px;">Recent Emails (' + emails.length + ')</div>';
                emails.forEach(function(e) {
                    html += '<div style="font-size:11px;margin-bottom:4px;">';
                    html += '<div style="color:var(--text1);font-weight:500;">' + esc(e.subject || 'No subject') + '</div>';
                    html += '<div style="color:var(--text3);font-size:10px;">' + esc(e.sender_name || '') + (e.received_date ? ' &middot; ' + new Date(e.received_date).toLocaleDateString() : '') + '</div>';
                    html += '</div>';
                });
            }

            if (!interactions.length && !obls.length && !emails.length && !p.notes && !p.role_context) {
                html += '<div style="font-size:12px;color:var(--text3);">No additional context available yet.</div>';
            }

            html += '</div>'; // end detail panel
            html += '</div>'; // end card
        });
    }

    // Add person button
    html += '<button onclick="showAddTripPerson()" style="font-size:12px;font-family:var(--font);padding:6px 14px;background:transparent;border:1px dashed var(--border);border-radius:6px;color:var(--text3);cursor:pointer;width:100%;margin-top:4px;">+ Add person</button>';
    return html;
}

function renderOutreachCard(people) {
    if (!people || people.length === 0) {
        return '<div style="font-size:12px;color:var(--text3);">Add people to the trip first to track outreach.</div>';
    }
    var html = '';
    var statusOrder = { confirmed: 0, sent: 1, none: 2 };
    var sorted = people.slice().sort(function(a, b) {
        return (statusOrder[a.outreach_status] || 9) - (statusOrder[b.outreach_status] || 9);
    });
    sorted.forEach(function(p) {
        var st = p.outreach_status || 'none';
        var stColor = st === 'confirmed' ? 'var(--green)' : st === 'sent' ? 'var(--amber)' : 'var(--text3)';
        var stLabel = st === 'none' ? 'Not reached out' : st.charAt(0).toUpperCase() + st.slice(1);
        html += '<div style="display:flex;align-items:center;gap:8px;font-size:12px;margin-bottom:6px;padding:6px 0;border-bottom:1px solid var(--border-light);">';
        html += '<span class="nav-dot" style="background:' + stColor + ';margin-top:1px;"></span>';
        html += '<span style="color:var(--text1);font-weight:500;">' + esc(p.name) + '</span>';
        html += '<span style="color:var(--text3);margin-left:auto;font-size:11px;">' + esc(stLabel) + '</span>';
        html += '</div>';
    });
    return html;
}

async function showAddTripPerson() {
    if (!_currentTripId) return;
    var name = prompt('Search contact by name:');
    if (!name || !name.trim()) return;
    try {
        var resp = await bakerFetch('/api/networking/contacts');
        if (!resp.ok) return;
        var data = await resp.json();
        var contacts = data.contacts || [];
        var q = name.trim().toLowerCase();
        var matches = contacts.filter(function(c) {
            return (c.name || '').toLowerCase().indexOf(q) !== -1;
        }).slice(0, 10);
        if (matches.length === 0) {
            alert('No contacts found matching "' + name.trim() + '"');
            return;
        }
        var pickList = matches.map(function(c, i) {
            return (i + 1) + '. ' + c.name + (c.role ? ' (' + c.role + ')' : '');
        }).join('\n');
        var pick = prompt('Select a contact (enter number):\n' + pickList);
        if (!pick) return;
        var idx = parseInt(pick, 10) - 1;
        if (isNaN(idx) || idx < 0 || idx >= matches.length) return;
        var selected = matches[idx];
        var notes = prompt('Notes for this trip contact (optional):') || '';
        var roiStr = prompt('ROI score 1-10 (optional):') || '';
        var roi = roiStr ? parseInt(roiStr, 10) : null;
        if (roi !== null && (isNaN(roi) || roi < 1 || roi > 10)) roi = null;

        var addResp = await bakerFetch('/api/trips/' + _currentTripId + '/people', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                contact_id: selected.id,
                role: 'counterparty',
                roi_score: roi,
                notes: notes || null,
            }),
        });
        if (addResp.ok) {
            showTripView(_currentTripId);
        } else {
            alert('Failed to add contact.');
        }
    } catch (e) {
        console.error('showAddTripPerson failed:', e);
    }
}
