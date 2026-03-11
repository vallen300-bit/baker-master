# BRIEF: DEEP-MODE-1 — Dashboard = Maximum Intelligence by Default

**Author:** AI Head (Session 20, revised per Director input)
**For:** Code 300
**Priority:** HIGHEST — this IS the Baker dashboard endgame
**Estimated scope:** 3 files, ~200 lines new code

---

## Vision

The Baker dashboard is where the Director sits and thinks. It's not a quick-reply tool — it's a strategic cockpit. Every question asked from the dashboard deserves the maximum intelligence Baker can deliver. Cost is not a constraint — the cost of NOT having this capability is orders of magnitude higher than API costs.

The dashboard has advantages raw Claude doesn't: proactive alerts with "Do it" buttons, visual KPIs, matter tracking, multi-channel actions. The missing piece is matching Claude's thinking quality. This brief closes that gap.

**Old path:** question → intent classifier → score trigger → capability router → prompt builder → Claude (30s, 3-5 tool calls, ~20K context)

**New path:** question → action check only → maximum context + all tools → Claude (90s, 15 tool calls, 100K+ context)

The routing layers (intent classifier, score trigger, capability router) are removed from the dashboard chat path. They were built for background triggers and WhatsApp quick replies where speed matters. At the dashboard, quality is all that matters.

## Architecture

### What changes:
- **Dashboard Ask Baker**: always uses the deep path (no toggle, no opt-in — it's the default)
- **Dashboard Ask Specialist**: keeps capability routing (specialist selection is explicit)
- **WhatsApp**: keeps current agentic path with 30s timeout (speed matters for mobile)
- **Background triggers**: unchanged

### The deep path does:
1. Check for actions first (email send, WA send, ClickUp) — these still route normally
2. Pre-stuff 100K+ tokens of relevant context into the system prompt
3. Give Claude ALL 12 tools + extended thinking
4. 90-second timeout, 15 iterations maximum
5. Full session history (every turn, no cap)
6. Claude decides what to search, how deep to go

## Implementation

### File 1: `outputs/dashboard.py`

#### 1A. Replace the routing block in `scan_chat()`:

Find the current routing logic (after action routing, ~line 3310). Replace everything from "Try implicit capability routing" through the end of the tier/mode routing with:

```python
    # DEEP-MODE-1: Dashboard always gets maximum intelligence.
    # Action routing (email/WA/ClickUp) already handled above.
    # Everything else goes through the deep path — no capability routing,
    # no tier/mode routing. Maximum context + tools + time.
    return _scan_chat_deep(req, start, task_id=_task_id,
                           domain=_domain, mode=_mode)
```

DELETE the capability routing try/except block AND the tier/mode routing block. They're replaced by the single deep path call.

**IMPORTANT:** Keep all the action routing ABOVE this (email_action, whatsapp_action, deadline_action, vip_action/contact_action, fireflies_fetch, clickup_action/fetch/plan). Those still need their dedicated handlers. Only the "question" fallback changes.

#### 1B. New function `_scan_chat_deep()`:

```python
def _scan_chat_deep(req: ScanRequest, start: float, task_id: int = None,
                    domain: str = "projects", mode: str = "handle"):
    """
    DEEP-MODE-1: Maximum intelligence path for dashboard.
    Pre-stuffs context, extended timeout, full tools, no routing overhead.
    """
    from orchestrator.scan_prompt import (
        SCAN_SYSTEM_PROMPT, build_mode_aware_prompt, build_entity_context,
    )
    from orchestrator.agent import run_agent_loop_streaming
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # --- 1. Pre-fetch context (what the agent would search for in its first 3-4 calls) ---
    pre_parts = []
    retriever = _get_retriever()

    # Entity context (people + matters mentioned)
    try:
        entity_ctx = build_entity_context(req.question, req.history, req.project)
        if entity_ctx:
            pre_parts.append(entity_ctx)
    except Exception:
        pass

    # Relevant emails
    try:
        emails = retriever.get_email_messages(req.question, limit=5)
        recent_emails = retriever.get_recent_emails(limit=3)
        all_emails = emails + [e for e in recent_emails
                               if e.metadata.get("message_id") not in
                               {x.metadata.get("message_id") for x in emails}]
        if all_emails:
            lines = [f"[EMAIL] {e.metadata.get('label', '')} ({e.metadata.get('date', '')}): "
                     f"{e.content[:2000]}" for e in all_emails[:8]]
            pre_parts.append("## PRE-FETCHED EMAILS\n" + "\n\n".join(lines))
    except Exception:
        pass

    # Relevant WhatsApp messages
    try:
        wa = retriever.get_whatsapp_messages(req.question, limit=5)
        recent_wa = retriever.get_recent_whatsapp(limit=3)
        all_wa = wa + [w for w in recent_wa
                       if w.metadata.get("msg_id") not in
                       {x.metadata.get("msg_id") for x in wa}]
        if all_wa:
            lines = [f"[WHATSAPP] {w.metadata.get('label', '')} ({w.metadata.get('date', '')}): "
                     f"{w.content[:1000]}" for w in all_wa[:8]]
            pre_parts.append("## PRE-FETCHED WHATSAPP\n" + "\n\n".join(lines))
    except Exception:
        pass

    # Relevant meeting transcripts
    try:
        meetings = retriever.get_meeting_transcripts(req.question, limit=3)
        recent_meetings = retriever.get_recent_meeting_transcripts(limit=2)
        all_meetings = meetings + [m for m in recent_meetings
                                   if m.metadata.get("meeting_id") not in
                                   {x.metadata.get("meeting_id") for x in meetings}]
        if all_meetings:
            lines = [f"[MEETING] {m.metadata.get('label', '')} ({m.metadata.get('date', '')}): "
                     f"{m.content[:4000]}" for m in all_meetings[:5]]
            pre_parts.append("## PRE-FETCHED MEETINGS\n" + "\n\n".join(lines))
    except Exception:
        pass

    # Recent decisions
    try:
        decisions = retriever.get_recent_decisions(limit=5)
        if decisions:
            pre_parts.append("## RECENT BAKER DECISIONS\n" +
                           "\n".join(d.content[:500] for d in decisions[:5]))
    except Exception:
        pass

    # Past deep analyses
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if conn:
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute("""
                    SELECT topic, analysis_text FROM deep_analyses
                    WHERE created_at > NOW() - INTERVAL '30 days'
                    ORDER BY created_at DESC LIMIT 3
                """)
                analyses = cur.fetchall()
                if analyses:
                    lines = [f"### {a['topic']}\n{(a['analysis_text'] or '')[:2000]}"
                             for a in analyses]
                    pre_parts.append("## RECENT BAKER ANALYSES\n" + "\n\n".join(lines))
                cur.close()
            finally:
                store._put_conn(conn)
    except Exception:
        pass

    # Deadlines
    try:
        from models.deadlines import get_active_deadlines
        deadlines = get_active_deadlines(limit=20)
        if deadlines:
            dl_lines = [f"- [{dl.get('priority','normal').upper()}] "
                       f"{dl.get('due_date').strftime('%Y-%m-%d') if dl.get('due_date') else 'TBD'}: "
                       f"{dl.get('description','')}"
                       for dl in deadlines]
            pre_parts.append("## ACTIVE DEADLINES\n" + "\n".join(dl_lines))
    except Exception:
        pass

    pre_context = "\n\n".join(pre_parts)

    # --- 2. Build system prompt ---
    base_prompt = (
        f"{SCAN_SYSTEM_PROMPT}\n\n"
        f"## CURRENT TIME\n{now}\n\n"
        f"## INSTRUCTIONS\n"
        f"The Director is at the dashboard. Give thorough, detailed analysis. "
        f"Use multiple tools to cross-reference. Cite specific sources "
        f"(emails, meetings, WhatsApp messages, documents). "
        f"If information is incomplete, say so explicitly.\n\n"
        f"{pre_context}\n"
    )
    system_prompt = build_mode_aware_prompt(base_prompt, domain, mode,
                                             question=req.question,
                                             history=req.history,
                                             project=req.project)

    # --- 3. Full session history (no cap) ---
    history = []
    for msg in (req.history or []):
        role = msg.get("role", "user") if isinstance(msg, dict) else "user"
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
        if role in ("user", "assistant") and content:
            history.append({"role": role, "content": content})

    # --- 4. Stream with extended timeout ---
    async def event_stream():
        import queue as _queue
        import asyncio

        q = _queue.Queue()
        full_response = ""
        agent_result = None

        def _run_agent():
            try:
                gen = run_agent_loop_streaming(
                    question=req.question,
                    system_prompt=system_prompt,
                    history=history,
                    max_iterations=15,
                    timeout_override=90.0,
                )
                for item in gen:
                    q.put_nowait(item)
            except Exception as e:
                logger.error(f"Deep path agent error: {e}")
                q.put_nowait({"error": str(e)})
            finally:
                q.put_nowait(None)

        import threading
        agent_thread = asyncio.get_event_loop().run_in_executor(None, _run_agent)

        while True:
            try:
                item = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, lambda: q.get(timeout=8)),
                    timeout=10.0,
                )
            except (asyncio.TimeoutError, Exception):
                yield ": keepalive\n\n"
                continue

            if item is None:
                break

            if "_agent_result" in item:
                agent_result = item["_agent_result"]
            elif "token" in item:
                full_response += item["token"]
                yield f"data: {json.dumps({'token': item['token']})}\n\n"
            elif "tool_call" in item:
                yield f"data: {json.dumps({'tool_call': item['tool_call']})}\n\n"
            elif "error" in item:
                yield f"data: {json.dumps({'error': item['error']})}\n\n"

        await agent_thread

        if task_id:
            yield f"data: {json.dumps({'task_id': task_id})}\n\n"
        yield "data: [DONE]\n\n"

        extra = {}
        if agent_result:
            extra = {
                "agent_iterations": agent_result.iterations,
                "agent_tool_calls": len(agent_result.tool_calls),
                "agent_input_tokens": agent_result.total_input_tokens,
                "agent_output_tokens": agent_result.total_output_tokens,
                "agent_elapsed_ms": agent_result.elapsed_ms,
            }
        _scan_store_back(req, full_response, start, extra, task_id=task_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
```

### File 2: `outputs/static/app.js`

#### 2A. Send full history (no 25-turn cap):

In `sendScanMessage()`, change:
```javascript
// FROM:
history: getScanHistory().slice(-25),
// TO:
history: getScanHistory(),
```

And remove the history cap that trims to 50:
```javascript
// FROM:
if (getScanHistory().length > 50) _scanHistories[_scanCurrentContext] = getScanHistory().slice(-50);
// TO:
// No cap — full session history preserved
```

#### 2B. Extend SSE timeout:

The `sendScanMessage` fetch already has 180s timeout — that's fine for 90s agent loops.

No other JS changes needed. The artifact panel already shows tool_call events and capabilities. The deep path streams the same SSE format.

### File 3: `outputs/static/style.css`

No CSS changes needed — no toggle button.

### File 4: `orchestrator/agent.py`

No changes needed — `run_agent_loop_streaming()` already accepts `max_iterations` and `timeout_override`.

## What Changes for the Director

| Before | After |
|--------|-------|
| Simple questions: ~5s, single-pass | Simple questions: ~10-15s, agent with tools (still fast — agent exits early if 1 tool call suffices) |
| Complex questions: ~30s, 3-5 tool calls, ~20K context | Complex questions: ~30-90s, up to 15 tool calls, 100K+ context |
| Routing misfires lose the question | No routing to misfire — question goes straight to Claude |
| Capability match required for tools | Tools always available |
| 25-turn memory | Full session memory |

## What Does NOT Change

- Ask Specialist: keeps capability routing (specialist picker is explicit intent)
- WhatsApp: keeps 30s agentic path (speed matters for mobile)
- Background triggers: unchanged
- Action routing: email/WA/ClickUp actions still handled by dedicated handlers
- Morning briefing, alerts, fires: unchanged

## Testing

1. Syntax check dashboard.py, app.js
2. Ask a simple question ("what time is it?") — should still be fast (agent exits after 0 tool calls)
3. Ask a complex question ("what's the full status of the Hagenauer dispute?") — should be thorough with multiple sources cited, 30-60s
4. Ask "send email to X" — should still route to email handler (action routing preserved)
5. Check artifact panel shows tool calls during deep analysis
