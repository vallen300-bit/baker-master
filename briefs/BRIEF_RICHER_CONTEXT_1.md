# BRIEF: RICHER-CONTEXT-1 — Expand Baker's Context Window

**Author:** AI Head (Session 20)
**For:** Code 300 (fresh instance)
**Priority:** HIGH — single biggest intelligence improvement
**Estimated scope:** 4 files, ~150 lines added/changed

---

## Problem

Baker uses Claude Opus 4.6 (1M context) but sends it a tiny context window:
- Only 10 conversation turns (Baker forgets what was discussed 5 messages ago)
- No information about the PEOPLE mentioned in the question
- No information about the MATTER/PROJECT being discussed
- No recent decisions or analyses about the same topic

This makes Baker seem "dumb" even though the model is capable — it just doesn't have the context.

## Solution — 3 changes

### Change 1: Increase conversation turns (10 → 25)

**Frontend — `outputs/static/app.js`:**

Line 1745 (inside `sendScanMessage`):
```javascript
// CHANGE FROM:
history: getScanHistory().slice(-10),
// CHANGE TO:
history: getScanHistory().slice(-25),
```

Line ~1824 (history cap in same function):
```javascript
// CHANGE FROM:
if (getScanHistory().length > 20) _scanHistories[_scanCurrentContext] = getScanHistory().slice(-20);
// CHANGE TO:
if (getScanHistory().length > 50) _scanHistories[_scanCurrentContext] = getScanHistory().slice(-50);
```

(Specialist already sends 30 — leave it.)

**Backend — `outputs/dashboard.py`:**

Three locations — all change `[-10:]` to `[-25:]`:
1. Line ~3661 in `_scan_chat_agentic()`: `for msg in (req.history or [])[-25:]:`
2. Line ~3829 in `_scan_chat_legacy_stream()`: `for msg in (req.history or [])[-25:]:`
3. Line ~3927 in `_scan_chat_legacy()`: `for msg in (req.history or [])[-25:]:`

### Change 2: Auto-inject contact profiles of mentioned people

Create a new helper function in `orchestrator/scan_prompt.py`:

```python
def build_entity_context(question: str, history: list = None, project: str = None) -> str:
    """
    Extract people and matters mentioned in the question + recent history.
    Query DB for their profiles. Return a context block to inject into system prompt.

    Returns empty string if no entities found (no-op — safe to always call).
    """
    import re

    # 1. Collect text to scan for names
    text_pool = question
    for msg in (history or [])[-5:]:  # only scan last 5 turns for names
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
        text_pool += " " + content

    # 2. Query contacts table for any names that appear in the text
    contacts_context = ""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return ""
        try:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # Fetch all contacts with meaningful profiles
            cur.execute("""
                SELECT name, role, email, whatsapp_id, domain, tier,
                       role_context, expertise, communication_pref
                FROM vip_contacts
                WHERE name IS NOT NULL AND name != ''
            """)
            all_contacts = cur.fetchall()

            # Match: check if any contact name appears in the text pool
            text_lower = text_pool.lower()
            matched = []
            for c in all_contacts:
                cname = (c.get("name") or "").strip()
                if not cname:
                    continue
                # Full name match (case-insensitive)
                if cname.lower() in text_lower:
                    matched.append(c)
                    continue
                # Last name match (for 2+ word names)
                parts = cname.split()
                if len(parts) >= 2 and parts[-1].lower() in text_lower.split():
                    matched.append(c)

            if matched:
                lines = ["## PEOPLE MENTIONED IN THIS CONVERSATION"]
                for c in matched[:5]:  # cap at 5 profiles
                    name = c.get("name", "")
                    parts_list = []
                    if c.get("role"):
                        parts_list.append(f"Role: {c['role']}")
                    if c.get("role_context"):
                        parts_list.append(f"Context: {c['role_context']}")
                    if c.get("expertise"):
                        parts_list.append(f"Expertise: {c['expertise']}")
                    if c.get("domain"):
                        parts_list.append(f"Domain: {c['domain']}")
                    if c.get("email"):
                        parts_list.append(f"Email: {c['email']}")
                    if c.get("communication_pref"):
                        parts_list.append(f"Preferred contact: {c['communication_pref']}")
                    detail = "; ".join(parts_list) if parts_list else "No profile details"
                    lines.append(f"- **{name}**: {detail}")
                contacts_context = "\n".join(lines)

            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        import logging
        logging.getLogger("sentinel.scan_prompt").debug(f"Entity context: contacts lookup failed: {e}")

    # 3. Query matter registry if project is specified or matter name appears in text
    matter_context = ""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return contacts_context
        try:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            if project:
                # Direct match — scan is scoped to a matter
                cur.execute(
                    "SELECT * FROM matter_registry WHERE LOWER(matter_name) = LOWER(%s) AND status = 'active'",
                    (project,)
                )
            else:
                # Check all active matters against text
                cur.execute("SELECT * FROM matter_registry WHERE status = 'active'")

            matters = cur.fetchall()
            matched_matters = []

            for m in matters:
                if project and m.get("matter_name", "").lower() == project.lower():
                    matched_matters.append(m)
                    continue
                # Check if matter name or keywords appear in text
                mname = (m.get("matter_name") or "").lower()
                if mname and mname in text_lower:
                    matched_matters.append(m)
                    continue
                keywords = m.get("keywords") or []
                if isinstance(keywords, str):
                    import json as _json
                    try:
                        keywords = _json.loads(keywords)
                    except Exception:
                        keywords = [keywords]
                for kw in keywords:
                    if kw.lower() in text_lower:
                        matched_matters.append(m)
                        break

            if matched_matters:
                lines = ["## ACTIVE MATTERS RELATED TO THIS QUESTION"]
                for m in matched_matters[:3]:  # cap at 3 matters
                    name = m.get("matter_name", "")
                    desc = m.get("description", "")
                    people = m.get("people") or []
                    if isinstance(people, str):
                        import json as _json
                        try:
                            people = _json.loads(people)
                        except Exception:
                            people = [people]
                    people_str = ", ".join(people) if people else ""
                    lines.append(f"- **{name}**: {desc}")
                    if people_str:
                        lines.append(f"  Key people: {people_str}")
                matter_context = "\n".join(lines)

            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        import logging
        logging.getLogger("sentinel.scan_prompt").debug(f"Entity context: matter lookup failed: {e}")

    # 4. Combine
    parts = [p for p in [contacts_context, matter_context] if p]
    return "\n\n".join(parts)
```

### Change 3: Inject entity context into all scan paths

The entity context must be injected into the system prompt for ALL three scan paths + capability runner. The cleanest approach: add it to `build_mode_aware_prompt()`.

**`orchestrator/scan_prompt.py` — modify `build_mode_aware_prompt()`:**

Add new parameters `question` and `history` and `project`:

```python
def build_mode_aware_prompt(base_prompt: str, domain: str = None,
                            mode: str = None, question: str = None,
                            history: list = None, project: str = None) -> str:
    """..."""
    parts = [base_prompt]

    # Domain context (existing)
    ...existing code...

    # Strategic priorities (existing)
    ...existing code...

    # Communication style (existing)
    ...existing code...

    # NEW: Entity context — people + matters mentioned in conversation
    if question:
        entity_ctx = build_entity_context(question, history, project)
        if entity_ctx:
            parts.append(entity_ctx)

    # Mode extension (existing)
    if mode and mode in MODE_PROMPT_EXTENSIONS:
        parts.append(MODE_PROMPT_EXTENSIONS[mode])

    return "\n\n".join(parts)
```

**Then update all callers to pass question/history/project:**

1. `outputs/dashboard.py` — `_scan_chat_agentic()` (~line 3648):
```python
system_prompt = build_mode_aware_prompt(base_prompt, domain, mode,
                                         question=req.question, history=req.history,
                                         project=req.project)
```

2. `outputs/dashboard.py` — `_scan_chat_legacy_stream()` (~line 3826):
```python
system_prompt = build_mode_aware_prompt(base_prompt, domain, mode,
                                         question=req.question, history=req.history,
                                         project=req.project)
```

3. `outputs/dashboard.py` — `_scan_chat_legacy()` (~line 3923):
```python
system_prompt = build_mode_aware_prompt(base_prompt, domain, mode,
                                         question=req.question, history=req.history,
                                         project=req.project)
```

4. `orchestrator/capability_runner.py` — `_build_system_prompt()` (~line 516):
This one doesn't have access to question/history at the prompt-build stage (they're passed separately to messages). **Skip this for now** — the entity context will be in the scan prompt for capabilities that use it (line 503: `enriched = base + role_injection` where base = `SCAN_SYSTEM_PROMPT` which gets entity context via the dashboard callers).

WAIT — actually the capability runner builds its OWN system prompt from `SCAN_SYSTEM_PROMPT` directly. It doesn't go through the dashboard's `build_mode_aware_prompt()` with the question/history params. So we need to pass entity context to the capability runner too.

**Fix: Add entity_context parameter to capability runner:**

In `orchestrator/capability_runner.py`, modify `run_single()` and `run_streaming()` to accept `entity_context: str = ""`:

```python
def run_single(self, capability, question, history=None, domain=None, mode=None, entity_context=""):
    ...
    system = self._build_system_prompt(capability, domain, mode, entity_context=entity_context)
    ...

def run_streaming(self, capability, question, history=None, domain=None, mode=None, entity_context=""):
    ...
    system = self._build_system_prompt(capability, domain, mode, entity_context=entity_context)
    ...
```

And in `_build_system_prompt()`:
```python
def _build_system_prompt(self, capability, domain=None, mode=None, entity_context=""):
    ...
    # After line 513 (baker_insights injection), add:
    if entity_context:
        enriched += f"\n\n{entity_context}\n"

    return build_mode_aware_prompt(enriched, domain=domain, mode=mode)
```

**Then in `outputs/dashboard.py`, the capability path (~line 3505):**
```python
# Before calling runner.run_streaming() or runner.run_single(), compute entity context:
from orchestrator.scan_prompt import build_entity_context
_entity_ctx = build_entity_context(req.question, req.history, req.project)

# Pass to runner:
runner.run_streaming(cap, req.question, history=req.history,
                     domain=domain, mode=mode, entity_context=_entity_ctx)
```

Do the same for the `run_multi()` call in the delegate path (~line 3606).

## Files to Modify

| File | Changes |
|------|---------|
| `outputs/static/app.js` | `slice(-10)` → `slice(-25)`, history cap 20 → 50 |
| `outputs/dashboard.py` | 3x `[-10:]` → `[-25:]`, pass question/history/project to `build_mode_aware_prompt`, compute + pass entity_context to capability runner |
| `orchestrator/scan_prompt.py` | New function `build_entity_context()`, add params to `build_mode_aware_prompt()` |
| `orchestrator/capability_runner.py` | Add `entity_context` param to `run_single()`, `run_streaming()`, `run_multi()`, `_build_system_prompt()` |

## What NOT to Change

- Don't change the specialist picker history (already 30 — good)
- Don't change classify_intent's 15-turn DB history (separate mechanism, already works)
- Don't change the WhatsApp webhook history handling
- Don't change the retrieval system (that's a separate workstream)

## Testing

1. Syntax check all 4 files
2. Manual test: Ask Baker "What do we know about Oskolkov?" — the entity context should inject Oskolkov's contact profile into the system prompt, giving Baker immediate context about who this person is
3. Manual test: Ask Baker about a known matter — matter context should appear
4. Verify no regression: Ask Baker a simple question with no entity matches — should work identically to before (entity_context = empty string, no injection)

## Cost Impact

Minimal. The DB queries are:
- `SELECT FROM vip_contacts` — ~120 rows, cached by connection pooling
- `SELECT FROM matter_registry WHERE status = 'active'` — ~13 rows

No LLM cost added. The extra system prompt tokens (~200-500 for entity context) are negligible vs the 1M context window.
