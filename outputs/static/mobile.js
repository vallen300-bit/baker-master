/* Baker Mobile — phone adaptation of Baker Dashboard + Ask Baker/Specialist */

// ═══ CONFIG ═══
const BAKER = { apiKey: '' };

async function loadConfig() {
    try {
        const r = await fetch('/api/client-config');
        if (r.ok) { const d = await r.json(); BAKER.apiKey = d.apiKey; }
    } catch (e) { console.error('Config load failed:', e); }
}

function bakerFetch(url, opts = {}) {
    const headers = { ...(opts.headers || {}), 'X-Baker-Key': BAKER.apiKey };
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), opts.timeout || 30000);
    return fetch(url, { ...opts, headers, signal: ctrl.signal }).finally(() => clearTimeout(timer));
}

// ═══ STATE ═══
let bakerHistory = [];
let specialistHistory = [];
let specialistSlug = null;
let streaming = false;
// ═══ VOICE READBACK (SpeechSynthesis — tap to play) ═══
function speakText(text) {
    if (!text || !window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    var clean = text
        .replace(/\*\*(.+?)\*\*/g, '$1')
        .replace(/\*(.+?)\*/g, '$1')
        .replace(/^#{1,3}\s+/gm, '')
        .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
        .replace(/\[Source: [^\]]+\]/g, '')
        .replace(/^\|.*\|$/gm, '')
        .replace(/^-{3,}$/gm, '')
        .replace(/\n{2,}/g, '\n')
        .trim();
    if (!clean) return;
    if (clean.length > 2000) clean = clean.substring(0, 2000) + '... end of summary.';
    var utterance = new SpeechSynthesisUtterance(clean);
    utterance.rate = 1.05;
    utterance.pitch = 1.0;
    var voices = window.speechSynthesis.getVoices();
    var preferred = voices.find(function(v) { return v.name === 'Samantha' || v.name === 'Daniel'; })
        || voices.find(function(v) { return v.lang.startsWith('en') && v.localService; })
        || voices[0];
    if (preferred) utterance.voice = preferred;
    window.speechSynthesis.speak(utterance);
}

function stopSpeaking() {
    if (window.speechSynthesis) window.speechSynthesis.cancel();
}

function addResponseToolbar(replyEl, text, taskId) {
    if (!replyEl || !text) return;
    var toolbar = document.createElement('div');
    toolbar.className = 'msg-toolbar';

    // Copy
    var copyBtn = document.createElement('button');
    copyBtn.textContent = 'Copy';
    copyBtn.addEventListener('click', function() {
        navigator.clipboard.writeText(text).then(function() {
            copyBtn.textContent = 'Copied';
            setTimeout(function() { copyBtn.textContent = 'Copy'; }, 2000);
        });
    });
    toolbar.appendChild(copyBtn);

    // Play / Stop (iOS needs direct user tap to allow speech)
    if (window.speechSynthesis) {
        var playBtn = document.createElement('button');
        playBtn.textContent = 'Play';
        playBtn.addEventListener('click', function() {
            if (window.speechSynthesis.speaking) {
                stopSpeaking();
                playBtn.textContent = 'Play';
            } else {
                speakText(text);
                playBtn.textContent = 'Stop';
                // Reset button when speech ends
                var checkDone = setInterval(function() {
                    if (!window.speechSynthesis.speaking) {
                        playBtn.textContent = 'Play';
                        clearInterval(checkDone);
                    }
                }, 500);
            }
        });
        toolbar.appendChild(playBtn);
    }

    // A6 LEARNING-LOOP: Feedback buttons (only if we have a task_id)
    if (taskId) {
        var sep = document.createElement('span');
        sep.style.cssText = 'width:1px;height:14px;background:var(--border);margin:0 2px;';
        toolbar.appendChild(sep);

        var fbBtns = [
            { text: '\u2713', feedback: 'accepted', title: 'Good' },
            { text: '\u2717', feedback: 'rejected', title: 'Wrong' },
        ];
        fbBtns.forEach(function(b) {
            var btn = document.createElement('button');
            btn.textContent = b.text;
            btn.title = b.title;
            btn.addEventListener('click', function() { _submitMobileFeedback(taskId, b.feedback, toolbar); });
            toolbar.appendChild(btn);
        });
    }

    replyEl.appendChild(toolbar);
}

function _submitMobileFeedback(taskId, feedback, toolbarEl) {
    var comment = null;
    if (feedback !== 'accepted') {
        comment = prompt('What should Baker do differently?');
        if (comment === null) return;
    }
    var body = { feedback: feedback };
    if (comment) body.comment = comment;

    bakerFetch('/api/tasks/' + taskId + '/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    }).then(function(r) {
        if (!r.ok) throw new Error('API ' + r.status);
        // Replace feedback buttons with confirmation
        var btns = toolbarEl.querySelectorAll('button');
        for (var i = 0; i < btns.length; i++) {
            if (btns[i].title === 'Good' || btns[i].title === 'Wrong') btns[i].remove();
        }
        var sep = toolbarEl.querySelector('span');
        if (sep) sep.remove();
        var done = document.createElement('span');
        done.style.cssText = 'font-size:11px;color:var(--text2);';
        done.textContent = feedback === 'accepted' ? 'Thanks!' : 'Noted';
        toolbarEl.appendChild(done);
    }).catch(function(e) {
        console.error('Feedback failed:', e);
    });
}

// ═══ CHAT-TRIAGE-1: Mobile triage bar ═══
function _renderMobileTriage(replyEl, question, answer) {
    var bar = document.createElement('div');
    bar.className = 'chat-triage';
    bar.style.cssText = 'display:flex;gap:8px;padding:8px 0;margin-top:8px;border-top:1px solid rgba(255,255,255,0.08);flex-wrap:wrap;align-items:center;';

    var saveBtn = document.createElement('button');
    saveBtn.style.cssText = 'padding:6px 14px;border-radius:6px;border:1px solid rgba(201,169,110,0.3);background:rgba(255,255,255,0.04);color:#c9a96e;cursor:pointer;font-size:12px;min-height:44px;';
    saveBtn.textContent = 'Save to Dossiers';
    saveBtn.addEventListener('click', function() {
        saveBtn.textContent = 'Saving...';
        saveBtn.disabled = true;
        bakerFetch('/api/dossiers/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: question, answer: answer }),
        }).then(function(r) {
            if (r.ok) { saveBtn.textContent = '\u2713 Saved'; saveBtn.style.color = '#4ecdc4'; }
            else { saveBtn.textContent = 'Failed'; saveBtn.disabled = false; }
        }).catch(function() { saveBtn.textContent = 'Failed'; saveBtn.disabled = false; });
    });
    bar.appendChild(saveBtn);

    var dismissBtn = document.createElement('button');
    dismissBtn.style.cssText = 'margin-left:auto;border:none;background:none;color:#555;font-size:16px;padding:6px 10px;cursor:pointer;min-height:44px;';
    dismissBtn.textContent = '\u2715';
    dismissBtn.addEventListener('click', function() { bar.style.display = 'none'; });
    bar.appendChild(dismissBtn);

    replyEl.appendChild(bar);
}

// ═══ PEOPLE-SECTION-1: Mobile issue cards ═══
function _renderMobileIssueCards(replyEl, person, issues) {
    var container = document.createElement('div');
    container.style.cssText = 'margin-top:12px;border-top:1px solid rgba(255,255,255,0.08);padding-top:10px;';

    var header = document.createElement('div');
    header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;font-size:13px;color:#999;';
    header.innerHTML = '<span>' + issues.length + ' issue' + (issues.length !== 1 ? 's' : '') + ' for <strong>' + esc(person) + '</strong></span>';
    var saveAllBtn = document.createElement('button');
    saveAllBtn.style.cssText = 'padding:6px 14px;border-radius:6px;border:1px solid rgba(201,169,110,0.3);background:rgba(255,255,255,0.04);color:#c9a96e;cursor:pointer;font-size:12px;min-height:44px;';
    saveAllBtn.textContent = 'Save All';
    saveAllBtn.addEventListener('click', function() {
        saveAllBtn.textContent = 'Saving...';
        saveAllBtn.disabled = true;
        bakerFetch('/api/people/issues', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ person_name: person, issues: issues }),
        }).then(function(r) {
            if (r.ok) { saveAllBtn.textContent = '\u2713 Saved'; saveAllBtn.style.color = '#4ecdc4'; }
            else { saveAllBtn.textContent = 'Failed'; saveAllBtn.disabled = false; }
        }).catch(function() { saveAllBtn.textContent = 'Failed'; saveAllBtn.disabled = false; });
    });
    header.appendChild(saveAllBtn);
    container.appendChild(header);

    for (var i = 0; i < issues.length; i++) {
        var issue = issues[i];
        var card = document.createElement('div');
        card.style.cssText = 'background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:12px;margin-bottom:8px;' +
            (issue.status === 'overdue' ? 'border-left:3px solid #e74c3c;' : issue.due_date ? 'border-left:3px solid #d4af37;' : 'border-left:3px solid #4ecdc4;');
        var badge = issue.status === 'overdue' ? '<span style="font-size:10px;font-weight:600;padding:2px 8px;border-radius:4px;background:rgba(231,76,60,0.2);color:#e74c3c;text-transform:uppercase;">OVERDUE</span>'
            : issue.due_date ? '<span style="font-size:10px;font-weight:600;padding:2px 8px;border-radius:4px;background:rgba(212,175,55,0.2);color:#d4af37;text-transform:uppercase;">DUE ' + esc(issue.due_date) + '</span>'
            : '<span style="font-size:10px;font-weight:600;padding:2px 8px;border-radius:4px;background:rgba(78,205,196,0.2);color:#4ecdc4;text-transform:uppercase;">OPEN</span>';
        card.innerHTML = badge + '<div style="font-size:14px;font-weight:500;color:#e0e0e0;margin:6px 0 4px;">' + esc(issue.title) + '</div>' +
            (issue.detail ? '<div style="font-size:12px;color:#999;line-height:1.4;">' + esc(issue.detail) + '</div>' : '');
        container.appendChild(card);
    }
    replyEl.appendChild(container);
}

// ═══ HTML SAFETY ═══
function esc(s) {
    if (!s) return '';
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

/**
 * SECURITY: setSafeHTML — only accepts output from md() or esc().
 * md() always calls esc() first, so all user input is HTML-entity-escaped
 * before any markdown formatting is applied. Same pattern as main app.js.
 */
function setSafeHTML(el, safeHtml) {
    if (el) el.innerHTML = safeHtml;
}

/** Scheme allowlist + attribute-safe encoder for md() link hrefs.
 *  esc() runs FIRST on the markdown input (entity-escapes &, <, >) but does NOT
 *  sanitize URL schemes and does NOT escape `"`. _safeHref is the second layer.
 *  Closes five V0.1-review bypass classes:
 *    - bare      javascript:alert(1)            → scheme-not-in-allowlist → '#'
 *    - encoded   javascript%3Aalert(1)          → percent-decode-before-check → '#'
 *    - quoted    https://x"onclick=alert(1)//   → `"` → `&quot;` at return barrier
 *    - relative  //evil.com                     → blocked before single-slash allow
 *    - hidden    java\tscript:alert(1)          → \t\n\r stripped pre-scheme-check
 *  Future maintainers: keep esc() in md() AND keep all five layers here. */
function _safeHref(url) {
    if (!url) return '#';
    // Browsers strip TAB/CR/LF inside URLs during parsing (WHATWG URL spec §4.1),
    // so `java\tscript:` would otherwise reconstitute to `javascript:` at click time.
    const trimmed = url.trim().replace(/[\t\n\r]/g, '');
    // Empty after trim+strip → no scheme, no path. Return '#' explicitly so all
    // whitespace-only inputs collapse to the same safe sentinel.
    if (!trimmed) return '#';
    // Percent-decode (bounded loop). Catches single-encoded `javascript%3A` plus
    // a few multiply-encoded variants. decodeURIComponent throws on malformed
    // sequences — treat that as "no further decoding possible" and check what we have.
    let decoded = trimmed;
    for (let i = 0; i < 4; i++) {
        try {
            const next = decodeURIComponent(decoded);
            if (next === decoded) break;
            decoded = next;
        } catch (e) { if (!(e instanceof URIError)) throw e; break; }
    }
    // Protocol-relative `//evil.com` opens an external origin under the page's
    // scheme — must block before the single-slash relative-path allow.
    if (decoded.startsWith('//')) return '#';
    let allowed = null;
    if (decoded.startsWith('#') || decoded.startsWith('/') || decoded.startsWith('?')) {
        allowed = trimmed;
    } else {
        const schemeMatch = decoded.match(/^([a-zA-Z][a-zA-Z0-9+\-.]*):/);
        if (!schemeMatch) {
            allowed = trimmed;
        } else {
            const scheme = schemeMatch[1].toLowerCase();
            if (scheme === 'https' || scheme === 'http' || scheme === 'mailto' || scheme === 'tel') {
                allowed = trimmed;
            }
        }
    }
    if (allowed === null) return '#';
    // Single return barrier: escape `"` so a URL containing it can't terminate
    // the href attribute. esc() did NOT do this (textContent→innerHTML escapes
    // only & < > in text nodes; `"` survives). escAttr() at ~line 555 is for
    // inline-JS attribute context (\x22 / \\') and is also wrong for href.
    return allowed.replace(/"/g, '&quot;');
}

function md(text) {
    if (!text) return '';
    let h = esc(text); // XSS-safe: escapes ALL HTML entities first

    // Tables
    h = h.replace(/((?:^\|.+\|$\n?)+)/gm, function(block) {
        const rows = block.trim().split('\n');
        if (rows.length < 2) return block;
        let t = '<table>';
        for (let i = 0; i < rows.length; i++) {
            const row = rows[i].trim();
            if (!row.startsWith('|')) continue;
            if (/^\|[\s\-:|]+\|$/.test(row)) continue;
            const cells = row.split('|').filter((c, j, a) => j > 0 && j < a.length - 1);
            const tag = i === 0 ? 'th' : 'td';
            t += '<tr>';
            for (const cell of cells) t += '<' + tag + '>' + cell.trim() + '</' + tag + '>';
            t += '</tr>';
        }
        return t + '</table>';
    });

    h = h.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    h = h.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    h = h.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    h = h.replace(/\*(.+?)\*/g, '<em>$1</em>');
    h = h.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function(match, label, url) {
        return '<a href="' + _safeHref(url) + '" target="_blank" rel="noopener">' + label + '</a>';
    });
    h = h.replace(/\[Source: ([^\]]+)\]/g, '<span class="citation" title="$1">$1</span>');
    h = h.replace(/^- (.+)$/gm, '<li>$1</li>');
    h = h.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
    h = h.replace(/\n/g, '<br>');
    return h;
}

// ═══ MOBILE DASHBOARD ═══
function _mobileSetText(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value == null ? '' : String(value);
}

function _mobileGreeting() {
    var h = new Date().getHours();
    if (h < 12) return 'Good morning, Dimitry';
    if (h < 18) return 'Good afternoon, Dimitry';
    return 'Good evening, Dimitry';
}

function _mobileDateLabel() {
    try {
        return new Date().toLocaleDateString('en-GB', {
            weekday: 'short',
            day: 'numeric',
            month: 'short',
        });
    } catch (e) {
        return '';
    }
}

function _mobileTimeLabel(iso) {
    if (!iso) return '';
    try {
        var d = new Date(iso);
        if (isNaN(d.getTime())) return String(iso).slice(0, 16);
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch (e) {
        return String(iso).slice(0, 16);
    }
}

function _mobileRelativeTime(iso) {
    if (!iso) return '';
    try {
        var d = new Date(iso);
        if (isNaN(d.getTime())) return '';
        var mins = Math.floor((new Date() - d) / 60000);
        if (mins < 1) return 'Now';
        if (mins < 60) return mins + 'm ago';
        var hrs = Math.floor(mins / 60);
        if (hrs < 24) return hrs + 'h ago';
        return Math.floor(hrs / 24) + 'd ago';
    } catch (e) {
        return '';
    }
}

function _mobileDayLabel(dateStr) {
    if (!dateStr) return '';
    var d = String(dateStr).slice(0, 10);
    var today = new Date().toISOString().slice(0, 10);
    if (d === today) return 'Today';
    var diff = Math.round((new Date(d) - new Date(today)) / 86400000);
    if (diff === 1) return 'Tomorrow';
    if (diff > 1 && diff <= 7) return 'In ' + diff + ' days';
    if (diff < 0) return Math.abs(diff) + 'd ago';
    return d;
}

function _mobileDeadlineLabel(dateStr) {
    if (!dateStr) return '';
    var d = String(dateStr).slice(0, 10);
    var today = new Date().toISOString().slice(0, 10);
    var diff = Math.ceil((new Date(d) - new Date(today)) / 86400000);
    if (diff < 0) return Math.abs(diff) + 'd overdue';
    if (diff === 0) return 'Today';
    if (diff === 1) return 'Tomorrow';
    return diff + ' days';
}

function _mobileCreateDashCard(kind, title, meta, sub, body, dot) {
    var card = document.createElement('div');
    card.className = 'mobile-dash-card ' + (kind || 'info');

    var main = document.createElement('div');
    main.className = 'mobile-dash-card-main';

    var dotEl = document.createElement('span');
    dotEl.className = 'mobile-dash-dot ' + (dot || '');
    main.appendChild(dotEl);

    var titleEl = document.createElement('div');
    titleEl.className = 'mobile-dash-title';
    titleEl.textContent = title || 'Untitled';
    main.appendChild(titleEl);

    if (meta) {
        var metaEl = document.createElement('div');
        metaEl.className = 'mobile-dash-meta';
        metaEl.textContent = meta;
        main.appendChild(metaEl);
    }
    card.appendChild(main);

    if (sub) {
        var subEl = document.createElement('div');
        subEl.className = 'mobile-dash-sub';
        subEl.textContent = sub;
        card.appendChild(subEl);
    }

    if (body) {
        var detail = document.createElement('div');
        detail.className = 'mobile-dash-card-detail';
        detail.textContent = body;
        card.appendChild(detail);
        card.addEventListener('click', function() {
            card.classList.toggle('expanded');
        });
    }

    return card;
}

function _mobileRenderBucket(bodyId, countId, pillId, items, emptyText) {
    var body = document.getElementById(bodyId);
    if (!body) return;
    body.textContent = '';
    if (!items.length) {
        var empty = document.createElement('div');
        empty.className = 'mobile-empty';
        empty.textContent = emptyText;
        body.appendChild(empty);
    } else {
        for (var i = 0; i < items.length; i++) body.appendChild(items[i]);
    }
    var n = items.length || 0;
    _mobileSetText(countId, n ? n : '');
    _mobileSetText(pillId, n);
}

function _mobileBuildTravelItems(data) {
    var items = [];
    var trips = data.trips || [];
    for (var i = 0; i < trips.length; i++) {
        var trip = trips[i];
        var end = trip.end_date || trip.start_date;
        var title = trip.event_name || trip.destination || 'Trip';
        var meta = _mobileDayLabel(trip.start_date);
        if (end && end !== trip.start_date) meta += ' - ' + _mobileDayLabel(end);
        var sub = [trip.origin, trip.destination].filter(Boolean).join(' -> ');
        var body = [trip.status, trip.category].filter(Boolean).join(' · ');
        items.push(_mobileCreateDashCard('travel', title, meta, sub, body, trip.status === 'confirmed' ? 'green' : 'amber'));
    }

    var events = data.travel_today || [];
    for (var ei = 0; ei < events.length; ei++) {
        var ev = events[ei];
        items.push(_mobileCreateDashCard(
            'travel',
            ev.title || 'Travel event',
            _mobileTimeLabel(ev.start),
            ev.location || '',
            ev.description || ev.prep_notes || '',
            'amber'
        ));
    }

    var deadlines = data.travel_deadlines || [];
    for (var di = 0; di < deadlines.length; di++) {
        var dl = deadlines[di];
        items.push(_mobileCreateDashCard(
            'travel',
            dl.description || 'Travel deadline',
            _mobileDeadlineLabel(dl.due_date),
            dl.priority || '',
            dl.source_snippet || '',
            'amber'
        ));
    }

    var alerts = data.travel_alerts || [];
    for (var ai = 0; ai < alerts.length; ai++) {
        var a = alerts[ai];
        var title = (a.title || 'Travel alert').replace(/^(TODAY|In \d+d):\s*/i, '');
        items.push(_mobileCreateDashCard(
            'travel',
            title,
            a.travel_date ? _mobileDayLabel(a.travel_date) : _mobileRelativeTime(a.created_at),
            (a.source || '').replace(/_/g, ' '),
            a.body || '',
            'blue'
        ));
    }
    return items;
}

function _mobileBuildCriticalItems(data) {
    var items = [];
    var critical = data.critical_items || [];
    for (var i = 0; i < critical.length; i++) {
        var ci = critical[i];
        items.push(_mobileCreateDashCard(
            'critical',
            ci.description || 'Critical item',
            _mobileRelativeTime(ci.critical_flagged_at),
            ci.priority || 'critical',
            ci.source_snippet || '',
            'red'
        ));
    }
    return items;
}

function _mobileBuildPromisedItems(data) {
    var items = [];
    var deadlines = data.deadlines || [];
    for (var i = 0; i < deadlines.length; i++) {
        var dl = deadlines[i];
        var priority = (dl.priority || 'normal').toLowerCase();
        var dot = priority === 'critical' ? 'red' : priority === 'high' ? 'amber' : '';
        items.push(_mobileCreateDashCard(
            'promised',
            dl.description || 'Deadline',
            _mobileDeadlineLabel(dl.due_date),
            dl.priority || '',
            dl.source_snippet || '',
            dot
        ));
    }
    return items;
}

function _mobileBuildMeetingItems(data) {
    var items = [];
    var meetings = (data.meetings_today || []).filter(function(m) {
        return !(m.title || '').startsWith('[Baker Prep]');
    });
    for (var i = 0; i < meetings.length; i++) {
        var m = meetings[i];
        var attendees = (m.attendees || []).slice(0, 3).join(', ');
        if ((m.attendees || []).length > 3) attendees += ' +' + ((m.attendees || []).length - 3);
        items.push(_mobileCreateDashCard(
            'meeting',
            m.title || 'Meeting',
            _mobileTimeLabel(m.start),
            attendees || (m.prepped ? 'Prepped' : 'Prep pending'),
            [m.location, m.prep_notes].filter(Boolean).join('\n\n'),
            m.prepped ? 'green' : 'amber'
        ));
    }

    var detected = data.detected_meetings || [];
    for (var di = 0; di < detected.length; di++) {
        var dm = detected[di];
        var participants = (dm.participant_names || []).join(', ');
        items.push(_mobileCreateDashCard(
            'meeting',
            dm.title || 'Detected meeting',
            [dm.meeting_time, _mobileDayLabel(dm.meeting_date)].filter(Boolean).join(' · '),
            participants || dm.status || 'proposed',
            dm.location || '',
            dm.status === 'confirmed' ? 'green' : 'amber'
        ));
    }

    var meetingAlerts = data.meeting_alerts || [];
    for (var ai = 0; ai < meetingAlerts.length; ai++) {
        var ma = meetingAlerts[ai];
        items.push(_mobileCreateDashCard(
            'meeting',
            ma.title || 'Meeting alert',
            _mobileRelativeTime(ma.created_at),
            (ma.source || '').replace(/_/g, ' '),
            ma.body || '',
            'blue'
        ));
    }
    return items;
}

function _mobileCortexRow(label, value, statusClass) {
    var row = document.createElement('div');
    row.className = 'mobile-cortex-row';
    var l = document.createElement('span');
    l.textContent = label;
    row.appendChild(l);
    var v = document.createElement('strong');
    v.textContent = value;
    if (statusClass) v.className = statusClass;
    row.appendChild(v);
    return row;
}

async function loadMobileCortexSummary() {
    var body = document.getElementById('mobileCortexBody');
    if (!body) return;
    body.textContent = 'Loading Cortex status...';
    try {
        function getJson(url) {
            return bakerFetch(url).then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; });
        }
        var results = await Promise.all([
            getJson('/api/health/scheduler'),
            getJson('/api/cortex/events?limit=10'),
            getJson('/api/cortex/lint?status=open&limit=20'),
            getJson('/api/cortex/cycles/pending?limit=20&include_smoke=false'),
        ]);
        var health = results[0];
        var events = (results[1] && results[1].events) || [];
        var lint = (results[2] && results[2].lint_results) || [];
        var pending = (results[3] && results[3].cycles) || [];

        body.textContent = '';
        var liveLabel = health ? (health.alive ? 'Alive' : 'Stale') : 'Unknown';
        body.appendChild(_mobileCortexRow('Scheduler', liveLabel));
        body.appendChild(_mobileCortexRow('Events', String(events.length)));
        body.appendChild(_mobileCortexRow('Open lint', String(lint.length)));
        body.appendChild(_mobileCortexRow('Pending cycles', String(pending.length)));

        var count = [];
        if (events.length) count.push(events.length + ' events');
        if (lint.length) count.push(lint.length + ' lint');
        if (pending.length) count.push(pending.length + ' pending');
        _mobileSetText('mobileCortexCount', count.join(', '));
    } catch (e) {
        body.textContent = 'Cortex status unavailable.';
        _mobileSetText('mobileCortexCount', '');
    }
}

async function loadMobileDashboard() {
    _mobileSetText('mobileBriefGreeting', _mobileGreeting());
    _mobileSetText('mobileBriefDate', _mobileDateLabel());
    _mobileSetText('mobileBriefStatus', 'Loading your cockpit...');

    try {
        var resp = await bakerFetch('/api/dashboard/morning-brief', { timeout: 25000 });
        if (!resp.ok) throw new Error('Server returned ' + resp.status);
        var data = await resp.json();

        var travelItems = _mobileBuildTravelItems(data);
        var criticalItems = _mobileBuildCriticalItems(data);
        var promisedItems = _mobileBuildPromisedItems(data);
        var meetingItems = _mobileBuildMeetingItems(data);

        _mobileRenderBucket('mobileGridTravel', 'mobileGridTravelCount', 'mobileTravelCount', travelItems, 'No travel today.');
        _mobileRenderBucket('mobileGridCritical', 'mobileGridCriticalCount', 'mobileCriticalCount', criticalItems, 'No critical items. All clear.');
        _mobileRenderBucket('mobileGridPromised', 'mobileGridPromisedCount', 'mobilePromisedCount', promisedItems, 'No deadlines this week.');
        _mobileRenderBucket('mobileGridMeetings', 'mobileGridMeetingsCount', 'mobileMeetingsCount', meetingItems, 'No meetings today.');

        var status = [];
        if (data.fire_count) status.push(data.fire_count + ' critical');
        if (data.unanswered_count) status.push(data.unanswered_count + ' awaiting reply');
        status.push('briefing live');
        _mobileSetText('mobileBriefStatus', status.join(' · '));

        loadMobileCortexSummary();
    } catch (e) {
        _mobileSetText('mobileBriefStatus', 'Briefing unavailable (' + (e.message || String(e)) + ').');
        _mobileRenderBucket('mobileGridTravel', 'mobileGridTravelCount', 'mobileTravelCount', [], 'Travel unavailable.');
        _mobileRenderBucket('mobileGridCritical', 'mobileGridCriticalCount', 'mobileCriticalCount', [], 'Critical items unavailable.');
        _mobileRenderBucket('mobileGridPromised', 'mobileGridPromisedCount', 'mobilePromisedCount', [], 'Promised work unavailable.');
        _mobileRenderBucket('mobileGridMeetings', 'mobileGridMeetingsCount', 'mobileMeetingsCount', [], 'Meetings unavailable.');
        var cortex = document.getElementById('mobileCortexBody');
        if (cortex) cortex.textContent = 'Cortex status unavailable.';
    }
}

// ═══ TABS ═══
function switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(function(b) {
        b.classList.toggle('active', b.dataset.tab === tab);
    });
    document.querySelectorAll('.chat-panel').forEach(function(p) {
        p.classList.toggle('active', p.id === 'panel-' + tab);
    });
    if (tab === 'dashboard') {
        loadMobileDashboard();
    } else if (tab === 'feed') {
        loadMobileAlerts();
    } else {
        var inputId = tab === 'baker' ? 'bakerInput' : 'specialistInput';
        var input = document.getElementById(inputId);
        if (input) setTimeout(function() { input.focus(); }, 100);
    }
}

// ═══ MESSAGES ═══
function addMessage(containerId, role, content, id) {
    const container = document.getElementById(containerId);
    if (!container) return null;

    // Clear empty state on first message
    var empty = container.querySelector('.empty-state');
    if (empty) empty.remove();

    const div = document.createElement('div');
    div.className = 'msg ' + (role === 'user' ? 'user' : 'baker');
    if (id) div.id = id;

    if (role === 'assistant' && !content) {
        // Thinking indicator — static safe HTML, no user input
        var dots = document.createElement('div');
        dots.className = 'thinking';
        var dotsSpan = document.createElement('span');
        dotsSpan.className = 'thinking-dots';
        for (var i = 0; i < 3; i++) dotsSpan.appendChild(document.createElement('span'));
        dots.appendChild(dotsSpan);
        dots.appendChild(document.createTextNode(' '));
        var label = document.createElement('span');
        label.className = 'think-label';
        label.textContent = 'Thinking...';
        dots.appendChild(label);
        div.appendChild(dots);
    } else if (role === 'assistant') {
        var mdDiv = document.createElement('div');
        mdDiv.className = 'md-content';
        setSafeHTML(mdDiv, md(content)); // SECURITY: md() calls esc() first
        div.appendChild(mdDiv);
    } else {
        div.textContent = content; // User messages: plain text only
    }

    // Prepend (newest at top, input is at top — Cowork style)
    container.prepend(div);
    container.scrollTop = 0;
    return div;
}

function updateThinkingLabel(el, text) {
    if (!el) return;
    var span = el.querySelector('.think-label');
    if (span) span.textContent = text;
}

// CORTEX_RUN_SCAN_UI_RENDER_1: mobile parallel of desktop renderCortexEvent.
// Inline DOM (no md() heavy markdown — mobile uses simpler rendering).
// Phase ticker is collapsed to a single-line progress label; terminal card
// shows status + cost + cycle hash + proposal text.
function renderCortexEventMobile(data, replyEl, full) {
    if (!replyEl) return full;
    var t = data.type;

    var ctxEl = replyEl.querySelector('.cortex-stream-mobile');
    if (!ctxEl) {
        replyEl.textContent = '';
        ctxEl = document.createElement('div');
        ctxEl.className = 'cortex-stream-mobile';
        var hdr = document.createElement('div');
        hdr.className = 'cortex-header-mobile';
        hdr.appendChild(document.createTextNode(
            'Cortex · ' + (data.matter_slug || 'unknown') + ' · ' + (data.triggered_by || 'manual')
        ));
        ctxEl.appendChild(hdr);
        var prog = document.createElement('div');
        prog.className = 'cortex-progress-mobile';
        prog.appendChild(document.createTextNode('Starting…'));
        ctxEl.appendChild(prog);
        replyEl.appendChild(ctxEl);
    }

    var prog2 = ctxEl.querySelector('.cortex-progress-mobile');

    if (t === 'phase_changed') {
        if (prog2) {
            prog2.textContent = '';
            prog2.appendChild(document.createTextNode(_cortexPhaseLabelMobile(data.phase) + '…'));
        }
        return full;
    }
    if (t === 'phase_output') {
        if (prog2) {
            prog2.appendChild(document.createTextNode(' ·'));
        }
        return full;
    }
    if (t === 'terminal') {
        if (prog2) prog2.remove();
        var card = document.createElement('div');
        card.className = 'cortex-terminal-mobile';
        card.appendChild(document.createTextNode(
            _cortexStatusLabelMobile(data.status) +
            ' — $' + Number(data.cost_dollars || 0).toFixed(4)
        ));
        if (data.cycle_id) {
            var sub = document.createElement('div');
            sub.className = 'cortex-terminal-sub';
            sub.appendChild(document.createTextNode('cycle ' + data.cycle_id.slice(0, 8) + '…'));
            card.appendChild(sub);
        }
        var body = document.createElement('div');
        body.className = 'cortex-terminal-body-mobile';
        body.appendChild(document.createTextNode('Loading proposal…'));
        card.appendChild(body);
        ctxEl.appendChild(card);

        if (data.cycle_id && data.status !== 'failed' && data.status !== 'timeout') {
            _fetchCortexProposalMobile(data.cycle_id, body);
        } else {
            body.textContent = '';
            body.appendChild(document.createTextNode(
                data.status === 'timeout' ? 'Cycle timed out.' : 'Cycle did not complete propose phase.'
            ));
        }
        return full;
    }
    return full;
}

function _cortexPhaseLabelMobile(phase) {
    var labels = { sense: 'Sensing', load: 'Loading', reason: 'Reasoning', propose: 'Proposing', archive: 'Archiving' };
    return labels[phase] || (phase || 'Phase');
}

function _cortexStatusLabelMobile(status) {
    var labels = {
        tier_b_pending: 'Proposal ready',
        completed: 'Complete',
        rejected: 'Rejected',
        failed: 'Failed',
        timeout: 'Timeout',
        archived: 'Archived'
    };
    return labels[status] || (status || 'unknown');
}

async function _fetchCortexProposalMobile(cycle_id, bodyEl) {
    try {
        var resp = await bakerFetch('/api/cortex/cycles/' + encodeURIComponent(cycle_id) + '/proposal');
        if (!resp.ok) {
            bodyEl.textContent = '';
            bodyEl.appendChild(document.createTextNode('Fetch failed (HTTP ' + resp.status + ')'));
            return;
        }
        var d = await resp.json();
        bodyEl.textContent = '';
        if (d.has_proposal && d.proposal_text) {
            setSafeHTML(bodyEl, '<div class="md-content">' + md(d.proposal_text) + '</div>');
        } else {
            bodyEl.appendChild(document.createTextNode('No proposal yet (' + (d.current_phase || 'unknown') + ').'));
        }
    } catch (e) {
        bodyEl.textContent = '';
        bodyEl.appendChild(document.createTextNode('Error: ' + e.message));
    }
}

// ═══ SSE STREAM HANDLER ═══
async function streamChat(url, body, containerId, history) {
    if (streaming) return;
    streaming = true;

    var question = body.question;
    history.push({ role: 'user', content: question });
    addMessage(containerId, 'user', question);

    var replyId = 'reply-' + Date.now();
    addMessage(containerId, 'assistant', '', replyId);
    var replyEl = document.getElementById(replyId);

    // Disable inputs
    var panel = document.getElementById(containerId).closest('.chat-panel');
    var input = panel ? panel.querySelector('.chat-input') : null;
    var btn = panel ? panel.querySelector('.send-btn') : null;
    if (input) { input.disabled = true; input.value = ''; input.style.height = 'auto'; }
    if (btn) btn.disabled = true;

    var full = '';
    var capturedTaskId = null;
    var statusLabels = {
        'retrieving': 'Searching memory...',
        'thinking': 'Analyzing...',
        'generating': 'Writing response...'
    };

    try {
        var resp = await bakerFetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            timeout: 180000,
            body: JSON.stringify(body),
        });
        if (!resp.ok) throw new Error('API returned ' + resp.status);

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
                    // Status labels for thinking dots
                    if (data.status && !full && replyEl) {
                        var lbl = statusLabels[data.status];
                        if (lbl) updateThinkingLabel(replyEl, lbl);
                    }
                    // CORTEX_RUN_SCAN_UI_RENDER_1: typed events from
                    // /api/cortex/run via Scan cortex_run_action intent.
                    if (data.type === 'started' || data.type === 'phase_changed'
                        || data.type === 'phase_output' || data.type === 'terminal') {
                        full = renderCortexEventMobile(data, replyEl, full);
                        continue;
                    }
                    if (data.token) {
                        if (!full && replyEl) replyEl.textContent = '';
                        full += data.token;
                        // SECURITY: md() calls esc() first — all user input sanitized
                        if (replyEl) setSafeHTML(replyEl, '<div class="md-content">' + md(full) + '</div>');
                        // Keep scroll pinned to top (newest-first layout)
                        var msgContainer = document.getElementById(containerId);
                        if (msgContainer) msgContainer.scrollTop = 0;
                    }
                    if (data.screenshot) {
                        // BROWSER-AGENT-1: Show page screenshot inline
                        full += '\n\n![Page screenshot](data:image/jpeg;base64,' + data.screenshot + ')\n\n';
                        if (replyEl) setSafeHTML(replyEl, '<div class="md-content">' + md(full) + '</div>');
                    }
                    if (data.task_id) {
                        capturedTaskId = data.task_id;
                    }
                    if (data.error) {
                        full += '\n[Error: ' + data.error + ']';
                        if (replyEl) setSafeHTML(replyEl, '<div class="md-content">' + md(full) + '</div>');
                    }
                } catch (e) { /* skip unparseable */ }
            }
        }
    } catch (err) {
        full = 'Connection error: ' + err.message;
        if (replyEl) replyEl.textContent = full;
    }

    history.push({ role: 'assistant', content: full });
    if (history.length > 40) history.splice(0, history.length - 40);

    // Toolbar: Copy + Play + Feedback (tap to hear)
    if (full && !full.startsWith('Connection error')) {
        addResponseToolbar(replyEl, full, capturedTaskId);
    }

    // PEOPLE-SECTION-1: Parse baker-issues + render cards, or show general triage
    var _issueData = null;
    var _issueMatch = full.match(/```baker-issues\s*([\s\S]*?)```/);
    if (_issueMatch) {
        try { _issueData = JSON.parse(_issueMatch[1]); } catch(e) {}
    }
    if (_issueData && _issueData.person && _issueData.issues && _issueData.issues.length && replyEl) {
        var _clean = full.replace(/```baker-issues[\s\S]*?```/, '').trim();
        if (_clean) setSafeHTML(replyEl, '<div class="md-content">' + md(_clean) + '</div>');
        _renderMobileIssueCards(replyEl, _issueData.person, _issueData.issues);
    } else if (full && full.length > 300 && !full.startsWith('Connection error') && replyEl) {
        // CHAT-TRIAGE-1: General triage bar
        _renderMobileTriage(replyEl, question, full);
    }

    streaming = false;
    if (input) { input.disabled = false; input.focus(); }
    if (btn) btn.disabled = false;
}

// ═══ NEW CHAT ═══
function newChat() {
    // Determine which panel is active
    var bakerPanel = document.getElementById('panel-baker');
    var specialistPanel = document.getElementById('panel-specialist');
    var isBaker = bakerPanel && bakerPanel.classList.contains('active');
    var isSpecialist = specialistPanel && specialistPanel.classList.contains('active');

    if (!isBaker && !isSpecialist) {
        switchTab('baker');
        setTimeout(newChat, 0);
        return;
    }

    if (isBaker) {
        bakerHistory = [];
        var container = document.getElementById('bakerMessages');
        if (container) {
            container.textContent = '';
            var empty = document.createElement('div');
            empty.className = 'empty-state';
            var icon = document.createElement('div');
            icon.className = 'icon';
            icon.textContent = '\uD83D\uDCAC';
            empty.appendChild(icon);
            empty.appendChild(document.createTextNode('Ask Baker anything about your business, deals, contacts, or upcoming meetings.'));
            container.appendChild(empty);
        }
        var input = document.getElementById('bakerInput');
        if (input) { input.value = ''; input.style.height = 'auto'; input.focus(); }
    } else {
        specialistHistory = [];
        var container = document.getElementById('specialistMessages');
        if (container) {
            container.textContent = '';
            var empty = document.createElement('div');
            empty.className = 'empty-state';
            var icon = document.createElement('div');
            icon.className = 'icon';
            icon.textContent = '\uD83E\uDDE0';
            empty.appendChild(icon);
            empty.appendChild(document.createTextNode('Pick a specialist above, then ask a deep question in their domain.'));
            container.appendChild(empty);
        }
        var input = document.getElementById('specialistInput');
        if (input) { input.value = ''; input.style.height = 'auto'; input.focus(); }
    }
}

// ═══ IMAGE UPLOAD ═══
var pendingImage = null; // File object

function setupCamera() {
    var camBtn = document.getElementById('bakerCamBtn');
    var fileInput = document.getElementById('bakerCamera');
    var preview = document.getElementById('bakerImgPreview');

    camBtn.addEventListener('click', function() {
        fileInput.click();
    });

    fileInput.addEventListener('change', function() {
        var file = fileInput.files[0];
        if (!file) return;
        pendingImage = file;

        // Show preview
        preview.hidden = false;
        preview.textContent = '';
        var img = document.createElement('img');
        img.src = URL.createObjectURL(file);
        preview.appendChild(img);

        var label = document.createElement('span');
        label.style.cssText = 'font-size:12px;color:var(--text2);';
        label.textContent = file.name.length > 20 ? file.name.substring(0, 20) + '...' : file.name;
        preview.appendChild(label);

        var removeBtn = document.createElement('button');
        removeBtn.className = 'remove-img';
        removeBtn.textContent = 'Remove';
        removeBtn.addEventListener('click', function() {
            pendingImage = null;
            preview.hidden = true;
            preview.textContent = '';
            fileInput.value = '';
        });
        preview.appendChild(removeBtn);

        // Focus the input for optional question
        var input = document.getElementById('bakerInput');
        if (input) {
            input.placeholder = 'Add a question about this image (optional)...';
            input.focus();
        }
    });
}

async function sendImage(question) {
    if (!pendingImage) return;
    if (streaming) return;
    streaming = true;

    var displayQ = question || 'Analyze this image';
    bakerHistory.push({ role: 'user', content: '[Image: ' + pendingImage.name + '] ' + displayQ });
    addMessage('bakerMessages', 'user', displayQ + ' [with image]');

    var replyId = 'reply-' + Date.now();
    addMessage('bakerMessages', 'assistant', '', replyId);
    var replyEl = document.getElementById(replyId);
    if (replyEl) updateThinkingLabel(replyEl, 'Analyzing image...');

    var input = document.getElementById('bakerInput');
    var btn = document.getElementById('bakerSendBtn');
    if (input) { input.disabled = true; input.value = ''; input.style.height = 'auto'; }
    if (btn) btn.disabled = true;

    var full = '';
    try {
        var formData = new FormData();
        formData.append('file', pendingImage);
        formData.append('question', question || 'What is this? Analyze it and tell me anything relevant.');

        // Direct fetch (not bakerFetch) — avoid abort controller issues on slow mobile uploads
        var resp = await fetch('/api/scan/image', {
            method: 'POST',
            headers: { 'X-Baker-Key': BAKER.apiKey },
            body: formData,
        });
        if (!resp.ok) {
            var errText = '';
            try { errText = (await resp.json()).detail || resp.status; } catch(e) { errText = resp.status; }
            throw new Error(errText);
        }
        var data = await resp.json();
        full = data.answer || 'No response';
        if (replyEl) setSafeHTML(replyEl, '<div class="md-content">' + md(full) + '</div>');
    } catch (err) {
        full = 'Error: ' + err.message;
        if (replyEl) replyEl.textContent = full;
    }

    bakerHistory.push({ role: 'assistant', content: full });

    // Toolbar: Copy + Play
    if (full && !full.startsWith('Error:')) {
        addResponseToolbar(replyEl, full);
    }

    // Clear image state
    pendingImage = null;
    var preview = document.getElementById('bakerImgPreview');
    if (preview) { preview.hidden = true; preview.textContent = ''; }
    var fileInput = document.getElementById('bakerCamera');
    if (fileInput) fileInput.value = '';
    if (input) { input.disabled = false; input.placeholder = 'Ask Baker anything...'; input.focus(); }
    if (btn) btn.disabled = false;
    streaming = false;
}

// ═══ SEND FUNCTIONS ═══
function sendBaker() {
    var input = document.getElementById('bakerInput');
    var q = input ? input.value.trim() : '';
    // If there's a pending image, send via image endpoint
    if (pendingImage) {
        sendImage(q);
        return;
    }
    if (!q) return;
    streamChat('/api/scan', {
        question: q,
        history: bakerHistory,
    }, 'bakerMessages', bakerHistory);
}

function sendSpecialist() {
    var input = document.getElementById('specialistInput');
    var q = input ? input.value.trim() : '';
    if (!q || !specialistSlug) return;
    streamChat('/api/scan/specialist', {
        question: q,
        capability_slug: specialistSlug,
        history: specialistHistory.slice(-30),
    }, 'specialistMessages', specialistHistory);
}

// ═══ CAPABILITY LOADER ═══
async function loadCapabilities() {
    var select = document.getElementById('capPicker');
    if (!select) return;

    // Show loading state while fetching
    var loadingOpt = document.createElement('option');
    loadingOpt.value = '';
    loadingOpt.textContent = 'Loading specialists...';
    loadingOpt.disabled = true;
    select.textContent = '';
    select.appendChild(loadingOpt);
    select.disabled = true;

    try {
        var r = await bakerFetch('/api/capabilities');
        if (!r.ok) return;
        var data = await r.json();
        var caps = (data.capabilities || []).filter(function(c) {
            return c.active && c.slug !== 'decomposer' && c.slug !== 'synthesizer';
        });
        caps.sort(function(a, b) { return (a.name || '').localeCompare(b.name || ''); });

        // Replace loading with real options
        select.textContent = '';
        var defaultOpt = document.createElement('option');
        defaultOpt.value = '';
        defaultOpt.textContent = 'Select a specialist...';
        select.appendChild(defaultOpt);

        for (var i = 0; i < caps.length; i++) {
            var opt = document.createElement('option');
            opt.value = caps[i].slug;
            opt.textContent = caps[i].name || caps[i].slug;
            select.appendChild(opt);
        }
        select.disabled = false;
    } catch (e) {
        console.error('Failed to load capabilities:', e);
        select.textContent = '';
        var errOpt = document.createElement('option');
        errOpt.value = '';
        errOpt.textContent = 'Failed to load — tap to retry';
        select.appendChild(errOpt);
        select.disabled = false;
    }
}

// ═══ ALERT BADGE ═══
async function refreshAlertBadge() {
    try {
        // API returns only pending alerts; count T1+T2
        var r = await bakerFetch('/api/alerts');
        if (!r.ok) return;
        var data = await r.json();
        var alerts = data.alerts || [];
        var count = 0;
        for (var i = 0; i < alerts.length; i++) {
            if (alerts[i].tier <= 2) count++;
        }
        var badge = document.getElementById('alertBadge');
        if (!badge) return;
        if (count > 0) {
            badge.textContent = count;
            badge.hidden = false;
        } else {
            badge.hidden = true;
        }
    } catch (e) { /* silent */ }
}

// ═══ INIT ═══
async function init() {
    await loadConfig();
    await loadCapabilities();

    // Camera, New Chat, Upload, Trip, Voice
    setupCamera();
    _setupUpload();
    _setupVoiceInput();
    loadActiveTrip();
    document.getElementById('newChatBtn').addEventListener('click', function() { stopSpeaking(); newChat(); });
    document.getElementById('tripBackBtn').addEventListener('click', function() { _closeTripOverlay(); });

    // Pre-load voices for Play button (iOS requires this)
    if (window.speechSynthesis) {
        window.speechSynthesis.getVoices();
        window.speechSynthesis.onvoiceschanged = function() { window.speechSynthesis.getVoices(); };
    }

    // Tab switching
    document.querySelectorAll('.tab-btn').forEach(function(btn) {
        btn.addEventListener('click', function() { switchTab(btn.dataset.tab); });
    });

    // Badge click → alerts tab
    var alertBadge = document.getElementById('alertBadge');
    if (alertBadge) {
        alertBadge.style.cursor = 'pointer';
        alertBadge.addEventListener('click', function(e) {
            e.stopPropagation();
            switchTab('feed');
        });
    }

    // Baker form
    document.getElementById('bakerForm').addEventListener('submit', function(e) {
        e.preventDefault();
        sendBaker();
    });

    // Specialist form
    document.getElementById('specialistForm').addEventListener('submit', function(e) {
        e.preventDefault();
        sendSpecialist();
    });

    // Capability picker
    var picker = document.getElementById('capPicker');
    picker.addEventListener('change', function() {
        specialistSlug = picker.value || null;
        var input = document.getElementById('specialistInput');
        var btn = document.getElementById('specialistSendBtn');
        if (input) input.disabled = !specialistSlug;
        if (btn) btn.disabled = !specialistSlug;
        // Clear messages on capability switch
        specialistHistory = [];
        var container = document.getElementById('specialistMessages');
        if (container) {
            container.textContent = '';
            // Re-add empty state
            var empty = document.createElement('div');
            empty.className = 'empty-state';
            setSafeHTML(empty, '<div class="icon">&#x1F9E0;</div>Pick a specialist above, then ask a deep question in their domain.');
            container.appendChild(empty);
        }
        if (specialistSlug && input) input.focus();
    });

    // Auto-resize textareas
    document.querySelectorAll('.chat-input').forEach(function(ta) {
        ta.addEventListener('input', function() {
            ta.style.height = 'auto';
            ta.style.height = Math.min(ta.scrollHeight, 120) + 'px';
        });
    });

    // Alert badge — load now + refresh every 5 min
    refreshAlertBadge();
    setInterval(refreshAlertBadge, 5 * 60 * 1000);

    // Auto-refresh visible operational tab.
    setInterval(function() {
        var dashboardPanel = document.getElementById('panel-dashboard');
        var feedPanel = document.getElementById('panel-feed');
        if (dashboardPanel && dashboardPanel.classList.contains('active')) {
            loadMobileDashboard();
        } else if (feedPanel && feedPanel.classList.contains('active')) {
            loadMobileAlerts();
        }
    }, 60000);

    // REALTIME-PUSH-1: Request notification permission + connect live stream
    if (window.Notification && Notification.permission === 'default') {
        Notification.requestPermission();
    }
    _connectMobileAlertStream();

    // E3: Register service worker + subscribe to Web Push
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/static/sw.js').then(function(reg) {
            console.log('SW registered:', reg.scope);
            return reg.pushManager.getSubscription().then(function(sub) {
                if (sub) return sub; // already subscribed
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

    // Default tab — check for deep link
    var urlParams = new URLSearchParams(window.location.search);
    var deepTab = urlParams.get('tab');
    if (deepTab && ['dashboard', 'feed', 'baker', 'specialist'].indexOf(deepTab) !== -1) {
        switchTab(deepTab);
    } else {
        switchTab('dashboard');
    }
}

// ═══ MOBILE ALERTS VIEW ═══
var _mobileAlerts = [];
var _alertTierFilter = '';
var _alertSourceFilter = '';

function _fmtTimeAgo(dateStr) {
    if (!dateStr) return '';
    var d = new Date(dateStr);
    var now = new Date();
    var diffMs = now - d;
    var mins = Math.floor(diffMs / 60000);
    if (mins < 60) return mins + 'm ago';
    var hrs = Math.floor(mins / 60);
    if (hrs < 24) return hrs + 'h ago';
    var days = Math.floor(hrs / 24);
    return days + 'd ago';
}

async function loadMobileAlerts() {
    var list = document.getElementById('alertsList');
    if (!list) return;
    list.textContent = '';
    var loadDiv = document.createElement('div');
    loadDiv.className = 'empty-state';
    loadDiv.textContent = 'Loading alerts...';
    list.appendChild(loadDiv);

    try {
        var r = await bakerFetch('/api/alerts');
        if (!r.ok) throw new Error('API ' + r.status);
        var data = await r.json();
        _mobileAlerts = data.alerts || [];
        _buildAlertToolbar();
        _renderMobileAlerts();
        _buildAlertFooter();
    } catch (e) {
        list.textContent = '';
        var err = document.createElement('div');
        err.className = 'empty-state';
        err.textContent = 'Failed to load alerts.';
        list.appendChild(err);
    }
}

function _buildAlertToolbar() {
    var toolbar = document.getElementById('alertsToolbar');
    if (!toolbar) return;
    toolbar.textContent = '';

    // Dossier Library link
    var dossierLink = document.createElement('a');
    dossierLink.href = '/dossiers?key=' + encodeURIComponent(BAKER.apiKey);
    dossierLink.className = 'filter-chip';
    dossierLink.style.cssText = 'text-decoration:none;background:#1e3a5f;color:#60a5fa;';
    dossierLink.textContent = 'Dossiers';
    toolbar.appendChild(dossierLink);

    // Tier filter chips
    var tiers = [
        { value: '', label: 'All' },
        { value: '1', label: 'T1' },
        { value: '2', label: 'T2' },
        { value: '3', label: 'T3+' },
    ];
    for (var i = 0; i < tiers.length; i++) {
        var chip = document.createElement('button');
        chip.className = 'filter-chip' + (_alertTierFilter === tiers[i].value ? ' active' : '');
        chip.textContent = tiers[i].label;
        chip.dataset.tier = tiers[i].value;
        chip.addEventListener('click', function() {
            _alertTierFilter = this.dataset.tier;
            _alertSourceFilter = '';
            _buildAlertToolbar();
            _renderMobileAlerts();
        });
        toolbar.appendChild(chip);
    }

    // Source filter chips (only show sources that exist)
    var sources = {};
    for (var si = 0; si < _mobileAlerts.length; si++) {
        var src = _mobileAlerts[si].source || 'unknown';
        sources[src] = (sources[src] || 0) + 1;
    }
    var srcKeys = Object.keys(sources).sort();
    if (srcKeys.length > 1) {
        var sep = document.createElement('span');
        sep.style.cssText = 'width:1px;height:16px;background:var(--border);flex-shrink:0;';
        toolbar.appendChild(sep);
        for (var ski = 0; ski < srcKeys.length; ski++) {
            var sChip = document.createElement('button');
            sChip.className = 'filter-chip' + (_alertSourceFilter === srcKeys[ski] ? ' active' : '');
            sChip.textContent = srcKeys[ski].replace(/_/g, ' ');
            sChip.dataset.source = srcKeys[ski];
            sChip.addEventListener('click', function() {
                _alertSourceFilter = _alertSourceFilter === this.dataset.source ? '' : this.dataset.source;
                _buildAlertToolbar();
                _renderMobileAlerts();
            });
            toolbar.appendChild(sChip);
        }
    }
}

function _classifyAlertSection(a) {
    // Needs Your Decision
    if (a.action_required === true) return 'decision';
    if (a.source === 'browser_transaction' || a.source === 'pending_draft') return 'decision';
    if (a.tier <= 1) return 'decision';
    // Baker Recommends
    var recommendSources = ['research', 'research_executor', 'obligation', 'initiative', 'convergence'];
    if (recommendSources.indexOf(a.source) >= 0) return 'recommends';
    if (a.tier === 2 && a.structured_actions && Object.keys(a.structured_actions).length > 0) return 'recommends';
    // For Your Info
    return 'fyi';
}

function _renderMobileAlerts() {
    var list = document.getElementById('alertsList');
    if (!list) return;
    list.textContent = '';

    // Pin travel card at top of Actions only on travel day (start_date === today)
    if (_activeTrip && !_alertTierFilter && !_alertSourceFilter) {
        var _today = new Date().toISOString().slice(0, 10);
        var _tripEnd = _activeTrip.end_date || _activeTrip.start_date;
        if (_activeTrip.start_date <= _today && _tripEnd >= _today) {
            list.appendChild(_createTravelFeedCard(_activeTrip));
        }
    }

    var filtered = _mobileAlerts.filter(function(a) {
        if (_alertTierFilter) {
            var tf = parseInt(_alertTierFilter);
            if (tf === 3) { if (a.tier < 3) return false; }
            else { if (a.tier !== tf) return false; }
        }
        if (_alertSourceFilter && (a.source || 'unknown') !== _alertSourceFilter) return false;
        return true;
    });

    // Update tab count
    var tabCount = document.getElementById('tabAlertCount');
    if (tabCount) {
        if (_mobileAlerts.length > 0) {
            tabCount.textContent = _mobileAlerts.length;
            tabCount.hidden = false;
        } else {
            tabCount.hidden = true;
        }
    }

    if (filtered.length === 0 && !_activeTrip) {
        var empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.textContent = _mobileAlerts.length > 0 ? 'No alerts matching filter.' : 'No pending alerts.';
        list.appendChild(empty);
        return;
    }

    // Group into sections
    var decisions = [];
    var recommends = [];
    var fyi = [];
    for (var i = 0; i < filtered.length; i++) {
        var section = _classifyAlertSection(filtered[i]);
        if (section === 'decision') decisions.push(filtered[i]);
        else if (section === 'recommends') recommends.push(filtered[i]);
        else fyi.push(filtered[i]);
    }

    // Render sections with sticky headers
    if (decisions.length > 0) {
        var hdr = document.createElement('div');
        hdr.className = 'actions-section-header needs-decision';
        hdr.textContent = 'NEEDS YOUR DECISION (' + decisions.length + ')';
        list.appendChild(hdr);
        for (var di = 0; di < decisions.length; di++) {
            list.appendChild(_createAlertCard(decisions[di]));
        }
    }
    if (recommends.length > 0) {
        var hdr = document.createElement('div');
        hdr.className = 'actions-section-header recommends';
        hdr.textContent = 'BAKER RECOMMENDS (' + recommends.length + ')';
        list.appendChild(hdr);
        for (var ri = 0; ri < recommends.length; ri++) {
            list.appendChild(_createAlertCard(recommends[ri]));
        }
    }
    if (fyi.length > 0) {
        var hdr = document.createElement('div');
        hdr.className = 'actions-section-header fyi';
        hdr.textContent = 'FOR YOUR INFO (' + fyi.length + ')';
        list.appendChild(hdr);
        for (var fi = 0; fi < fyi.length; fi++) {
            list.appendChild(_createAlertCard(fyi[fi]));
        }
    }
}

function _createTravelFeedCard(trip) {
    var card = document.createElement('div');
    card.className = 'travel-feed-card';

    // Route: Origin → Destination
    var route = document.createElement('div');
    route.className = 'travel-feed-route';
    var routeText = '';
    if (trip.origin) routeText += trip.origin + ' ';
    var arrow = document.createElement('span');
    arrow.className = 'travel-feed-route-arrow';
    arrow.textContent = '\u2708\uFE0F';
    var destText = trip.destination || 'Trip';
    route.textContent = '';
    if (trip.origin) {
        route.appendChild(document.createTextNode(trip.origin + ' '));
        route.appendChild(arrow);
        route.appendChild(document.createTextNode(' ' + destText));
    } else {
        route.appendChild(arrow);
        route.appendChild(document.createTextNode(' ' + destText));
    }
    card.appendChild(route);

    // Event + dates
    var event = document.createElement('div');
    event.className = 'travel-feed-event';
    var dateStr = trip.start_date || '';
    if (trip.end_date && trip.end_date !== trip.start_date) dateStr += ' \u2014 ' + trip.end_date;
    event.textContent = (trip.event_name ? trip.event_name + ' \u00B7 ' : '') + dateStr;
    card.appendChild(event);

    // Status indicator
    var today = new Date().toISOString().slice(0, 10);
    var endDate = trip.end_date || trip.start_date;
    var isActive = trip.start_date <= today && endDate >= today;
    var daysUntil = Math.ceil((new Date(trip.start_date) - new Date(today)) / 86400000);

    var detail = document.createElement('div');
    detail.className = 'travel-feed-detail';
    if (isActive) {
        detail.innerHTML = '<span class="travel-feed-detail-icon">\uD83D\uDFE2</span> Trip in progress';
    } else if (daysUntil === 0) {
        detail.innerHTML = '<span class="travel-feed-detail-icon">\uD83D\uDFE2</span> Departing today';
    } else if (daysUntil === 1) {
        detail.innerHTML = '<span class="travel-feed-detail-icon">\uD83D\uDFE1</span> Departing tomorrow';
    } else if (daysUntil > 0 && daysUntil <= 7) {
        detail.innerHTML = '<span class="travel-feed-detail-icon">\uD83D\uDD35</span> In ' + daysUntil + ' days';
    } else if (daysUntil > 7) {
        detail.innerHTML = '<span class="travel-feed-detail-icon">\uD83D\uDD35</span> ' + trip.start_date;
    } else {
        detail.innerHTML = '<span class="travel-feed-detail-icon">\u2705</span> Completed';
    }
    card.appendChild(detail);

    // Tap hint
    var hint = document.createElement('div');
    hint.className = 'travel-feed-tap-hint';
    hint.textContent = 'Tap for trip cards \u203A';
    card.appendChild(hint);

    // Click → open trip overlay
    card.addEventListener('click', function() { _openTripOverlay(trip); });

    return card;
}

function _createAlertCard(alert) {
    var tier = alert.tier || 3;
    var card = document.createElement('div');
    card.className = 'alert-card t' + Math.min(tier, 3);
    card.dataset.alertId = alert.id;

    var menuBtn = document.createElement('button');
    menuBtn.type = 'button';
    menuBtn.className = 'alert-kebab-btn';
    menuBtn.setAttribute('aria-label', 'More actions for this card');
    menuBtn.textContent = '\u22EF';
    menuBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        _showContextMenu(alert);
    });
    card.appendChild(menuBtn);

    // Header row
    var header = document.createElement('div');
    header.className = 'alert-card-header';

    var tierBadge = document.createElement('span');
    tierBadge.className = 'alert-tier t' + Math.min(tier, 3);
    tierBadge.textContent = 'T' + tier;
    header.appendChild(tierBadge);

    var title = document.createElement('span');
    title.className = 'alert-title';
    title.textContent = alert.title || 'Untitled';
    header.appendChild(title);

    var time = document.createElement('span');
    time.className = 'alert-time';
    time.textContent = _fmtTimeAgo(alert.created_at);
    header.appendChild(time);

    card.appendChild(header);

    // Meta (source)
    if (alert.source) {
        var meta = document.createElement('div');
        meta.className = 'alert-meta';
        meta.textContent = (alert.source || '').replace(/_/g, ' ');
        if (alert.matter_slug) meta.textContent += ' · ' + alert.matter_slug.replace(/_/g, ' ');
        card.appendChild(meta);
    }

    // Expandable body
    if (alert.body) {
        var body = document.createElement('div');
        body.className = 'alert-body';
        body.textContent = alert.body;
        card.appendChild(body);
    }

    // Primary action stays visible; secondary actions live behind the menu.
    var sa = alert.structured_actions || {};
    var btnRow = document.createElement('div');
    btnRow.className = 'alert-action-buttons triage-buttons';
    btnRow.style.marginTop = '8px';
    var hasPrimaryAction = false;

    // Run button — only when there's an actionable structured_action
    if (alert.source === 'browser_transaction' && sa.action_id) {
        var runBtn = document.createElement('button');
        runBtn.className = 'triage-btn approve';
        runBtn.textContent = 'Run';
        runBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            _confirmBrowserAction(sa.action_id, alert.id, card);
        });
        btnRow.appendChild(runBtn);
        hasPrimaryAction = true;
    } else if (sa.research_proposal_id) {
        // Check if dossier is already completed — show View link directly
        if (sa.status === 'completed') {
            var viewLink = document.createElement('a');
            viewLink.href = '/api/research-proposals/' + sa.research_proposal_id + '/view?key=' + encodeURIComponent(BAKER.apiKey);
            viewLink.className = 'triage-btn approve';
            viewLink.style.cssText = 'text-decoration:none;text-align:center;';
            viewLink.textContent = 'View Dossier';
            viewLink.target = '_blank';
            viewLink.addEventListener('click', function(e) { e.stopPropagation(); });
            btnRow.appendChild(viewLink);
            hasPrimaryAction = true;
        } else {
            var runBtn = document.createElement('button');
            runBtn.className = 'triage-btn approve';
            runBtn.textContent = 'Run';
            runBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                _runDossierFromAlert(sa.research_proposal_id, alert.id, card);
            });
            btnRow.appendChild(runBtn);
            hasPrimaryAction = true;
        }
    } else if (alert.source === 'obligation' && sa.action_id) {
        var runBtn = document.createElement('button');
        runBtn.className = 'triage-btn approve';
        runBtn.textContent = 'Run';
        runBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            _resolveAlertCard(alert.id, card);
        });
        btnRow.appendChild(runBtn);
        hasPrimaryAction = true;
    }

    if (hasPrimaryAction) card.appendChild(btnRow);

    // Long-press → context menu
    var _lpTimer = null;
    var _lpStartX = 0, _lpStartY = 0;
    card.addEventListener('touchstart', function(e) {
        _lpStartX = e.touches[0].clientX;
        _lpStartY = e.touches[0].clientY;
        _lpTimer = setTimeout(function() {
            _lpTimer = null;
            if (navigator.vibrate) navigator.vibrate(50);
            _showContextMenu(alert);
        }, 500);
    }, { passive: true });
    card.addEventListener('touchmove', function(e) {
        if (!_lpTimer) return;
        if (Math.abs(e.touches[0].clientX - _lpStartX) > 10 || Math.abs(e.touches[0].clientY - _lpStartY) > 10) {
            clearTimeout(_lpTimer);
            _lpTimer = null;
        }
    }, { passive: true });
    card.addEventListener('touchend', function() {
        if (_lpTimer) { clearTimeout(_lpTimer); _lpTimer = null; }
    });

    // Tap to expand/collapse
    card.addEventListener('click', function(e) {
        if (e.target.tagName === 'BUTTON' || e.target.tagName === 'A') return;
        card.classList.toggle('expanded');
    });

    // Swipe to dismiss
    _setupSwipeDismiss(card, alert.id);

    return card;
}

function _setupSwipeDismiss(card, alertId) {
    var startX = 0;
    var currentX = 0;
    var swiping = false;

    card.addEventListener('touchstart', function(e) {
        startX = e.touches[0].clientX;
        swiping = true;
    }, { passive: true });

    card.addEventListener('touchmove', function(e) {
        if (!swiping) return;
        currentX = e.touches[0].clientX - startX;
        if (currentX > 0) {
            card.style.transform = 'translateX(' + Math.min(currentX, 150) + 'px)';
            card.style.opacity = Math.max(1 - currentX / 200, 0.3);
        }
    }, { passive: true });

    card.addEventListener('touchend', function() {
        if (!swiping) return;
        swiping = false;
        if (currentX > 80) {
            // Dismiss
            card.style.transform = 'translateX(100%)';
            card.style.opacity = '0';
            setTimeout(function() { card.remove(); }, 200);
            _dismissAlertWithUndo(alertId);
        } else {
            card.style.transform = '';
            card.style.opacity = '';
        }
        currentX = 0;
    });
}

function _dismissAlertWithUndo(alertId) {
    var undoTimeout = null;

    // Show undo toast
    var toast = document.createElement('div');
    toast.className = 'undo-toast';
    var text = document.createElement('span');
    text.textContent = 'Alert dismissed';
    toast.appendChild(text);

    var undoBtn = document.createElement('button');
    undoBtn.textContent = 'Undo';
    undoBtn.addEventListener('click', function() {
        clearTimeout(undoTimeout);
        toast.remove();
        // Re-render (alert still in _mobileAlerts)
        _renderMobileAlerts();
    });
    toast.appendChild(undoBtn);
    document.body.appendChild(toast);

    // Actually dismiss after 3s
    undoTimeout = setTimeout(function() {
        toast.remove();
        // Remove from local cache
        _mobileAlerts = _mobileAlerts.filter(function(a) { return a.id !== alertId; });
        // API call
        bakerFetch('/api/alerts/' + alertId + '/dismiss', { method: 'POST' })
            .then(function() { refreshAlertBadge(); })
            .catch(function() { /* silent */ });
        _buildAlertFooter();
    }, 3000);
}

function _buildAlertFooter() {
    var footer = document.getElementById('alertsFooter');
    if (!footer) return;
    footer.textContent = '';

    var t3Count = 0;
    for (var i = 0; i < _mobileAlerts.length; i++) {
        if (_mobileAlerts[i].tier >= 3) t3Count++;
    }

    if (t3Count > 0) {
        var t3Btn = document.createElement('button');
        t3Btn.className = 'danger';
        t3Btn.textContent = 'Dismiss all T3+ (' + t3Count + ')';
        t3Btn.addEventListener('click', function() { _bulkDismissT3(); });
        footer.appendChild(t3Btn);
        footer.hidden = false;
    } else {
        footer.hidden = true;
    }
}

async function _bulkDismissT3() {
    try {
        var r = await bakerFetch('/api/alerts/bulk-dismiss', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tier: 3 }),
        });
        if (!r.ok) throw new Error('API ' + r.status);
        _mobileAlerts = _mobileAlerts.filter(function(a) { return a.tier < 3; });
        _renderMobileAlerts();
        _buildAlertFooter();
        refreshAlertBadge();
    } catch (e) { console.error('bulkDismissT3 failed:', e); }
}

// ═══ REALTIME-PUSH-1: Live alert stream (mobile) ═══
var _mobileMuted = false;

function _mobileBeep() {
    if (_mobileMuted) return;
    try {
        var ctx = new (window.AudioContext || window.webkitAudioContext)();
        var osc = ctx.createOscillator();
        var gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.frequency.value = 880;
        osc.type = 'sine';
        gain.gain.value = 0.3;
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
        osc.start();
        osc.stop(ctx.currentTime + 0.4);
    } catch (e) { /* no audio */ }
}

function _showMobileToast(alert) {
    var isT1 = alert.tier === 1;
    var toast = document.createElement('div');
    toast.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:9999;padding:14px 16px;font-size:13px;font-family:inherit;color:#fff;cursor:pointer;'
        + (isT1 ? 'background:#dc2626;' : 'background:#0a6fdb;');

    var text = document.createElement('span');
    text.textContent = 'T' + alert.tier + '  ' + (alert.title || '').substring(0, 60);
    toast.appendChild(text);

    toast.addEventListener('click', function() { toast.remove(); switchTab('feed'); });
    document.body.appendChild(toast);

    setTimeout(function() {
        toast.style.transition = 'opacity 0.3s';
        toast.style.opacity = '0';
        setTimeout(function() { toast.remove(); }, 300);
    }, isT1 ? 30000 : 10000);
}

function _connectMobileAlertStream() {
    var key = BAKER.apiKey || '';
    if (!key) {
        setTimeout(_connectMobileAlertStream, 3000);
        return;
    }
    var es = new EventSource('/api/alerts/stream?key=' + encodeURIComponent(key));

    es.onmessage = function(event) {
        try {
            var data = JSON.parse(event.data);
            if (data.type === 'new_alert' && data.tier <= 2) {
                _showMobileToast(data);
                refreshAlertBadge();
                if (data.tier === 1) _mobileBeep();
                // Browser notification
                if (window.Notification && Notification.permission === 'granted') {
                    try {
                        new Notification('Baker T' + data.tier, {
                            body: (data.title || '').substring(0, 100),
                            icon: '/static/baker-face-green.svg',
                            tag: 'baker-alert-' + data.id,
                        });
                    } catch (e) { /* silent */ }
                }
            }
        } catch (e) { /* skip */ }
    };

    es.onerror = function() {
        es.close();
        setTimeout(_connectMobileAlertStream, 30000);
    };
}

// ═══ E4: TRIP BANNER + CARDS ═══
var _activeTrip = null;
var _tripCardsData = null;

async function loadActiveTrip() {
    try {
        var r = await bakerFetch('/api/trips');
        if (!r.ok) return;
        var data = await r.json();
        var trips = data.trips || [];
        if (trips.length === 0) return;

        // Find active trip: prefer one that covers today, else nearest upcoming
        var today = new Date().toISOString().slice(0, 10);
        var active = null;
        for (var i = 0; i < trips.length; i++) {
            var t = trips[i];
            if (t.status === 'discarded' || t.status === 'completed') continue;
            var endDate = t.end_date || t.start_date;
            if (t.start_date <= today && endDate >= today) { active = t; break; }
        }
        if (!active) {
            // Find nearest upcoming
            var upcoming = trips.filter(function(t) {
                return t.status !== 'discarded' && t.status !== 'completed' && t.start_date >= today;
            }).sort(function(a, b) { return a.start_date.localeCompare(b.start_date); });
            if (upcoming.length > 0) active = upcoming[0];
        }
        // No fallback to past trips — only show today's or upcoming

        if (!active) return;
        _activeTrip = active;
        _renderTripBanner(active);
        // Re-render feed to inject travel card if alerts already loaded
        if (_mobileAlerts.length > 0 || document.getElementById('alertsList')) {
            _renderMobileAlerts();
        }
    } catch (e) {
        console.error('loadActiveTrip failed:', e);
    }
}

function _renderTripBanner(trip) {
    var banner = document.getElementById('tripBanner');
    var content = document.getElementById('tripBannerContent');
    if (!banner || !content) return;

    var dateStr = trip.start_date || '';
    if (trip.end_date && trip.end_date !== trip.start_date) dateStr += ' \u2014 ' + trip.end_date;
    // Add relative day label so user knows when the trip is
    var today = new Date().toISOString().slice(0, 10);
    var dayLabel = '';
    if (trip.start_date === today) { dayLabel = 'Today'; }
    else if (trip.start_date) {
        var diffMs = new Date(trip.start_date) - new Date(today);
        var diffDays = Math.round(diffMs / 86400000);
        if (diffDays === 1) dayLabel = 'Tomorrow';
        else if (diffDays > 1 && diffDays <= 7) dayLabel = 'In ' + diffDays + ' days';
    }
    var meta = (dayLabel ? dayLabel + ' \u00B7 ' : '') + dateStr;
    if (trip.event_name) meta = (dayLabel ? dayLabel + ' \u00B7 ' : '') + trip.event_name + ' \u00B7 ' + dateStr;

    content.textContent = '';
    var dest = document.createElement('div');
    dest.className = 'trip-banner-dest';
    dest.textContent = (trip.origin ? trip.origin + ' \u2192 ' : '') + (trip.destination || 'Trip');
    content.appendChild(dest);

    var metaEl = document.createElement('div');
    metaEl.className = 'trip-banner-meta';
    metaEl.textContent = meta;
    content.appendChild(metaEl);

    banner.hidden = false;
    banner.addEventListener('click', function() { _openTripOverlay(trip); });
}

async function _openTripOverlay(trip) {
    var overlay = document.getElementById('tripOverlay');
    var title = document.getElementById('tripOverlayTitle');
    var container = document.getElementById('tripCardsContainer');
    if (!overlay) return;

    title.textContent = trip.destination || 'Trip';
    container.textContent = '';
    var loading = document.createElement('div');
    loading.className = 'empty-state';
    loading.textContent = 'Loading trip cards...';
    container.appendChild(loading);
    overlay.hidden = false;

    try {
        var resp = await bakerFetch('/api/trips/' + trip.id + '/cards');
        if (!resp.ok) throw new Error('API ' + resp.status);
        _tripCardsData = await resp.json();
        _renderTripCards(trip, _tripCardsData, container);
    } catch (e) {
        container.textContent = '';
        var err = document.createElement('div');
        err.className = 'empty-state';
        err.textContent = 'Failed to load trip cards.';
        container.appendChild(err);
    }
}

function _closeTripOverlay() {
    var overlay = document.getElementById('tripOverlay');
    if (overlay) overlay.hidden = true;
}

function _renderTripCards(trip, cards, container) {
    container.textContent = '';

    // Objective card (from trip data)
    if (trip.strategic_objective) {
        container.appendChild(_makeTripCard('Objective', '\uD83C\uDFAF', null, function(body) {
            var obj = document.createElement('div');
            obj.className = 'trip-objective';
            obj.textContent = trip.strategic_objective;
            body.appendChild(obj);
        }, true));
    }

    // Timezone card
    var tz = (cards.logistics || {}).timezone || (cards.timezone || {}).timezone || {};
    if (tz.diff) {
        container.appendChild(_makeTripCard('Timezone', '\uD83C\uDF0D', null, function(body) {
            var strip = document.createElement('div');
            strip.className = 'trip-tz-strip';
            var d = document.createElement('span');
            d.textContent = 'Destination: ';
            var dStrong = document.createElement('strong');
            dStrong.textContent = tz.local_now || '?';
            d.appendChild(dStrong);
            strip.appendChild(d);
            var h = document.createElement('span');
            h.textContent = 'Zurich: ' + (tz.home_now || '?');
            strip.appendChild(h);
            var diff = document.createElement('span');
            diff.textContent = tz.diff;
            var diffStrong = document.createElement('strong');
            diffStrong.textContent = tz.diff;
            diff.textContent = '';
            diff.appendChild(diffStrong);
            strip.appendChild(diff);
            body.appendChild(strip);
        }, true));
    }

    // Agenda card
    var agenda = cards.agenda || {};
    var days = agenda.days || [];
    var eventCount = 0;
    for (var di = 0; di < days.length; di++) eventCount += (days[di].events || []).length;
    container.appendChild(_makeTripCard('Agenda', '\uD83D\uDCC5', eventCount || null, function(body) {
        if (days.length === 0) {
            _addEmpty(body, 'No calendar events for this trip.');
            return;
        }
        for (var i = 0; i < days.length; i++) {
            var dayLabel = document.createElement('div');
            dayLabel.style.cssText = 'font-size:11px;font-weight:600;color:var(--text3);text-transform:uppercase;margin:8px 0 4px;';
            dayLabel.textContent = days[i].date;
            body.appendChild(dayLabel);
            var evts = days[i].events || [];
            for (var j = 0; j < evts.length; j++) {
                var ev = evts[j];
                var item = document.createElement('div');
                item.className = 'trip-card-item';
                var startTime = '';
                try { startTime = new Date(ev.start).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}); } catch(e) {}
                var titleDiv = document.createElement('div');
                titleDiv.className = 'trip-card-item-title';
                titleDiv.textContent = (startTime ? startTime + '  ' : '') + (ev.title || '');
                item.appendChild(titleDiv);
                if (ev.location) {
                    var loc = document.createElement('div');
                    loc.className = 'trip-card-item-sub';
                    loc.textContent = ev.location;
                    item.appendChild(loc);
                }
                body.appendChild(item);
            }
        }
    }));

    // Logistics card
    var logistics = cards.logistics || {};
    var emails = logistics.emails || [];
    var wa = logistics.whatsapp || [];
    var logCount = emails.length + wa.length;
    container.appendChild(_makeTripCard('Logistics', '\uD83D\uDCE7', logCount || null, function(body) {
        if (emails.length === 0 && wa.length === 0) {
            _addEmpty(body, 'No logistics messages found.');
            return;
        }
        if (emails.length > 0) {
            var emailLabel = document.createElement('div');
            emailLabel.style.cssText = 'font-size:10px;color:var(--text3);text-transform:uppercase;margin-bottom:4px;';
            emailLabel.textContent = 'Emails (' + emails.length + ')';
            body.appendChild(emailLabel);
            for (var i = 0; i < Math.min(emails.length, 5); i++) {
                var em = emails[i];
                var item = document.createElement('div');
                item.className = 'trip-card-item';
                var t = document.createElement('div');
                t.className = 'trip-card-item-title';
                t.textContent = em.subject || 'No subject';
                item.appendChild(t);
                var sub = document.createElement('div');
                sub.className = 'trip-card-item-sub';
                sub.textContent = (em.sender_name || '') + (em.received_date ? ' \u00B7 ' + new Date(em.received_date).toLocaleDateString() : '');
                item.appendChild(sub);
                body.appendChild(item);
            }
        }
        if (wa.length > 0) {
            var waLabel = document.createElement('div');
            waLabel.style.cssText = 'font-size:10px;color:var(--text3);text-transform:uppercase;margin:8px 0 4px;';
            waLabel.textContent = 'WhatsApp (' + wa.length + ')';
            body.appendChild(waLabel);
            for (var i = 0; i < Math.min(wa.length, 5); i++) {
                var m = wa[i];
                var item = document.createElement('div');
                item.className = 'trip-card-item';
                var t = document.createElement('div');
                t.className = 'trip-card-item-title';
                t.textContent = m.sender_name || '';
                item.appendChild(t);
                var snip = document.createElement('div');
                snip.className = 'trip-card-item-sub';
                snip.textContent = (m.snippet || '').substring(0, 120);
                item.appendChild(snip);
                body.appendChild(item);
            }
        }
    }));

    // Reading card
    var reading = cards.reading || {};
    var docs = reading.documents || [];
    container.appendChild(_makeTripCard('Reading', '\uD83D\uDCD6', docs.length || null, function(body) {
        if (docs.length === 0) {
            _addEmpty(body, 'No priority documents found.');
            return;
        }
        for (var i = 0; i < docs.length; i++) {
            var d = docs[i];
            var item = document.createElement('div');
            item.className = 'trip-card-item';
            var t = document.createElement('div');
            t.className = 'trip-card-item-title';
            t.textContent = d.filename || 'Document';
            item.appendChild(t);
            if (d.document_type) {
                var sub = document.createElement('div');
                sub.className = 'trip-card-item-sub';
                sub.textContent = d.document_type.replace(/_/g, ' ');
                item.appendChild(sub);
            }
            body.appendChild(item);
        }
    }));

    // Radar card
    var radar = cards.radar || {};
    var dormant = radar.dormant_contacts || [];
    container.appendChild(_makeTripCard('Radar', '\uD83D\uDCE1', dormant.length || null, function(body) {
        if (dormant.length === 0) {
            _addEmpty(body, 'No dormant contacts at this destination.');
            return;
        }
        for (var i = 0; i < dormant.length; i++) {
            var c = dormant[i];
            var item = document.createElement('div');
            item.className = 'trip-card-item';
            item.style.display = 'flex';
            item.style.justifyContent = 'space-between';
            item.style.alignItems = 'center';
            var left = document.createElement('div');
            var name = document.createElement('span');
            name.className = 'trip-card-item-title';
            name.textContent = c.name || '';
            left.appendChild(name);
            if (c.role) {
                var role = document.createElement('div');
                role.className = 'trip-card-item-sub';
                role.textContent = c.role;
                left.appendChild(role);
            }
            item.appendChild(left);
            var ago = document.createElement('span');
            ago.style.cssText = 'font-size:11px;color:var(--text3);flex-shrink:0;';
            ago.textContent = c.days_since_contact ? c.days_since_contact + 'd ago' : 'Never';
            item.appendChild(ago);
            body.appendChild(item);
        }
    }));
}

function _makeTripCard(title, icon, count, renderFn, startExpanded) {
    var card = document.createElement('div');
    card.className = 'trip-card' + (startExpanded ? ' expanded' : '');

    var header = document.createElement('div');
    header.className = 'trip-card-header';

    var iconEl = document.createElement('span');
    iconEl.className = 'trip-card-icon';
    iconEl.textContent = icon;
    header.appendChild(iconEl);

    var titleEl = document.createElement('span');
    titleEl.className = 'trip-card-title';
    titleEl.textContent = title;
    header.appendChild(titleEl);

    if (count !== null && count !== undefined) {
        var countEl = document.createElement('span');
        countEl.className = 'trip-card-count';
        countEl.textContent = count;
        header.appendChild(countEl);
    }

    var toggle = document.createElement('span');
    toggle.className = 'trip-card-toggle';
    toggle.textContent = '\u25BE';
    header.appendChild(toggle);

    header.addEventListener('click', function() { card.classList.toggle('expanded'); });
    card.appendChild(header);

    var body = document.createElement('div');
    body.className = 'trip-card-body';
    renderFn(body);
    card.appendChild(body);

    return card;
}

function _addEmpty(container, text) {
    var el = document.createElement('div');
    el.className = 'trip-card-empty';
    el.textContent = text;
    container.appendChild(el);
}

// ═══ E5: VOICE INPUT (Web Speech API) ═══
var _recognition = null;
var _isRecording = false;
var _interimTranscript = '';
var _finalTranscript = '';

function _setupVoiceInput() {
    var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return; // API not available — mic stays hidden

    var micBtn = document.getElementById('micBtn');
    micBtn.hidden = false;

    _recognition = new SpeechRecognition();
    _recognition.continuous = true;
    _recognition.interimResults = true;
    _recognition.lang = 'en-US';
    _recognition.maxAlternatives = 1;

    _recognition.onresult = function(event) {
        _interimTranscript = '';
        _finalTranscript = '';
        for (var i = 0; i < event.results.length; i++) {
            if (event.results[i].isFinal) {
                _finalTranscript += event.results[i][0].transcript;
            } else {
                _interimTranscript += event.results[i][0].transcript;
            }
        }
        var input = document.getElementById('bakerInput');
        if (input) {
            input.value = _finalTranscript + _interimTranscript;
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 120) + 'px';
        }
    };

    _recognition.onerror = function(event) {
        console.warn('Speech recognition error:', event.error);
        if (event.error === 'not-allowed') {
            var label = document.getElementById('micLabel');
            if (label) label.textContent = 'Microphone blocked';
        }
        _stopRecording();
    };

    _recognition.onend = function() {
        if (_isRecording) {
            // Auto-restart if user hasn't explicitly stopped
            try { _recognition.start(); } catch(e) { _stopRecording(); }
        }
    };

    micBtn.addEventListener('click', function() {
        if (_isRecording) {
            _stopRecording();
        } else {
            _startRecording();
        }
    });

    // Language selector
    var langSel = document.getElementById('micLang');
    if (langSel) {
        langSel.addEventListener('change', function() {
            _recognition.lang = langSel.value;
            if (_isRecording) {
                _recognition.stop();
                setTimeout(function() { try { _recognition.start(); } catch(e) {} }, 100);
            }
        });
    }
}

function _startRecording() {
    if (!_recognition) return;
    _isRecording = true;
    _finalTranscript = '';
    _interimTranscript = '';

    var micBtn = document.getElementById('micBtn');
    var micStatus = document.getElementById('micStatus');
    var micLabel = document.getElementById('micLabel');
    var langSel = document.getElementById('micLang');

    if (micBtn) micBtn.classList.add('recording');
    if (micStatus) micStatus.hidden = false;
    if (micLabel) micLabel.textContent = 'Listening...';
    if (langSel) _recognition.lang = langSel.value;

    try {
        _recognition.start();
    } catch(e) {
        console.warn('Recognition start failed:', e);
        _stopRecording();
    }

    // Auto-stop after 60s
    setTimeout(function() {
        if (_isRecording) _stopRecording();
    }, 60000);
}

function _stopRecording() {
    _isRecording = false;
    var micBtn = document.getElementById('micBtn');
    var micStatus = document.getElementById('micStatus');

    if (micBtn) micBtn.classList.remove('recording');
    if (micStatus) micStatus.hidden = true;

    if (_recognition) {
        try { _recognition.stop(); } catch(e) {}
    }

    // Focus input for editing
    var input = document.getElementById('bakerInput');
    if (input) input.focus();
}

// ═══ E8: FILE UPLOAD ═══
var _uploadFile = null;

function _setupUpload() {
    var btn = document.getElementById('uploadBtn');
    var overlay = document.getElementById('uploadOverlay');
    var closeBtn = document.getElementById('uploadCloseBtn');
    var dropzone = document.getElementById('uploadDropzone');
    var fileInput = document.getElementById('uploadFileInput');
    var sendBtn = document.getElementById('uploadSendBtn');

    btn.addEventListener('click', function() { _openUploadSheet(); });
    closeBtn.addEventListener('click', function() { _closeUploadSheet(); });
    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) _closeUploadSheet();
    });
    dropzone.addEventListener('click', function() { fileInput.click(); });
    fileInput.addEventListener('change', function() {
        if (fileInput.files[0]) _previewUploadFile(fileInput.files[0]);
    });
    sendBtn.addEventListener('click', function() { _doUpload(); });
}

function _openUploadSheet() {
    _uploadFile = null;
    var overlay = document.getElementById('uploadOverlay');
    var dropzone = document.getElementById('uploadDropzone');
    var preview = document.getElementById('uploadPreview');
    var progress = document.getElementById('uploadProgress');
    var result = document.getElementById('uploadResult');
    var fileInput = document.getElementById('uploadFileInput');

    dropzone.hidden = false;
    preview.hidden = true;
    progress.hidden = true;
    result.hidden = true;
    result.className = 'upload-result';
    fileInput.value = '';
    overlay.hidden = false;
}

function _closeUploadSheet() {
    document.getElementById('uploadOverlay').hidden = true;
    _uploadFile = null;
}

function _previewUploadFile(file) {
    _uploadFile = file;
    var dropzone = document.getElementById('uploadDropzone');
    var preview = document.getElementById('uploadPreview');
    var info = document.getElementById('uploadFileInfo');
    var warn = document.getElementById('uploadSizeWarn');

    dropzone.hidden = true;
    preview.hidden = false;

    var sizeMB = (file.size / 1048576).toFixed(1);
    info.textContent = file.name + ' (' + sizeMB + ' MB)';
    warn.hidden = file.size <= 5242880;
}

async function _doUpload() {
    if (!_uploadFile) return;
    var preview = document.getElementById('uploadPreview');
    var progress = document.getElementById('uploadProgress');
    var result = document.getElementById('uploadResult');
    var sendBtn = document.getElementById('uploadSendBtn');

    sendBtn.disabled = true;
    preview.hidden = true;
    progress.hidden = false;

    try {
        var formData = new FormData();
        formData.append('file', _uploadFile);

        var resp = await fetch('/api/documents/upload', {
            method: 'POST',
            headers: { 'X-Baker-Key': BAKER.apiKey },
            body: formData,
        });

        progress.hidden = true;
        result.hidden = false;

        if (!resp.ok) {
            var errText = '';
            try { errText = (await resp.json()).detail || resp.status; } catch(e) { errText = resp.status; }
            throw new Error(errText);
        }

        var data = await resp.json();
        result.className = 'upload-result success';
        result.textContent = 'Document uploaded \u2014 Baker will analyze it shortly.';

        // Auto-close after 2s
        setTimeout(function() { _closeUploadSheet(); }, 2000);
    } catch (e) {
        result.className = 'upload-result error';
        result.textContent = 'Upload failed: ' + e.message;
        sendBtn.disabled = false;
    }
}

// ═══ CONTEXT MENU (Long-Press) ═══

function _showContextMenu(alert) {
    var old = document.getElementById('contextMenuOverlay');
    if (old) old.remove();

    var overlay = document.createElement('div');
    overlay.id = 'contextMenuOverlay';
    overlay.className = 'context-menu-overlay';

    var sheet = document.createElement('div');
    sheet.className = 'context-menu-sheet';

    // Header
    var header = document.createElement('div');
    header.className = 'context-menu-header';
    var headerTitle = document.createElement('div');
    headerTitle.className = 'context-menu-title';
    headerTitle.textContent = (alert.title || 'Alert').substring(0, 60);
    header.appendChild(headerTitle);
    var headerMeta = document.createElement('div');
    headerMeta.className = 'context-menu-meta';
    headerMeta.textContent = 'T' + (alert.tier || 3) + ' \u00B7 ' + (alert.source || '').replace(/_/g, ' ');
    header.appendChild(headerMeta);
    sheet.appendChild(header);

    // Actions
    var actions = [
        { icon: '\u270F\uFE0F', label: 'Draft a reply', id: 'draft' },
        { icon: '\uD83D\uDCAC', label: 'Ask Baker about this', id: 'ask' },
        { icon: '\u23F0', label: 'Snooze', id: 'snooze' },
        { icon: '\u27A1\uFE0F', label: 'Delegate', id: 'delegate' },
        { icon: '\u2715', label: 'Dismiss', id: 'dismiss' },
    ];

    actions.forEach(function(action) {
        var btn = document.createElement('button');
        btn.className = 'context-menu-action';

        var iconSpan = document.createElement('span');
        iconSpan.className = 'context-menu-action-icon';
        iconSpan.textContent = action.icon;
        btn.appendChild(iconSpan);

        var labelSpan = document.createElement('span');
        labelSpan.textContent = action.label;
        btn.appendChild(labelSpan);

        btn.addEventListener('click', function() {
            _closeContextMenu();
            if (action.id === 'ask') _askBakerAbout(alert);
            else if (action.id === 'snooze') _showSnoozeOptions(alert);
            else if (action.id === 'draft') _draftReply(alert);
            else if (action.id === 'delegate') _delegateAlert(alert);
            else if (action.id === 'dismiss') _dismissAlertCard(alert.id);
        });

        sheet.appendChild(btn);
    });

    // Cancel
    var cancelBtn = document.createElement('button');
    cancelBtn.className = 'context-menu-cancel';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', _closeContextMenu);
    sheet.appendChild(cancelBtn);

    overlay.appendChild(sheet);
    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) _closeContextMenu();
    });
    document.body.appendChild(overlay);

    requestAnimationFrame(function() {
        overlay.classList.add('visible');
    });
}

function _closeContextMenu() {
    var overlay = document.getElementById('contextMenuOverlay');
    if (overlay) {
        overlay.classList.remove('visible');
        setTimeout(function() { overlay.remove(); }, 200);
    }
}

// ═══ ASK BAKER ABOUT ALERT ═══

function _askBakerAbout(alert) {
    // SCAN-CONTEXT-1: Clear old history to prevent context bleed
    bakerHistory = [];
    var container = document.getElementById('bakerMessages');
    if (container) container.textContent = '';

    // Inject alert context as system message so Baker knows the topic
    var alertContext = '[Context from alert: "' + (alert.title || '') + '"';
    if (alert.body) alertContext += '\n' + (alert.body || '').substring(0, 500);
    alertContext += ']';
    bakerHistory.push({ role: 'system', content: alertContext });

    var sa = alert.structured_actions || {};
    var context = sa.suggested_action || (alert.body || '').substring(0, 200) || alert.title || '';
    var prefix = 'About: "' + (alert.title || '').substring(0, 80) + '"';
    if (alert.source) prefix += ' (' + alert.source.replace(/_/g, ' ') + ')';
    prefix += '\n\n' + context;

    switchTab('baker');
    var input = document.getElementById('bakerInput');
    if (input) {
        input.value = prefix;
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
        setTimeout(function() { input.focus(); }, 150);
    }
}

// ═══ SNOOZE ═══

function _showSnoozeOptions(alert) {
    var old = document.getElementById('contextMenuOverlay');
    if (old) old.remove();

    var overlay = document.createElement('div');
    overlay.id = 'contextMenuOverlay';
    overlay.className = 'context-menu-overlay';

    var sheet = document.createElement('div');
    sheet.className = 'context-menu-sheet';

    var header = document.createElement('div');
    header.className = 'context-menu-header';
    var title = document.createElement('div');
    title.className = 'context-menu-title';
    title.textContent = 'Snooze: ' + (alert.title || 'Alert').substring(0, 50);
    header.appendChild(title);
    sheet.appendChild(header);

    var options = [
        { label: '4 hours', value: '4h' },
        { label: 'Tomorrow morning', value: 'tomorrow' },
        { label: 'Next week', value: 'next_week' },
    ];

    options.forEach(function(opt) {
        var btn = document.createElement('button');
        btn.className = 'context-menu-action';
        var iconSpan = document.createElement('span');
        iconSpan.className = 'context-menu-action-icon';
        iconSpan.textContent = '\u23F0';
        btn.appendChild(iconSpan);
        var labelSpan = document.createElement('span');
        labelSpan.textContent = opt.label;
        btn.appendChild(labelSpan);
        btn.addEventListener('click', function() {
            _closeContextMenu();
            _snoozeAlert(alert.id, opt.value, opt.label);
        });
        sheet.appendChild(btn);
    });

    var cancelBtn = document.createElement('button');
    cancelBtn.className = 'context-menu-cancel';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', _closeContextMenu);
    sheet.appendChild(cancelBtn);

    overlay.appendChild(sheet);
    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) _closeContextMenu();
    });
    document.body.appendChild(overlay);
    requestAnimationFrame(function() { overlay.classList.add('visible'); });
}

function _snoozeAlert(alertId, duration, label) {
    // Optimistic UI: remove card
    var card = document.querySelector('.alert-card[data-alert-id="' + alertId + '"]');
    if (card) {
        card.style.transition = 'opacity 0.3s, transform 0.3s';
        card.style.opacity = '0';
        card.style.transform = 'scale(0.95)';
        setTimeout(function() { card.remove(); }, 300);
    }
    _mobileAlerts = _mobileAlerts.filter(function(a) { return a.id !== alertId; });

    // Toast
    var toast = document.createElement('div');
    toast.className = 'undo-toast';
    var text = document.createElement('span');
    text.textContent = 'Snoozed until ' + label;
    toast.appendChild(text);
    document.body.appendChild(toast);
    setTimeout(function() {
        toast.style.transition = 'opacity 0.3s';
        toast.style.opacity = '0';
        setTimeout(function() { toast.remove(); }, 300);
    }, 3000);

    // API call
    bakerFetch('/api/alerts/' + alertId + '/snooze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ duration: duration }),
    }).then(function() {
        refreshAlertBadge();
    }).catch(function(e) {
        console.error('Snooze failed:', e);
    });
}

// ═══ DRAFT A REPLY ═══

function _draftReply(alert) {
    // Create full-screen draft overlay
    var old = document.getElementById('draftOverlay');
    if (old) old.remove();

    var overlay = document.createElement('div');
    overlay.id = 'draftOverlay';
    overlay.className = 'draft-overlay';

    // Header
    var header = document.createElement('div');
    header.className = 'draft-header';
    var backBtn = document.createElement('button');
    backBtn.className = 'draft-back-btn';
    backBtn.textContent = '\u2190 Back';
    backBtn.addEventListener('click', function() { overlay.remove(); });
    header.appendChild(backBtn);
    var titleEl = document.createElement('span');
    titleEl.className = 'draft-title';
    titleEl.textContent = 'Draft Reply';
    header.appendChild(titleEl);
    overlay.appendChild(header);

    // Body
    var body = document.createElement('div');
    body.className = 'draft-body';

    // Alert context
    var ctx = document.createElement('div');
    ctx.style.cssText = 'font-size:12px;color:var(--text3);margin-bottom:12px;padding:8px;background:var(--bg2);border-radius:8px;';
    ctx.textContent = 'Re: ' + (alert.title || 'Alert').substring(0, 100);
    body.appendChild(ctx);

    // Loading state
    var loading = document.createElement('div');
    loading.className = 'draft-loading';
    loading.innerHTML = '<div class="spinner"></div><div style="margin-top:8px">Generating draft...</div>';
    body.appendChild(loading);

    overlay.appendChild(body);

    // Actions bar (hidden until draft loads)
    var actions = document.createElement('div');
    actions.className = 'draft-actions';
    actions.style.display = 'none';

    var copyBtn = document.createElement('button');
    copyBtn.className = 'draft-edit-btn';
    copyBtn.textContent = 'Copy';
    actions.appendChild(copyBtn);

    var askBtn = document.createElement('button');
    askBtn.className = 'draft-send-btn';
    askBtn.textContent = 'Send to Baker';
    actions.appendChild(askBtn);

    var discardBtn = document.createElement('button');
    discardBtn.className = 'draft-discard-btn';
    discardBtn.textContent = 'Discard';
    discardBtn.addEventListener('click', function() { overlay.remove(); });
    actions.appendChild(discardBtn);

    overlay.appendChild(actions);
    document.body.appendChild(overlay);

    // Fetch draft
    bakerFetch('/api/alerts/' + alert.id + '/draft', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
    }).then(function(r) {
        if (!r.ok) throw new Error('API ' + r.status);
        return r.json();
    }).then(function(data) {
        loading.remove();
        var draftText = data.draft || 'Could not generate draft.';

        // Editable textarea
        var ta = document.createElement('textarea');
        ta.style.cssText = 'width:100%;min-height:200px;padding:12px;border:1px solid var(--border);border-radius:8px;background:var(--bg2);color:var(--text);font-family:inherit;font-size:14px;line-height:1.6;resize:vertical;';
        ta.value = draftText;
        body.appendChild(ta);

        actions.style.display = 'flex';

        // Copy to clipboard
        copyBtn.addEventListener('click', function() {
            navigator.clipboard.writeText(ta.value).then(function() {
                copyBtn.textContent = 'Copied!';
                setTimeout(function() { copyBtn.textContent = 'Copy'; }, 1500);
            });
        });

        // Send to Baker for refinement
        askBtn.addEventListener('click', function() {
            overlay.remove();
            switchTab('baker');
            var input = document.getElementById('bakerInput');
            if (input) {
                input.value = 'Refine this draft reply for "' + (alert.title || '').substring(0, 60) + '":\n\n' + ta.value;
                input.style.height = 'auto';
                input.style.height = Math.min(input.scrollHeight, 120) + 'px';
                setTimeout(function() { input.focus(); }, 150);
            }
        });
    }).catch(function(e) {
        loading.remove();
        var err = document.createElement('div');
        err.style.cssText = 'text-align:center;color:var(--red);padding:24px;';
        err.textContent = 'Failed to generate draft. Try again.';
        body.appendChild(err);
        actions.style.display = 'flex';
    });
}

// ═══ DELEGATE ═══

var _delegateContacts = null;

function _delegateAlert(alert) {
    _closeContextMenu();

    // Show contact picker as context menu sheet
    var old = document.getElementById('contextMenuOverlay');
    if (old) old.remove();

    var overlay = document.createElement('div');
    overlay.id = 'contextMenuOverlay';
    overlay.className = 'context-menu-overlay';

    var sheet = document.createElement('div');
    sheet.className = 'context-menu-sheet';
    sheet.style.maxHeight = '70vh';
    sheet.style.display = 'flex';
    sheet.style.flexDirection = 'column';

    // Header
    var header = document.createElement('div');
    header.className = 'context-menu-header';
    var headerTitle = document.createElement('div');
    headerTitle.className = 'context-menu-title';
    headerTitle.textContent = 'Delegate to...';
    header.appendChild(headerTitle);
    sheet.appendChild(header);

    // Search
    var search = document.createElement('input');
    search.className = 'delegate-search';
    search.placeholder = 'Search contacts...';
    search.type = 'text';
    sheet.appendChild(search);

    // Contact list container
    var contactsList = document.createElement('div');
    contactsList.className = 'delegate-contacts-list';
    var loadingEl = document.createElement('div');
    loadingEl.style.cssText = 'text-align:center;padding:20px;color:var(--text3);font-size:13px;';
    loadingEl.textContent = 'Loading contacts...';
    contactsList.appendChild(loadingEl);
    sheet.appendChild(contactsList);

    // Cancel
    var cancelBtn = document.createElement('button');
    cancelBtn.className = 'context-menu-cancel';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', _closeContextMenu);
    sheet.appendChild(cancelBtn);

    overlay.appendChild(sheet);
    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) _closeContextMenu();
    });
    document.body.appendChild(overlay);
    requestAnimationFrame(function() { overlay.classList.add('visible'); });

    // Fetch contacts
    var renderContacts = function(filter) {
        contactsList.textContent = '';
        var contacts = _delegateContacts || [];
        if (filter) {
            var lf = filter.toLowerCase();
            contacts = contacts.filter(function(c) {
                return (c.name || '').toLowerCase().indexOf(lf) >= 0 ||
                       (c.role || '').toLowerCase().indexOf(lf) >= 0;
            });
        }
        if (contacts.length === 0) {
            var empty = document.createElement('div');
            empty.style.cssText = 'text-align:center;padding:20px;color:var(--text3);font-size:13px;';
            empty.textContent = filter ? 'No matching contacts.' : 'No contacts found.';
            contactsList.appendChild(empty);
            return;
        }
        for (var i = 0; i < contacts.length; i++) {
            contactsList.appendChild(_createDelegateContactItem(contacts[i], alert));
        }
    };

    search.addEventListener('input', function() { renderContacts(search.value); });

    if (_delegateContacts) {
        renderContacts('');
    } else {
        bakerFetch('/api/contacts/vips').then(function(r) {
            if (!r.ok) throw new Error('API ' + r.status);
            return r.json();
        }).then(function(data) {
            _delegateContacts = (data.contacts || []).sort(function(a, b) {
                return (a.tier || 99) - (b.tier || 99);
            });
            renderContacts('');
        }).catch(function() {
            contactsList.textContent = '';
            var err = document.createElement('div');
            err.style.cssText = 'text-align:center;padding:20px;color:var(--red);font-size:13px;';
            err.textContent = 'Failed to load contacts.';
            contactsList.appendChild(err);
        });
    }
}

function _createDelegateContactItem(contact, alert) {
    var item = document.createElement('div');
    item.className = 'delegate-contact-item';

    // Avatar (initials)
    var avatar = document.createElement('div');
    avatar.className = 'delegate-contact-avatar';
    var initials = (contact.name || '?').split(' ').map(function(w) { return w[0]; }).join('').substring(0, 2).toUpperCase();
    avatar.textContent = initials;
    item.appendChild(avatar);

    // Info
    var info = document.createElement('div');
    info.className = 'delegate-contact-info';
    var name = document.createElement('div');
    name.className = 'delegate-contact-name';
    name.textContent = contact.name || 'Unknown';
    info.appendChild(name);
    if (contact.role) {
        var role = document.createElement('div');
        role.className = 'delegate-contact-role';
        role.textContent = contact.role;
        info.appendChild(role);
    }
    item.appendChild(info);

    // Tier badge
    if (contact.tier) {
        var tier = document.createElement('span');
        tier.className = 'delegate-contact-tier t' + contact.tier;
        tier.textContent = 'T' + contact.tier;
        item.appendChild(tier);
    }

    // Click → delegate
    item.addEventListener('click', function() {
        _closeContextMenu();
        _executeDelegation(alert, contact);
    });

    return item;
}

function _executeDelegation(alert, contact) {
    // Send to Baker: "Forward this alert to [contact] — draft a message"
    switchTab('baker');
    var input = document.getElementById('bakerInput');
    if (input) {
        var msg = 'Delegate to ' + contact.name;
        if (contact.email) msg += ' (' + contact.email + ')';
        msg += ':\n\nAlert: "' + (alert.title || '').substring(0, 80) + '"';
        if (alert.body) msg += '\nDetails: ' + (alert.body || '').substring(0, 200);
        msg += '\n\nPlease draft a forwarding message for this person.';

        input.value = msg;
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
        setTimeout(function() { input.focus(); }, 150);
    }

    // Toast
    var toast = document.createElement('div');
    toast.className = 'undo-toast';
    toast.textContent = 'Delegating to ' + contact.name + '...';
    document.body.appendChild(toast);
    setTimeout(function() {
        toast.style.transition = 'opacity 0.3s';
        toast.style.opacity = '0';
        setTimeout(function() { toast.remove(); }, 300);
    }, 2000);
}

// ═══ ALERT ACTION HELPERS ═══

function _resolveAlertCard(alertId, card) {
    card.style.transition = 'opacity 0.3s, transform 0.3s';
    card.style.opacity = '0';
    card.style.transform = 'translateX(100%)';
    setTimeout(function() { card.remove(); }, 300);
    _mobileAlerts = _mobileAlerts.filter(function(a) { return a.id !== alertId; });
    bakerFetch('/api/alerts/' + alertId + '/resolve', { method: 'POST' })
        .then(function() { refreshAlertBadge(); })
        .catch(function() {});
}

function _dismissAlertCard(alertId, card) {
    if (!card) {
        var cards = document.querySelectorAll('.alert-card');
        for (var i = 0; i < cards.length; i++) {
            if (cards[i].dataset.alertId === String(alertId)) {
                card = cards[i];
                break;
            }
        }
    }
    if (card) {
        card.style.transition = 'opacity 0.3s, transform 0.3s';
        card.style.opacity = '0';
        card.style.transform = 'translateX(-100%)';
        setTimeout(function() { card.remove(); }, 300);
    }
    _mobileAlerts = _mobileAlerts.filter(function(a) { return a.id !== alertId; });
    bakerFetch('/api/alerts/' + alertId + '/dismiss', { method: 'POST' })
        .then(function() { refreshAlertBadge(); })
        .catch(function() {});
}

function _runDossierFromAlert(proposalId, alertId, card) {
    // First check if already completed — go straight to view
    bakerFetch('/api/research-proposals/' + proposalId + '/status').then(function(r) {
        return r.ok ? r.json() : null;
    }).then(function(data) {
        if (data && data.status === 'completed') {
            // Already done — navigate to view page (window.open blocked on iOS)
            window.location.href = '/api/research-proposals/' + proposalId + '/view?key=' + encodeURIComponent(BAKER.apiKey);
            return;
        }
        // Not completed — run it
        var btns = card.querySelector('.alert-action-buttons');
        if (btns) {
            btns.innerHTML = '<div style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--green);font-weight:500;">' +
                '<span class="triage-spinner"></span><span class="dossier-progress-text"> Running specialists...</span></div>';
        }
        card.style.opacity = '0.85';

        bakerFetch('/api/research-proposals/' + proposalId + '/respond', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ response: 'approved' }),
        }).then(function() {
            _pollDossierFromAlert(proposalId, alertId, card);
        }).catch(function(e) { console.error('Dossier launch failed:', e); });
    }).catch(function() {
        // Status check failed — try running anyway
        var btns = card.querySelector('.alert-action-buttons');
        if (btns) {
            btns.innerHTML = '<div style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--green);font-weight:500;">' +
                '<span class="triage-spinner"></span><span class="dossier-progress-text"> Running specialists...</span></div>';
        }
        card.style.opacity = '0.85';
        bakerFetch('/api/research-proposals/' + proposalId + '/respond', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ response: 'approved' }),
        }).then(function() {
            _pollDossierFromAlert(proposalId, alertId, card);
        }).catch(function(e) { console.error('Dossier launch failed:', e); });
    });
}

function _pollDossierFromAlert(proposalId, alertId, card) {
    var pollCount = 0;
    var labels = ['Running specialists...', 'Analyzing...', 'Combining results...', 'Generating document...'];
    var interval = setInterval(function() {
        pollCount++;
        var textEl = card ? card.querySelector('.dossier-progress-text') : null;
        if (textEl) {
            var idx = Math.min(Math.floor(pollCount / 5), labels.length - 1);
            textEl.textContent = ' ' + labels[idx];
        }
        if (pollCount >= 90) {
            clearInterval(interval);
            if (textEl) textEl.textContent = ' Timed out — check back later';
            card.style.opacity = '1';
            return;
        }
        bakerFetch('/api/research-proposals/' + proposalId + '/status').then(function(r) {
            return r.ok ? r.json() : null;
        }).then(function(data) {
            if (!data) return;
            if (data.status === 'failed') {
                clearInterval(interval);
                card.style.opacity = '1';
                card.style.borderLeftColor = '#ef4444';
                var btns2 = card.querySelector('.alert-action-buttons');
                if (btns2) btns2.innerHTML = '<div style="font-size:12px;color:#ef4444;">Failed — tap to retry</div>';
                return;
            }
            if (data.status !== 'completed') return;
            clearInterval(interval);
            if (!card) return;
            card.style.opacity = '1';
            card.style.borderLeftColor = '#22c55e';
            var title = card.querySelector('.alert-title');
            if (title) title.textContent = 'Dossier ready: ' + (data.subject_name || 'Research');
            var btns = card.querySelector('.alert-action-buttons');
            if (btns) {
                btns.innerHTML = '';
                var viewBtn = document.createElement('a');
                viewBtn.href = '/api/research-proposals/' + proposalId + '/view?key=' + encodeURIComponent(BAKER.apiKey);
                viewBtn.className = 'triage-btn approve';
                viewBtn.style.cssText = 'text-decoration:none;text-align:center;display:block;flex:1;';
                viewBtn.textContent = 'View Dossier';
                viewBtn.target = '_blank';
                btns.appendChild(viewBtn);
            }
            // Resolve the alert
            _mobileAlerts = _mobileAlerts.filter(function(a) { return a.id !== alertId; });
            bakerFetch('/api/alerts/' + alertId + '/resolve', { method: 'POST' }).catch(function() {});
        }).catch(function() {});
    }, 5000);
}

// ═══ BROWSER ACTION HELPERS (BROWSER-AGENT-1 Phase 3) ═══

function _confirmBrowserAction(actionId, alertId, card) {
    var btns = card.querySelector('.alert-action-buttons');
    if (btns) {
        btns.innerHTML = '<div style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--green);font-weight:500;">' +
            '<span class="triage-spinner"></span> Executing action...</div>';
    }
    card.style.opacity = '0.85';

    bakerFetch('/api/browser/confirm/' + actionId, {
        method: 'POST',
    }).then(function(r) {
        if (!r.ok) throw new Error('Confirm failed');
        return r.json();
    }).then(function(data) {
        card.style.opacity = '1';
        card.style.borderLeftColor = '#22c55e';
        if (btns) btns.innerHTML = '<div style="font-size:12px;color:var(--green);">Action executed</div>';
        _mobileAlerts = _mobileAlerts.filter(function(a) { return a.id !== alertId; });
        bakerFetch('/api/alerts/' + alertId + '/resolve', { method: 'POST' }).catch(function() {});
        setTimeout(function() {
            card.style.transition = 'opacity 0.3s';
            card.style.opacity = '0';
            setTimeout(function() { card.remove(); }, 300);
        }, 2000);
        refreshAlertBadge();
    }).catch(function(e) {
        console.error('Browser action confirm failed:', e);
        if (btns) btns.innerHTML = '<div style="font-size:12px;color:var(--red);">Confirm failed — may have expired</div>';
    });
}

function _cancelBrowserAction(actionId, alertId, card) {
    card.style.transition = 'opacity 0.3s, transform 0.3s';
    card.style.opacity = '0';
    card.style.transform = 'translateX(-100%)';
    setTimeout(function() { card.remove(); }, 300);
    _mobileAlerts = _mobileAlerts.filter(function(a) { return a.id !== alertId; });

    bakerFetch('/api/browser/cancel/' + actionId, {
        method: 'POST',
    }).then(function() {
        refreshAlertBadge();
    }).catch(function() {});
}

function _showBrowserActionPreview(actionId) {
    // Fetch the action with screenshot and show in a modal overlay
    bakerFetch('/api/browser/actions/' + actionId).then(function(r) {
        return r.ok ? r.json() : null;
    }).then(function(data) {
        if (!data || !data.action) return;
        var action = data.action;

        // Create overlay
        var overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.85);z-index:10000;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:16px;';

        // Close on tap outside
        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) overlay.remove();
        });

        var content = document.createElement('div');
        content.style.cssText = 'max-width:400px;width:100%;background:var(--card-bg,#1a1a1a);border-radius:12px;overflow:hidden;';

        // Header
        var header = document.createElement('div');
        header.style.cssText = 'padding:12px 16px;font-weight:600;font-size:14px;border-bottom:1px solid rgba(255,255,255,0.1);';
        header.textContent = 'Browser Action Preview';
        content.appendChild(header);

        // Screenshot
        if (action.screenshot_b64) {
            var img = document.createElement('img');
            img.src = 'data:image/jpeg;base64,' + action.screenshot_b64;
            img.style.cssText = 'width:100%;max-height:300px;object-fit:contain;';
            content.appendChild(img);
        }

        // Action info
        var info = document.createElement('div');
        info.style.cssText = 'padding:12px 16px;font-size:13px;line-height:1.5;';
        info.innerHTML = '<div><strong>Action:</strong> ' + _esc(action.action_type || '') + '</div>' +
            '<div><strong>Page:</strong> ' + _esc((action.url || '').substring(0, 60)) + '</div>' +
            (action.target_selector ? '<div><strong>Target:</strong> ' + _esc(action.target_selector) + '</div>' : '') +
            (action.target_text ? '<div><strong>Target text:</strong> ' + _esc(action.target_text) + '</div>' : '') +
            (action.fill_value ? '<div><strong>Value:</strong> ' + _esc(action.fill_value) + '</div>' : '') +
            '<div style="margin-top:8px;color:rgba(255,255,255,0.6);font-size:12px;">' + _esc(action.description || '') + '</div>';
        content.appendChild(info);

        // Close button
        var closeBtn = document.createElement('button');
        closeBtn.textContent = 'Close';
        closeBtn.style.cssText = 'width:calc(100% - 32px);margin:0 16px 16px;padding:10px;border:none;border-radius:8px;background:rgba(255,255,255,0.1);color:white;font-size:14px;cursor:pointer;';
        closeBtn.addEventListener('click', function() { overlay.remove(); });
        content.appendChild(closeBtn);

        overlay.appendChild(content);
        document.body.appendChild(overlay);
    }).catch(function(e) {
        console.error('Preview load failed:', e);
    });
}

function _esc(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

document.addEventListener('DOMContentLoaded', init);
