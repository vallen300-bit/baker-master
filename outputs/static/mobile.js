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
let voiceEnabled = true; // auto-read responses aloud

// ═══ VOICE READBACK (SpeechSynthesis) ═══
function speakText(text) {
    if (!voiceEnabled || !text || !window.speechSynthesis) return;
    // Stop any ongoing speech
    window.speechSynthesis.cancel();
    // Strip markdown formatting for cleaner speech
    var clean = text
        .replace(/\*\*(.+?)\*\*/g, '$1')
        .replace(/\*(.+?)\*/g, '$1')
        .replace(/^#{1,3}\s+/gm, '')
        .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
        .replace(/\[Source: [^\]]+\]/g, '')
        .replace(/^\|.*\|$/gm, '') // strip table rows
        .replace(/^-{3,}$/gm, '')
        .replace(/\n{2,}/g, '\n')
        .trim();
    if (!clean) return;
    // Truncate very long responses to avoid iOS TTS cutting out
    if (clean.length > 2000) clean = clean.substring(0, 2000) + '... end of summary.';
    var utterance = new SpeechSynthesisUtterance(clean);
    utterance.rate = 1.05;
    utterance.pitch = 1.0;
    // Prefer a natural English voice on iOS
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

function toggleVoice() {
    voiceEnabled = !voiceEnabled;
    var btn = document.getElementById('voiceToggle');
    if (btn) {
        btn.textContent = voiceEnabled ? '\uD83D\uDD0A' : '\uD83D\uDD07';
        btn.classList.toggle('voice-off', !voiceEnabled);
    }
    if (!voiceEnabled) stopSpeaking();
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

    // Auto-read response aloud
    if (full && !full.startsWith('Connection error')) {
        speakText(full);
    }

    // Toolbar: Copy + Stop Speaking
    if (replyEl && full && !full.startsWith('Connection error')) {
        var toolbar = document.createElement('div');
        toolbar.className = 'msg-toolbar';
        var copyBtn = document.createElement('button');
        copyBtn.textContent = 'Copy';
        copyBtn.addEventListener('click', function() {
            navigator.clipboard.writeText(full).then(function() {
                copyBtn.textContent = 'Copied';
                setTimeout(function() { copyBtn.textContent = 'Copy'; }, 2000);
            });
        });
        toolbar.appendChild(copyBtn);

        if (voiceEnabled) {
            var stopBtn = document.createElement('button');
            stopBtn.textContent = 'Stop';
            stopBtn.addEventListener('click', function() {
                stopSpeaking();
                stopBtn.textContent = 'Stopped';
                setTimeout(function() { stopBtn.textContent = 'Stop'; }, 2000);
            });
            toolbar.appendChild(stopBtn);
        }

        replyEl.appendChild(toolbar);
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

        var resp = await bakerFetch('/api/scan/image', {
            method: 'POST',
            body: formData,
            timeout: 60000,
        });
        if (!resp.ok) throw new Error('API returned ' + resp.status);
        var data = await resp.json();
        full = data.answer || 'No response';
        if (replyEl) setSafeHTML(replyEl, '<div class="md-content">' + md(full) + '</div>');
    } catch (err) {
        full = 'Error: ' + err.message;
        if (replyEl) replyEl.textContent = full;
    }

    bakerHistory.push({ role: 'assistant', content: full });

    // Voice readback
    if (full && !full.startsWith('Error:')) speakText(full);

    // Toolbar
    if (replyEl && full && !full.startsWith('Error:')) {
        var toolbar = document.createElement('div');
        toolbar.className = 'msg-toolbar';
        var copyBtn = document.createElement('button');
        copyBtn.textContent = 'Copy';
        copyBtn.addEventListener('click', function() {
            navigator.clipboard.writeText(full).then(function() {
                copyBtn.textContent = 'Copied';
                setTimeout(function() { copyBtn.textContent = 'Copy'; }, 2000);
            });
        });
        toolbar.appendChild(copyBtn);
        if (voiceEnabled) {
            var stopBtn = document.createElement('button');
            stopBtn.textContent = 'Stop';
            stopBtn.addEventListener('click', function() { stopSpeaking(); });
            toolbar.appendChild(stopBtn);
        }
        replyEl.appendChild(toolbar);
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
    try {
        var r = await bakerFetch('/api/capabilities');
        if (!r.ok) return;
        var data = await r.json();
        var select = document.getElementById('capPicker');
        if (!select) return;
        var caps = (data.capabilities || []).filter(function(c) {
            return c.active && c.slug !== 'decomposer' && c.slug !== 'synthesizer';
        });
        caps.sort(function(a, b) { return (a.name || '').localeCompare(b.name || ''); });
        for (var i = 0; i < caps.length; i++) {
            var opt = document.createElement('option');
            opt.value = caps[i].slug;
            opt.textContent = caps[i].name || caps[i].slug;
            select.appendChild(opt);
        }
    } catch (e) { console.error('Failed to load capabilities:', e); }
}

// ═══ INIT ═══
async function init() {
    await loadConfig();
    await loadCapabilities();

    // Camera, New Chat, Voice toggle
    setupCamera();
    document.getElementById('newChatBtn').addEventListener('click', function() { stopSpeaking(); newChat(); });
    document.getElementById('voiceToggle').addEventListener('click', toggleVoice);

    // Pre-load voices (iOS requires this)
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

    // Default tab
    switchTab('baker');
}

document.addEventListener('DOMContentLoaded', init);
