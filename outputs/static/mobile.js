/* Baker Mobile — minimal JS for Ask Baker + Ask Specialist */

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
    h = h.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    h = h.replace(/\[Source: ([^\]]+)\]/g, '<span class="citation" title="$1">$1</span>');
    h = h.replace(/^- (.+)$/gm, '<li>$1</li>');
    h = h.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
    h = h.replace(/\n/g, '<br>');
    return h;
}

// ═══ TABS ═══
function switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(function(b) {
        b.classList.toggle('active', b.dataset.tab === tab);
    });
    document.querySelectorAll('.chat-panel').forEach(function(p) {
        p.classList.toggle('active', p.id === 'panel-' + tab);
    });
    if (tab === 'alerts') {
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
                    if (data.token) {
                        if (!full && replyEl) replyEl.textContent = '';
                        full += data.token;
                        // SECURITY: md() calls esc() first — all user input sanitized
                        if (replyEl) setSafeHTML(replyEl, '<div class="md-content">' + md(full) + '</div>');
                        // Keep scroll pinned to top (newest-first layout)
                        var msgContainer = document.getElementById(containerId);
                        if (msgContainer) msgContainer.scrollTop = 0;
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

    streaming = false;
    if (input) { input.disabled = false; input.focus(); }
    if (btn) btn.disabled = false;
}

// ═══ NEW CHAT ═══
function newChat() {
    // Determine which panel is active
    var bakerPanel = document.getElementById('panel-baker');
    var isBaker = bakerPanel && bakerPanel.classList.contains('active');

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
            switchTab('alerts');
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

    // Default tab
    switchTab('baker');
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

function _renderMobileAlerts() {
    var list = document.getElementById('alertsList');
    if (!list) return;
    list.textContent = '';

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

    if (filtered.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.textContent = _mobileAlerts.length > 0 ? 'No alerts matching filter.' : 'No pending alerts.';
        list.appendChild(empty);
        return;
    }

    for (var i = 0; i < filtered.length; i++) {
        list.appendChild(_createAlertCard(filtered[i]));
    }
}

function _createAlertCard(alert) {
    var tier = alert.tier || 3;
    var card = document.createElement('div');
    card.className = 'alert-card t' + Math.min(tier, 3);
    card.dataset.alertId = alert.id;

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

    // Tap to expand/collapse
    card.addEventListener('click', function(e) {
        if (e.target.tagName === 'BUTTON') return;
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

    toast.addEventListener('click', function() { toast.remove(); switchTab('alerts'); });
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
            if (t.status === 'discarded') continue;
            var endDate = t.end_date || t.start_date;
            if (t.start_date <= today && endDate >= today) { active = t; break; }
        }
        if (!active) {
            // Find nearest upcoming
            var upcoming = trips.filter(function(t) {
                return t.status !== 'discarded' && t.start_date >= today;
            }).sort(function(a, b) { return a.start_date.localeCompare(b.start_date); });
            if (upcoming.length > 0) active = upcoming[0];
        }
        // Fallback: most recent past trip within 3 days
        if (!active) {
            var recent = trips.filter(function(t) {
                if (t.status === 'discarded') return false;
                var ed = t.end_date || t.start_date;
                if (!ed) return false;
                var diffDays = (new Date(today) - new Date(ed)) / 86400000;
                return diffDays >= 0 && diffDays <= 3;
            }).sort(function(a, b) { return (b.end_date || b.start_date).localeCompare(a.end_date || a.start_date); });
            if (recent.length > 0) active = recent[0];
        }

        if (!active) return;
        _activeTrip = active;
        _renderTripBanner(active);
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
    var meta = dateStr;
    if (trip.event_name) meta = trip.event_name + ' \u00B7 ' + dateStr;

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

document.addEventListener('DOMContentLoaded', init);
