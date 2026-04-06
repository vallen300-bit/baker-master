# BRIEF: LOCAL-OLLAMA-ROUTING — Route simple Ask Baker queries to local Gemma via Ollama

## Context
Every "Ask Baker" question hits Render → Opus agent loop (~EUR 0.50/query). Generic questions ("what is RETT?", "translate X", "summarize this") don't need Baker's database, tools, or knowledge. Director installed Ollama + Gemma 4 locally. This brief routes simple queries to `localhost:11434` directly from the browser — zero backend changes, zero API cost for generic questions.

**Cost impact:** ~EUR 75-150/month savings if 5-10 generic queries/day go local.

## Estimated time: ~2h
## Complexity: Low-Medium
## Prerequisites: Ollama running locally with gemma4 model pulled + CORS configured
## CORS/Mixed Content Note: Chrome blocks HTTP fetch from HTTPS pages. The Cockpit on `https://baker-master.onrender.com` CANNOT reach `http://localhost:11434` (mixed content block). Two access paths:
## - **Local dev** (`http://localhost:8080`): Works — no mixed content issue. Director uses this when on his Mac for local AI.
## - **Render HTTPS**: Ollama unreachable → feature gracefully degrades to 100% Baker routing. No errors, no broken UI.
## - **Cloudflare tunnel** (`https://ollama.brisen-infra.com`): Configured as fallback — requires bypassing Cloudflare Access (future enhancement).
## Edita's Mac does NOT have Ollama — feature degrades gracefully (badge hidden, all queries → Baker).
## Cowork Review: APPROVED with 4 validations — all addressed below

---

## Feature 1: Ollama Availability Detection

### Problem
Frontend doesn't know if Ollama is running on the user's machine.

### Current State
All queries go to Render via `bakerFetch('/api/scan', ...)`. No local AI awareness.

### Implementation

**File: `outputs/static/app.js`**

Add after the `BAKER_CONFIG` / state section (after line 41, before the ARTIFACT PANEL section):

```javascript
// ═══ LOCAL AI (Ollama) ═══
var _ollamaAvailable = false;
var _ollamaModels = [];
var _ollamaEnabled = true; // user toggle — persists in localStorage
// Try localhost first (works from http:// pages), then Cloudflare tunnel (works from https://)
var _OLLAMA_ENDPOINTS = ['http://localhost:11434', 'https://ollama.brisen-infra.com'];
var _OLLAMA_BASE = '';

// Check if Ollama is reachable from any endpoint
async function checkOllama() {
    for (var i = 0; i < _OLLAMA_ENDPOINTS.length; i++) {
        try {
            var resp = await fetch(_OLLAMA_ENDPOINTS[i] + '/api/tags', {
                signal: AbortSignal.timeout(2000)
            });
            if (!resp.ok) continue;
            var data = await resp.json();
            var models = (data.models || []).map(function(m) { return m.name; });
            if (models.length > 0) {
                _OLLAMA_BASE = _OLLAMA_ENDPOINTS[i];
                _ollamaModels = models;
                _ollamaAvailable = true;
                window._ollamaModel = models.find(function(m) { return m.startsWith('gemma4'); }) || models[0] || '';
                updateOllamaIndicator();
                return;
            }
        } catch (e) { /* try next endpoint */ }
    }
    _ollamaAvailable = false;
    updateOllamaIndicator();
}

function updateOllamaIndicator() {
    var badge = document.getElementById('ollamaStatusBadge');
    if (!badge) return;
    if (_ollamaAvailable && _ollamaEnabled) {
        badge.style.display = 'inline-flex';
        badge.title = 'Local AI active: ' + (window._ollamaModel || 'unknown') + '. Simple queries go to local Gemma (free). Click to toggle.';
        badge.classList.add('active');
    } else if (_ollamaAvailable && !_ollamaEnabled) {
        badge.style.display = 'inline-flex';
        badge.title = 'Local AI available but disabled. Click to enable.';
        badge.classList.remove('active');
    } else {
        badge.style.display = 'none';
    }
}

function toggleOllama() {
    _ollamaEnabled = !_ollamaEnabled;
    try { localStorage.setItem('baker_ollama_enabled', _ollamaEnabled ? '1' : '0'); } catch(e) {}
    updateOllamaIndicator();
}

// Restore toggle state from localStorage
try {
    var _stored = localStorage.getItem('baker_ollama_enabled');
    if (_stored !== null) _ollamaEnabled = _stored === '1';
} catch(e) {}

// Check on load + every 60s (handles Ollama start/stop)
checkOllama();
setInterval(checkOllama, 60000);
```

### Key Constraints
- `AbortSignal.timeout(2000)` — don't hang if Ollama is down.
- 60s polling is lightweight (single GET, ~100 bytes response).
- No backend changes.

### Verification
Open browser console, type `_ollamaAvailable` — should return `true` when Ollama is running.

---

## Feature 2: Simple Question Classifier (Rule-Based)

### Problem
Need to decide which queries are "simple" (route to local Gemma) vs "complex" (need Baker's tools/knowledge).

### Current State
No client-side classification exists. Everything goes to Render.

### Implementation

**File: `outputs/static/app.js`**

Add after the Ollama detection code:

```javascript
// ═══ LOCAL AI ROUTING ═══
var _BAKER_KEYWORDS = [
    // People
    'oskolkov', 'ao', 'balazs', 'edita', 'sandra', 'constantinos', 'francesca',
    'conrad', 'wertheimer', 'yurkovich', 'balducci', 'neubauer', 'schran',
    // Projects
    'hagenauer', 'kitzb', 'lilienmatt', 'morv', 'aukera', 'balgerstrasse',
    'mandarin', 'fx mayr', 'cap ferrat', 'annaberg', 'alpengold', 'citic',
    'prague', 'woosley', 'campus', 'schlüter',
    // Baker features
    'briefing', 'deadline', 'clickup', 'todoist', 'alert', 'critical',
    'promised', 'meeting', 'dossier', 'email', 'whatsapp',
    // Domain terms that imply Baker data needed (Cowork #1: conservative)
    'hotel', 'occupancy', 'adr', 'revpar', 'residence', 'apartment',
    'insolvency', 'capital call', 'financing', 'restructur', 'loan',
    'investor', 'investment', 'equity', 'shareholder',
    'acquisition', 'due diligence', 'term sheet', 'irr',
    // Actions requiring tools
    'send', 'draft', 'create', 'schedule', 'arrange', 'prepare',
    'show me', 'list', 'get me', 'find', 'check', 'update', 'dismiss',
    'promote', 'reject',
    // Context references (need conversation history on server)
    'the same', 'that email', 'his response', 'follow up', 'as discussed',
    'previous', 'last time'
];

function isSimpleQuestion(question) {
    // Hard requirement: Ollama must be running with a model
    if (!_ollamaAvailable || !window._ollamaModel) return false;

    var q = question.toLowerCase().trim();

    // Explicit prefixes override everything (even toggle)
    if (q.startsWith('local:') || q.startsWith('gemma:')) return true;
    if (q.startsWith('baker:')) return false;

    // Respect user toggle
    if (!_ollamaEnabled) return false;

    // Too short or too long — let Baker handle edge cases
    if (q.length < 10 || q.length > 2000) return false;

    // Has conversation history — needs server context
    var history = getScanHistory();
    if (history.length > 2) return false;

    // Check for Baker-specific keywords
    for (var i = 0; i < _BAKER_KEYWORDS.length; i++) {
        if (q.indexOf(_BAKER_KEYWORDS[i]) !== -1) return false;
    }

    // Default: route locally if no keywords matched
    return true;
}
```

### Key Constraints
- **Conservative classifier** — if in doubt, route to Baker. False negatives (sending to Baker when Gemma could handle it) are fine. False positives (sending to Gemma when Baker was needed) are bad.
- Keyword list is deliberately broad — better to over-route to Baker.
- History check: if conversation has >2 messages, user is in a back-and-forth → needs Baker's context.
- `local:` / `gemma:` prefix lets user force local. `baker:` forces remote.

### Verification
In console: `isSimpleQuestion("what is RETT?")` → `true`. `isSimpleQuestion("send email to Balazs")` → `false`.

---

## Feature 3: Local Chat Function (Ollama Streaming)

### Problem
Need a function to stream responses from local Ollama and render them in the same chat UI.

### Current State
`sendScanMessage()` streams from Render's SSE endpoint. Need a parallel path for local.

### Implementation

**File: `outputs/static/app.js`**

Add after the classifier:

```javascript
async function sendLocalMessage(question) {
    // Strip prefix if user typed "local:" or "gemma:"
    var cleanQ = question.replace(/^(local:|gemma:)\s*/i, '');

    scanStreaming = true;
    var sendBtn = document.getElementById('scanSendBtn');
    var input = document.getElementById('scanInput');
    if (sendBtn) sendBtn.disabled = true;
    if (input) { input.disabled = true; input.value = ''; input.style.height = 'auto'; }

    getScanHistory().push({ role: 'user', content: cleanQ });
    appendScanBubble('user', cleanQ);

    var assistantId = 'scan-reply-' + Date.now();
    appendScanBubble('assistant', '', assistantId);
    var replyEl = document.getElementById(assistantId);
    if (replyEl) {
        replyEl.innerHTML = '<div class="thinking local-thinking"><span class="thinking-dots"><span></span><span></span><span></span></span> Local AI is thinking...</div>';
        replyEl.classList.add('local-ai');
    }

    var fullResponse = '';
    try {
        var resp = await fetch(_OLLAMA_BASE + '/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                model: window._ollamaModel,
                messages: [{ role: 'user', content: cleanQ }],
                stream: true
            })
        });

        if (!resp.ok) throw new Error('Ollama returned ' + resp.status);

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
                var line = lines[li].trim();
                if (!line) continue;
                try {
                    var data = JSON.parse(line);
                    if (data.message && data.message.content) {
                        if (!fullResponse && replyEl) replyEl.textContent = '';
                        fullResponse += data.message.content;
                        if (replyEl) {
                            setSafeHTML(replyEl, '<div class="local-ai-badge">&#9889; Local AI</div>' +
                                '<div class="md-content">' + md(fullResponse) + '</div>' +
                                '<div class="streaming-indicator"><span class="thinking-dots"><span></span><span></span><span></span></span></div>');
                            var scanMsgs = document.getElementById('scanMessages');
                            if (scanMsgs) scanMsgs.scrollTop = scanMsgs.scrollHeight;
                        }
                    }
                } catch(e) { /* skip unparseable */ }
            }
        }
    } catch (err) {
        // Fallback: if Ollama fails, re-send via Baker
        console.warn('Local AI failed, falling back to Baker:', err.message);
        if (replyEl) replyEl.remove();
        getScanHistory().pop(); // remove the user message we added
        getScanHistory().pop(); // remove the assistant placeholder
        scanStreaming = false;
        if (sendBtn) sendBtn.disabled = false;
        if (input) input.disabled = false;
        sendScanMessage(question); // re-route to Baker
        return;
    }

    // Finalize: remove streaming indicator, add re-ask button
    if (replyEl) {
        var si = replyEl.querySelector('.streaming-indicator');
        if (si) si.remove();
        if (!replyEl.querySelector('.local-ai-badge')) {
            var badge = document.createElement('div');
            badge.className = 'local-ai-badge';
            badge.textContent = '\u26A1 Local AI';
            replyEl.prepend(badge);
        }
        // Add "Re-ask Baker" button
        var reaskBtn = document.createElement('button');
        reaskBtn.className = 'reask-baker-btn';
        reaskBtn.textContent = 'Re-ask Baker \u2192';
        reaskBtn.onclick = function() {
            replyEl.remove();
            // Remove last assistant + user from history
            var h = getScanHistory();
            if (h.length >= 2) { h.pop(); h.pop(); }
            scanStreaming = false;
            sendScanMessage(question);
        };
        replyEl.appendChild(reaskBtn);
    }

    // Save to history
    getScanHistory().push({ role: 'assistant', content: fullResponse });

    scanStreaming = false;
    if (sendBtn) sendBtn.disabled = false;
    if (input) input.disabled = false;
    if (input) input.focus();
}
```

### Key Constraints
- **Automatic fallback:** If Ollama call fails (connection error, model not loaded), silently re-routes to Baker. User sees a brief flash, then Baker responds normally.
- **"Re-ask Baker" button:** Every local response gets a button to escalate to Baker. One click, seamless.
- **Same UI:** Uses the same `appendScanBubble`, `md()`, `setSafeHTML` functions. Only visual difference is the "Local AI" badge.
- **Ollama streaming format** differs from Baker SSE: Ollama returns newline-delimited JSON objects with `{"message": {"content": "..."}}`, not `data: {"token": "..."}`.
- **No artifact panel** for local responses — local AI doesn't use tools.
- **History NOT sent** to Ollama — each local query is standalone. This is intentional: Gemma doesn't have Baker context, so history would confuse it.

### Verification
1. With Ollama running: type "what is RETT?" → should see "Local AI is thinking..." → response with ⚡ badge
2. Kill Ollama, type generic question → should briefly attempt local, then seamlessly fall back to Baker
3. Click "Re-ask Baker" → should re-send same question to Baker pipeline

---

## Feature 4: Route Integration in sendScanMessage

### Problem
`sendScanMessage()` currently always sends to Render. Need to intercept and route to local when appropriate.

### Current State
`sendScanMessage()` is called from the form submit handler at line 3540.

### Implementation

**File: `outputs/static/app.js`**

Find the beginning of `sendScanMessage` (line 3540):

```javascript
async function sendScanMessage(question) {
    if (scanStreaming || !question.trim()) return;
    scanStreaming = true;
```

Replace with:

```javascript
async function sendScanMessage(question) {
    if (scanStreaming || !question.trim()) return;

    // LOCAL-OLLAMA-ROUTING: Check if this is a simple question for local AI
    if (isSimpleQuestion(question)) {
        sendLocalMessage(question);
        return;
    }

    scanStreaming = true;
```

### Key Constraints
- This is the ONLY change to the existing `sendScanMessage` function — a 4-line intercept at the top.
- `isSimpleQuestion` returns false if Ollama is unavailable, so existing behavior is unchanged when Ollama isn't installed.
- The `scanStreaming` guard still works because `sendLocalMessage` sets it.

### Verification
Type "what is RETT?" → routes to local. Type "show deadlines" → routes to Baker.

---

## Feature 5: UI Elements (Badge + Toggle)

### Problem
User needs to see when local AI is active and have a way to toggle it.

### Current State
No local AI indicators exist in the UI.

### Implementation

**File: `outputs/static/index.html`**

Find the Ask Baker form (line 295-299):

```html
<form id="scanForm" class="scan-form" autocomplete="off">
```

Add the Ollama status badge BEFORE the form, inside `.scan-view-body`:

```html
<div id="ollamaStatusBadge" class="ollama-badge" style="display:none" onclick="toggleOllama()">
    <span class="ollama-dot"></span> <span id="ollamaBadgeText">Local AI</span>
</div>
<form id="scanForm" class="scan-form" autocomplete="off">
```

Also bump cache versions:
- `style.css?v=65` → `style.css?v=66`
- `app.js?v=97` → `app.js?v=98`

**File: `outputs/static/style.css`**

Add at the end of the file:

```css
/* ═══ LOCAL AI (Ollama) ═══ */
.ollama-badge {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 10px; margin-bottom: 6px;
    font-size: 11px; color: #888; border-radius: 12px;
    background: rgba(255,255,255,0.04); cursor: pointer;
    user-select: none; transition: all 0.2s;
}
.ollama-badge:hover { background: rgba(255,255,255,0.08); }
.ollama-badge.active { color: #7ecf8e; }
.ollama-badge .ollama-dot {
    width: 6px; height: 6px; border-radius: 50%;
    background: #555; transition: background 0.2s;
}
.ollama-badge.active .ollama-dot { background: #7ecf8e; }

.scan-msg.local-ai { border-left: 2px solid #7ecf8e; }
.local-ai-badge {
    font-size: 10px; color: #7ecf8e; margin-bottom: 4px;
    letter-spacing: 0.5px; font-weight: 600;
}
.local-thinking { color: #7ecf8e !important; }

.reask-baker-btn {
    display: inline-block; margin-top: 8px; padding: 4px 12px;
    font-size: 11px; color: #aaa; background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.1); border-radius: 6px;
    cursor: pointer; transition: all 0.2s;
}
.reask-baker-btn:hover { color: #fff; background: rgba(255,255,255,0.1); }
```

### Key Constraints
- Badge only visible when Ollama is detected (display:none default).
- Green dot = active, grey dot = available but disabled.
- Clicking toggles on/off, persists in localStorage.
- Local responses get green left border + "⚡ Local AI" badge to clearly distinguish from Baker.

### Verification
1. With Ollama running: green badge appears above Ask Baker input
2. Click badge → toggles off (grey), local routing disabled
3. Local response has green left border + ⚡ badge + "Re-ask Baker" button

---

## Files Modified
- `outputs/static/app.js` — Ollama detection, classifier, local chat function, routing intercept (~120 lines added)
- `outputs/static/style.css` — Local AI styling (~30 lines added)
- `outputs/static/index.html` — Ollama badge element + cache bust

## Do NOT Touch
- `outputs/dashboard.py` — no backend changes
- `orchestrator/` — no server-side routing changes
- `memory/store_back.py` — no DB changes
- Any existing `sendScanMessage` logic beyond the 4-line intercept at top

## Quality Checkpoints
1. Syntax check: open app.js in browser, check console for errors
2. With Ollama running + model loaded: type "what is RETT?" → local response with ⚡ badge
3. Type "show deadlines this week" → routes to Baker (keyword match)
4. Type "send email to Balazs" → routes to Baker (action + name)
5. Kill Ollama → badge disappears, all queries go to Baker
6. Restart Ollama → badge reappears within 60s
7. Click badge to toggle off → "what is RETT?" now goes to Baker
8. Type "local: explain quantum computing" → forces local even if toggle is off (explicit prefix overrides toggle).
9. On a local response, click "Re-ask Baker →" → same question re-sent to Baker pipeline
10. Check mobile rendering of badge and local responses (PWA)
11. Cache bust: verify `?v=66` on CSS and `?v=98` on JS in index.html

## Verification SQL
N/A — no database changes. Verification is purely frontend.
