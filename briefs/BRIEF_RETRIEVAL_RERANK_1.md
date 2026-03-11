# BRIEF: RETRIEVAL-RERANK-1 — Re-rank Retrieved Results by Relevance

**Author:** AI Head (Session 20)
**For:** Code 300 (after SMART-ROUTING-1)
**Priority:** HIGH — with 4,000+ documents, ranking quality is critical
**Estimated scope:** 1 file (`memory/retriever.py`), ~80 lines added
**Cost:** Zero — pure Python, no API calls

---

## Problem

Baker's retrieval returns results sorted purely by **cosine similarity** from Qdrant. This causes:

1. **Name misses**: "What did Oskolkov say?" — a general project doc may outscore Oskolkov's actual WhatsApp message
2. **Keyword blindness**: Query mentions "insurance" but the top result is about "property management" (semantically close but wrong)
3. **Stale results**: A 6-month-old email outscores yesterday's WhatsApp on pure vector similarity
4. **Source noise**: A vague `baker-health` or `baker-todoist` chunk outscores a precise email match

## Solution

Add a `_rerank_results()` function inside `search_all_collections()` that re-scores results AFTER Qdrant returns them. The new score blends vector similarity with three signals:

1. **Exact term boost** (+0.15): Any significant word from the query appears in the result content
2. **Name match boost** (+0.20): A person name from the query appears in the result
3. **Recency boost** (+0.05 to +0.10): Results from last 7 days get a small boost

The re-ranking happens INSIDE the retriever, so ALL paths benefit automatically (legacy, agentic, capability).

## Implementation

### File: `memory/retriever.py`

#### Add new function after `_enrich_with_full_text()`:

```python
def _rerank_results(self, contexts: list, query: str) -> list:
    """
    Re-rank retrieved contexts by blending vector score with exact-match signals.
    Called after Qdrant search, before enrichment.

    Boosts:
      +0.15  — any significant query term appears in content (exact keyword match)
      +0.20  — a proper name from the query appears in content (person/entity match)
      +0.05  — result is from the last 24 hours
      +0.10  — result is from the last 7 days (but not last 24h — that gets +0.05)

    All boosts are additive on top of the original vector score.
    Results re-sorted by adjusted score (descending).
    """
    if not contexts or not query:
        return contexts

    import re
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)

    # Extract significant words from query (3+ chars, not stopwords)
    stopwords = {
        "the", "and", "for", "are", "but", "not", "you", "all", "can",
        "had", "her", "was", "one", "our", "out", "has", "his", "how",
        "its", "may", "new", "now", "old", "see", "way", "who", "did",
        "get", "got", "let", "say", "she", "too", "use", "what", "when",
        "where", "which", "who", "why", "with", "about", "after", "been",
        "before", "being", "between", "both", "each", "from", "have",
        "into", "more", "most", "much", "must", "over", "same", "some",
        "such", "than", "that", "them", "then", "they", "this", "those",
        "through", "under", "very", "what", "will", "would", "your",
        "baker", "tell", "show", "find", "check", "give", "know",
        "please", "could", "should", "does", "there",
    }
    query_words = [
        w for w in re.findall(r'\b\w+\b', query.lower())
        if len(w) >= 3 and w not in stopwords
    ]

    # Detect proper names: capitalized words in the ORIGINAL query (not lowered)
    # "What did Oskolkov say about RG7?" → ["Oskolkov", "RG7"]
    proper_names = [
        w for w in re.findall(r'\b[A-Z][a-zA-Z0-9]+\b', query)
        if len(w) >= 3 and w.lower() not in stopwords
    ]
    proper_names_lower = [n.lower() for n in proper_names]

    for ctx in contexts:
        boost = 0.0
        content_lower = (ctx.content or "").lower()

        # 1. Exact query term match
        matched_terms = sum(1 for w in query_words if w in content_lower)
        if matched_terms > 0:
            # Scale: 1 match = +0.08, 2+ matches = +0.15
            boost += 0.08 if matched_terms == 1 else 0.15

        # 2. Proper name match (strongest signal)
        name_matched = any(n in content_lower for n in proper_names_lower)
        if name_matched:
            boost += 0.20

        # 3. Recency boost
        date_str = ctx.metadata.get("date", "") or ctx.metadata.get("received_date", "") or ""
        if date_str:
            try:
                # Try parsing ISO format and common date formats
                if isinstance(date_str, datetime):
                    result_date = date_str
                elif isinstance(date_str, str):
                    # Try ISO first, then common formats
                    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
                        try:
                            result_date = datetime.strptime(date_str.split("+")[0].split(".")[0], fmt)
                            if result_date.tzinfo is None:
                                result_date = result_date.replace(tzinfo=timezone.utc)
                            break
                        except ValueError:
                            continue
                    else:
                        result_date = None
                else:
                    result_date = None

                if result_date:
                    age = now - result_date
                    if age < timedelta(hours=24):
                        boost += 0.05
                    elif age < timedelta(days=7):
                        boost += 0.10
            except Exception:
                pass  # Date parsing failed — no boost, no crash

        # Apply boost
        ctx.score = ctx.score + boost
        # Store boost in metadata for debugging
        ctx.metadata["rerank_boost"] = round(boost, 3)

    # Re-sort by adjusted score
    contexts.sort(key=lambda c: c.score, reverse=True)
    return contexts
```

#### Integrate into `search_all_collections()`:

Find the merge-and-sort section (after all collections are searched, before enrichment). Insert the rerank call:

```python
# After combining all results and sorting by score:
all_contexts.sort(key=lambda c: c.score, reverse=True)

# NEW: Re-rank with exact-match signals
all_contexts = self._rerank_results(all_contexts, query)

# Then enrichment:
all_contexts = self._enrich_with_full_text(all_contexts)
```

The key: rerank BEFORE enrichment, because enrichment replaces content (which would invalidate our keyword matching). We match against the original Qdrant chunk content, then enrich the top results with full text.

## What NOT to Change

- Don't change the Qdrant search parameters (limit, threshold)
- Don't change the enrichment logic
- Don't change agent tool methods (they call `search_all_collections` which now includes reranking)
- Don't change PostgreSQL keyword searches (they already use ILIKE matching)
- Don't add any API calls — this is pure Python string matching

## Testing

1. `python3 -c "import py_compile; py_compile.compile('memory/retriever.py', doraise=True)"`
2. The `rerank_boost` metadata field will show in logs — useful for debugging ranking quality

## Expected Impact

| Query | Before | After |
|-------|--------|-------|
| "What did Oskolkov say?" | Generic project doc (score 0.82) | Oskolkov's WA message (0.72 + 0.20 name = 0.92) |
| "Latest on insurance renewal" | Old insurance doc (0.78) | Yesterday's email about renewal (0.71 + 0.15 term + 0.05 recency = 0.91) |
| "RG7 project status" | Random project chunk (0.80) | RG7-specific email (0.75 + 0.15 term = 0.90) |
