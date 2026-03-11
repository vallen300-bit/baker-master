"""
Baker AI — Agentic RAG Loop (AGENTIC-RAG-1)

Replaces single-pass "retrieve everything then call Claude once" with a
tool-use loop where Claude decides what to retrieve.  Typically 1-2
iterations for simple questions, up to max_iterations for complex ones.

Two entry points:
  run_agent_loop()           — blocking, returns AgentResult  (WhatsApp)
  run_agent_loop_streaming() — generator yielding text tokens  (Scan SSE)

Feature flag: BAKER_AGENTIC_RAG=true  (env var on Render).
"""
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Generator, Optional

import anthropic

from config.settings import config

logger = logging.getLogger("baker.agent")

_AGENTIC_RAG = os.getenv("BAKER_AGENTIC_RAG", "false").lower() == "true"

# Hard wall-clock timeout (PM review item #1).
# If the agent loop exceeds this, we abandon and fall back to single-pass.
AGENT_TIMEOUT_SECONDS = float(os.getenv("BAKER_AGENT_TIMEOUT", "30"))


# ─────────────────────────────────────────────────
# Tool Definitions (Anthropic format)
# ─────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "search_memory",
        "description": (
            "Broad semantic search across ALL of Baker's stored knowledge "
            "(WhatsApp, emails, meetings, contacts, deals, projects, documents, "
            "health, interactions, ClickUp, Todoist).  Returns the top results "
            "ranked by relevance.\n\n"
            "Use for:\n"
            "- 'What do we know about the Atlas deal?'\n"
            "- 'Any context on Hagenauer?'\n"
            "- 'What has Baker stored about the LP fundraise?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Semantic search query — use natural language.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results per collection (default 8).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_meetings",
        "description": (
            "Search meeting transcripts (Fireflies) by keyword or get recent "
            "meetings.  Searches title, participants, organizer, and full "
            "transcript text.\n\n"
            "Use for:\n"
            "- 'What did we discuss with Hagenauer?'\n"
            "- 'Last meeting notes'\n"
            "- 'What was decided in the board call?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword to search in transcripts. Omit or leave empty for recent meetings.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 5).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "search_emails",
        "description": (
            "Search email messages by keyword or get recent emails.  Searches "
            "subject, sender, and full body.\n\n"
            "Use for:\n"
            "- 'Any emails from Marco about the contract?'\n"
            "- 'What did the lawyer send last week?'\n"
            "- 'Show me recent emails'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword to search in emails. Omit or leave empty for recent emails.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 5).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "search_whatsapp",
        "description": (
            "Search WhatsApp messages by keyword or get recent messages.  "
            "Searches sender name and message text.\n\n"
            "Use for:\n"
            "- 'What did Marco say on WhatsApp?'\n"
            "- 'Any WhatsApp messages about the Zurich trip?'\n"
            "- 'Recent WhatsApp messages'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword to search in WhatsApp messages. Omit or leave empty for recent messages.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 5).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_contact",
        "description": (
            "Look up a contact profile by name.  Returns role, company, email, "
            "phone, relationship tier, communication style, and notes.\n\n"
            "Use for:\n"
            "- 'Who is Thomas Hagenauer?'\n"
            "- 'What's Marco's email?'\n"
            "- 'Tell me about our relationship with Wertheimer'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Contact name (fuzzy match supported).",
                },
            },
            "required": ["name"],
        },
    },
    # STEP1B: 3 new retrieval tools (tools 6-8)
    {
        "name": "get_deadlines",
        "description": (
            "Get all active deadlines and upcoming dates from Baker's deadline "
            "tracker.  Returns every active and pending deadline ordered by due "
            "date — no keyword needed.\n\n"
            "Use for:\n"
            "- 'What deadlines do I have coming up?'\n"
            "- 'What's due this week?'\n"
            "- 'Any upcoming submission deadlines?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_clickup_tasks",
        "description": (
            "Search ClickUp tasks by keyword, status, or list name.  Searches "
            "task name and description across all synced workspaces.\n\n"
            "Use for:\n"
            "- 'What ClickUp tasks are open for Hagenauer?'\n"
            "- 'Show me high priority tasks'\n"
            "- 'Any tasks about the MO Vienna permit?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword to search in task name and description.",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status (e.g. 'open', 'in progress'). Optional.",
                },
                "priority": {
                    "type": "string",
                    "description": "Filter by priority (e.g. 'urgent', 'high'). Optional.",
                },
                "list_name": {
                    "type": "string",
                    "description": "Filter by ClickUp list name (partial match). Optional.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 10).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "search_deals_insights",
        "description": (
            "Search active deals and strategic insights.  Returns results from "
            "both the deals pipeline and the insights table (strategic analysis "
            "stored by Claude Code / Cowork sessions).\n\n"
            "Use for:\n"
            "- 'What is the status of the Wertheimer deal?'\n"
            "- 'Any strategic analysis on LP fundraise?'\n"
            "- 'Show me active deals'\n"
            "- 'What insights do we have on ClaimsMax?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword to search insights. Deals are always returned in full.",
                },
            },
            "required": ["query"],
        },
    },
    # PLUGINS-1: Web search tool (tool #10)
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
    # RETRIEVAL-FIX-1: Matter context tool (tool #9)
    {
        "name": "get_matter_context",
        "description": (
            "Look up a business matter/issue by name to get all connected people, "
            "keywords, and context. Use this FIRST when a question mentions a deal, "
            "dispute, project, or person — it reveals who else is involved and what "
            "keywords to search for.\n\n"
            "Use for:\n"
            "- 'What's the latest on Cupial?' → reveals Hassa, escrow, Top 4 etc.\n"
            "- 'Any updates on the Hagenauer project?' → reveals Ofenheimer, permit\n"
            "- 'Tell me about ClaimsMax' → reveals Philip, UBM, Jurkovic"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Matter name or keyword to look up.",
                },
            },
            "required": ["query"],
        },
    },
    # PLUGINS-1: Document reader tool (tool #11)
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
    # SPECIALIST-UPGRADE-1B: Document search tool (tool #12)
    {
        "name": "search_documents",
        "description": (
            "Search Baker's document store for full documents by type, matter, "
            "parties, or keywords. Returns full text and any structured extractions "
            "(amounts, dates, terms, clauses). Use when you need complete contracts, "
            "invoices, Nachträge, Schlussrechnungen, or correspondence — not fragments."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search terms to match against document text, filename, or parties",
                },
                "document_type": {
                    "type": "string",
                    "description": "Filter by type: contract, invoice, nachtrag, schlussrechnung, correspondence, protocol, report",
                },
                "matter_slug": {
                    "type": "string",
                    "description": "Filter by matter name",
                },
            },
            "required": ["query"],
        },
    },
    # CLICKUP-CREATE-1: Allow specialists to create ClickUp tasks
    {
        "name": "clickup_create",
        "description": (
            "Create a new task in ClickUp (BAKER space, Handoff Notes list). "
            "Use when the Director asks to track something, create a follow-up, "
            "or when analysis reveals an action item that should be tracked.\n\n"
            "Use for:\n"
            "- 'Create a task to follow up on the Hagenauer claim'\n"
            "- 'Track this as a ClickUp task'\n"
            "- 'Add a task for Mykola to review the invoice'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Task name — short, actionable (e.g. 'Follow up on Hagenauer claim').",
                },
                "description": {
                    "type": "string",
                    "description": "Task description with context. Optional.",
                },
                "priority": {
                    "type": "integer",
                    "description": "Priority: 1=Urgent, 2=High, 3=Normal, 4=Low. Default: 3.",
                },
                "due_date": {
                    "type": "string",
                    "description": "Due date in ISO format (YYYY-MM-DD). Optional.",
                },
            },
            "required": ["name"],
        },
    },
]


# ─────────────────────────────────────────────────
# Tool Executor
# ─────────────────────────────────────────────────

class ToolExecutor:
    """Maps tool names to retriever methods, formats results for Claude."""

    def __init__(self):
        from memory.retriever import SentinelRetriever
        self._retriever = SentinelRetriever()

    def execute(self, tool_name: str, tool_input: dict) -> str:
        """
        Execute a tool and return formatted text.
        Catches all exceptions per-tool (PM review item #4) so Claude
        gets a structured error and can try an alternative.
        """
        try:
            if tool_name == "search_memory":
                return self._search_memory(tool_input)
            elif tool_name == "search_meetings":
                return self._search_meetings(tool_input)
            elif tool_name == "search_emails":
                return self._search_emails(tool_input)
            elif tool_name == "search_whatsapp":
                return self._search_whatsapp(tool_input)
            elif tool_name == "get_contact":
                return self._get_contact(tool_input)
            elif tool_name == "get_deadlines":
                return self._get_deadlines(tool_input)
            elif tool_name == "get_clickup_tasks":
                return self._get_clickup_tasks(tool_input)
            elif tool_name == "search_deals_insights":
                return self._search_deals_insights(tool_input)
            elif tool_name == "get_matter_context":
                return self._get_matter_context(tool_input)
            elif tool_name == "web_search":
                return self._web_search(tool_input)
            elif tool_name == "read_document":
                return self._read_document(tool_input)
            elif tool_name == "search_documents":
                return self._search_documents(tool_input)
            elif tool_name == "clickup_create":
                return self._clickup_create(tool_input)
            else:
                return json.dumps({"error": f"Unknown tool: {tool_name}"})
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            return json.dumps({"error": f"{tool_name} unavailable: {str(e)}"})

    # -- Individual tool implementations --

    def _search_memory(self, inp: dict) -> str:
        query = inp.get("query", "")
        limit = inp.get("limit", 8)
        contexts = self._retriever.search_all_collections(
            query=query,
            limit_per_collection=limit,
            score_threshold=0.3,
        )
        return self._format_contexts(contexts, "MEMORY")

    def _search_meetings(self, inp: dict) -> str:
        query = inp.get("query", "")
        limit = inp.get("limit", 5)
        if query:
            results = self._retriever.get_meeting_transcripts(query, limit=limit)
        else:
            results = self._retriever.get_recent_meeting_transcripts(limit=limit)
        return self._format_contexts(results, "MEETINGS")

    def _search_emails(self, inp: dict) -> str:
        query = inp.get("query", "")
        limit = inp.get("limit", 5)
        if query:
            results = self._retriever.get_email_messages(query, limit=limit)
            # RETRIEVAL-FIX-1: Expand via matter registry (max 3 extra queries)
            expanded_terms = self._retriever.expand_query_via_matters(query)
            if expanded_terms:
                seen_ids = {c.metadata.get("message_id") for c in results}
                # Search people names first (most likely to find connected emails)
                for term in expanded_terms[:3]:
                    extra = self._retriever.get_email_messages(term, limit=3)
                    for e in extra:
                        if e.metadata.get("message_id") not in seen_ids:
                            results.append(e)
                            seen_ids.add(e.metadata.get("message_id"))
        else:
            results = self._retriever.get_recent_emails(limit=limit)
        return self._format_contexts(results, "EMAILS")

    def _search_whatsapp(self, inp: dict) -> str:
        query = inp.get("query", "")
        limit = inp.get("limit", 5)
        if query:
            results = self._retriever.get_whatsapp_messages(query, limit=limit)
            # RETRIEVAL-FIX-1: Expand via matter registry (max 3 extra queries)
            expanded_terms = self._retriever.expand_query_via_matters(query)
            if expanded_terms:
                seen_ids = {c.metadata.get("msg_id") for c in results}
                for term in expanded_terms[:3]:
                    extra = self._retriever.get_whatsapp_messages(term, limit=3)
                    for e in extra:
                        if e.metadata.get("msg_id") not in seen_ids:
                            results.append(e)
                            seen_ids.add(e.metadata.get("msg_id"))
        else:
            results = self._retriever.get_recent_whatsapp(limit=limit)
        return self._format_contexts(results, "WHATSAPP")

    def _get_contact(self, inp: dict) -> str:
        name = inp.get("name", "")
        parts = []

        # 1. Search VIP contacts (enriched profiles with role_context, expertise)
        try:
            conn = self._retriever._get_pg_conn()
            cur = conn.cursor(cursor_factory=__import__('psycopg2.extras', fromlist=['RealDictCursor']).RealDictCursor)
            # Full-name exact match first, then fuzzy
            cur.execute("""
                SELECT * FROM vip_contacts
                WHERE LOWER(name) = LOWER(%s)
                   OR similarity(name, %s) > 0.35
                ORDER BY
                    CASE WHEN LOWER(name) = LOWER(%s) THEN 0 ELSE 1 END,
                    similarity(name, %s) DESC
                LIMIT 3
            """, (name, name, name, name))
            vips = [dict(r) for r in cur.fetchall()]
            cur.close()
            if vips:
                for v in vips:
                    # Remove None values
                    v = {k: str(val) for k, val in v.items() if val is not None}
                    parts.append(f"[VIP CONTACT] {json.dumps(v, default=str)}")
        except Exception as e:
            logger.warning(f"VIP contact lookup failed (non-fatal): {e}")

        # 2. Search old contacts table
        result = self._retriever.get_contact_profile(name)
        if result:
            parts.append(result.content)

        # 3. Search decisions/analyses mentioning this person
        try:
            conn = self._retriever._get_pg_conn()
            cur = conn.cursor(cursor_factory=__import__('psycopg2.extras', fromlist=['RealDictCursor']).RealDictCursor)
            cur.execute("""
                SELECT decision, reasoning, project, created_at
                FROM decisions
                WHERE decision ILIKE %s OR reasoning ILIKE %s
                ORDER BY created_at DESC LIMIT 3
            """, (f'%{name}%', f'%{name}%'))
            decisions = [dict(r) for r in cur.fetchall()]
            cur.close()
            for d in decisions:
                parts.append(f"[DECISION] {d.get('decision', '')} | {d.get('reasoning', '')}")
        except Exception as e:
            logger.debug(f"Decision lookup for contact failed: {e}")

        if parts:
            return "\n\n".join(parts)
        return json.dumps({"result": f"No contact found matching '{name}'"})

    # -- STEP1B: 3 new tool implementations --

    def _get_deadlines(self, inp: dict) -> str:
        try:
            from models.deadlines import get_active_deadlines
            deadlines = get_active_deadlines(limit=50)
        except Exception as e:
            return json.dumps({"error": f"Deadlines unavailable: {str(e)}"})

        if not deadlines:
            return "[No active deadlines found]"

        lines = [f"--- DEADLINES ({len(deadlines)} active) ---"]
        for dl in deadlines:
            due = dl.get("due_date")
            due_str = due.strftime("%Y-%m-%d") if due else "TBD"
            priority = (dl.get("priority") or "normal").upper()
            status = dl.get("status", "active")
            desc = dl.get("description", "")
            lines.append(f"[{priority}] {due_str}: {desc} ({status})")
        return "\n".join(lines)

    def _get_clickup_tasks(self, inp: dict) -> str:
        query = inp.get("query", "")
        results = self._retriever.get_clickup_tasks_search(
            query=query,
            status=inp.get("status"),
            priority=inp.get("priority"),
            list_name=inp.get("list_name"),
            limit=inp.get("limit", 10),
        )
        return self._format_contexts(results, "CLICKUP TASKS")

    def _search_deals_insights(self, inp: dict) -> str:
        query = inp.get("query", "")
        deals = self._retriever.get_active_deals()
        insights = self._retriever.get_insights(query, limit=5) if query else []
        combined = deals + insights
        if not combined:
            return "[No deals or insights found]"
        return self._format_contexts(combined, "DEALS & INSIGHTS")

    def _get_matter_context(self, inp: dict) -> str:
        query = inp.get("query", "")
        matter = self._retriever.get_matter_context(query)
        if not matter:
            return json.dumps({"result": f"No matter found matching '{query}'"})

        parts = [
            f"--- MATTER: {matter.get('matter_name', '?')} ---",
            f"Description: {matter.get('description', 'N/A')}",
            f"People: {', '.join(matter.get('people', []))}",
            f"Keywords: {', '.join(matter.get('keywords', []))}",
            f"Projects: {', '.join(matter.get('projects', []))}",
            f"Status: {matter.get('status', 'active')}",
        ]

        # Auto-fetch recent emails and WhatsApp from connected people
        # so Claude gets the full picture in one tool call
        people = matter.get("people", [])
        if people:
            email_results = []
            wa_results = []
            seen_email_ids = set()
            seen_wa_ids = set()
            for person in people[:3]:  # top 3 people
                try:
                    emails = self._retriever.get_email_messages(person, limit=2)
                    for e in emails:
                        eid = e.metadata.get("message_id")
                        if eid not in seen_email_ids:
                            email_results.append(e)
                            seen_email_ids.add(eid)
                except Exception:
                    pass
                try:
                    wa = self._retriever.get_whatsapp_messages(person, limit=2)
                    for w in wa:
                        wid = w.metadata.get("msg_id")
                        if wid not in seen_wa_ids:
                            wa_results.append(w)
                            seen_wa_ids.add(wid)
                except Exception:
                    pass

            if email_results:
                parts.append(f"\n--- RECENT EMAILS from connected people ({len(email_results)}) ---")
                for ctx in email_results[:5]:
                    parts.append(ctx.content[:500])
            if wa_results:
                parts.append(f"\n--- RECENT WHATSAPP from connected people ({len(wa_results)}) ---")
                for ctx in wa_results[:5]:
                    parts.append(ctx.content[:500])
            if not email_results and not wa_results:
                parts.append("\n[No recent emails or WhatsApp from connected people found]")

        return "\n".join(parts)

    # -- PLUGINS-1: Web search --

    def _web_search(self, inp: dict) -> str:
        """Search the web via Tavily API."""
        try:
            from tavily import TavilyClient
        except ImportError:
            return json.dumps({"error": "tavily-python not installed"})

        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            return json.dumps({"error": "Web search not configured (TAVILY_API_KEY missing)"})

        try:
            client = TavilyClient(api_key=api_key)
            query = inp.get("query", "")
            max_results = min(inp.get("max_results", 5), 10)
            depth = inp.get("search_depth", "basic")

            results = client.search(
                query=query,
                max_results=max_results,
                search_depth=depth,
            )

            parts = [f"--- WEB SEARCH: '{query}' ({len(results.get('results', []))} results) ---"]
            for r in results.get("results", []):
                title = r.get("title", "")
                url = r.get("url", "")
                content = r.get("content", "")[:1500]
                parts.append(f"[{title}] ({url})\n{content}")

            return "\n\n".join(parts) if len(parts) > 1 else "[No web results found]"
        except Exception as e:
            return json.dumps({"error": f"Web search failed: {str(e)}"})

    # -- PLUGINS-1: Document reader --

    def _read_document(self, inp: dict) -> str:
        """Read and extract text from a document (email attachment or file path)."""
        email_query = inp.get("email_query", "")
        if email_query:
            return self._read_email_attachment(email_query)

        file_path = inp.get("file_path", "")
        if file_path:
            return self._read_file(file_path)

        return json.dumps({"error": "Provide either email_query or file_path"})

    def _read_email_attachment(self, query: str) -> str:
        """Find the most recent email matching query that has attachments, return the attachment text."""
        import psycopg2.extras
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            conn = store._get_conn()
            if not conn:
                return json.dumps({"error": "Database unavailable"})
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                # Search emails that contain attachment sections in their body
                cur.execute("""
                    SELECT subject, sender_name, sender_email, received_date, full_body
                    FROM email_messages
                    WHERE (subject ILIKE %s OR sender_name ILIKE %s OR sender_email ILIKE %s)
                      AND full_body LIKE '%%=== ATTACHMENTS ===%'
                    ORDER BY received_date DESC
                    LIMIT 1
                """, (f"%{query}%", f"%{query}%", f"%{query}%"))
                row = cur.fetchone()
                cur.close()
                if not row:
                    return json.dumps({"result": f"No email with attachment found matching '{query}'"})

                # Extract attachment section from full_body
                body = row["full_body"] or ""
                att_marker = "=== ATTACHMENTS ==="
                att_idx = body.find(att_marker)
                if att_idx >= 0:
                    attachment_text = body[att_idx + len(att_marker):].strip()
                else:
                    attachment_text = body

                return (
                    f"--- DOCUMENT from email ---\n"
                    f"From: {row['sender_name'] or ''} <{row['sender_email'] or ''}>\n"
                    f"Subject: {row['subject'] or ''}\n"
                    f"Date: {row['received_date'] or ''}\n\n"
                    f"{attachment_text[:8000]}"
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

    def _search_documents(self, inp: dict) -> str:
        """Search documents table for full documents with optional type/matter filter (SPECIALIST-UPGRADE-1B)."""
        query = inp.get("query", "")
        doc_type = inp.get("document_type")
        matter = inp.get("matter_slug")

        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            conn = store._get_conn()
            if not conn:
                return json.dumps({"error": "Database unavailable"})
            try:
                cur = conn.cursor()
                conditions = ["full_text IS NOT NULL"]
                params = []

                if doc_type:
                    conditions.append("document_type = %s")
                    params.append(doc_type)
                if matter:
                    conditions.append("matter_slug ILIKE %s")
                    params.append(f"%{matter}%")
                if query:
                    conditions.append("(full_text ILIKE %s OR filename ILIKE %s OR %s = ANY(parties))")
                    params.extend([f"%{query}%", f"%{query}%", query])

                where = " AND ".join(conditions)
                cur.execute(f"""
                    SELECT d.id, d.filename, d.source_path, d.document_type,
                           d.matter_slug, d.parties, d.token_count,
                           LEFT(d.full_text, 12000),
                           de.structured_data
                    FROM documents d
                    LEFT JOIN document_extractions de ON de.document_id = d.id
                    WHERE {where}
                    ORDER BY d.ingested_at DESC
                    LIMIT 3
                """, params)
                rows = cur.fetchall()
                cur.close()

                if not rows:
                    return f"[No documents found matching '{query}']"

                parts = [f"--- Documents ({len(rows)} results) ---"]
                for doc_id, fname, spath, dtype, mslug, parties, tokens, text, extraction in rows:
                    meta = f"[Document: {fname}"
                    if dtype:
                        meta += f", type={dtype}"
                    if mslug:
                        meta += f", matter={mslug}"
                    if parties:
                        meta += f", parties={', '.join(parties)}"
                    meta += "]"

                    parts.append(f"[SOURCE:{meta}]")
                    if text:
                        parts.append(text)
                        if tokens and tokens > 3000:
                            parts.append("[TRUNCATED — full document available]")
                    if extraction:
                        parts.append(f"\n--- Structured Extraction ---\n{json.dumps(extraction, indent=2, default=str)}")
                    parts.append("[/SOURCE]")

                return "\n".join(parts)
            finally:
                store._put_conn(conn)
        except Exception as e:
            return json.dumps({"error": f"Document search failed: {str(e)}"})

    def _clickup_create(self, inp: dict) -> str:
        """Create a ClickUp task in BAKER space (Handoff Notes list). CLICKUP-CREATE-1."""
        name = inp.get("name", "Untitled Task")
        description = inp.get("description", "")
        priority = inp.get("priority", 3)
        due_date_str = inp.get("due_date")

        due_ms = None
        if due_date_str:
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(due_date_str.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                due_ms = int(dt.timestamp() * 1000)
            except (ValueError, TypeError):
                pass

        try:
            from clickup_client import ClickUpClient
            client = ClickUpClient._get_global_instance()
            result = client.create_task(
                list_id="901521426367",  # Handoff Notes list
                name=name,
                description=description,
                priority=priority,
                due_date=due_ms,
            )
            if result:
                task_id = result.get("id", "unknown")
                task_url = result.get("url", f"https://app.clickup.com/t/{task_id}")
                prio_labels = {1: "Urgent", 2: "High", 3: "Normal", 4: "Low"}
                parts = [f"ClickUp task created: **{name}**", f"- ID: {task_id}"]
                if priority:
                    parts.append(f"- Priority: {prio_labels.get(priority, str(priority))}")
                if due_date_str:
                    parts.append(f"- Due: {due_date_str}")
                parts.append(f"- [Open in ClickUp]({task_url})")
                return "\n".join(parts)
            return "Failed to create task in ClickUp."
        except Exception as e:
            logger.error(f"clickup_create failed: {e}")
            return json.dumps({"error": f"ClickUp create failed: {str(e)}"})

    @staticmethod
    def _format_contexts(contexts, label: str) -> str:
        if not contexts:
            return f"[No {label.lower()} results found]"
        parts = [f"--- {label} ({len(contexts)} results) ---"]
        for ctx in contexts:
            source_label = _build_source_label(ctx.metadata, ctx.source)
            # SPECIALIST-UPGRADE-1A: enriched full-text results get 12K chars (~3K tokens)
            if ctx.metadata.get("enriched"):
                content = ctx.content[:12000]
                if len(ctx.content) > 12000:
                    content += "\n[TRUNCATED — full document available]"
            else:
                content = ctx.content[:2000]
            parts.append(f"[SOURCE:{source_label}]\n{content}\n[/SOURCE]")
        return "\n".join(parts)


def _build_source_label(metadata: dict, source: str = "") -> str:
    """Build human-readable source label from chunk metadata for citations."""
    content_type = metadata.get("content_type", source or "")

    if "email" in content_type.lower():
        sender = metadata.get("sender", metadata.get("sender_name", "Unknown"))
        subject = metadata.get("subject", "")[:40]
        date = (metadata.get("date", "") or "")[:10]
        return f"Email from {sender}: {subject}, {date}".rstrip(", ")

    elif "meeting" in content_type.lower() or "transcript" in content_type.lower():
        title = metadata.get("title", metadata.get("label", "Meeting"))[:40]
        date = (metadata.get("date", "") or "")[:10]
        return f"Meeting: {title}, {date}".rstrip(", ")

    elif "whatsapp" in content_type.lower():
        sender = metadata.get("sender", metadata.get("author", "Unknown"))
        date = (metadata.get("date", "") or "")[:10]
        return f"WhatsApp from {sender}, {date}".rstrip(", ")

    elif "clickup" in content_type.lower():
        name = metadata.get("name", metadata.get("label", "Task"))[:40]
        return f"ClickUp: {name}"

    elif "document" in content_type.lower():
        label = metadata.get("label", metadata.get("filename", "Document"))[:40]
        return f"Document: {label}"

    else:
        label = metadata.get("label", content_type or source or "Source")[:40]
        date = (metadata.get("date", "") or "")[:10]
        return f"{label}, {date}".rstrip(", ") if date else label


# ─────────────────────────────────────────────────
# Agent Result
# ─────────────────────────────────────────────────

@dataclass
class AgentResult:
    """Returned by run_agent_loop()."""
    answer: str
    tool_calls: list = field(default_factory=list)   # [{name, input, duration_ms}]
    iterations: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    elapsed_ms: int = 0
    timed_out: bool = False


# ─────────────────────────────────────────────────
# Agent Loop — Blocking (WhatsApp)
# ─────────────────────────────────────────────────

def run_agent_loop(
    question: str,
    system_prompt: str,
    history: Optional[list] = None,
    max_iterations: int = 3,
    timeout_override: float = None,
) -> AgentResult:
    """
    Blocking agent loop.  Returns AgentResult with the final text answer.
    Used by WhatsApp (_handle_director_question).
    """
    from orchestrator.cost_monitor import log_api_cost, check_circuit_breaker
    from orchestrator.agent_metrics import log_tool_call

    t0 = time.time()
    timeout = timeout_override or AGENT_TIMEOUT_SECONDS
    executor = ToolExecutor()
    claude = anthropic.Anthropic(api_key=config.claude.api_key)

    messages = []
    for msg in (history or []):
        role = msg.get("role", "user") if isinstance(msg, dict) else "user"
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})

    tool_log = []
    total_in = 0
    total_out = 0

    for iteration in range(max_iterations):
        # Timeout check (PM review item #1)
        elapsed = time.time() - t0
        if elapsed > timeout:
            logger.warning(f"Agent loop timed out after {elapsed:.1f}s, {iteration} iterations")
            return AgentResult(
                answer="",
                tool_calls=tool_log,
                iterations=iteration,
                total_input_tokens=total_in,
                total_output_tokens=total_out,
                elapsed_ms=int(elapsed * 1000),
                timed_out=True,
            )

        # PHASE-4A: Circuit breaker check
        allowed, _daily = check_circuit_breaker()
        if not allowed:
            logger.error("Agent loop blocked by cost circuit breaker")
            return AgentResult(
                answer="Baker API budget exceeded for today. Resuming tomorrow.",
                tool_calls=tool_log, iterations=iteration,
                total_input_tokens=total_in, total_output_tokens=total_out,
                elapsed_ms=int((time.time() - t0) * 1000),
            )

        response = claude.messages.create(
            model=config.claude.model,
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
            tools=TOOL_DEFINITIONS,
        )

        total_in += response.usage.input_tokens
        total_out += response.usage.output_tokens

        # PHASE-4A: Log API cost
        log_api_cost(config.claude.model, response.usage.input_tokens,
                     response.usage.output_tokens, source="agent_loop")

        # Check stop reason
        if response.stop_reason == "end_turn":
            # Extract text from content blocks
            text_parts = [b.text for b in response.content if b.type == "text"]
            answer = "".join(text_parts)
            elapsed_ms = int((time.time() - t0) * 1000)
            logger.info(
                f"Agent loop done: {iteration + 1} iterations, "
                f"{len(tool_log)} tool calls, {elapsed_ms}ms, "
                f"tokens: {total_in}in/{total_out}out"
            )
            return AgentResult(
                answer=answer,
                tool_calls=tool_log,
                iterations=iteration + 1,
                total_input_tokens=total_in,
                total_output_tokens=total_out,
                elapsed_ms=elapsed_ms,
            )

        if response.stop_reason == "tool_use":
            # Build assistant message with all content blocks
            assistant_content = []
            tool_uses = []
            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
                    tool_uses.append(block)

            messages.append({"role": "assistant", "content": assistant_content})

            # Execute tools and build tool_result message
            tool_results = []
            for tu in tool_uses:
                tool_t0 = time.time()
                tool_ok = True
                tool_err = None
                try:
                    result_text = executor.execute(tu.name, tu.input)
                except Exception as e:
                    tool_ok = False
                    tool_err = str(e)[:500]
                    result_text = f"Error: {tool_err}"
                tool_ms = int((time.time() - tool_t0) * 1000)
                tool_log.append({
                    "name": tu.name,
                    "input": tu.input,
                    "duration_ms": tool_ms,
                })
                logger.info(f"Tool {tu.name}: {tool_ms}ms")
                # PHASE-4A: Log tool call metrics
                log_tool_call(tu.name, latency_ms=tool_ms,
                              success=tool_ok, error_message=tool_err,
                              source="agent_loop")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result_text,
                })

            messages.append({"role": "user", "content": tool_results})
            continue

        # Unexpected stop reason — treat as done
        text_parts = [b.text for b in response.content if b.type == "text"]
        answer = "".join(text_parts) or "I wasn't able to complete the search."
        elapsed_ms = int((time.time() - t0) * 1000)
        return AgentResult(
            answer=answer,
            tool_calls=tool_log,
            iterations=iteration + 1,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            elapsed_ms=elapsed_ms,
        )

    # Exhausted max_iterations without end_turn — return whatever we have
    elapsed_ms = int((time.time() - t0) * 1000)
    logger.warning(f"Agent loop hit max_iterations ({max_iterations})")
    return AgentResult(
        answer="I searched multiple sources but couldn't fully resolve your question. Here's what I found so far.",
        tool_calls=tool_log,
        iterations=max_iterations,
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        elapsed_ms=elapsed_ms,
    )


# ─────────────────────────────────────────────────
# Agent Loop — Streaming (Scan SSE)
# ─────────────────────────────────────────────────

def run_agent_loop_streaming(
    question: str,
    system_prompt: str,
    history: Optional[list] = None,
    max_iterations: int = 5,
    timeout_override: float = None,
) -> Generator[dict, None, AgentResult]:
    """
    Streaming agent loop for Scan SSE.

    Yields dicts:
      {"token": "text chunk"}   — stream to client
      {"tool_call": "name"}     — optional: frontend can show loading indicator

    Returns AgentResult (accessible after generator exhaustion via .value on
    StopIteration, but the caller should track state via the yielded dicts).

    The final AgentResult is also yielded as {"_agent_result": AgentResult}.
    """
    from orchestrator.cost_monitor import log_api_cost, check_circuit_breaker
    from orchestrator.agent_metrics import log_tool_call

    t0 = time.time()
    timeout = timeout_override or AGENT_TIMEOUT_SECONDS
    executor = ToolExecutor()
    claude = anthropic.Anthropic(api_key=config.claude.api_key)

    messages = []
    for msg in (history or []):
        role = msg.get("role", "user") if isinstance(msg, dict) else "user"
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})

    tool_log = []
    total_in = 0
    total_out = 0
    full_answer = ""

    for iteration in range(max_iterations):
        # Timeout check
        elapsed = time.time() - t0
        if elapsed > timeout:
            logger.warning(f"Agent streaming timed out after {elapsed:.1f}s")
            result = AgentResult(
                answer=full_answer,
                tool_calls=tool_log,
                iterations=iteration,
                total_input_tokens=total_in,
                total_output_tokens=total_out,
                elapsed_ms=int(elapsed * 1000),
                timed_out=True,
            )
            yield {"_agent_result": result}
            return

        # PHASE-4A: Circuit breaker check
        allowed, _daily = check_circuit_breaker()
        if not allowed:
            yield {"token": "Baker API budget exceeded for today. Resuming tomorrow."}
            result = AgentResult(
                answer="Baker API budget exceeded for today. Resuming tomorrow.",
                tool_calls=tool_log, iterations=iteration,
                total_input_tokens=total_in, total_output_tokens=total_out,
                elapsed_ms=int((time.time() - t0) * 1000),
            )
            yield {"_agent_result": result}
            return

        # Use non-streaming API to get tool_use blocks reliably
        # (streaming with tools is tricky — partial tool_use blocks)
        response = claude.messages.create(
            model=config.claude.model,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            tools=TOOL_DEFINITIONS,
        )

        total_in += response.usage.input_tokens
        total_out += response.usage.output_tokens

        # PHASE-4A: Log API cost
        log_api_cost(config.claude.model, response.usage.input_tokens,
                     response.usage.output_tokens, source="agent_loop_streaming")

        if response.stop_reason == "end_turn":
            # Stream the final text to client
            for block in response.content:
                if block.type == "text" and block.text:
                    full_answer += block.text
                    yield {"token": block.text}

            elapsed_ms = int((time.time() - t0) * 1000)
            logger.info(
                f"Agent streaming done: {iteration + 1} iterations, "
                f"{len(tool_log)} tool calls, {elapsed_ms}ms, "
                f"tokens: {total_in}in/{total_out}out"
            )
            result = AgentResult(
                answer=full_answer,
                tool_calls=tool_log,
                iterations=iteration + 1,
                total_input_tokens=total_in,
                total_output_tokens=total_out,
                elapsed_ms=elapsed_ms,
            )
            yield {"_agent_result": result}
            return

        if response.stop_reason == "tool_use":
            # Notify frontend of tool call (loading indicator)
            assistant_content = []
            tool_uses = []
            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                    # Stream any thinking text that comes before tool calls
                    if block.text:
                        full_answer += block.text
                        yield {"token": block.text}
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
                    tool_uses.append(block)
                    yield {"tool_call": block.name}

            messages.append({"role": "assistant", "content": assistant_content})

            # Execute tools
            tool_results = []
            for tu in tool_uses:
                tool_t0 = time.time()
                tool_ok = True
                tool_err = None
                try:
                    result_text = executor.execute(tu.name, tu.input)
                except Exception as e:
                    tool_ok = False
                    tool_err = str(e)[:500]
                    result_text = f"Error: {tool_err}"
                tool_ms = int((time.time() - tool_t0) * 1000)
                tool_log.append({
                    "name": tu.name,
                    "input": tu.input,
                    "duration_ms": tool_ms,
                })
                logger.info(f"Tool {tu.name}: {tool_ms}ms")
                # PHASE-4A: Log tool call metrics
                log_tool_call(tu.name, latency_ms=tool_ms,
                              success=tool_ok, error_message=tool_err,
                              source="agent_loop_streaming")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result_text,
                })

            messages.append({"role": "user", "content": tool_results})
            continue

        # Unexpected stop — stream whatever text we got
        for block in response.content:
            if block.type == "text" and block.text:
                full_answer += block.text
                yield {"token": block.text}
        break

    elapsed_ms = int((time.time() - t0) * 1000)
    result = AgentResult(
        answer=full_answer,
        tool_calls=tool_log,
        iterations=max_iterations,
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        elapsed_ms=elapsed_ms,
    )
    yield {"_agent_result": result}


def is_agentic_rag_enabled() -> bool:
    """Check feature flag — can be called from dashboard.py and waha_webhook.py."""
    return _AGENTIC_RAG
