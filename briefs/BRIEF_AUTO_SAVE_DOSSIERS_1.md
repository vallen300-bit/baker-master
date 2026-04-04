# BRIEF: Auto-Save Substantive Answers to Dossiers

**Priority:** High — Director loses valuable Baker analyses on page reload
**Ticket:** AUTO-SAVE-DOSSIERS-1

## Problem

When Baker produces a substantive summary/analysis in Ask Baker (e.g., a morning briefing, an issue map for Balazs, a risk summary), it's lost on page reload. The data exists in `conversation_memory` but:
1. The Ask Baker UI has no conversation history
2. Summaries get buried among short exchanges
3. There's no way to find a previous analysis without MCP tools

## Solution

Auto-save "dossier-worthy" answers to `deep_analyses` table. They then appear in the Dossiers section automatically — persistent, searchable, findable.

## What Qualifies as "Dossier-Worthy"

A response should be auto-saved when ALL of:
1. **Length:** answer > 800 characters (filters out confirmations, short replies, error messages)
2. **Not an action confirmation:** doesn't start with common action prefixes like "✅", "📧 Draft ready", "❌", "Noted —"
3. **Content signal:** contains structural markers like `##`, `**`, `|` (tables), `---`, or numbered lists — indicating a formatted analysis, not casual text

This is a simple heuristic. Err on the side of saving too much — the Director can ignore extras in Dossiers, but can't recover lost analyses.

## Implementation

### Change 1: Add auto-save function

**File:** `outputs/dashboard.py`

Add a helper function near the scan_chat area:

```python
def _maybe_save_to_dossiers(question: str, answer: str, owner: str = "dimitry"):
    """Auto-save substantive Baker answers to deep_analyses for Dossier persistence."""
    # Filter: too short
    if len(answer) < 800:
        return
    # Filter: action confirmations
    _skip_prefixes = ("✅", "📧", "❌", "Noted", "Done", "Got it", "I don't have", "I couldn't")
    if any(answer.lstrip().startswith(p) for p in _skip_prefixes):
        return
    # Filter: must have structural markers (formatted analysis)
    _structure_markers = ("## ", "**", "| ", "---", "1. ", "2. ", "3. ")
    if not any(m in answer for m in _structure_markers):
        return

    # Build a topic from the question (first 120 chars, cleaned)
    import re
    topic = re.sub(r'https?://\S+', '', question).strip()[:120]
    if not topic:
        topic = "Baker Analysis"

    try:
        from memory.store_back import store_deep_analysis
        store_deep_analysis(
            topic=f"Ask Baker: {topic}",
            analysis_text=answer,
            prompt=question,
            source_documents="conversation_memory"
        )
        logger.info(f"Auto-saved dossier: {topic[:60]}")
    except Exception as e:
        logger.warning(f"Auto-save to dossiers failed (non-fatal): {e}")
```

### Change 2: Call it after scan_chat stores to conversation_memory

**File:** `outputs/dashboard.py`, in `scan_chat()` function

Find the place where the full answer is stored to `conversation_memory` (after SSE streaming completes). Add:

```python
# Auto-save substantive answers to Dossiers
_maybe_save_to_dossiers(req.question, full_answer)
```

This should be in the `finally` or post-stream block where `full_answer` is available. Look for the `store_conversation_memory()` call — place the dossier save right after it.

### Change 3: Verify `store_deep_analysis` exists

**File:** `memory/store_back.py`

Check that `store_deep_analysis()` exists and writes to `deep_analyses` table. It should already exist (used by `baker_store_analysis` MCP tool). Verify the function signature matches:

```python
store_deep_analysis(topic, analysis_text, prompt=None, source_documents=None)
```

If the function doesn't exist or has a different name, find the correct function:
```bash
grep -n "def store.*analysis\|def store.*deep\|deep_analyses" memory/store_back.py
```

## Dedup Consideration

To avoid saving duplicate dossiers (e.g., if the Director asks the same question twice):
- Before saving, check if a dossier with the same topic already exists in the last 24h
- If yes, skip the save

```python
# Optional dedup check
cur.execute("""
    SELECT id FROM deep_analyses
    WHERE topic = %s AND created_at > NOW() - INTERVAL '24 hours'
    LIMIT 1
""", (f"Ask Baker: {topic}",))
if cur.fetchone():
    return  # Already saved
```

## Files to Modify

| File | Change |
|------|--------|
| `outputs/dashboard.py` | Add `_maybe_save_to_dossiers()` + call after conversation_memory store |
| `memory/store_back.py` | Verify `store_deep_analysis()` exists (likely no change needed) |

## Testing

1. Ask Baker a complex question (e.g., "What issues are connected with Balazs?")
2. Wait for full answer to stream
3. Navigate to Dossiers section → should see "Ask Baker: What issues are connected with Balazs?" as a new entry
4. Ask a short question (e.g., "What time is it?") → should NOT create a dossier
5. Send a WhatsApp → "✅ WhatsApp sent" → should NOT create a dossier

## Verification

```bash
python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"
```

Check DB after test:
```sql
SELECT id, topic, created_at FROM deep_analyses ORDER BY created_at DESC LIMIT 5;
```
