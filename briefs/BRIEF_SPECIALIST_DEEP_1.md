# BRIEF: SPECIALIST-DEEP-1 — Upgrade Ask Specialist to Deep Path Quality

**Author:** AI Head (Session 20)
**For:** Code 300
**Priority:** HIGH — Ask Specialist is the Director's focused analysis tool
**Estimated scope:** 1 file (dashboard.py), ~60 lines
**Cost:** Negligible — same pre-fetch as deep path

---

## Problem

DEEP-MODE-1 upgraded Ask Baker to pre-stuff 100K+ tokens of context. But Ask Specialist still uses the old `_scan_chat_capability()` path with:
- No pre-stuffed emails, WhatsApp, meetings, decisions, analyses
- No cross-session memory
- No entity context (RICHER-CONTEXT-1 was wired into capability_runner but NOT pre-fetched data)

When the Director opens Legal specialist and asks about Hagenauer, the specialist has to discover everything through tool calls. The deep path pre-fetches the most relevant data so the specialist starts with context.

## Solution

Upgrade `/api/scan/specialist` to pre-fetch context like the deep path, then pass it to the capability runner as `entity_context`. The capability runner already accepts this parameter (RICHER-CONTEXT-1 added it).

## Implementation

### File: `outputs/dashboard.py`

Replace the current `scan_specialist()` endpoint (~line 2206):

```python
@app.post("/api/scan/specialist", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def scan_specialist(req: SpecialistScanRequest):
    """
    Force-route a question to a specific capability with deep context.
    Pre-stuffs relevant data (emails, WA, meetings, decisions, cross-session memory)
    so the specialist starts with maximum context.
    """
    start = time.time()
    from orchestrator.capability_registry import CapabilityRegistry
    from orchestrator.capability_router import RoutingPlan
    from orchestrator.scan_prompt import build_entity_context

    registry = CapabilityRegistry.get_instance()
    cap = registry.get_by_slug(req.capability_slug)
    if not cap or not cap.active:
        raise HTTPException(status_code=404, detail=f"Capability '{req.capability_slug}' not found or inactive")

    # --- Pre-fetch context (same pattern as _scan_chat_deep) ---
    pre_parts = []
    retriever = _get_retriever()

    # Entity context (people + matters)
    try:
        entity_ctx = build_entity_context(req.question, req.history)
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
                     f"{e.content[:2000]}" for e in all_emails[:6]]
            pre_parts.append("## PRE-FETCHED EMAILS\n" + "\n\n".join(lines))
    except Exception:
        pass

    # Relevant WhatsApp
    try:
        wa = retriever.get_whatsapp_messages(req.question, limit=5)
        if wa:
            lines = [f"[WHATSAPP] {w.metadata.get('label', '')} ({w.metadata.get('date', '')}): "
                     f"{w.content[:1000]}" for w in wa[:6]]
            pre_parts.append("## PRE-FETCHED WHATSAPP\n" + "\n\n".join(lines))
    except Exception:
        pass

    # Relevant meetings
    try:
        meetings = retriever.get_meeting_transcripts(req.question, limit=3)
        if meetings:
            lines = [f"[MEETING] {m.metadata.get('label', '')} ({m.metadata.get('date', '')}): "
                     f"{m.content[:3000]}" for m in meetings[:3]]
            pre_parts.append("## PRE-FETCHED MEETINGS\n" + "\n\n".join(lines))
    except Exception:
        pass

    # Cross-session memory
    try:
        store = _get_store()
        relevant_convos = store.get_relevant_conversations(req.question, limit=5, exclude_hours=1)
        if relevant_convos:
            lines = []
            for c in relevant_convos:
                date_str = c['created_at'].strftime('%Y-%m-%d %H:%M') if c.get('created_at') else ''
                q = (c.get('question') or '')[:200]
                a = (c.get('answer') or '')[:800]
                lines.append(f"[{date_str}] Director: {q}\nBaker: {a}")
            pre_parts.append("## PRIOR CONVERSATIONS ON THIS TOPIC\n" + "\n---\n".join(lines))
    except Exception:
        pass

    entity_context = "\n\n".join(pre_parts)

    # --- Route through capability with pre-fetched context ---
    plan = RoutingPlan(mode="fast", capabilities=[cap])
    scan_req = ScanRequest(question=req.question, history=req.history)

    # Pass entity_context to _scan_chat_capability
    return _scan_chat_capability(scan_req, start, {"plan": plan},
                                  entity_context=entity_context)
```

Then update `_scan_chat_capability()` to accept and forward `entity_context`:

In the function signature (~line 3684):
```python
def _scan_chat_capability(req, start: float, intent_or_plan: dict = None,
                          task_id: int = None, domain: str = None, mode: str = None,
                          entity_context: str = ""):
```

And pass it to the runner calls. In the fast path (~line 3730 area):
```python
runner.run_streaming(cap, req.question, history=req.history,
                     domain=domain, mode=mode, entity_context=entity_context)
```

And in the delegate path (~line 3810 area):
```python
runner.run_multi(plan, req.question, history=req.history,
                 domain=domain, mode=mode, entity_context=entity_context)
```

## Also: Increase specialist timeout

The capability_sets DB has `timeout_seconds: 90` already. But the frontend `sendSpecialistMessage()` in app.js has `timeout: 180000` (3 min) which is fine. No changes needed.

## What This Gets Us

| Before | After |
|--------|-------|
| Specialist starts cold — has to search with tools | Specialist starts with relevant emails, WA, meetings, prior conversations |
| No cross-session memory | Prior Baker conversations on same topic available |
| ~5 tool calls to gather context | Context pre-loaded, tools used for deeper analysis |

## Testing

1. Syntax check dashboard.py
2. Open Ask Specialist → Legal → ask about Hagenauer → verify pre-fetched emails/WA appear in the artifact panel sources
3. Verify normal Ask Baker deep path still works (no regression)
