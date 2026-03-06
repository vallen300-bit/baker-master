# BRIEF: PLUGINS — Web Search + Document Reader Agent Tools

**Author:** Code 300 (Architect)
**Builder:** Code Brisen
**Depends on:** AGENT-FRAMEWORK-1 (merged, live)
**Priority:** High — unlocks full value for Research, IT, Legal, Finance capabilities

---

## 1. Summary

Add two new tools to Baker's agent tool set (currently 9 tools in `agent.py`):

1. **`web_search`** — search the web for real-time information (hardware specs, Microsoft docs, market data, competitor info, legal references)
2. **`read_document`** — extract text from a file by path or URL (PDF, DOCX, XLSX that arrive as email attachments or sit in Dropbox)

Both tools become available to all capabilities via the existing `TOOL_DEFINITIONS` list.
Capabilities that need them get the tool names added to their `tools` JSONB array.
No new infrastructure — just two new tools in the ToolExecutor.

---

## 2. Plugin 1: Web Search (`web_search`)

### API Choice: Tavily

**Why Tavily:**
- Built specifically for AI agents — returns clean, LLM-optimized text snippets (not raw HTML)
- Free tier: 1,000 searches/month (covers Baker's initial volume)
- $30/month for 4,000 searches if we scale
- Clean Python SDK: `pip install tavily-python`
- 4-line integration: `TavilyClient(api_key).search(query)`

**Alternatives considered:**
- Brave Search: good free tier but recently eliminated it for new users
- SerpAPI: $50/month minimum, overkill for our volume
- Serper: cheapest ($0.30/1K) but returns SERP metadata, not full content
- Exa: excellent semantic search but more expensive for general queries

### Tool Definition

Add to `TOOL_DEFINITIONS` in `orchestrator/agent.py`:

```python
{
    "name": "web_search",
    "description": (
        "Search the web for current information not available in Baker's memory. "
        "Returns relevant web page excerpts ranked by relevance.\n\n"
        "Use for:\n"
        "- Hardware specifications and product comparisons\n"
        "- Microsoft documentation (M365, Entra ID, Conditional Access policies)\n"
        "- Market data, competitor information, industry reports\n"
        "- Legal references (Austrian law, court decisions, regulatory updates)\n"
        "- Current pricing and availability\n"
        "- Any question where Baker's stored memory is insufficient or outdated\n\n"
        "Do NOT use for information that Baker already has in memory — "
        "search_memory, search_emails, search_meetings first."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query — use specific, descriptive terms.",
            },
            "max_results": {
                "type": "integer",
                "description": "Max results to return (default 5, max 10).",
            },
            "search_depth": {
                "type": "string",
                "description": "'basic' (fast, 1 credit) or 'advanced' (thorough, 2 credits). Default: basic.",
                "enum": ["basic", "advanced"],
            },
        },
        "required": ["query"],
    },
},
```

### Tool Implementation

Add to `ToolExecutor` in `orchestrator/agent.py`:

```python
def _web_search(self, inp: dict) -> str:
    """Search the web via Tavily API."""
    try:
        from tavily import TavilyClient
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            return json.dumps({"error": "Web search not configured (TAVILY_API_KEY missing)"})

        client = TavilyClient(api_key=api_key)
        query = inp.get("query", "")
        max_results = min(inp.get("max_results", 5), 10)
        depth = inp.get("search_depth", "basic")

        results = client.search(
            query=query,
            max_results=max_results,
            search_depth=depth,
        )

        # Format results for Claude
        parts = [f"--- WEB SEARCH: '{query}' ({len(results.get('results', []))} results) ---"]
        for r in results.get("results", []):
            title = r.get("title", "")
            url = r.get("url", "")
            content = r.get("content", "")[:1500]  # Cap per result
            parts.append(f"[{title}] ({url})\n{content}")

        return "\n\n".join(parts) if len(parts) > 1 else "[No web results found]"
    except Exception as e:
        return json.dumps({"error": f"Web search failed: {str(e)}"})
```

### Config

New env var on Render:

```
TAVILY_API_KEY=tvly-xxxxx
```

Get API key from: https://app.tavily.com/home (free signup, instant key)

### Dependency

Add to `requirements.txt`:

```
tavily-python>=0.5.0
```

---

## 3. Plugin 2: Document Reader (`read_document`)

### What Already Exists

Baker already has document extraction built:

| File | What It Does |
|------|-------------|
| `tools/ingest/extractors.py` | Extracts text from PDF, DOCX, XLSX, CSV, TXT, MD, JSON, images |
| `triggers/waha_client.py` | Downloads media files + calls extractors (WhatsApp attachments) |
| `scripts/extract_gmail.py` | Extracts text from email attachments |
| `document_generator.py` | Generates DOCX/XLSX/PDF/PPTX (write direction) |

**What's missing:** These extractors are not exposed as an agent tool. The agent can't
say "read the PDF attached to the last BCOMM email" because there's no tool for it.

### Tool Definition

```python
{
    "name": "read_document",
    "description": (
        "Read and extract text from a document file. Supports PDF, DOCX, XLSX, "
        "CSV, and plain text files.\n\n"
        "Two modes:\n"
        "1. By email reference: provide a sender name or subject keyword — Baker "
        "   finds the most recent matching email with an attachment and extracts it.\n"
        "2. By file path: provide a direct path to a file (Dropbox, temp download).\n\n"
        "Use for:\n"
        "- 'Read the PDF that BCOMM sent last week'\n"
        "- 'Extract the spreadsheet from Dennis's migration email'\n"
        "- 'What does the Hagenauer contract say about termination?'\n"
        "- Analyzing vendor offers, contracts, term sheets, invoices"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "email_query": {
                "type": "string",
                "description": "Search for email attachment by sender name, subject keyword, or both. Baker finds the most recent match.",
            },
            "file_path": {
                "type": "string",
                "description": "Direct path to a file. Use if you already know the file location.",
            },
        },
        "required": [],
    },
},
```

### Tool Implementation

```python
def _read_document(self, inp: dict) -> str:
    """Read and extract text from a document (email attachment or file path)."""
    # Mode 1: Find email attachment
    email_query = inp.get("email_query", "")
    if email_query:
        return self._read_email_attachment(email_query)

    # Mode 2: Direct file path
    file_path = inp.get("file_path", "")
    if file_path:
        return self._read_file(file_path)

    return json.dumps({"error": "Provide either email_query or file_path"})

def _read_email_attachment(self, query: str) -> str:
    """Find the most recent email matching query, extract its attachment."""
    try:
        # Search email_messages for matching emails with attachments
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return json.dumps({"error": "Database unavailable"})
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            # Search for emails with attachment text
            cur.execute("""
                SELECT subject, sender, received_at, attachment_text,
                       full_text
                FROM email_messages
                WHERE (subject ILIKE %s OR sender ILIKE %s)
                  AND attachment_text IS NOT NULL
                  AND attachment_text != ''
                ORDER BY received_at DESC
                LIMIT 1
            """, (f"%{query}%", f"%{query}%"))
            row = cur.fetchone()
            cur.close()
            if not row:
                return json.dumps({"result": f"No email with attachment found matching '{query}'"})
            return (
                f"--- DOCUMENT from email ---\n"
                f"From: {row['sender']}\n"
                f"Subject: {row['subject']}\n"
                f"Date: {row['received_at']}\n\n"
                f"{row['attachment_text'][:8000]}"
            )
        finally:
            store._put_conn(conn)
    except Exception as e:
        return json.dumps({"error": f"Email attachment search failed: {str(e)}"})

def _read_file(self, file_path: str) -> str:
    """Extract text from a file at the given path."""
    from pathlib import Path
    try:
        from tools.ingest.extractors import extract, SUPPORTED_EXTENSIONS
        p = Path(file_path)
        if not p.exists():
            return json.dumps({"error": f"File not found: {file_path}"})
        if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return json.dumps({"error": f"Unsupported file type: {p.suffix}"})
        text = extract(p)
        if not text:
            return json.dumps({"result": "File extracted but no text content found"})
        return (
            f"--- DOCUMENT: {p.name} ---\n"
            f"{text[:8000]}"
        )
    except Exception as e:
        return json.dumps({"error": f"File extraction failed: {str(e)}"})
```

### No New Dependencies

Document extraction uses libraries already in the project:
- `pdfplumber` — PDF extraction
- `python-docx` — DOCX extraction
- `openpyxl` — XLSX extraction
- Anthropic API — image extraction (Claude Vision)

### No New Env Vars

The `read_document` tool uses existing database connections and file extractors.

---

## 4. Register Tools in ToolExecutor

In `orchestrator/agent.py`, add the tool dispatch:

```python
# In ToolExecutor.execute(), add cases:
elif tool_name == "web_search":
    return self._web_search(tool_input)
elif tool_name == "read_document":
    return self._read_document(tool_input)
```

---

## 5. Update Capability Tool Lists

After the tools are built, update the `capability_sets` table to grant
relevant capabilities access to the new tools:

```sql
-- Web search: nearly all capabilities benefit
UPDATE capability_sets
SET tools = tools || '["web_search"]'::jsonb
WHERE slug IN ('research', 'it', 'finance', 'sales', 'asset_mgmt', 'ib', 'marketing', 'legal')
  AND NOT tools @> '["web_search"]'::jsonb;

-- Document reader: capabilities that analyze vendor docs, contracts, term sheets
UPDATE capability_sets
SET tools = tools || '["read_document"]'::jsonb
WHERE slug IN ('legal', 'finance', 'it', 'ib', 'comms')
  AND NOT tools @> '["read_document"]'::jsonb;
```

---

## 6. Implementation Order

### Step 1: Web Search Tool
1. Sign up at tavily.com, get API key
2. Add `TAVILY_API_KEY` to Render env vars
3. Add `tavily-python` to requirements.txt
4. Add `web_search` to TOOL_DEFINITIONS in agent.py
5. Add `_web_search()` to ToolExecutor
6. Add dispatch case in `execute()`
7. Test: agent loop with "search the web for M365 Business Premium vs E3 comparison"

### Step 2: Document Reader Tool
1. Add `read_document` to TOOL_DEFINITIONS in agent.py
2. Add `_read_document()`, `_read_email_attachment()`, `_read_file()` to ToolExecutor
3. Add dispatch case in `execute()`
4. Test: agent loop with "read the PDF that BCOMM sent" (should find the AN26-00022 offer)
5. Test: agent loop with "read the contract at /path/to/file.docx"

### Step 3: Update Capability Tool Lists
1. Run the SQL updates to grant new tools to relevant capabilities
2. Test: "Baker, have the IT agent compare Business Premium vs E3" → IT capability now uses web_search
3. Test: "Baker, have the legal agent read the Hagenauer contract" → Legal capability uses read_document

---

## 7. Safety & Cost Controls

### Web Search
- **Rate limit:** Tavily free tier = 1,000/month. At ~30 Baker queries/day touching web search,
  that's ~900/month — fits free tier. Monitor via Tavily dashboard.
- **Cost cap:** If free tier is exceeded, Tavily returns an error. Baker falls back gracefully
  (tool returns error message, Claude uses memory-only context).
- **No recursive fetching:** The tool returns snippets, not full pages. No risk of
  downloading large files or following redirect chains.
- **Prompt instruction:** Tool description tells Claude to use memory tools FIRST,
  web search only when memory is insufficient. This minimizes unnecessary web calls.

### Document Reader
- **File size cap:** Extract max 8,000 chars per document (prevents context overflow
  from a 200-page PDF).
- **Supported types only:** Rejects unsupported extensions with clear error.
- **No arbitrary file access:** email_query mode searches the database (no filesystem traversal).
  file_path mode is for explicit paths provided by the Director.
- **No network fetching:** The tool reads local files or database content. It does not
  download from URLs (that would be a separate tool if needed).

---

## 8. Testing Checklist

- [ ] `python3 -c "import py_compile; py_compile.compile('orchestrator/agent.py', doraise=True)"`
- [ ] Web search returns results for "Microsoft 365 Business Premium features"
- [ ] Web search returns graceful error when TAVILY_API_KEY is missing
- [ ] Web search results capped at max_results
- [ ] Document reader finds BCOMM email attachment by sender name
- [ ] Document reader finds email attachment by subject keyword
- [ ] Document reader extracts PDF text via file path
- [ ] Document reader extracts DOCX text via file path
- [ ] Document reader rejects unsupported file types
- [ ] Document reader returns error for nonexistent files
- [ ] Extracted text capped at 8,000 chars
- [ ] Existing 9 tools still work (no regression)
- [ ] Capabilities without new tools in their list do NOT see web_search/read_document

---

## 9. Code Brisen — Opening Prompt

```
Read CLAUDE.md. Read briefs/BRIEF_PLUGINS_WEB_SEARCH_DOC_READER.md.
Two new agent tools: web_search (Tavily) and read_document (email attachments + file paths).
Implement Steps 1-3 in order.
Commit locally after each step. Do NOT push.
Each commit message: "feat: PLUGINS step N — [description]"
```
