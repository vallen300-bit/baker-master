# Brief: CITATION-CONFIDENCE-1 — Citation Adherence + Extraction Confidence

**Author:** AI Head (Session 21)
**For:** Code 300
**Priority:** HIGH — Director trust depends on verifiable sources and reliable extraction quality

---

## Part A: Citation Adherence

### Problem

Specialist prompts include citation rules (capability_runner.py:504-509), but specialists rarely cite sources in practice. The current instruction is generic and easy to ignore:

```
When referencing information from retrieved sources, cite them using
[Source: label] format inline.
```

Session 21 testing confirmed: legal specialist produced a detailed Hagenauer analysis with zero inline citations despite having SOURCE-tagged tool results.

### Root Cause

1. The citation instruction is buried in a wall of text (role description + citation rules + feedback + insights + entity context + pre-fetched context + preferences). By the time Claude reaches the actual question, the citation rule is forgotten.
2. No enforcement mechanism — the model isn't penalized or reminded when it skips citations.
3. The instruction says "cite them" but doesn't say "you MUST cite" or "every factual claim needs a source."

### Fix

**Modify `orchestrator/capability_runner.py` — `_build_specialist_prompt()` method (~line 504):**

Replace the current citation rules:

```python
f"## CITATION RULES\n"
f"When referencing information from retrieved sources, cite them using "
f"[Source: label] format inline. The sources are marked with [SOURCE:label]...[/SOURCE] "
f"tags in the tool results.\n"
f'Example: "The payment deadline is March 11 [Source: Email from Ofenheimer, 6 Mar 2026]."\n'
f"Always cite the specific source — never fabricate citations."
```

With this stronger version:

```python
f"## CITATION RULES (MANDATORY)\n"
f"Every factual claim in your response MUST include an inline citation.\n"
f"Format: [Source: label] — where label matches the [SOURCE:label] tags in tool results.\n\n"
f"Examples:\n"
f'- "The retention is 5% [Source: Contract Hagenauer, 2023-04-15]."\n'
f'- "Cupial rejected 3 line items [Source: Email from Ofenheimer, 6 Mar 2026]."\n'
f'- "Recovery was 72% [Source: Whoop, 12 Mar 2026]."\n\n'
f"Rules:\n"
f"- If you cannot cite a source for a claim, say \"[unverified]\" after it.\n"
f"- Never fabricate citations. Only cite sources you actually retrieved.\n"
f"- General knowledge (dates, definitions) does not need citation.\n"
f"- At the end of your response, add a ## Sources section listing all cited sources."
```

**Also add a citation reminder at the END of the prompt** (after all context injection), right before it's returned. This ensures the instruction is fresh in the model's context:

```python
# Add at the end of _build_specialist_prompt(), just before the return
enriched += "\n\nREMINDER: Cite every factual claim with [Source: label]. End with ## Sources."
```

### Files to Modify

| File | Change |
|------|--------|
| `orchestrator/capability_runner.py` | Strengthen citation block (~line 504) + add trailing reminder |

### Verification

1. Ask legal specialist: "What is the status of the Hagenauer dispute?"
2. Response should contain inline `[Source: ...]` citations
3. Response should end with a `## Sources` section
4. Claims without sources should show `[unverified]`

---

## Part B: Extraction Confidence

### Problem

Every document extraction gets `confidence = "medium"` hardcoded (document_pipeline.py:385). The field is dead metadata — it doesn't reflect actual extraction quality. A clean 2-page invoice gets the same confidence as an OCR'd 50-page contract with missing pages.

### Fix

**Modify `tools/document_pipeline.py`:**

**Step 1: Update the extraction prompt** to ask Haiku for a confidence assessment.

Replace `_EXTRACT_PROMPT` (~line 169):

```python
_EXTRACT_PROMPT = """Extract structured data from this {doc_type}.
Return ONLY valid JSON with these fields: {schema}

Additionally, include a "_confidence" field with value "high", "medium", or "low" based on:
- "high": All key fields clearly present, amounts unambiguous, dates explicit
- "medium": Most fields present but some inferred or partially readable
- "low": Significant fields missing, text unclear, amounts ambiguous

Use null for fields you cannot determine. Use EUR for all amounts.

Document text (first 12000 chars):
{text}"""
```

**Step 2: Extract the confidence from the response** and pass it to `_store_extraction`.

In `extract_document()` (~line 216), after `structured = json.loads(raw)`:

```python
structured = json.loads(raw)

# Extract confidence from model response, default to "medium"
confidence = structured.pop("_confidence", "medium")
if confidence not in ("high", "medium", "low"):
    confidence = "medium"
```

**Step 3: Pass confidence to `_store_extraction()`.**

Change the function signature and call:

```python
# In extract_document():
_store_extraction(doc_id, document_type, structured, confidence)

# Update _store_extraction signature:
def _store_extraction(doc_id: int, doc_type: str, structured: dict, confidence: str = "medium"):
```

And update the INSERT:

```python
cur.execute("""
    INSERT INTO document_extractions
        (document_id, extraction_type, structured_data, confidence, extracted_by)
    VALUES (%s, %s, %s, %s, %s)
""", (doc_id, extraction_type, json.dumps(structured), confidence, _HAIKU_MODEL))
```

### Files to Modify

| File | Change |
|------|--------|
| `tools/document_pipeline.py` | Update _EXTRACT_PROMPT, extract confidence from response, pass to _store_extraction |

### Verification

1. Trigger extraction on a clean contract: `confidence` should be "high"
2. Trigger extraction on a blurry scan: `confidence` should be "low" or "medium"
3. Check `document_extractions` table: `SELECT confidence, COUNT(*) FROM document_extractions GROUP BY 1` — should show distribution, not all "medium"
4. Verify `_confidence` field is NOT stored in `structured_data` JSON (it's popped out)

### Note on Backfill

Existing 3,287 extractions keep `confidence = "medium"`. No backfill needed — only new extractions get real confidence. If we want to re-assess, that's a separate $40 Haiku backfill job (deferred).

---

## Execution Order

1. **Part B first** — it's a contained change in one file, zero risk to user-facing behavior
2. **Part A second** — affects all specialist prompts, test with one specialist before deploying

Syntax-check all modified files. Commit and push when done.
