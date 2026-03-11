# BRIEF: FOLLOWUP-SUGGESTIONS-1 — Smart Follow-Up Questions After Each Response

**Author:** AI Head (Session 20)
**For:** Code 300
**Priority:** MEDIUM — UX enhancement, makes Baker feel intelligent
**Estimated scope:** 3 files (dashboard.py, app.js, style.css), ~100 lines
**Cost:** ~$0.001 per response (one Haiku call to generate suggestions)

---

## Vision

After Baker answers a question, show 2-3 clickable follow-up questions below the response. The Director clicks one instead of typing — saves time and guides deeper exploration. This is a standard pattern in premium AI chat UIs.

Example:
```
Director: "What's the latest on Hagenauer?"
Baker: [detailed answer about the claim status...]

  Follow up:
  ┌──────────────────────────────────┐ ┌──────────────────────────────────┐ ┌──────────────────────────────────┐
  │ What are the open deadlines?     │ │ Draft a follow-up to Ofenheimer  │ │ What did we discuss last week?    │
  └──────────────────────────────────┘ └──────────────────────────────────┘ └──────────────────────────────────┘
```

## Implementation

### File 1: `outputs/dashboard.py`

#### 1A. New endpoint to generate follow-up suggestions:

```python
@app.post("/api/scan/followups", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def generate_followups(req: FollowupRequest):
    """Generate 2-3 follow-up questions based on the conversation."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=config.claude.api_key)

        prompt = (
            f"Based on this conversation, suggest exactly 3 brief follow-up questions "
            f"the Director might want to ask next. Each should be a different angle: "
            f"one action-oriented (draft/send/create), one analytical (analyze/compare/assess), "
            f"one exploratory (what about/any updates on/related to).\n\n"
            f"Return ONLY a JSON array of 3 strings, no other text.\n"
            f"Keep each under 50 characters.\n\n"
            f"Question: {req.question[:300]}\n"
            f"Answer: {req.answer[:1000]}"
        )

        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )

        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens,
                        resp.usage.output_tokens, source="followup_suggestions")
        except Exception:
            pass

        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        import json
        suggestions = json.loads(raw)
        if isinstance(suggestions, list) and len(suggestions) >= 2:
            return {"suggestions": suggestions[:3]}
        return {"suggestions": []}

    except Exception as e:
        logger.debug(f"Followup generation failed (non-fatal): {e}")
        return {"suggestions": []}
```

#### 1B. Add request model:

```python
class FollowupRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    answer: str = Field(..., min_length=1, max_length=2000)
```

### File 2: `outputs/static/app.js`

#### 2A. After each Baker response completes, fetch and render follow-ups:

In `sendScanMessage()`, after the copy button / feedback buttons block, add:

```javascript
    // Follow-up suggestions
    if (fullResponse && fullResponse.length > 100 && !fullResponse.startsWith('Connection error:')) {
        _fetchFollowups(replyEl, question, fullResponse);
    }
```

New function:

```javascript
async function _fetchFollowups(replyEl, question, answer) {
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
            btn.addEventListener('click', (function(text) {
                return function() {
                    sendScanMessage(text);
                };
            })(data.suggestions[i]));
            bar.appendChild(btn);
        }

        replyEl.appendChild(bar);
    } catch (e) {
        // Non-fatal — just don't show suggestions
    }
}
```

Also add to `sendSpecialistMessage()` — same pattern after the toolbar block.

### File 3: `outputs/static/style.css`

```css
/* Follow-up suggestions */
.followup-bar {
  display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px;
  padding-top: 10px; border-top: 1px solid var(--border-light);
}
.followup-btn {
  padding: 6px 14px; border: 1px solid var(--border); border-radius: var(--radius-pill);
  background: var(--bg); font-size: 12px; font-weight: 400;
  color: var(--text2); cursor: pointer; font-family: var(--font);
  transition: all 0.15s; text-align: left;
}
.followup-btn:hover {
  border-color: var(--blue); color: var(--blue); background: var(--blue-bg);
}
```

## Bump cache versions

In `index.html`:
```html
<link rel="stylesheet" href="/static/style.css?v=28">
<script src="/static/app.js?v=28"></script>
```

## Testing

1. Syntax check dashboard.py, app.js
2. Ask Baker a question → after response, 3 follow-up pills should appear
3. Click a pill → sends that question as a new message
4. Short responses (<100 chars) should NOT show follow-ups (e.g., action confirmations)
5. Ask Specialist → same behavior
