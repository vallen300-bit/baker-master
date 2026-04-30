# BRIEF: CORTEX_RUN_SCAN_UI_RENDER_1 — Scan UI renders Cortex SSE events

## Context
Wave 1 of CORTEX_MANUAL_INVOKE_1 (PR #88, deployed `7a36312` on 2026-04-30 04:46Z) shipped end-to-end manual Cortex invocation through Scan intent + `/api/cortex/run`. **AI Head B's PR #88 review §F-2 (MEDIUM) flagged this exact gap and Director's post-deploy smoke confirmed it live**: typing `run cortex on hagenauer-rg7 — give me a 1-line state of play` into the Scan box correctly triggered cycle `18a18ec5-ea69-4e44-97c9-4308488b8aba` (cost $1.46, status `tier_b_pending`, full propose-phase synthesis written to DB), but the Scan card sat on `Baker is thinking…` for 5+ minutes because the front-end SSE consumers only render payloads with a `data.token` field — the typed events the Cortex stream emits (`{type: started|phase_changed|phase_output|terminal, ...}`) have no `token` and are silently swallowed.

This brief adds the front-end render path. **Backend is unchanged** — it works correctly today. The only delta is in the two Scan SSE consumers (desktop `app.js`, mobile `mobile.js`), one new read-only endpoint to surface the proposal text after `terminal`, and the CSS / cache-bust to make the new UI elements visible.

Wave 2 priority #1 per Director ratification 2026-04-30 ~05:35Z (swap with `CORTEX_NOTIFICATION_DEFER_1`).

## Estimated time: ~6h
## Complexity: Medium (touches DB read endpoint + 2 frontend SSE consumers + CSS + 2 cache busts)
## Prerequisites:
- PR #88 merged (`7a36312`) — present on `main`
- Cycle `18a18ec5-ea69-4e44-97c9-4308488b8aba` exists in `cortex_phase_outputs` for manual smoke verification (Director's 2026-04-30 smoke run)

---

## Fix/Feature 1: New endpoint — `GET /api/cortex/cycles/{cycle_id}/proposal`

### Problem
After the SSE `terminal` event, the front-end has the `cycle_id` but no way to fetch the propose-phase synthesis text (the actual answer to Director's question). The synthesis is stored in `cortex_phase_outputs.payload->>'proposal_text'` for the row where `artifact_type = 'synthesis'` AND `phase = 'reason'`. We need a tiny read-only endpoint that surfaces this.

### Current State
- `outputs/dashboard.py:3952` — `GET /api/cortex/events` (filters `cortex_events`, not `cortex_phase_outputs`)
- `outputs/dashboard.py:4051` — `GET /api/cortex/stats`
- **No endpoint surfaces a single cycle's proposal text.**

DB schema verified via `information_schema.columns`:
```
cortex_phase_outputs: output_id, cycle_id, phase, phase_order, artifact_type, payload (JSONB), citations, created_at
cortex_cycles: cycle_id (UUID PK), matter_slug, triggered_by, started_at, completed_at, status, current_phase, cost_tokens, cost_dollars, aborted_reason
```

Verified payload shape for the synthesis row (cycle `18a18ec5`):
```json
{
  "cost_tokens": 7924,
  "cost_dollars": 0.237581,
  "proposal_text": "# Hagenauer RG7 — State of Play\n\n## Bottom Line\n..."
}
```

### Implementation

Add immediately AFTER `outputs/dashboard.py:4001` (end of `get_cortex_events`):

```python
@app.get(
    "/api/cortex/cycles/{cycle_id}/proposal",
    tags=["cortex"],
    dependencies=[Depends(verify_api_key)],
)
async def get_cortex_cycle_proposal(cycle_id: str):
    """Return the propose-phase synthesis text for a cycle.

    Read-only. Backs the Scan UI's terminal card render in
    CORTEX_RUN_SCAN_UI_RENDER_1. Returns 404 if cycle has no
    synthesis row yet (cycle still running, archived without propose,
    or failed pre-synthesis).
    """
    # Validate cycle_id is UUID-shaped to prevent SQL surprise; psycopg2
    # parameterises but cheap precondition catches obvious garbage.
    import uuid as _uuid
    try:
        _uuid.UUID(cycle_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid cycle_id")

    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # Cycle metadata (so the UI can show matter + status + cost
        # without a second round-trip).
        cur.execute(
            """
            SELECT cycle_id::text, matter_slug, triggered_by, status,
                   current_phase, cost_dollars, cost_tokens,
                   started_at, completed_at, aborted_reason
            FROM cortex_cycles
            WHERE cycle_id = %s
            LIMIT 1
            """,
            (cycle_id,),
        )
        cyc = cur.fetchone()
        if not cyc:
            cur.close()
            conn.commit()
            raise HTTPException(status_code=404, detail="Cycle not found")

        # Synthesis row (Phase 3c output written by cortex_runner).
        # Bound LIMIT 1 — only one synthesis row per cycle by design.
        cur.execute(
            """
            SELECT payload, created_at
            FROM cortex_phase_outputs
            WHERE cycle_id = %s
              AND artifact_type = 'synthesis'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (cycle_id,),
        )
        syn = cur.fetchone()
        cur.close()
        conn.commit()

        proposal_text = None
        if syn and isinstance(syn.get("payload"), dict):
            proposal_text = syn["payload"].get("proposal_text")

        # Use existing _serialize helper at outputs/dashboard.py:376 (verified).
        # It handles datetime → ISO string for any datetime fields in the dict
        # — same pattern used by get_cortex_events at line 3989.
        result = _serialize({
            "cycle_id": cyc["cycle_id"],
            "matter_slug": cyc["matter_slug"],
            "triggered_by": cyc["triggered_by"],
            "status": cyc["status"],
            "current_phase": cyc["current_phase"],
            "cost_dollars": float(cyc.get("cost_dollars") or 0.0),
            "cost_tokens": int(cyc.get("cost_tokens") or 0),
            "started_at": cyc.get("started_at"),
            "completed_at": cyc.get("completed_at"),
            "aborted_reason": cyc.get("aborted_reason"),
        })
        result["proposal_text"] = proposal_text
        result["has_proposal"] = bool(proposal_text)
        return result
    except HTTPException:
        raise
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("get_cortex_cycle_proposal: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        store._put_conn(conn)
```

### Key Constraints
- **Helper `_serialize_dt`**: grep for it first. If absent, fall back to `_serialize` (used at `outputs/dashboard.py:3989`) which already handles datetimes — pass the whole dict through `_serialize(dict(...))` instead of field-by-field. Pick whichever exists; do not invent.
- **JSONB payload**: psycopg2 returns `dict` for JSONB columns when using `RealDictCursor`. Defensive `isinstance(..., dict)` check above is enough — do not add a `json.loads` fallback (would mask a real bug).
- **No new DB writes** — read-only endpoint.
- **LIMIT 1** on both queries (lessons.md #2/#3 — every DB query has a LIMIT).
- **`conn.rollback()` in except** — standard pattern, present above.
- **`store._put_conn(conn)`** in `finally` — present above.

### Verification

```bash
curl -s -H "X-Baker-Key: bakerbhavanga" \
  "https://baker-master.onrender.com/api/cortex/cycles/18a18ec5-ea69-4e44-97c9-4308488b8aba/proposal" \
  | python3 -m json.tool
```

Expected: `has_proposal: true`, `proposal_text` non-empty starting with `"# Hagenauer RG7 — State of Play"`, `cost_dollars: 1.4620`, `status: "tier_b_pending"`.

```bash
# 404 for nonexistent
curl -s -o /dev/null -w "%{http_code}\n" -H "X-Baker-Key: bakerbhavanga" \
  "https://baker-master.onrender.com/api/cortex/cycles/00000000-0000-0000-0000-000000000000/proposal"
# expect: 404

# 400 for malformed
curl -s -o /dev/null -w "%{http_code}\n" -H "X-Baker-Key: bakerbhavanga" \
  "https://baker-master.onrender.com/api/cortex/cycles/not-a-uuid/proposal"
# expect: 400
```

---

## Fix/Feature 2: Desktop Scan SSE consumer renders Cortex events (`outputs/static/app.js`)

### Problem
`sendScanMessage()` in `outputs/static/app.js` (around line 3996) only handles `data.token`, `data.status`, `data.tool_call`, `data.task_id`, `data.error`, `data.capabilities`. Cortex events have a `data.type` discriminator and no `token`, so they hit the catch-all `try { ... } catch (e) { /* skip */ }` and disappear.

### Current State
Verified entry point: `outputs/static/app.js:3963` — `async function sendScanMessage(question)`.
Verified SSE loop: `outputs/static/app.js:4023-4079` — the `for (const line of lines)` block inside the `while (true)` reader loop.
Verified existing helpers: `appendScanBubble`, `md`, `esc`, `setSafeHTML` are all defined in this file. `bakerFetch` is also defined locally. **`document.createTextNode`** is the XSS-safe path for plain text in vanilla JS (lessons.md guidance).

### Implementation

**Step 1.** Inside `sendScanMessage()`, **immediately above** the existing `if (data.token) { ... }` block (around line 4053), insert the Cortex branch:

```javascript
                    // CORTEX_RUN_SCAN_UI_RENDER_1: handle typed events from
                    // /api/cortex/run stream proxied through /api/scan when
                    // intent='cortex_run_action'. Narrow `data.type` check to
                    // the four event types cortex_run_stream emits — avoids
                    // accidental capture if a future Scan response gains a
                    // `type` field.
                    if (data.type === 'started' || data.type === 'phase_changed'
                        || data.type === 'phase_output' || data.type === 'terminal') {
                        renderCortexEvent(data, replyEl, assistantId);
                        continue;
                    }
```

**Step 2.** Add the `renderCortexEvent` helper at module scope, **immediately above** `async function sendScanMessage(question) {` (around line 3962):

```javascript
// CORTEX_RUN_SCAN_UI_RENDER_1: Scan-driven Cortex cycles emit typed SSE
// events (started → phase_changed* → phase_output* → terminal). We render
// a phase ticker progressively, then on terminal call the proposal
// endpoint and render the synthesis text inline. Cycles that disconnect
// mid-stream still complete server-side (cortex_run_stream guarantees
// this); the user can refetch by cycle_id later.
function renderCortexEvent(data, replyEl, assistantId) {
    if (!replyEl) return;
    var t = data.type;

    // Lazy-init the Cortex container inside the assistant bubble — replace
    // the "Baker is thinking…" indicator on first event.
    var ctxEl = replyEl.querySelector('.cortex-stream');
    if (!ctxEl) {
        replyEl.textContent = '';
        ctxEl = document.createElement('div');
        ctxEl.className = 'cortex-stream';
        ctxEl.appendChild(_cortexHeader(data));
        ctxEl.appendChild(_cortexTicker());
        replyEl.appendChild(ctxEl);
    }

    if (t === 'started') {
        // Already rendered in lazy-init; nothing more to do.
        return;
    }

    if (t === 'phase_changed') {
        var ticker = ctxEl.querySelector('.cortex-ticker');
        if (ticker) {
            // Mark prior phase complete (if any), append new phase row.
            var phases = ticker.querySelectorAll('.cortex-phase');
            for (var i = 0; i < phases.length; i++) {
                phases[i].classList.add('cortex-phase-done');
            }
            var row = document.createElement('div');
            row.className = 'cortex-phase cortex-phase-active';
            var dot = document.createElement('span');
            dot.className = 'cortex-phase-dot';
            row.appendChild(dot);
            var label = document.createElement('span');
            label.className = 'cortex-phase-label';
            label.appendChild(document.createTextNode(_cortexPhaseLabel(data.phase)));
            row.appendChild(label);
            ticker.appendChild(row);
        }
        return;
    }

    if (t === 'phase_output') {
        // Increment count badge on the active phase row.
        var active = ctxEl.querySelector('.cortex-phase-active');
        if (active) {
            var badge = active.querySelector('.cortex-phase-count');
            if (!badge) {
                badge = document.createElement('span');
                badge.className = 'cortex-phase-count';
                active.appendChild(badge);
            }
            badge.textContent = '· ' + (data.count || 1);
        }
        return;
    }

    if (t === 'terminal') {
        var ticker2 = ctxEl.querySelector('.cortex-ticker');
        if (ticker2) {
            var phases2 = ticker2.querySelectorAll('.cortex-phase');
            for (var j = 0; j < phases2.length; j++) {
                phases2[j].classList.remove('cortex-phase-active');
                phases2[j].classList.add('cortex-phase-done');
            }
        }

        var card = document.createElement('div');
        card.className = 'cortex-terminal-card cortex-terminal-' + esc(data.status || 'unknown');

        var heading = document.createElement('div');
        heading.className = 'cortex-terminal-status';
        heading.appendChild(document.createTextNode(
            _cortexStatusLabel(data.status) +
            ' — $' + Number(data.cost_dollars || 0).toFixed(4) +
            ' / ' + Number(data.cost_tokens || 0).toLocaleString() + ' tokens'
        ));
        card.appendChild(heading);

        if (data.cycle_id) {
            var meta = document.createElement('div');
            meta.className = 'cortex-terminal-meta';
            meta.appendChild(document.createTextNode('cycle ' + data.cycle_id.slice(0, 8) + '…'));
            card.appendChild(meta);
        }

        if (data.aborted_reason) {
            var reason = document.createElement('div');
            reason.className = 'cortex-terminal-reason';
            reason.appendChild(document.createTextNode('Aborted: ' + data.aborted_reason));
            card.appendChild(reason);
        }

        var body = document.createElement('div');
        body.className = 'cortex-terminal-body';
        body.appendChild(document.createTextNode('Loading proposal…'));
        card.appendChild(body);

        ctxEl.appendChild(card);

        if (data.cycle_id && data.status !== 'failed' && data.status !== 'timeout') {
            _fetchCortexProposal(data.cycle_id, body);
        } else {
            body.textContent = '';
            body.appendChild(document.createTextNode(
                data.status === 'timeout' ? 'Cycle timed out — partial outputs may exist in /api/cortex/events.'
                : 'Cycle did not complete propose phase.'
            ));
        }
        return;
    }
}

function _cortexHeader(data) {
    var h = document.createElement('div');
    h.className = 'cortex-header';
    h.appendChild(document.createTextNode(
        'Cortex · ' + (data.matter_slug || 'unknown matter') + ' · ' + (data.triggered_by || 'manual')
    ));
    return h;
}

function _cortexTicker() {
    var el = document.createElement('div');
    el.className = 'cortex-ticker';
    return el;
}

function _cortexPhaseLabel(phase) {
    var labels = {
        sense: 'Sensing signals',
        load: 'Loading context',
        reason: 'Reasoning + specialists',
        propose: 'Drafting proposal',
        archive: 'Archiving cycle'
    };
    return labels[phase] || (phase || 'Unknown phase');
}

function _cortexStatusLabel(status) {
    var labels = {
        tier_b_pending: 'Proposal ready — awaiting Director ratification',
        completed: 'Cycle complete',
        rejected: 'Cycle rejected',
        failed: 'Cycle failed',
        timeout: 'Cycle timed out',
        archived: 'Archived'
    };
    return labels[status] || ('Status: ' + (status || 'unknown'));
}

async function _fetchCortexProposal(cycle_id, bodyEl) {
    try {
        var resp = await bakerFetch('/api/cortex/cycles/' + encodeURIComponent(cycle_id) + '/proposal');
        if (!resp.ok) {
            bodyEl.textContent = '';
            bodyEl.appendChild(document.createTextNode('Could not fetch proposal (HTTP ' + resp.status + ')'));
            return;
        }
        var d = await resp.json();
        bodyEl.textContent = '';
        if (d.has_proposal && d.proposal_text) {
            // SECURITY: md() calls esc() first — same path used elsewhere in this file.
            setSafeHTML(bodyEl, '<div class="md-content cortex-proposal">' + md(d.proposal_text) + '</div>');
        } else {
            bodyEl.appendChild(document.createTextNode(
                'No proposal text yet (current phase: ' + (d.current_phase || 'unknown') + ').'
            ));
        }
    } catch (e) {
        bodyEl.textContent = '';
        bodyEl.appendChild(document.createTextNode('Proposal fetch error: ' + e.message));
    }
}
```

### Key Constraints
- **Do NOT replace the `if (data.token) { ... }` branch.** Keep it — non-cortex Scan responses still use it.
- **`document.createTextNode` for any string interpolated from `data.*`** (lessons.md "phantom helper" + general XSS rule).
- **Reuse existing `bakerFetch`, `md`, `esc`, `setSafeHTML`, `appendScanBubble`** — verified present in this file. Do not duplicate.
- **`continue` after `renderCortexEvent`** so the typed event doesn't fall through to the token branch.
- **Helper functions added at module scope, ABOVE `sendScanMessage`** — JS hoisting handles function declarations, but module scope keeps them discoverable via grep.

### Verification

After deploy, in Chrome DevTools console on the dashboard:
```javascript
// 1. Manually fire a stream and watch the bubble.
sendScanMessage('run cortex on hagenauer-rg7 — give me a 1-line state of play');
// Expected: "Cortex · hagenauer-rg7 · scan_intent" header,
//           phases ticking sense → load → reason → propose,
//           terminal card showing "$X.XX / N,NNN tokens", cycle hash,
//           proposal text rendered as markdown.
```

---

## Fix/Feature 3: Mobile Scan SSE consumer renders Cortex events (`outputs/static/mobile.js`)

### Problem
Mobile path is `streamChat()` at `outputs/static/mobile.js:339`, called from `sendBaker()` at line 616. Same `data.token`-only blind spot.

### Current State
- Entry: `outputs/static/mobile.js:614` — `function sendBaker()`
- Stream loop: `outputs/static/mobile.js:386-419` — `for (var li = 0; ...)` block

### Implementation

Add the `renderCortexEventMobile` helper at module scope **above `function streamChat`** (around line 338):

```javascript
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
            // Append small dot per output landed.
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
```

Then inside `streamChat()` at line ~389, **above the existing `if (data.token)` check**, insert:

```javascript
                    if (data.type === 'started' || data.type === 'phase_changed'
                        || data.type === 'phase_output' || data.type === 'terminal') {
                        full = renderCortexEventMobile(data, replyEl, full);
                        continue;
                    }
```

### Key Constraints
- Mobile uses lighter markdown — `md()` and `setSafeHTML()` are present in `mobile.js` (verified at lines 339-419 — same helpers as `app.js` available in mobile bundle).
- Same `continue` discipline.
- Don't import jQuery or any libs.

### Verification

On a phone with the dashboard PWA installed:
1. Add `?v=N+1` to manifest cache buster.
2. Reload dashboard.
3. Type `run cortex on hagenauer-rg7 — quick smoke` in Ask Baker.
4. Expected: bubble shows "Cortex · hagenauer-rg7 · scan_intent" → "Reasoning…" → "Proposal ready" card with cost + cycle hash + proposal markdown.

---

## Fix/Feature 4: CSS for the new UI elements (`outputs/static/style.css`)

### Implementation

Append to `outputs/static/style.css`:

```css
/* CORTEX_RUN_SCAN_UI_RENDER_1: Scan-driven Cortex stream rendering */
.cortex-stream {
    border-left: 3px solid var(--accent, #6b8e9f);
    padding: 0.5rem 0.75rem;
    margin: 0.25rem 0;
    background: rgba(107, 142, 159, 0.05);
    border-radius: 0 4px 4px 0;
}
.cortex-header {
    font-size: 0.75rem;
    color: var(--muted, #888);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 0.5rem;
}
.cortex-ticker {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    margin-bottom: 0.5rem;
}
.cortex-phase {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.85rem;
    opacity: 0.6;
}
.cortex-phase-active { opacity: 1; font-weight: 500; }
.cortex-phase-done { opacity: 0.5; }
.cortex-phase-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--muted, #888);
    flex-shrink: 0;
}
.cortex-phase-active .cortex-phase-dot {
    background: var(--accent, #6b8e9f);
    animation: cortex-pulse 1.2s ease-in-out infinite;
}
.cortex-phase-done .cortex-phase-dot { background: var(--success, #6a9f6b); }
.cortex-phase-count {
    font-size: 0.75rem;
    color: var(--muted, #888);
    margin-left: 0.25rem;
}
@keyframes cortex-pulse {
    0%, 100% { opacity: 0.4; transform: scale(0.8); }
    50%      { opacity: 1.0; transform: scale(1.0); }
}
.cortex-terminal-card {
    border: 1px solid var(--accent, #6b8e9f);
    border-radius: 4px;
    padding: 0.5rem 0.75rem;
    margin-top: 0.5rem;
    background: var(--card-bg, #fafafa);
}
.cortex-terminal-tier_b_pending { border-color: var(--warning, #c98b3b); }
.cortex-terminal-failed,
.cortex-terminal-timeout       { border-color: var(--danger, #b04a4a); }
.cortex-terminal-rejected      { border-color: var(--muted, #888); }
.cortex-terminal-status {
    font-weight: 600;
    font-size: 0.9rem;
    margin-bottom: 0.25rem;
}
.cortex-terminal-meta,
.cortex-terminal-reason {
    font-size: 0.75rem;
    color: var(--muted, #888);
    margin-bottom: 0.25rem;
}
.cortex-terminal-body { margin-top: 0.5rem; }
.cortex-proposal { font-size: 0.9rem; line-height: 1.5; }

/* Mobile compact variants */
.cortex-stream-mobile {
    border-left: 2px solid var(--accent, #6b8e9f);
    padding: 0.4rem 0.6rem;
    margin: 0.2rem 0;
    background: rgba(107, 142, 159, 0.04);
    font-size: 0.85rem;
}
.cortex-header-mobile {
    font-size: 0.7rem;
    color: var(--muted, #888);
    margin-bottom: 0.3rem;
}
.cortex-progress-mobile {
    font-size: 0.85rem;
    color: var(--accent, #6b8e9f);
    margin-bottom: 0.3rem;
}
.cortex-terminal-mobile {
    border: 1px solid var(--accent, #6b8e9f);
    border-radius: 3px;
    padding: 0.4rem 0.6rem;
    margin-top: 0.3rem;
    font-size: 0.85rem;
}
.cortex-terminal-sub {
    font-size: 0.7rem;
    color: var(--muted, #888);
}
.cortex-terminal-body-mobile { margin-top: 0.3rem; }
```

### Key Constraints
- **Use existing CSS variables** (`--accent`, `--muted`, `--success`, `--warning`, `--danger`, `--card-bg`) — grep `outputs/static/style.css` to confirm names. If a variable is missing, add a fallback (already done above) and don't introduce new `:root` declarations.
- **Don't touch existing rules** — additive only.

---

## Fix/Feature 5: Cache bust in `index.html` and (if applicable) `mobile.html`

### Problem
iOS PWA aggressively caches `app.js`, `mobile.js`, `style.css`. Without bumping `?v=N`, Director will not see the new render path even after a successful deploy (lessons.md #4).

### Implementation

In `outputs/static/index.html`, find every reference to `app.js?v=` and `style.css?v=` — bump each `v=N` by exactly 1 (do not invent a new scheme).

Same in `outputs/static/mobile.html` for `mobile.js?v=` and `mobile.css?v=` if such references exist (grep first).

### Verification
```bash
grep -nE 'app\.js\?v=|style\.css\?v=|mobile\.js\?v=|mobile\.css\?v=' outputs/static/index.html outputs/static/mobile.html
# Confirm every match is N+1 vs main.
```

---

## Fix/Feature 6: Tests

### New file: `tests/test_cortex_proposal_endpoint.py`

```python
"""Tests for GET /api/cortex/cycles/{cycle_id}/proposal.

Mirrors the pattern in tests/test_cortex_run_endpoint.py — monkeypatches
SentinelStoreBack._get_global_instance to return a stub that returns
a predictable cursor result.
"""
import json
import uuid
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    from outputs import dashboard
    return TestClient(dashboard.app)


def _api_key_headers():
    import os
    return {"X-Baker-Key": os.environ.get("BAKER_API_KEY", "bakerbhavanga")}


class _StubCursor:
    def __init__(self, results):
        self._results = list(results)
        self._idx = 0

    def execute(self, sql, params=None):
        self._last_sql = sql

    def fetchone(self):
        if self._idx >= len(self._results):
            return None
        r = self._results[self._idx]
        self._idx += 1
        return r

    def close(self):
        pass


class _StubConn:
    def __init__(self, cursor_results):
        self._cursor_results = cursor_results

    def cursor(self, cursor_factory=None):
        return _StubCursor(self._cursor_results)

    def commit(self): pass
    def rollback(self): pass


class _StubStore:
    def __init__(self, cursor_results):
        self._cr = cursor_results
    def _get_conn(self): return _StubConn(self._cr)
    def _put_conn(self, conn): pass


def test_proposal_returns_200_with_synthesis(monkeypatch, client):
    cyc_id = str(uuid.uuid4())
    cycle_row = {
        "cycle_id": cyc_id,
        "matter_slug": "hagenauer-rg7",
        "triggered_by": "scan_intent",
        "status": "tier_b_pending",
        "current_phase": "propose",
        "cost_dollars": 1.46,
        "cost_tokens": 4922,
        "started_at": None,
        "completed_at": None,
        "aborted_reason": None,
    }
    syn_row = {
        "payload": {"proposal_text": "# State of Play\n\nTest proposal."},
        "created_at": None,
    }
    from outputs import dashboard
    monkeypatch.setattr(dashboard, "_get_store", lambda: _StubStore([cycle_row, syn_row]))

    resp = client.get(f"/api/cortex/cycles/{cyc_id}/proposal", headers=_api_key_headers())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["has_proposal"] is True
    assert body["proposal_text"].startswith("# State of Play")
    assert body["matter_slug"] == "hagenauer-rg7"
    assert body["status"] == "tier_b_pending"


def test_proposal_returns_404_when_cycle_missing(monkeypatch, client):
    from outputs import dashboard
    monkeypatch.setattr(dashboard, "_get_store", lambda: _StubStore([None]))
    cyc_id = str(uuid.uuid4())
    resp = client.get(f"/api/cortex/cycles/{cyc_id}/proposal", headers=_api_key_headers())
    assert resp.status_code == 404


def test_proposal_returns_400_for_invalid_uuid(client):
    resp = client.get("/api/cortex/cycles/not-a-uuid/proposal", headers=_api_key_headers())
    assert resp.status_code == 400


def test_proposal_returns_has_proposal_false_when_no_synthesis(monkeypatch, client):
    cyc_id = str(uuid.uuid4())
    cycle_row = {
        "cycle_id": cyc_id, "matter_slug": "movie", "triggered_by": "signal",
        "status": "running", "current_phase": "load",
        "cost_dollars": 0.0, "cost_tokens": 0,
        "started_at": None, "completed_at": None, "aborted_reason": None,
    }
    from outputs import dashboard
    monkeypatch.setattr(dashboard, "_get_store", lambda: _StubStore([cycle_row, None]))
    resp = client.get(f"/api/cortex/cycles/{cyc_id}/proposal", headers=_api_key_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_proposal"] is False
    assert body["proposal_text"] is None
```

### Extend `tests/test_scan_cortex_intent.py`

Add a test asserting the cortex_run_action branch produces typed events (verifying our new front-end will receive them):

```python
def test_scan_cortex_intent_yields_typed_events(monkeypatch, client):
    """Smoke: when intent='cortex_run_action' fires, the SSE response
    contains at least one `data: {"type": ...}` line — confirming the
    event shape that CORTEX_RUN_SCAN_UI_RENDER_1 frontend depends on.
    """
    # Mirror existing fixture pattern in this file. Stub
    # cortex_run_stream.stream_cycle_events to yield a deterministic
    # sequence: started → terminal.
    async def fake_stream(*, matter_slug, director_question, triggered_by):
        import json as _j
        yield f"data: {_j.dumps({'type':'started','matter_slug':matter_slug,'triggered_by':triggered_by,'ts':0})}\n\n"
        yield f"data: {_j.dumps({'type':'terminal','status':'tier_b_pending','cycle_id':'00000000-0000-0000-0000-000000000001','current_phase':'propose','cost_dollars':0.05,'cost_tokens':100,'ts':0})}\n\n"

    from outputs import cortex_run_stream
    monkeypatch.setattr(cortex_run_stream, "stream_cycle_events", fake_stream)
    # ...rest follows existing test pattern
```

### Ship gate

```
pytest tests/test_cortex_proposal_endpoint.py tests/test_scan_cortex_intent.py tests/test_cortex_run_endpoint.py tests/test_cortex_run_stream.py -v
```

Must produce literal green output — no "pass by inspection." Paste the literal pytest tail in the ship report.

---

## Files Modified
- `outputs/dashboard.py` — add `GET /api/cortex/cycles/{cycle_id}/proposal` endpoint after `get_cortex_events` (~line 4002)
- `outputs/static/app.js` — add `renderCortexEvent` + helpers + branch in `sendScanMessage`
- `outputs/static/mobile.js` — add `renderCortexEventMobile` + helpers + branch in `streamChat`
- `outputs/static/style.css` — append Cortex UI styles
- `outputs/static/index.html` — bump cache busters
- `outputs/static/mobile.html` — bump cache busters (if file exists; grep first)
- `tests/test_cortex_proposal_endpoint.py` — new
- `tests/test_scan_cortex_intent.py` — extend with typed-event passthrough test

## Do NOT Touch
- `outputs/cortex_run_stream.py` — backend SSE source-of-truth, works correctly
- `orchestrator/action_handler.py` — intent classifier, works correctly
- `outputs/dashboard.py:7854-7886` — Scan branch routing, works correctly
- `outputs/dashboard.py:7611-7644` (`_action_stream_response`) — token-only helper, intentional
- Any `cortex_phase_outputs` schema — read-only path
- `triggers/cortex_pre_review_gate.py` — config-presence check, separate concern
- Any other `/api/cortex/*` endpoint

## Quality Checkpoints

1. `curl -H 'X-Baker-Key: bakerbhavanga' https://baker-master.onrender.com/api/cortex/cycles/18a18ec5-ea69-4e44-97c9-4308488b8aba/proposal` returns the Hagenauer state-of-play markdown
2. `curl ... /not-a-uuid/proposal` returns HTTP 400; `/00000000-...0/proposal` returns HTTP 404
3. Director runs `run cortex on hagenauer-rg7 — give me a 1-line state of play` in Scan (desktop). UI shows: header → phase ticker animating sense→load→reason→propose with output count badges → terminal card "Proposal ready — awaiting Director ratification — $1.46 / 4,922 tokens · cycle 18a18ec5…" → proposal markdown rendered inline within ~3s of terminal event
4. Director runs same on iPhone PWA. UI shows compact mobile variant with same data
5. iOS PWA: hard reload after deploy shows new behavior (cache-bust verified)
6. Existing non-cortex Scan questions (e.g. "what's our position on AO?") still render via the `data.token` path — no regression
7. `pytest tests/test_cortex_proposal_endpoint.py tests/test_scan_cortex_intent.py tests/test_cortex_run_endpoint.py tests/test_cortex_run_stream.py` is literal green
8. CSP / XSS: every `data.*` interpolation goes through `document.createTextNode()` or `esc()`; `proposal_text` goes through `md()` → `setSafeHTML()` (same path as existing token rendering — already XSS-safe)
9. JS console clean: no `Uncaught ReferenceError` for `_serialize_dt`, `bakerFetch`, `setSafeHTML`, `md`, `esc`, or any helper added in this brief
10. Render deploy lands without import errors (pre-flight `python -c "from outputs.dashboard import app"` clean)

## Verification SQL

```sql
-- Confirm the cycle the smoke fired against has a synthesis row:
SELECT cycle_id, phase, artifact_type, LEFT(payload->>'proposal_text', 60) AS proposal_head
FROM cortex_phase_outputs
WHERE cycle_id = '18a18ec5-ea69-4e44-97c9-4308488b8aba'
  AND artifact_type = 'synthesis'
LIMIT 1;
-- Expected: phase='reason', artifact_type='synthesis', proposal_head='# Hagenauer RG7 — State of Play...'

-- Confirm cycle metadata:
SELECT cycle_id, matter_slug, status, cost_dollars, cost_tokens
FROM cortex_cycles
WHERE cycle_id = '18a18ec5-ea69-4e44-97c9-4308488b8aba'
LIMIT 1;
-- Expected: matter_slug='hagenauer-rg7', status='tier_b_pending', cost_dollars≈1.46, cost_tokens=4922
```

---

## API version / deprecation / fallback notes (Code Brief Standards 1-3)

- **API version:** internal endpoints only. No external API touched. FastAPI version per `requirements.txt`. `psycopg2.extras.RealDictCursor` pattern matches existing `get_cortex_events`.
- **Deprecation check:** N/A — internal Baker endpoints.
- **Fallback:** if `cortex_phase_outputs.payload` schema changes (it currently stores `proposal_text` at top level for `artifact_type='synthesis'` rows), the endpoint returns `has_proposal: false` instead of crashing. Frontend handles the false case explicitly.

## Migration-vs-bootstrap DDL check (Code Brief Standards #4)
- **No DDL.** Brief is read-only on `cortex_phase_outputs` and `cortex_cycles`. No `ADD COLUMN`, no migration. `store_back.py` grep not required (rule #4 conditional on column adds).

## Singleton pattern check (Code Brief Standards #8)
- Endpoint uses `store = _get_store()` (canonical accessor). No `SentinelStoreBack(...)` constructor calls. Pre-push singleton hook `scripts/check_singletons.sh` passes.

## File:line citation verification (Code Brief Standards #7)
- `outputs/dashboard.py:7854` — verified (cortex_run_action branch)
- `outputs/dashboard.py:3952` — verified (`get_cortex_events` start, anchor for new endpoint placement)
- `outputs/dashboard.py:4001` — verified (end of `get_cortex_events`)
- `outputs/static/app.js:3963` — verified (`async function sendScanMessage`)
- `outputs/static/app.js:4023-4079` — verified (SSE reader loop)
- `outputs/static/mobile.js:339` — verified (`async function streamChat`)
- `outputs/static/mobile.js:614` — verified (`function sendBaker`)
- `outputs/cortex_run_stream.py:230-349` — verified (SSE event types: started/phase_changed/phase_output/terminal)
