# BRIEF 8 — Baker's Scan (AI Chat) + Contact Search UI

**Date:** 2026-02-20
**Layer:** Baker (RAG pipeline) + CEO Cockpit (dashboard)
**Priority:** HIGH — This is the feature that turns the dashboard from a display into a Chief of Staff
**Predecessor:** Brief 7 (Gmail Live Polling) — 20/20 PASS

---

## OBJECTIVE

Add an interactive AI chat interface ("Scan") to the CEO Dashboard. The user types a
question → Baker retrieves context from ALL sources (Qdrant collections + PostgreSQL) →
streams a conversational answer in real-time via SSE. Bundle a Contact Search UI as a
quick win using the existing `/api/contacts/{name}` endpoint.

**End state:** Dimitry opens the dashboard → clicks Scan → types "What's the status with
Müller?" → Baker searches email vectors, WhatsApp threads, meeting transcripts, deals,
contacts → streams a synthesized answer with citations → Dimitry follows up with "What
about the pricing issue?" and Baker understands it's still about Müller.

---

## ARCHITECTURE DECISIONS

1. **SSE streaming** — `/api/scan` returns Server-Sent Events so Baker "thinks" in
   real-time. Conversational feel, not a loading screen.

2. **Cross-source retrieval in a single query** — Scan retrieves from ALL Qdrant
   collections + PostgreSQL structured data, then assembles context the same way the
   pipeline does for triggers. This is the core value: one question, synthesized answer
   across email, WhatsApp, transcripts, deals, and contacts. Without this, it's just a
   search box, not a Chief of Staff.

3. **Session memory** — Frontend keeps last 10 messages (5 exchanges) in state and passes
   them with each `/api/scan` request. This enables follow-up questions ("What about the
   pricing issue?" → Baker knows it's about Müller from the previous exchange). Without
   session memory, every question is isolated and the experience breaks.

4. **Conversational prompt** — Scan uses a dedicated `SCAN_SYSTEM_PROMPT` based on
   `baker_rag.py`'s conversational style (bottom-line first, cite sources, flag gaps,
   recommend actions). NOT the pipeline's JSON output format.

5. **Contact search** — Frontend search box that hits existing `/api/contacts/{name}`
   with fuzzy match. No backend changes needed.

---

## PHASE 0 — Scan System Prompt

### 0a. Create `orchestrator/scan_prompt.py`

New file with a conversational system prompt for Scan queries. Based on `baker_rag.py`'s
`BAKER_SYSTEM_PROMPT` but optimized for interactive Q&A:

```python
"""
Baker AI — Scan (Interactive Query) Prompt
Conversational prompt for the Scan chat interface.
"""

SCAN_SYSTEM_PROMPT = """You are Baker, the AI Chief of Staff for Dimitry Vallen, Chairman of Brisengroup.

You are answering a direct question from Dimitry via the Scan interface on the CEO Dashboard.
You have access to retrieved context from across Baker's memory: emails, WhatsApp messages,
meeting transcripts, deal records, contact profiles, and previous decisions.

## Response Style
1. **Bottom-line first** — lead with the direct answer, then supporting detail
2. **Be specific** — cite names, dates, figures, and direct quotes from the retrieved context
3. **Source attribution** — when citing information, note where it came from (e.g., "per email from Buchwalder on 12 Feb", "from WhatsApp thread with Oskolkov")
4. **Flag gaps** — if the context doesn't fully answer the question, say what's missing
5. **Be actionable** — end with concrete next steps or recommendations when relevant
6. **Person-centric** — organize information by WHO, not by data source
7. **Concise** — aim for 3-8 paragraphs. Don't pad.

## What NOT to do
- Don't produce JSON or structured data — this is a conversation
- Don't repeat the question back
- Don't hedge with "Based on the available information..." — just answer
- Don't list every source — weave citations naturally into the text

## Conversation Context
If previous messages are provided, treat this as a continuing conversation. Resolve pronouns
and references against the conversation history (e.g., "he" → the person mentioned in the
previous exchange, "the pricing issue" → whatever pricing was discussed).
"""
```

### 0b. Unit test for prompt loading

Create `tests/test_scan_prompt.py`:

```python
"""Verify scan prompt loads and has expected structure."""
from orchestrator.scan_prompt import SCAN_SYSTEM_PROMPT

def test_scan_prompt_exists():
    assert len(SCAN_SYSTEM_PROMPT) > 200
    assert "Baker" in SCAN_SYSTEM_PROMPT
    assert "Bottom-line first" in SCAN_SYSTEM_PROMPT

def test_scan_prompt_no_json_instruction():
    """Scan prompt must NOT ask for JSON output."""
    assert "JSON" not in SCAN_SYSTEM_PROMPT.upper().split("NOT TO DO")[0]
```

### Phase 0 success criteria
- [ ] `orchestrator/scan_prompt.py` exists with `SCAN_SYSTEM_PROMPT`
- [ ] Prompt is conversational (no JSON output requirement)
- [ ] Unit tests pass

---

## PHASE 1 — Backend: `/api/scan` Endpoint

### 1a. Add scan endpoint to `outputs/dashboard.py`

New POST endpoint that:
1. Accepts query + optional contact + optional conversation history
2. Retrieves context via `SentinelRetriever.retrieve_for_trigger()`
3. Builds prompt with `SCAN_SYSTEM_PROMPT` + retrieved context + conversation history
4. Streams Claude's response via SSE

```python
from fastapi.responses import StreamingResponse
from orchestrator.scan_prompt import SCAN_SYSTEM_PROMPT
from pydantic import BaseModel

class ScanRequest(BaseModel):
    query: str
    contact: str | None = None
    history: list[dict] | None = None  # [{"role": "user"|"assistant", "content": "..."}]

@app.post("/api/scan", tags=["scan"])
async def scan(req: ScanRequest):
    """
    Interactive AI query with cross-source retrieval and streaming response.
    Returns SSE stream: data events with text chunks, final event with metadata.
    """
    import anthropic
    from config.settings import config
    from memory.retriever import SentinelRetriever

    retriever = SentinelRetriever()

    # Step 1: Retrieve context (same cross-source logic as pipeline)
    contexts = retriever.retrieve_for_trigger(
        trigger_text=req.query,
        trigger_type="scan",
        contact_name=req.contact,
    )

    # Step 2: Format context block
    context_block = _format_scan_context(contexts)

    # Step 3: Build messages array
    messages = []
    # Include conversation history (last 10 messages max)
    if req.history:
        for msg in req.history[-10:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
    # Add current query with retrieved context
    messages.append({
        "role": "user",
        "content": f"## Retrieved Context\n{context_block}\n\n## Question\n{req.query}",
    })

    # Step 4: Stream response via SSE
    client = anthropic.Anthropic(api_key=config.claude.api_key)

    async def event_stream():
        try:
            with client.messages.stream(
                model=config.claude.model,
                max_tokens=4096,
                system=SCAN_SYSTEM_PROMPT,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    yield f"data: {json.dumps({'type': 'text', 'content': text})}\n\n"

                # Final event with metadata
                response = stream.get_final_message()
                yield f"data: {json.dumps({'type': 'done', 'usage': {'input': response.usage.input_tokens, 'output': response.usage.output_tokens}, 'contexts_used': len(contexts)})}\n\n"
        except Exception as e:
            logger.error(f"Scan stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

### 1b. Add context formatter helper

Add to `dashboard.py` (or a shared utility):

```python
def _format_scan_context(contexts, max_tokens: int = 100_000) -> str:
    """Format retrieved contexts into a text block for the scan prompt."""
    if not contexts:
        return "(No relevant context found in Baker's memory.)"

    blocks = []
    token_count = 0
    for ctx in contexts:
        source = ctx.metadata.get("collection", ctx.metadata.get("source", "unknown"))
        text = ctx.text[:2000]  # Cap individual context
        est_tokens = len(text) // 4
        if token_count + est_tokens > max_tokens:
            break
        blocks.append(f"[Source: {source}]\n{text}")
        token_count += est_tokens

    return "\n\n---\n\n".join(blocks)
```

### 1c. Add store-back for scan queries

After streaming completes, log the scan query as a trigger for the learning loop.
This is fire-and-forget (non-blocking):

```python
import threading

def _log_scan_async(query, contact, context_count):
    """Log scan query to trigger_log in background thread."""
    try:
        store = _get_store()
        store.log_trigger(
            trigger_type="scan",
            source_id=f"scan-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            content=query[:1000],
            contact_id=None,
            priority="medium",
        )
    except Exception as e:
        logger.warning(f"Scan store-back failed (non-fatal): {e}")
```

### 1d. Integration test

Create `tests/test_scan_endpoint.py`:

```python
"""Integration test for /api/scan endpoint."""
import pytest
from fastapi.testclient import TestClient

# Note: requires PostgreSQL + Qdrant running
# Run with: pytest tests/test_scan_endpoint.py -v

def test_scan_returns_sse_stream():
    """Verify /api/scan returns SSE content-type and streams data."""
    from outputs.dashboard import app
    client = TestClient(app)

    response = client.post(
        "/api/scan",
        json={"query": "What deals are currently active?"},
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    # Should contain at least one data event
    assert "data:" in response.text

def test_scan_with_contact():
    """Verify contact-scoped retrieval works."""
    from outputs.dashboard import app
    client = TestClient(app)

    response = client.post(
        "/api/scan",
        json={"query": "Latest updates?", "contact": "Buchwalder"},
    )
    assert response.status_code == 200

def test_scan_with_history():
    """Verify conversation history is accepted."""
    from outputs.dashboard import app
    client = TestClient(app)

    response = client.post(
        "/api/scan",
        json={
            "query": "What about the pricing?",
            "history": [
                {"role": "user", "content": "What's the status with Müller?"},
                {"role": "assistant", "content": "Müller is involved in the Kuppel-Ahl deal..."},
            ],
        },
    )
    assert response.status_code == 200
```

### Phase 1 success criteria
- [ ] `POST /api/scan` returns SSE stream with `text/event-stream` content-type
- [ ] Cross-source retrieval uses ALL Qdrant collections + PostgreSQL
- [ ] Conversation history (up to 10 messages) accepted and passed to Claude
- [ ] Scan queries logged to `trigger_log` with `type='scan'`
- [ ] All 3 integration tests pass

---

## PHASE 2 — Frontend: Scan Chat Panel

### 2a. Add Scan button to sidebar (`index.html`)

Add after the Briefing button in the `#sideRail` nav:

```html
<button class="rail-btn" data-section="scan">
    <span class="rail-icon">&#9906;</span>
    <span class="rail-label">Scan</span>
</button>
```

Add the section container in `#mainContent`:

```html
<div id="scanSection" class="section"></div>
```

### 2b. Add Scan section renderer (`app.js`)

Add to the `loadSection()` switch and create the Scan UI:

```javascript
// ---- Scan (AI Chat) ----

let scanHistory = [];  // Session memory: [{role, content}]

function renderScan() {
    const el = document.getElementById("scanSection");
    el.innerHTML = `
        <div class="scan-container">
            <div class="scan-header">
                <h2>Scan</h2>
                <button class="btn-ghost" onclick="clearScanHistory()">Clear</button>
            </div>
            <div id="scanMessages" class="scan-messages"></div>
            <form id="scanForm" class="scan-input-area" onsubmit="return handleScan(event)">
                <input type="text" id="scanInput" placeholder="Ask Baker anything..."
                       autocomplete="off" autofocus />
                <button type="submit" class="btn-primary" id="scanSubmit">Send</button>
            </form>
        </div>
    `;
    // Re-render existing messages
    renderScanMessages();
}

function renderScanMessages() {
    const container = document.getElementById("scanMessages");
    if (!container) return;
    container.innerHTML = scanHistory.map(msg => `
        <div class="scan-msg scan-msg-${msg.role}">
            <span class="scan-msg-label">${msg.role === "user" ? "You" : "Baker"}</span>
            <div class="scan-msg-body">${msg.role === "assistant" ? md(msg.content) : esc(msg.content)}</div>
        </div>
    `).join("");
    container.scrollTop = container.scrollHeight;
}

async function handleScan(e) {
    e.preventDefault();
    const input = document.getElementById("scanInput");
    const query = input.value.trim();
    if (!query) return;

    // Add user message
    scanHistory.push({ role: "user", content: query });
    input.value = "";
    renderScanMessages();

    // Disable input while streaming
    input.disabled = true;
    document.getElementById("scanSubmit").disabled = true;

    // Add placeholder for assistant response
    scanHistory.push({ role: "assistant", content: "" });
    renderScanMessages();

    try {
        const response = await fetch("/api/scan", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                query: query,
                history: scanHistory.slice(0, -1),  // Exclude the empty placeholder
            }),
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop();  // Keep incomplete line in buffer

            for (const line of lines) {
                if (!line.startsWith("data: ")) continue;
                try {
                    const event = JSON.parse(line.slice(6));
                    if (event.type === "text") {
                        // Append text to last assistant message
                        scanHistory[scanHistory.length - 1].content += event.content;
                        renderScanMessages();
                    } else if (event.type === "done") {
                        // Streaming complete — metadata available
                        console.log("Scan done:", event);
                    } else if (event.type === "error") {
                        scanHistory[scanHistory.length - 1].content += "\n\n⚠ Error: " + event.message;
                        renderScanMessages();
                    }
                } catch (parseErr) {
                    // Ignore malformed events
                }
            }
        }
    } catch (err) {
        scanHistory[scanHistory.length - 1].content = "⚠ Connection error: " + err.message;
        renderScanMessages();
    }

    // Re-enable input
    input.disabled = false;
    document.getElementById("scanSubmit").disabled = false;
    input.focus();

    // Trim history to last 10 messages (5 exchanges)
    if (scanHistory.length > 10) {
        scanHistory = scanHistory.slice(-10);
    }
}

function clearScanHistory() {
    scanHistory = [];
    renderScanMessages();
}
```

### 2c. Add Scan CSS (`style.css`)

Add styles for the chat interface:

```css
/* ---- Scan Chat ---- */
.scan-container {
    display: flex;
    flex-direction: column;
    height: calc(100vh - 120px);
}
.scan-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0 0 1rem;
    border-bottom: 1px solid var(--border);
}
.scan-messages {
    flex: 1;
    overflow-y: auto;
    padding: 1rem 0;
    display: flex;
    flex-direction: column;
    gap: 1rem;
}
.scan-msg {
    max-width: 85%;
    padding: 0.75rem 1rem;
    border-radius: 8px;
    line-height: 1.6;
}
.scan-msg-user {
    align-self: flex-end;
    background: var(--accent-dim);
    color: var(--text);
}
.scan-msg-assistant {
    align-self: flex-start;
    background: var(--surface);
    border: 1px solid var(--border);
}
.scan-msg-label {
    display: block;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    opacity: 0.5;
    margin-bottom: 0.25rem;
}
.scan-msg-body {
    font-size: 0.9rem;
}
.scan-msg-body p { margin: 0.5em 0; }
.scan-input-area {
    display: flex;
    gap: 0.5rem;
    padding: 1rem 0 0;
    border-top: 1px solid var(--border);
}
.scan-input-area input {
    flex: 1;
    padding: 0.75rem 1rem;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-family: inherit;
    font-size: 0.9rem;
}
.scan-input-area input:focus {
    outline: none;
    border-color: var(--accent);
}
.btn-primary {
    padding: 0.75rem 1.5rem;
    background: var(--accent);
    color: var(--bg);
    border: none;
    border-radius: 6px;
    cursor: pointer;
    font-weight: 500;
}
.btn-primary:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}
.btn-ghost {
    padding: 0.5rem 1rem;
    background: none;
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text-dim);
    cursor: pointer;
    font-size: 0.8rem;
}
```

### 2d. Wire up navigation

In the `loadSection()` function in `app.js`, add the case:

```javascript
case "scan":
    renderScan();
    break;
```

### Phase 2 success criteria
- [ ] Scan button appears in sidebar navigation
- [ ] Chat panel renders with message area + input box
- [ ] User messages appear on the right, Baker responses on the left
- [ ] Streaming text appears character-by-character (not after full response)
- [ ] "Clear" button resets conversation history
- [ ] Follow-up questions work (session memory passed via history parameter)
- [ ] Input auto-focuses after response completes
- [ ] History trimmed to last 10 messages automatically

---

## PHASE 3 — Contact Search UI

### 3a. Add Contact Search section (`app.js`)

Add a search box to the Deals or Home section (or as a standalone section).
Uses the existing `/api/contacts/{name}` endpoint:

```javascript
// ---- Contact Search ----

function renderContactSearch() {
    return `
        <div class="contact-search">
            <h3>Contact Lookup</h3>
            <form onsubmit="return searchContact(event)" class="contact-search-form">
                <input type="text" id="contactSearchInput"
                       placeholder="Search by name..." autocomplete="off" />
                <button type="submit" class="btn-ghost">Search</button>
            </form>
            <div id="contactResult"></div>
        </div>
    `;
}

async function searchContact(e) {
    e.preventDefault();
    const name = document.getElementById("contactSearchInput").value.trim();
    if (!name) return;

    const el = document.getElementById("contactResult");
    el.innerHTML = '<span class="loading-text">Searching...</span>';

    try {
        const data = await api(`/api/contacts/${encodeURIComponent(name)}`);
        el.innerHTML = `
            <div class="contact-card">
                <h4>${esc(data.name || name)}</h4>
                ${data.company ? `<p class="contact-company">${esc(data.company)}</p>` : ""}
                ${data.role ? `<p class="contact-role">${esc(data.role)}</p>` : ""}
                ${data.relationship ? `<p><strong>Relationship:</strong> ${esc(data.relationship)}</p>` : ""}
                ${data.email ? `<p><strong>Email:</strong> ${esc(data.email)}</p>` : ""}
                ${data.phone ? `<p><strong>Phone:</strong> ${esc(data.phone)}</p>` : ""}
                ${data.notes ? `<p class="contact-notes">${md(data.notes)}</p>` : ""}
                ${data.last_interaction ? `<p class="contact-meta">Last interaction: ${timeAgo(data.last_interaction)}</p>` : ""}
            </div>
        `;
    } catch (err) {
        if (err.message.includes("404")) {
            el.innerHTML = `<p class="no-result">No contact found matching "${esc(name)}"</p>`;
        } else {
            el.innerHTML = `<p class="error-text">Search failed: ${esc(err.message)}</p>`;
        }
    }
}
```

### 3b. Embed in Home section

Add the contact search widget to the Home section renderer (below the status summary):

```javascript
// In renderHome(), append:
html += renderContactSearch();
```

### 3c. Add contact card CSS (`style.css`)

```css
/* ---- Contact Search ---- */
.contact-search { margin-top: 2rem; }
.contact-search-form {
    display: flex;
    gap: 0.5rem;
    margin: 0.75rem 0;
}
.contact-search-form input {
    flex: 1;
    padding: 0.6rem 1rem;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-family: inherit;
}
.contact-card {
    padding: 1rem;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-top: 0.75rem;
}
.contact-card h4 { margin: 0 0 0.25rem; }
.contact-company { color: var(--accent); margin: 0; }
.contact-role { color: var(--text-dim); margin: 0 0 0.5rem; font-size: 0.85rem; }
.contact-notes { font-size: 0.85rem; opacity: 0.8; margin-top: 0.5rem; }
.contact-meta { font-size: 0.75rem; color: var(--text-dim); margin-top: 0.5rem; }
.no-result { color: var(--text-dim); font-style: italic; }
.error-text { color: var(--red, #e74c3c); }
```

### Phase 3 success criteria
- [ ] Contact search box visible on Home section
- [ ] Searching a known contact returns their profile card
- [ ] Searching an unknown name shows "not found" message
- [ ] Contact card displays all available fields (name, company, role, email, etc.)

---

## PHASE 4 — End-to-End Smoke Test

### 4a. Start dashboard

```bash
cd 01_build
python -m outputs.dashboard
```

### 4b. Test Scan flow manually

1. Open `http://localhost:8080`
2. Click "Scan" in sidebar
3. Type: "What deals are currently active?"
4. Verify: streaming response appears, sources cited
5. Follow up: "Tell me more about the largest one"
6. Verify: Baker understands "the largest one" from previous context

### 4c. Test Contact Search

1. Click "Home" in sidebar
2. In Contact Lookup, type: "Buchwalder"
3. Verify: contact card appears with profile data
4. Type: "nonexistent person xyz"
5. Verify: "not found" message appears

### 4d. Verify store-back

```sql
-- Check scan queries logged
SELECT type, source_id, content, received_at
FROM trigger_log
WHERE type = 'scan'
ORDER BY received_at DESC
LIMIT 5;
```

### 4e. Verify no regressions

1. Navigate to Alerts, Deals, Decisions, Briefing sections
2. Confirm all still load correctly
3. Auto-refresh still works (check footer timer)

### Phase 4 success criteria
- [ ] Scan streaming works end-to-end (query → retrieve → stream → display)
- [ ] Follow-up questions work (session memory active)
- [ ] Contact search returns profiles for known contacts
- [ ] Scan queries appear in `trigger_log`
- [ ] All existing dashboard sections unaffected
- [ ] No console errors in browser dev tools

---

## SUMMARY

| Phase | What | Checks |
|-------|------|--------|
| 0 | Scan system prompt | 3 |
| 1 | Backend: /api/scan endpoint | 5 |
| 2 | Frontend: Scan chat panel | 8 |
| 3 | Contact search UI | 4 |
| 4 | End-to-end smoke test | 6 |
| **Total** | | **26** |

**Success:** 26/26 PASS, 0 FAIL.

---

## HUMAN GATES

None. This brief is fully autonomous — no OAuth flows, no external credentials, no
manual browser steps. Claude Code can execute end-to-end.

---

## FILES TOUCHED

| File | Change |
|------|--------|
| `orchestrator/scan_prompt.py` | NEW — Scan conversational system prompt |
| `outputs/dashboard.py` | Add `POST /api/scan` endpoint + context formatter + store-back |
| `outputs/static/index.html` | Add Scan nav button + section container |
| `outputs/static/app.js` | Add Scan chat UI + SSE reader + session memory + contact search |
| `outputs/static/style.css` | Add Scan chat + contact card styles |
| `tests/test_scan_prompt.py` | NEW — prompt unit tests |
| `tests/test_scan_endpoint.py` | NEW — /api/scan integration tests |

---

## DEPENDENCIES

- Phase 0 has no dependencies (can run immediately)
- Phase 1 depends on Phase 0 (needs the prompt)
- Phase 2 depends on Phase 1 (needs the endpoint)
- Phase 3 has no dependencies (can run in parallel with Phases 0-2)
- Phase 4 depends on Phases 1-3

---

## KNOWN LIMITATIONS (this brief)

1. **No persistent chat history** — Session memory lives in frontend state only. If you
   refresh the page, conversation history is lost. Persistent history (saved to PostgreSQL)
   is a future enhancement, not this brief.

2. **No authentication** — Dashboard is currently open (localhost only). Auth is a separate
   concern for when Baker gets deployed beyond local.

3. **No file attachments in Scan** — Text-only queries. Attaching files (e.g., "summarize
   this PDF") is a future capability.

4. **Context window vs. history** — With 10 history messages + retrieved context, we may
   approach the context budget. The `_format_scan_context` function caps at 100K tokens
   which leaves plenty of room within the 1M window, but this should be monitored.
