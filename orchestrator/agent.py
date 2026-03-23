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
    # A7: Structured data query tool (Session 26)
    {
        "name": "query_baker_data",
        "description": (
            "Query Baker's structured data (PostgreSQL). Use for statistics, counts, "
            "trends, and operational questions that need exact numbers.\n\n"
            "Examples:\n"
            "- 'How many alerts this week by source?'\n"
            "- 'What matters have the most overdue deadlines?'\n"
            "- 'How many emails were processed in the last 7 days?'\n"
            "- 'Show me contacts with the most interactions'\n\n"
            "Returns structured results. Only SELECT queries (read-only)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Natural language question about Baker's data",
                },
            },
            "required": ["question"],
        },
    },
    # A1: Create deadline from agent loop (Session 26)
    {
        "name": "create_deadline",
        "description": (
            "Create a new deadline or obligation in Baker's tracking system. "
            "Use when analysis reveals a date-bound action item, or when the "
            "Director asks to track something with a due date.\n\n"
            "Examples:\n"
            "- 'Track that the Hagenauer response is due March 25'\n"
            "- 'Create a deadline for the IHIF follow-up emails'\n"
            "- 'Remind me to review the term sheet by Friday'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "What needs to happen — clear, actionable",
                },
                "due_date": {
                    "type": "string",
                    "description": "Due date in YYYY-MM-DD format",
                },
                "priority": {
                    "type": "string",
                    "description": "critical, high, or normal (default: normal)",
                },
            },
            "required": ["description", "due_date"],
        },
    },
    # A1: Draft email tool (Session 26)
    {
        "name": "draft_email",
        "description": (
            "Draft an email for the Director's review and approval. "
            "Baker queues the draft — Director must approve before sending.\n\n"
            "Use when analysis suggests an email should be sent:\n"
            "- Follow-up after a meeting\n"
            "- Response to a counterparty\n"
            "- Status update to stakeholders\n"
            "- Request for information\n\n"
            "External emails always require Director approval. "
            "Internal (@brisengroup.com) can auto-send."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                },
                "body": {
                    "type": "string",
                    "description": "Email body (plain text, professional tone)",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
    # A3: Calendar write tool (Session 26)
    {
        "name": "create_calendar_event",
        "description": (
            "Create an event on the Director's Google Calendar. Use for:\n"
            "- Blocking focus time ('Block 2 hours tomorrow morning for strategy review')\n"
            "- Scheduling follow-ups ('Add a call with Piras on Thursday at 3pm')\n"
            "- Setting reminders ('Block 15 min Friday to review the term sheet')\n\n"
            "Returns confirmation with event link."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Event title (e.g. 'Focus: Kempinski strategy review')",
                },
                "start": {
                    "type": "string",
                    "description": "Start time in ISO format (YYYY-MM-DDTHH:MM, e.g. '2026-03-20T09:00')",
                },
                "end": {
                    "type": "string",
                    "description": "End time in ISO format. If not provided, defaults to 1 hour after start.",
                },
                "description": {
                    "type": "string",
                    "description": "Optional event description/notes",
                },
            },
            "required": ["title", "start"],
        },
    },
    # C1: LinkedIn enrichment tool (Session 28)
    {
        "name": "enrich_linkedin",
        "description": (
            "Look up a person's professional profile via LinkedIn enrichment API. "
            "Returns current title, company, work history, education, skills, "
            "location, and profile photo.\n\n"
            "Use for:\n"
            "- Pre-meeting research: 'Who is Peter Storer from NVIDIA?'\n"
            "- Contact enrichment: 'What does Thomas Hagenauer do?'\n"
            "- Background checks: 'What's Marco's career history?'\n\n"
            "Requires LINKEDIN_API_KEY to be configured. "
            "Combine with web_search for a comprehensive dossier."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Person's full name (e.g. 'Peter Storer')",
                },
                "company": {
                    "type": "string",
                    "description": "Current or recent company (helps disambiguate common names). Optional.",
                },
                "linkedin_url": {
                    "type": "string",
                    "description": "Direct LinkedIn profile URL if known. Optional.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "browse_website",
        "description": (
            "Browse a website using Chrome on the Director's machine. "
            "Chrome has authenticated sessions (logged into WhatsApp, Gmail, Dropbox, WHOOP, etc.). "
            "Use this to:\n"
            "- Read authenticated pages the Director is logged into\n"
            "- Check order status, account info, prices\n"
            "- Extract content from JS-rendered pages\n\n"
            "Returns the page title and text content. "
            "This is a READ-ONLY tool. To interact with the page (click, fill, submit), "
            "use the browser_action tool instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full URL to navigate to (e.g. 'https://shop.whoop.com/us/en/products/')",
                },
                "wait_seconds": {
                    "type": "integer",
                    "description": "Seconds to wait for page to load (default 3, use 5-8 for heavy JS pages)",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "browser_action",
        "description": (
            "Perform an interactive action on the current Chrome page (click, fill form, submit). "
            "Use AFTER browse_website has loaded the target page.\n\n"
            "ALL browser actions require Director confirmation before executing. "
            "The action is queued with a screenshot and the Director confirms or cancels "
            "via the Dashboard/Feed. Actions expire after 10 minutes.\n\n"
            "Supported action types:\n"
            "- click: Click an element by CSS selector or visible text\n"
            "- fill: Fill a form field with a value\n"
            "- click_and_fill: Fill a field then click a button (e.g. search)\n\n"
            "After calling this tool, tell the Director that the action is queued "
            "for their confirmation on the Dashboard."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "enum": ["click", "fill", "click_and_fill"],
                    "description": "Type of interaction to perform.",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector for the target element (e.g. 'button.add-to-cart', '#email-input'). "
                                   "Use this OR target_text, not both.",
                },
                "target_text": {
                    "type": "string",
                    "description": "Visible text of the element to click (e.g. 'Add to Cart', 'Submit Order'). "
                                   "Used when CSS selector is unknown.",
                },
                "value": {
                    "type": "string",
                    "description": "Value to fill into the field (for 'fill' and 'click_and_fill' actions).",
                },
                "description": {
                    "type": "string",
                    "description": "Human-readable description of what this action does (shown to Director for confirmation). "
                                   "E.g. 'Click Add to Cart for WHOOP 4.0 Band ($49)'",
                },
            },
            "required": ["action_type", "description"],
        },
    },
]

# Agent loop tools — exclude clickup_create (Director prefers results in artifact panel,
# not ClickUp task creation). Specialists keep clickup_create via their own tool lists.
AGENT_TOOLS = [t for t in TOOL_DEFINITIONS if t["name"] != "clickup_create"]


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
            elif tool_name == "query_baker_data":
                return self._query_baker_data(tool_input)
            elif tool_name == "create_deadline":
                return self._create_deadline(tool_input)
            elif tool_name == "create_calendar_event":
                return self._create_calendar_event(tool_input)
            elif tool_name == "draft_email":
                return self._draft_email(tool_input)
            elif tool_name == "enrich_linkedin":
                return self._enrich_linkedin(tool_input)
            elif tool_name == "browse_website":
                return self._browse_website(tool_input)
            elif tool_name == "browser_action":
                return self._browser_action(tool_input)
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
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                for v in vips:
                    # Calculate silence period
                    last_contact = v.get("last_contact_date")
                    if last_contact:
                        if last_contact.tzinfo is None:
                            last_contact = last_contact.replace(tzinfo=timezone.utc)
                        days_silent = (now - last_contact).days
                        if days_silent > 30:
                            v["_silence_warning"] = f"NO CONTACT FOR {days_silent} DAYS — relationship may be cooling"
                        elif days_silent > 14:
                            v["_days_since_contact"] = f"{days_silent} days"
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

        # 4. Sentiment trajectory (SENTIMENT-TRAJECTORY-1)
        try:
            from orchestrator.sentiment_scorer import get_contact_sentiment
            sentiment = get_contact_sentiment(name)
            if sentiment and sentiment.get("total_scored", 0) > 0:
                trend = sentiment.get("trend", "unknown")
                avg = sentiment.get("avg_sentiment", 0)
                recent = sentiment.get("recent_avg", avg)
                parts.append(
                    f"[SENTIMENT] Trend: {trend} | Avg: {avg}/5 | Recent: {recent}/5 "
                    f"| Scored: {sentiment.get('total_scored', 0)} messages"
                )
                if trend == "cooling":
                    parts.append("⚠ SENTIMENT COOLING — tone in recent messages is more negative than historical average")
                elif trend == "warming":
                    parts.append("✓ SENTIMENT WARMING — tone in recent messages is more positive than historical average")
        except Exception as e:
            logger.debug(f"Sentiment lookup for contact failed: {e}")

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

        # B4: Inject memory summaries if available
        try:
            import psycopg2.extras as _pge
            conn = self._retriever._get_pg_conn()
            cur = conn.cursor(cursor_factory=_pge.RealDictCursor)
            cur.execute("""
                SELECT contact_name, summary, interaction_count, period_start, period_end
                FROM memory_summaries
                WHERE matter_slug = %s
                ORDER BY interaction_count DESC
                LIMIT 3
            """, (matter.get("matter_name", ""),))
            summaries = [dict(r) for r in cur.fetchall()]
            cur.close()
            if summaries:
                parts.append(f"\n--- HISTORICAL SUMMARIES ({len(summaries)}) ---")
                for s in summaries:
                    ps = s["period_start"].strftime("%Y-%m-%d") if s.get("period_start") else "?"
                    pe = s["period_end"].strftime("%Y-%m-%d") if s.get("period_end") else "?"
                    parts.append(
                        f"[{s.get('contact_name', 'general')}] ({ps} to {pe}, "
                        f"{s.get('interaction_count', 0)} interactions):\n{s['summary'][:1500]}"
                    )
        except Exception:
            pass  # Table may not exist yet — that's fine

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
                conditions = ["full_text IS NOT NULL", "COALESCE(content_class, 'document') = 'document'"]
                params = []

                if doc_type:
                    conditions.append("document_type = %s")
                    params.append(doc_type)
                if matter:
                    conditions.append("matter_slug ILIKE %s")
                    params.append(f"%{matter}%")
                if query:
                    # FTS: use tsvector GIN index for fast full-text search, fall back to ILIKE for filename/parties
                    fts_terms = " & ".join(w for w in query.split() if w.strip())
                    conditions.append(
                        "(search_vector @@ to_tsquery('simple', %s) OR filename ILIKE %s OR %s = ANY(parties))"
                    )
                    params.extend([fts_terms, f"%{query}%", query])

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

    def _query_baker_data(self, inp: dict) -> str:
        """A7: Answer structured data questions by generating and running SQL."""
        question = inp.get("question", "")
        if not question:
            return "[Please provide a question about Baker's data]"

        # Use Haiku to generate a safe SELECT query
        import anthropic
        try:
            client = anthropic.Anthropic(api_key=config.claude.api_key)
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                system=(
                    "Generate a PostgreSQL SELECT query to answer the user's question about Baker's data. "
                    "ONLY SELECT — no mutations. Available tables:\n"
                    "- alerts (id, tier, title, status, source, matter_slug, created_at)\n"
                    "- deadlines (id, description, due_date, status, priority, confidence, severity, source_type)\n"
                    "- vip_contacts (id, name, email, tier, domain, last_contact_date)\n"
                    "- contact_interactions (id, contact_id, interaction_type, subject, interaction_date)\n"
                    "- email_messages (id, subject, sender, created_at)\n"
                    "- whatsapp_messages (id, sender_name, body, timestamp, is_director)\n"
                    "- matter_registry (matter_name, status, keywords, people)\n"
                    "- baker_tasks (id, title, capability_slug, status, created_at)\n"
                    "- documents (id, filename, doc_type, matter_slug, created_at)\n"
                    "- sent_emails (id, to_address, subject, created_at, replied_at)\n\n"
                    "Return ONLY the SQL query, nothing else. Always include LIMIT (max 20)."
                ),
                messages=[{"role": "user", "content": question}],
            )
            try:
                from orchestrator.cost_monitor import log_api_cost
                log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="query_baker_data")
            except Exception:
                pass
            sql = resp.content[0].text.strip()
            # Strip markdown fences
            if sql.startswith("```"):
                sql = "\n".join(sql.split("\n")[1:-1])
            sql = sql.strip().rstrip(";")

            # Safety: only SELECT
            if not sql.upper().startswith("SELECT"):
                return "[Safety: only SELECT queries allowed]"

            # Execute
            from memory.store_back import SentinelStoreBack
            import psycopg2.extras
            store = SentinelStoreBack._get_global_instance()
            conn = store._get_conn()
            if not conn:
                return "[Database unavailable]"
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute(sql)
                rows = [dict(r) for r in cur.fetchall()]
                cur.close()

                if not rows:
                    return f"Query returned no results.\nSQL: {sql}"

                # Format results
                parts = [f"Query: {sql}", f"Results ({len(rows)} rows):"]
                for row in rows:
                    parts.append(str(row))
                return "\n".join(parts)
            finally:
                store._put_conn(conn)
        except Exception as e:
            logger.error(f"query_baker_data failed: {e}")
            return json.dumps({"error": f"Data query failed: {str(e)}"})

    def _create_deadline(self, inp: dict) -> str:
        """A1: Create a deadline from the agent loop."""
        description = inp.get("description", "")
        due_date_str = inp.get("due_date", "")
        priority = inp.get("priority", "normal")

        if not description or not due_date_str:
            return "[Both description and due_date are required]"

        try:
            from models.deadlines import insert_deadline
            from datetime import datetime, timezone

            due_date = datetime.fromisoformat(due_date_str)
            if due_date.tzinfo is None:
                due_date = due_date.replace(tzinfo=timezone.utc)

            dl_id = insert_deadline(
                description=description,
                due_date=due_date,
                source_type="agent",
                confidence="hard",
                priority=priority,
            )
            if dl_id:
                return f"Deadline created (#{dl_id}): **{description}** — due {due_date_str}, priority {priority}"
            return "Failed to create deadline."
        except Exception as e:
            logger.error(f"create_deadline failed: {e}")
            return json.dumps({"error": f"Deadline creation failed: {str(e)}"})

    def _draft_email(self, inp: dict) -> str:
        """A1: Queue an email draft for Director approval."""
        to = inp.get("to", "")
        subject = inp.get("subject", "")
        body = inp.get("body", "")

        if not to or not subject or not body:
            return "[to, subject, and body are all required]"

        try:
            from orchestrator.action_handler import _save_pending_draft
            _save_pending_draft(
                to_address=to,
                subject=subject,
                body=body,
                content_req="",
                channel="agent",
            )
            is_internal = to.lower().endswith("@brisengroup.com")
            if is_internal:
                return (
                    f"Email draft queued (internal — will auto-send):\n"
                    f"- **To:** {to}\n- **Subject:** {subject}\n"
                    f"- Preview: {body[:100]}..."
                )
            return (
                f"Email draft queued for Director approval:\n"
                f"- **To:** {to}\n- **Subject:** {subject}\n"
                f"- Preview: {body[:100]}...\n\n"
                f"Director can approve via chat ('send it') or WhatsApp."
            )
        except Exception as e:
            logger.error(f"draft_email failed: {e}")
            return json.dumps({"error": f"Email draft failed: {str(e)}"})

    def _create_calendar_event(self, inp: dict) -> str:
        """A3: Create a Google Calendar event from the agent loop."""
        title = inp.get("title", "Baker Event")
        start_str = inp.get("start", "")
        end_str = inp.get("end", "")
        description = inp.get("description", "")

        if not start_str:
            return "[start time is required (ISO format: YYYY-MM-DDTHH:MM)]"

        try:
            from triggers.calendar_trigger import _get_calendar_service
            from datetime import datetime, timezone, timedelta

            start = datetime.fromisoformat(start_str)
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)

            if end_str:
                end = datetime.fromisoformat(end_str)
                if end.tzinfo is None:
                    end = end.replace(tzinfo=timezone.utc)
            else:
                end = start + timedelta(hours=1)

            event = {
                "summary": title,
                "description": description or "Created by Baker",
                "start": {"dateTime": start.isoformat(), "timeZone": "Europe/Zurich"},
                "end": {"dateTime": end.isoformat(), "timeZone": "Europe/Zurich"},
                "reminders": {"useDefault": True},
            }

            service = _get_calendar_service()
            result = service.events().insert(calendarId="primary", body=event).execute()
            event_link = result.get("htmlLink", "")

            return (
                f"Calendar event created: **{title}**\n"
                f"- When: {start.strftime('%a %b %-d, %H:%M')} – {end.strftime('%H:%M')}\n"
                f"- [Open in Calendar]({event_link})"
            )
        except Exception as e:
            logger.error(f"create_calendar_event failed: {e}")
            return json.dumps({"error": f"Calendar event creation failed: {str(e)}"})

    def _enrich_linkedin(self, inp: dict) -> str:
        """C1: Look up a person's LinkedIn profile via enrichment API."""
        name = inp.get("name", "")
        company = inp.get("company", "")
        linkedin_url = inp.get("linkedin_url", "")

        if not name and not linkedin_url:
            return "[Either name or linkedin_url is required]"

        try:
            from tools.linkedin_client import get_enricher
            enricher = get_enricher()
            if not enricher.is_available():
                return json.dumps({"error": "LinkedIn enrichment not configured (LINKEDIN_API_KEY missing)"})

            profile = enricher.enrich_person(
                name=name, company=company, linkedin_url=linkedin_url,
            )
            if not profile:
                return f"[No LinkedIn profile found for '{name}'" + (f" at {company}]" if company else "]")

            # Also update Baker's contacts with enriched data
            try:
                from memory.store_back import SentinelStoreBack
                store = SentinelStoreBack._get_global_instance()
                updates = {}
                if profile.title:
                    updates["role"] = f"{profile.title} at {profile.company}" if profile.company else profile.title
                if profile.location:
                    updates["location"] = profile.location
                if profile.linkedin_url:
                    updates["linkedin_url"] = profile.linkedin_url
                if updates:
                    store.upsert_contact(profile.name or name, updates)
                    logger.info(f"Contact updated with LinkedIn data: {profile.name or name}")
            except Exception as e:
                logger.debug(f"Contact update from LinkedIn failed (non-fatal): {e}")

            return f"--- LINKEDIN PROFILE ---\n{profile.to_text()}"
        except Exception as e:
            logger.error(f"enrich_linkedin failed: {e}")
            return json.dumps({"error": f"LinkedIn enrichment failed: {str(e)}"})

    def _browse_website(self, inp: dict) -> str:
        """BROWSER-AGENT-1: Browse a website via Chrome on Director's machine."""
        url = inp.get("url", "")
        wait_seconds = inp.get("wait_seconds", 3)
        if not url:
            return "[url is required]"

        try:
            from triggers.browser_client import BrowserClient
            client = BrowserClient._get_global_instance()
            result = client.fetch_chrome(url, wait_seconds=wait_seconds)
            if result.get("error"):
                return json.dumps({"error": result["error"], "hint": "Chrome bridge may be offline (requires MacBook to be on with Tailscale Funnel running)"})
            title = result.get("title", "")
            content = result.get("content", "")
            if not content:
                return f"[Page loaded but no text content extracted. Title: {title}]"
            return f"--- WEB PAGE: {title} ---\nURL: {url}\n\n{content}"
        except Exception as e:
            logger.error(f"browse_website failed: {e}")
            return json.dumps({"error": f"Browse failed: {str(e)}"})

    def _browser_action(self, inp: dict) -> str:
        """BROWSER-AGENT-1 Phase 3: Queue an interactive browser action for Director confirmation."""
        action_type = inp.get("action_type", "")
        selector = inp.get("selector", "")
        target_text = inp.get("target_text", "")
        value = inp.get("value", "")
        description = inp.get("description", "")

        if not action_type:
            return "[action_type is required (click, fill, or click_and_fill)]"
        if not description:
            return "[description is required — explain what this action does]"
        if action_type in ("fill", "click_and_fill") and not value:
            return "[value is required for fill/click_and_fill actions]"
        if not selector and not target_text:
            return "[Either selector or target_text is required to identify the target element]"

        try:
            from triggers.browser_client import BrowserClient
            from memory.store_back import SentinelStoreBack

            client = BrowserClient._get_global_instance()
            store = SentinelStoreBack._get_global_instance()

            # Take screenshot of current page state (before action)
            screenshot = client.take_screenshot(format="jpeg", quality=60)
            screenshot_b64 = screenshot.get("data_b64", "")

            # Get current page URL for context
            page_info = client.get_page_info()
            current_url = page_info.get("url", "unknown")

            # Queue the action for Director confirmation
            action_id = store.create_browser_action(
                action_type=action_type,
                description=description,
                url=current_url,
                target_selector=selector or None,
                target_text=target_text or None,
                fill_value=value or None,
                screenshot_b64=screenshot_b64 if screenshot_b64 else None,
            )

            if not action_id:
                return json.dumps({"error": "Failed to queue browser action — database error"})

            # Create an alert so it appears on Feed/Dashboard
            alert_id = store.create_alert(
                tier=2,
                title=f"Browser Action: {description[:80]}",
                body=(
                    f"Baker wants to perform a browser action:\n\n"
                    f"Action: {action_type}\n"
                    f"Page: {current_url}\n"
                    f"Target: {selector or target_text}\n"
                    f"{'Value: ' + value + chr(10) if value else ''}"
                    f"Description: {description}\n\n"
                    f"Confirm or cancel on the Dashboard. Expires in 10 minutes."
                ),
                action_required=True,
                source="browser_transaction",
                source_id=f"ba_{action_id}",
                structured_actions={
                    "type": "browser_action_confirmation",
                    "action_id": action_id,
                    "action_type": action_type,
                    "confirm_url": f"/api/browser/confirm/{action_id}",
                    "cancel_url": f"/api/browser/cancel/{action_id}",
                },
            )

            # Link the alert back to the browser action
            if alert_id:
                store.update_browser_action(action_id, status="pending_confirmation")
                # Update alert_id on the browser action
                conn = store._get_conn()
                if conn:
                    try:
                        cur = conn.cursor()
                        cur.execute("UPDATE browser_actions SET alert_id = %s WHERE id = %s", (alert_id, action_id))
                        conn.commit()
                        cur.close()
                    except Exception:
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                    finally:
                        store._put_conn(conn)

            return (
                f"[Browser action #{action_id} queued for Director confirmation]\n"
                f"Action: {action_type} — {description}\n"
                f"Page: {current_url}\n"
                f"The Director will see a confirmation card on the Dashboard/Feed with a screenshot. "
                f"The action expires in 10 minutes if not confirmed."
            )

        except Exception as e:
            logger.error(f"browser_action failed: {e}")
            return json.dumps({"error": f"Browser action failed: {str(e)}"})

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
            tools=AGENT_TOOLS,
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
            tools=AGENT_TOOLS,
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
