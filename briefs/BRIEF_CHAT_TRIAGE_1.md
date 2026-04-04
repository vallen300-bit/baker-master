# BRIEF: Chat Response Triage Buttons

**Priority:** High — Director loses valuable Baker analyses on page reload
**Ticket:** CHAT-TRIAGE-1

## Problem

When Baker produces a substantive answer in Ask Baker, it's lost on page reload. No way to save or act on it.

## Solution

After every Baker response (above a minimum length), show triage action buttons underneath — just like the landing page cards. The Director decides what to do with the output.

## UX Design

After Baker's response streams in, append a triage bar below the answer:

```
┌─────────────────────────────────────────────┐
│  [Baker's full response here]               │
│                                             │
│  ─────────────────────────────────────────  │
│  💾 Save to Dossiers  │  [Baker suggestion] │
│  [Baker suggestion]   │  ✕ Dismiss          │
└─────────────────────────────────────────────┘
```

### Fixed buttons (always present):
- **Save to Dossiers** — saves the Q&A pair to `deep_analyses` table → appears in Dossiers section
- **Dismiss** — hides the triage bar (answer stays visible, just removes the buttons)

### Baker-suggested buttons (dynamic, 1-2 max):
After generating the answer, Baker picks 1-2 contextually relevant follow-up actions. Examples:
- After a person summary → "Run Full Dossier on [Name]"
- After a briefing → "Send to WhatsApp" or "Draft Email Summary"
- After a legal analysis → "Add Deadline" or "Flag as Critical"
- After a deal summary → "Create ClickUp Task"
- After a risk alert → "Ask Specialist"

**How to generate suggestions:** Add a small addition to the scan prompt (or a post-response Haiku call) that returns 1-2 suggested actions as JSON. Keep it cheap — Haiku, <100 tokens. Or: use simple keyword matching on the answer content (cheaper, no API call):
- Contains person names + "connected" / "issues" / "role" → "Run Full Dossier"
- Contains "deadline" / "due" / "overdue" → "Add Deadline"
- Contains "risk" / "critical" / "fire" → "Flag as Critical"
- Contains "draft" / "email" / "message" → "Send via WhatsApp"
- Default fallback → "Ask Follow-up" (pre-fills input with a follow-up prompt)

Recommend the keyword matching approach — zero API cost, instant.

## Implementation

### Change 1: Frontend — Triage bar component

**File:** `outputs/static/index.html` (or `app.js` depending on where chat rendering lives)

After the answer div is rendered (SSE stream complete), inject a triage bar:

```html
<div class="chat-triage" data-conversation-id="{id}">
  <button class="triage-btn triage-save" onclick="saveToDossiers(this)">
    💾 Save to Dossiers
  </button>
  <!-- Dynamic suggestions inserted here -->
  <button class="triage-btn triage-dismiss" onclick="dismissTriage(this)">
    ✕
  </button>
</div>
```

**Styling:** Match the existing triage button style from landing cards. Compact, horizontal row, subtle until hovered. Use the same `.triage-btn` class or similar.

**Minimum length gate:** Only show triage bar if answer > 300 characters. Don't show triage for "✅ WhatsApp sent" or "Noted" type responses.

### Change 2: Frontend — Save to Dossiers action

**File:** `outputs/static/app.js`

```javascript
async function saveToDossiers(btn) {
  const container = btn.closest('.chat-triage');
  const msgEl = container.previousElementSibling; // the answer div
  const answer = msgEl.innerText || msgEl.textContent;

  // Find the corresponding question (the user message above the answer)
  const questionEl = msgEl.previousElementSibling; // user's question div
  const question = questionEl ? (questionEl.innerText || '') : 'Baker Analysis';

  btn.textContent = 'Saving...';
  btn.disabled = true;

  try {
    const resp = await bakerFetch('/api/dossiers/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, answer })
    });
    if (resp.ok) {
      btn.textContent = '✓ Saved';
      btn.classList.add('triage-done');
    } else {
      btn.textContent = 'Failed — retry?';
      btn.disabled = false;
    }
  } catch (e) {
    btn.textContent = 'Failed — retry?';
    btn.disabled = false;
  }
}

function dismissTriage(btn) {
  const container = btn.closest('.chat-triage');
  container.style.display = 'none';
}
```

### Change 3: Frontend — Dynamic suggestions (keyword-based)

**File:** `outputs/static/app.js`

```javascript
function getSuggestedActions(answer, question) {
  const text = (answer + ' ' + question).toLowerCase();
  const suggestions = [];

  if (/(connected|issues|role|profile|background|dossier)/i.test(text)) {
    // Extract a person name from the question
    const nameMatch = question.match(/(?:about|on|for|with)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)/);
    if (nameMatch) {
      suggestions.push({
        label: `Run Full Dossier on ${nameMatch[1]}`,
        action: () => askBaker(`Run a full dossier on ${nameMatch[1]}`)
      });
    }
  }
  if (/(deadline|due|overdue|expir)/i.test(text)) {
    suggestions.push({
      label: 'Add Deadline',
      action: () => askBaker('Add a deadline for the items mentioned above')
    });
  }
  if (/(risk|critical|fire|urgent|escalat)/i.test(text)) {
    suggestions.push({
      label: 'Flag as Critical',
      action: () => askBaker('Flag the most urgent item above as critical')
    });
  }
  if (/(send|forward|share|whatsapp|email)/i.test(text) && !/(sent|delivered|drafted)/i.test(text)) {
    suggestions.push({
      label: 'Send via WhatsApp',
      action: () => askBaker('Send a summary of the above via WhatsApp')
    });
  }

  // Always offer a follow-up
  if (suggestions.length === 0) {
    suggestions.push({
      label: 'Ask Follow-up',
      action: () => { document.querySelector('.chat-input').focus(); }
    });
  }

  return suggestions.slice(0, 2); // max 2
}
```

Render these as additional `<button>` elements in the triage bar, between "Save to Dossiers" and "Dismiss".

### Change 4: Backend — Save to Dossiers endpoint

**File:** `outputs/dashboard.py`

Add a new endpoint:

```python
@app.post("/api/dossiers/save")
async def save_to_dossiers(request: Request):
    """Save a Baker chat answer to deep_analyses (Dossiers section)."""
    _check_auth(request)
    body = await request.json()
    question = body.get("question", "Baker Analysis")
    answer = body.get("answer", "")

    if not answer or len(answer) < 100:
        return JSONResponse({"error": "Answer too short to save"}, status_code=400)

    # Build topic from question (clean, truncated)
    import re
    topic = re.sub(r'https?://\S+', '', question).strip()[:120]
    if not topic:
        topic = "Baker Analysis"

    try:
        conn = get_pg_connection()
        cur = conn.cursor()
        # Dedup: skip if same topic saved in last 1 hour
        cur.execute("""
            SELECT id FROM deep_analyses
            WHERE topic = %s AND created_at > NOW() - INTERVAL '1 hour'
            LIMIT 1
        """, (topic,))
        if cur.fetchone():
            cur.close()
            conn.close()
            return JSONResponse({"status": "already_saved", "message": "Already in Dossiers"})

        cur.execute("""
            INSERT INTO deep_analyses (topic, analysis_text, prompt, source_documents, created_at)
            VALUES (%s, %s, %s, %s, NOW())
            RETURNING id
        """, (topic, answer, question, "ask_baker"))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return JSONResponse({"status": "saved", "id": row[0]})
    except Exception as e:
        try:
            conn.rollback()
        except:
            pass
        logger.error(f"Save to dossiers failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
```

**Important:** Verify `deep_analyses` table schema first:
```sql
SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'deep_analyses';
```
Adapt INSERT columns to match actual schema.

### Change 5: Mobile — Same triage pattern

**File:** `outputs/static/mobile.js` / `mobile.html`

Apply the same triage bar pattern to mobile Ask Baker responses. Use the same button styles but ensure touch-friendly sizing (min 44px tap targets).

## Files to Modify

| File | Change |
|------|--------|
| `outputs/static/app.js` | Triage bar rendering, saveToDossiers(), dismissTriage(), getSuggestedActions() |
| `outputs/static/index.html` | CSS for `.chat-triage` bar (or inline in app.js) |
| `outputs/dashboard.py` | `POST /api/dossiers/save` endpoint |
| `outputs/static/mobile.js` | Same triage pattern for mobile |

## CSS Guidelines

```css
.chat-triage {
  display: flex;
  gap: 8px;
  padding: 8px 0;
  margin-top: 8px;
  border-top: 1px solid rgba(255,255,255,0.1);
  flex-wrap: wrap;
}
.chat-triage .triage-btn {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid rgba(255,255,255,0.15);
  background: rgba(255,255,255,0.05);
  color: #ccc;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
}
.chat-triage .triage-btn:hover {
  background: rgba(255,255,255,0.12);
  color: #fff;
}
.chat-triage .triage-save {
  border-color: rgba(212,175,55,0.3);
  color: #d4af37;
}
.chat-triage .triage-save:hover {
  background: rgba(212,175,55,0.15);
}
.chat-triage .triage-done {
  color: #4ecdc4;
  border-color: rgba(78,205,196,0.3);
}
.chat-triage .triage-dismiss {
  margin-left: auto;
  border: none;
  color: #666;
}
```

## Testing

1. Ask Baker a complex question → answer streams → triage bar appears below
2. Click "Save to Dossiers" → button shows "✓ Saved" → navigate to Dossiers → entry is there
3. Click "Dismiss" → triage bar disappears, answer stays
4. Click a dynamic suggestion → pre-fills or triggers the suggested action
5. Ask a short question ("What time is it?") → no triage bar (too short)
6. Send "✅ WhatsApp sent" type action → no triage bar

## Verification

```bash
python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"
```

Test endpoint:
```bash
curl -X POST https://baker-master.onrender.com/api/dossiers/save \
  -H "X-Baker-Key: $BAKER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"question":"Test question","answer":"Test answer that is long enough to save..."}'
```
