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

function addResponseToolbar(replyEl, text) {
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

    replyEl.appendChild(toolbar);
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
    const inputId = tab === 'baker' ? 'bakerInput' : 'specialistInput';
    const input = document.getElementById(inputId);
    if (input) setTimeout(function() { input.focus(); }, 100);
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

    // Toolbar: Copy + Play (tap to hear)
    if (full && !full.startsWith('Connection error')) {
        addResponseToolbar(replyEl, full);
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

    // Camera, New Chat
    setupCamera();
    document.getElementById('newChatBtn').addEventListener('click', function() { stopSpeaking(); newChat(); });

    // Pre-load voices for Play button (iOS requires this)
    if (window.speechSynthesis) {
        window.speechSynthesis.getVoices();
        window.speechSynthesis.onvoiceschanged = function() { window.speechSynthesis.getVoices(); };
    }

    // Tab switching
    document.querySelectorAll('.tab-btn').forEach(function(btn) {
        btn.addEventListener('click', function() { switchTab(btn.dataset.tab); });
    });

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

    // Default tab
    switchTab('baker');
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

    toast.addEventListener('click', function() { toast.remove(); });
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

document.addEventListener('DOMContentLoaded', init);
