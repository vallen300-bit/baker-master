# BRIEF: Learning Loop — Close the Feedback Circuit

**Author:** Code 300 (Session 14)
**Date:** 2026-03-08
**Status:** Ready for Code Brisen
**Branch:** `feat/learning-loop`

---

## Context

Baker has a feedback endpoint (`POST /api/tasks/{id}/feedback`) and cascades feedback to `decomposition_log` — but nobody calls the endpoint. The decomposer consults past patterns via `{experience_context}` — but only for delegate-path (multi-capability) tasks, which are ~20% of queries. The remaining 80% (fast-path, single capability) get zero benefit from past feedback.

This brief closes the circuit: Director gives feedback → Baker remembers → next similar query is better.

---

## What Already Exists (DO NOT REBUILD)

| Component | File | Lines | Status |
|-----------|------|-------|--------|
| Feedback API endpoint | `outputs/dashboard.py` | 3437 | LIVE — accepts accepted/revised/rejected |
| `baker_tasks` feedback columns | `memory/store_back.py` | 847 | LIVE — director_feedback, feedback_comment, feedback_at |
| Feedback → decomposition_log cascade | `memory/store_back.py` | 970-986 | LIVE — auto-propagates on update |
| Experience retrieval for decomposer | `orchestrator/capability_router.py` | 216-258 | LIVE — fetches top 3 similar past patterns |
| `{experience_context}` injection | `orchestrator/capability_router.py` | 148-150 | LIVE — template substitution in decomposer prompt |

---

## Part 1: Feedback Buttons in Cockpit (frontend)

### What

After every Scan response, show three feedback buttons below the answer:
- **Good** (accepted) — green checkmark
- **Revise** (revised) — yellow edit icon
- **Wrong** (rejected) — red X

When clicked, POST to `/api/tasks/{task_id}/feedback` with the feedback value. If "revised" or "rejected", show an optional text input for the comment.

### Where

**`outputs/static/app.js`** — find the Scan response rendering section.

The SSE stream yields `{"_agent_result": {...}}` as the final event. The `baker_task_id` is available from the scan response metadata. After the response is rendered, append feedback buttons:

```javascript
// After scan response is complete and rendered:
function renderFeedbackButtons(taskId, container) {
    const fb = document.createElement('div');
    fb.className = 'feedback-bar';
    fb.innerHTML = `
        <span class="feedback-label">Was this helpful?</span>
        <button onclick="submitFeedback(${taskId}, 'accepted')" class="fb-btn fb-good" title="Good">✓</button>
        <button onclick="submitFeedback(${taskId}, 'revised')" class="fb-btn fb-revise" title="Needs revision">✎</button>
        <button onclick="submitFeedback(${taskId}, 'rejected')" class="fb-btn fb-wrong" title="Wrong">✗</button>
    `;
    container.appendChild(fb);
}

async function submitFeedback(taskId, feedback) {
    let comment = null;
    if (feedback !== 'accepted') {
        comment = prompt('What should Baker do differently?');
        if (comment === null) return; // Cancelled
    }
    const body = { feedback };
    if (comment) body.comment = comment;

    await bakerFetch(`/api/tasks/${taskId}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    // Replace buttons with confirmation
    event.target.closest('.feedback-bar').innerHTML =
        `<span class="feedback-done">Feedback recorded: ${feedback}</span>`;
}
```

### CSS

```css
.feedback-bar { margin-top: 12px; padding: 8px 0; border-top: 1px solid #eee; }
.feedback-label { font-size: 13px; color: #888; margin-right: 8px; }
.fb-btn { border: 1px solid #ddd; background: white; border-radius: 4px; padding: 4px 10px; cursor: pointer; font-size: 14px; margin-right: 4px; }
.fb-btn:hover { background: #f5f5f5; }
.fb-good:hover { border-color: #4caf50; color: #4caf50; }
.fb-revise:hover { border-color: #ff9800; color: #ff9800; }
.fb-wrong:hover { border-color: #f44336; color: #f44336; }
.feedback-done { font-size: 13px; color: #4caf50; }
```

### Finding the task_id

The `baker_task_id` must be available to the frontend after a scan response. Currently, the SSE stream sends `{"_agent_result": AgentResult}` — but this doesn't include the task ID.

**Fix needed in `outputs/dashboard.py`**: In the scan_chat SSE response, yield the task_id at the end:

```python
yield f"data: {json.dumps({'task_id': baker_task_id})}\n\n"
```

Search for where `_agent_result` is yielded in the scan SSE generator and add the task_id yield immediately after. The frontend stores it for the feedback buttons.

---

## Part 2: WhatsApp Feedback Detection

### What

When the Director replies to a Baker WhatsApp answer with feedback keywords, detect and store the feedback automatically.

### Feedback Keywords

```python
_WA_FEEDBACK_POSITIVE = re.compile(
    r"^(good|great|thanks|perfect|correct|exactly|yes|👍|✅)\s*$", re.IGNORECASE
)
_WA_FEEDBACK_NEGATIVE = re.compile(
    r"^(wrong|no|bad|incorrect|not right|nein|falsch|👎|❌)\s*$", re.IGNORECASE
)
_WA_FEEDBACK_REVISE = re.compile(
    r"^(revise|update|change|fix|adjust|anders|korrigier)\b", re.IGNORECASE
)
```

### Where

**`triggers/waha_webhook.py`** — inside `_handle_director_message()`, BEFORE the intent classification step.

```python
# Check if this is feedback on the last baker_task
if _is_feedback_message(text):
    _handle_wa_feedback(text, chat_id, store)
    return  # Don't route as a new question

def _is_feedback_message(text: str) -> bool:
    """Check if message looks like feedback (short, keyword match)."""
    if len(text) > 100:
        return False  # Too long to be feedback
    return bool(
        _WA_FEEDBACK_POSITIVE.match(text) or
        _WA_FEEDBACK_NEGATIVE.match(text) or
        _WA_FEEDBACK_REVISE.match(text)
    )

def _handle_wa_feedback(text: str, chat_id: str, store):
    """Store feedback on the most recent baker_task from this channel."""
    if _WA_FEEDBACK_POSITIVE.match(text):
        feedback = "accepted"
    elif _WA_FEEDBACK_NEGATIVE.match(text):
        feedback = "rejected"
    else:
        feedback = "revised"

    # Find the most recent completed baker_task from WhatsApp
    conn = store._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM baker_tasks
            WHERE channel = 'whatsapp'
              AND status = 'completed'
              AND director_feedback IS NULL
            ORDER BY completed_at DESC
            LIMIT 1
        """)
        row = cur.fetchone()
        if row:
            task_id = row[0]
            store.update_baker_task(task_id, director_feedback=feedback, feedback_comment=text)
            logger.info(f"WA feedback stored: task {task_id} = {feedback}")
            _wa_reply(chat_id, f"Feedback noted: {feedback}. I'll adjust next time.")
        cur.close()
    except Exception as e:
        logger.warning(f"WA feedback storage failed: {e}")
    finally:
        store._put_conn(conn)
```

---

## Part 3: Fast-Path Experience Retrieval

### What

Currently, `_retrieve_experience()` in `capability_router.py` only runs for delegate-path tasks (multi-capability decomposition). But 80% of tasks take the fast path (single capability). These tasks should also benefit from past feedback.

### How

When a **fast-path** capability is selected, check `baker_tasks` for recent feedback on similar tasks that used the same capability. If negative feedback exists, prepend a warning to the capability's system prompt.

### Where

**`orchestrator/capability_runner.py`** — in `_build_system_prompt()` (line 444), after building the system prompt but before returning it.

```python
def _build_system_prompt(self, capability, domain=None, mode=None):
    # ... existing prompt building ...

    # LEARNING-LOOP: Inject past feedback for this capability
    feedback_context = self._get_capability_feedback(capability.slug)
    if feedback_context:
        enriched += f"\n\n## PAST FEEDBACK ON YOUR RESPONSES\n{feedback_context}\n"

    return build_mode_aware_prompt(enriched, domain=domain, mode=mode)


def _get_capability_feedback(self, slug: str, limit: int = 3) -> str:
    """Fetch recent Director feedback on tasks handled by this capability."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return ""
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT title, director_feedback, feedback_comment
                FROM baker_tasks
                WHERE capability_slug = %s
                  AND director_feedback IS NOT NULL
                  AND director_feedback != 'accepted'
                ORDER BY feedback_at DESC
                LIMIT %s
            """, (slug, limit))
            rows = cur.fetchall()
            cur.close()
            if not rows:
                return ""
            parts = ["The Director gave feedback on past responses from this capability:"]
            for title, feedback, comment in rows:
                line = f"- Task \"{title[:80]}\": {feedback}"
                if comment:
                    line += f" — \"{comment}\""
                parts.append(line)
            parts.append("Adjust your approach based on this feedback.")
            return "\n".join(parts)
        except Exception as e:
            logger.warning(f"Capability feedback lookup failed: {e}")
            return ""
        finally:
            store._put_conn(conn)
    except Exception:
        return ""
```

### Prerequisite: capability_slug on baker_tasks

The `baker_tasks` table needs a `capability_slug` column to track which capability handled each task. Check if this already exists — if not, add it:

```sql
ALTER TABLE baker_tasks ADD COLUMN IF NOT EXISTS capability_slug TEXT;
```

Then ensure `capability_slug` is set when closing a task in the scan flow. Search dashboard.py for where `update_baker_task` is called after a capability run, and add the slug.

---

## Part 4: Capability Quality Dashboard Endpoint

### What

New endpoint that aggregates feedback quality per capability. Director can see: which capabilities are performing well, which need attention.

### Endpoint

**`outputs/dashboard.py`** — add:

```python
@app.get("/api/capability-quality", tags=["phase-4c"], dependencies=[Depends(verify_api_key)])
async def get_capability_quality():
    """Aggregate feedback quality per capability."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        return {"capabilities": []}
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT capability_slug,
                   COUNT(*) as total_tasks,
                   SUM(CASE WHEN director_feedback = 'accepted' THEN 1 ELSE 0 END) as accepted,
                   SUM(CASE WHEN director_feedback = 'revised' THEN 1 ELSE 0 END) as revised,
                   SUM(CASE WHEN director_feedback = 'rejected' THEN 1 ELSE 0 END) as rejected,
                   SUM(CASE WHEN director_feedback IS NULL THEN 1 ELSE 0 END) as no_feedback
            FROM baker_tasks
            WHERE capability_slug IS NOT NULL
              AND status = 'completed'
            GROUP BY capability_slug
            ORDER BY total_tasks DESC
        """)
        rows = cur.fetchall()
        cur.close()
        caps = []
        for slug, total, acc, rev, rej, nf in rows:
            rated = acc + rev + rej
            quality = round(acc / rated * 100) if rated > 0 else None
            caps.append({
                "slug": slug, "total_tasks": total,
                "accepted": acc, "revised": rev, "rejected": rej,
                "no_feedback": nf, "quality_pct": quality,
            })
        return {"capabilities": caps}
    except Exception as e:
        return {"capabilities": [], "error": str(e)}
    finally:
        store._put_conn(conn)
```

---

## Files Summary

| Action | File | What |
|--------|------|------|
| **MODIFY** | `outputs/static/app.js` | Feedback buttons after Scan response |
| **MODIFY** | `outputs/static/index.html` | CSS for feedback buttons (or inline in app.js) |
| **MODIFY** | `outputs/dashboard.py` | Yield task_id in SSE + capability quality endpoint |
| **MODIFY** | `triggers/waha_webhook.py` | WhatsApp feedback detection + storage |
| **MODIFY** | `orchestrator/capability_runner.py` | Fast-path experience retrieval |
| **MODIFY** | `memory/store_back.py` | Add capability_slug column to baker_tasks if needed |

**Estimated: ~250 lines across 6 files**

---

## Verification Checklist

- [ ] Scan response in Cockpit shows 3 feedback buttons (Good/Revise/Wrong)
- [ ] Clicking "Good" → POST accepted → buttons replaced with confirmation
- [ ] Clicking "Wrong" → prompt for comment → POST rejected with comment
- [ ] WhatsApp: Director replies "wrong" → feedback stored on last task
- [ ] WhatsApp: Director replies "good" → feedback stored as accepted
- [ ] Next Scan query using same capability → system prompt includes past negative feedback
- [ ] `GET /api/capability-quality` returns per-capability quality percentages
- [ ] `capability_slug` is populated on baker_tasks for capability-routed tasks

---

## What NOT to Build

- No automatic weight tuning on Decision Engine (that's Phase 4C+, needs more data)
- No prompt rewriting based on feedback (manual prompt evolution, not automated)
- No feedback UI in the morning briefing email (too invasive)
- No feedback aggregation scheduled job (the endpoint is sufficient for now)

---

## Context for Brisen

- `bakerFetch()` is the auth wrapper in app.js — use it for all API calls
- SSE streaming in scan_chat uses `EventSource` pattern — search app.js for "EventSource" or "text/event-stream"
- `_wa_reply()` in waha_webhook.py sends a WhatsApp message to Director — import and use for feedback confirmation
- `update_baker_task()` in store_back.py accepts arbitrary kwargs matching column names — no special handling needed
- The existing feedback endpoint is at line 3437 in dashboard.py — don't recreate it
