#!/usr/bin/env python3
"""
Baker MCP Server — Read + Write access to Baker AI's PostgreSQL database.

Exposes Baker's tables as queryable MCP tools for use in:
  - Cowork / Claude Desktop (via MCP config)
  - Terminal Claude Code sessions
  - Future Baker CLI clone

Read tools (17): query any Baker table.
Write tools (6): store decisions, deadlines, contacts, analyses, preferences, and VIP profiles back into Baker's memory.
Write operations use explicit INSERT/UPSERT statements — no raw SQL mutations allowed.

Environment variables (same as Baker production):
  POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER,
  POSTGRES_PASSWORD, POSTGRES_SSLMODE
  — OR —
  DATABASE_URL  (postgresql://user:pass@host:port/db?sslmode=require)

Usage:
  python baker_mcp_server.py              # stdio transport (default)
  python baker_mcp_server.py --sse 8765   # SSE transport on port 8765
"""
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse, parse_qs

import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# MCP SDK imports
# ---------------------------------------------------------------------------
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
logger = logging.getLogger("baker_mcp")

# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

def _parse_database_url(url: str) -> dict:
    """Parse DATABASE_URL into psycopg2 connect params."""
    parsed = urlparse(url)
    params = {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "dbname": parsed.path.lstrip("/"),
        "user": parsed.username,
        "password": parsed.password,
    }
    qs = parse_qs(parsed.query)
    if "sslmode" in qs:
        params["sslmode"] = qs["sslmode"][0]
    else:
        params["sslmode"] = "require"
    return params


def _get_conn_params() -> dict:
    """Build connection params from env vars."""
    database_url = os.getenv("DATABASE_URL", "")
    if database_url:
        return _parse_database_url(database_url)
    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "dbname": os.getenv("POSTGRES_DB", "sentinel"),
        "user": os.getenv("POSTGRES_USER", "sentinel"),
        "password": os.getenv("POSTGRES_PASSWORD", ""),
        "sslmode": os.getenv("POSTGRES_SSLMODE", "require"),
    }


def _query(sql: str, params: tuple = None, limit: int = 50) -> list[dict]:
    """Execute a read-only query. Returns list of dicts."""
    conn = psycopg2.connect(**_get_conn_params())
    conn.set_session(readonly=True, autocommit=True)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchmany(limit)
            return [dict(r) for r in rows]
    finally:
        conn.close()


def _write(sql: str, params: tuple = None) -> dict | None:
    """Execute a write query (INSERT/UPDATE). Returns the first row if RETURNING is used."""
    conn = psycopg2.connect(**_get_conn_params())
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            conn.commit()
            try:
                row = cur.fetchone()
                return dict(row) if row else None
            except psycopg2.ProgrammingError:
                return None
    finally:
        conn.close()


def _json_serial(obj: Any) -> str:
    """JSON serializer for datetime and other non-standard types."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return str(obj)


def _format_results(rows: list[dict], title: str = "") -> str:
    """Format query results as readable text."""
    if not rows:
        return f"{title}\nNo results found." if title else "No results found."
    header = f"{title} ({len(rows)} rows)\n{'='*60}\n" if title else ""
    lines = []
    for r in rows:
        parts = []
        for k, v in r.items():
            if v is not None:
                parts.append(f"  {k}: {v}")
        lines.append("\n".join(parts))
    return header + "\n---\n".join(lines)


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

app = Server("baker-mcp")


# ---- Tool definitions ----

TOOLS = [
    Tool(
        name="baker_deadlines",
        description="Get active deadlines from Baker's deadline register. Filter by status, priority, or date range.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter: active, dismissed, completed (default: active)", "default": "active"},
                "priority": {"type": "string", "description": "Filter: critical, high, normal, low"},
                "days_ahead": {"type": "integer", "description": "Show deadlines due within N days (default: 30)", "default": 30},
                "limit": {"type": "integer", "description": "Max rows (default: 50)", "default": 50},
            },
        },
    ),
    Tool(
        name="baker_vip_contacts",
        description="List Baker's VIP contacts — key people tracked by the system.",
        inputSchema={
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Search by name, role, or email"},
                "limit": {"type": "integer", "default": 50},
            },
        },
    ),
    Tool(
        name="baker_sent_emails",
        description="Recent emails sent by Baker. Track reply status.",
        inputSchema={
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Filter by recipient address"},
                "unreplied_only": {"type": "boolean", "description": "Only show emails awaiting reply", "default": False},
                "days": {"type": "integer", "description": "Emails from last N days (default: 7)", "default": 7},
                "limit": {"type": "integer", "default": 25},
            },
        },
    ),
    Tool(
        name="baker_actions",
        description="Baker's action log — ClickUp updates, emails sent, analyses triggered.",
        inputSchema={
            "type": "object",
            "properties": {
                "action_type": {"type": "string", "description": "Filter by type: clickup_update, email_send, analysis, etc."},
                "days": {"type": "integer", "default": 7},
                "limit": {"type": "integer", "default": 30},
            },
        },
    ),
    Tool(
        name="baker_clickup_tasks",
        description="ClickUp tasks synced by Baker. Search by name, status, or list.",
        inputSchema={
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Search task name or description"},
                "status": {"type": "string", "description": "Filter by status"},
                "list_name": {"type": "string", "description": "Filter by list name"},
                "limit": {"type": "integer", "default": 30},
            },
        },
    ),
    Tool(
        name="baker_todoist_tasks",
        description="Todoist tasks synced by Baker. Search by content, project, or priority.",
        inputSchema={
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Search task content"},
                "project_name": {"type": "string", "description": "Filter by project"},
                "priority": {"type": "integer", "description": "Filter by priority (1=normal, 4=urgent)"},
                "status": {"type": "string", "description": "active or completed", "default": "active"},
                "limit": {"type": "integer", "default": 30},
            },
        },
    ),
    Tool(
        name="baker_rss_feeds",
        description="RSS feeds monitored by Baker's RSS sentinel.",
        inputSchema={
            "type": "object",
            "properties": {
                "active_only": {"type": "boolean", "default": True},
                "category": {"type": "string", "description": "Filter by category"},
                "limit": {"type": "integer", "default": 50},
            },
        },
    ),
    Tool(
        name="baker_rss_articles",
        description="Recent RSS articles ingested by Baker.",
        inputSchema={
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Search article titles"},
                "feed_id": {"type": "integer", "description": "Filter by feed ID"},
                "days": {"type": "integer", "default": 3},
                "limit": {"type": "integer", "default": 30},
            },
        },
    ),
    Tool(
        name="baker_deep_analyses",
        description="Deep analysis reports generated by Baker (long-form research).",
        inputSchema={
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Search by topic"},
                "days": {"type": "integer", "default": 30},
                "limit": {"type": "integer", "default": 10},
            },
        },
    ),
    Tool(
        name="baker_briefing_queue",
        description="Items queued for Baker's next daily briefing.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 50},
            },
        },
    ),
    Tool(
        name="baker_watermarks",
        description="Trigger watermarks — last poll timestamps for each data source.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="baker_conversation_memory",
        description="Baker's conversation memory — past questions and answers.",
        inputSchema={
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Search questions"},
                "project": {"type": "string", "description": "Filter by project tag"},
                "days": {"type": "integer", "default": 30},
                "limit": {"type": "integer", "default": 20},
            },
        },
    ),
    Tool(
        name="baker_raw_query",
        description="Execute a custom read-only SQL query against Baker's database. Use for complex joins or analytics not covered by specific tools. SELECT only — no mutations.",
        inputSchema={
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SELECT query (read-only enforced at connection level)"},
                "limit": {"type": "integer", "default": 50},
            },
            "required": ["sql"],
        },
    ),
    Tool(
        name="baker_raw_write",
        description="Execute a write SQL query (INSERT, UPDATE, DELETE) against Baker's database. Use ONLY on Director's explicit instruction for changes not covered by specific tools. DDL (DROP, ALTER, CREATE, TRUNCATE) is blocked. Returns affected row count and first row if RETURNING is used.",
        inputSchema={
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "INSERT, UPDATE, or DELETE query. Use RETURNING * to see affected rows."},
                "params": {"type": "array", "items": {}, "description": "Optional query parameters (positional, matching %s placeholders)"},
            },
            "required": ["sql"],
        },
    ),
    # ------------------------------------------------------------------
    # WRITE TOOLS — push decisions, deadlines, contacts, analyses back
    # into Baker's memory from Cowork sessions.
    # ------------------------------------------------------------------
    Tool(
        name="baker_store_decision",
        description="Store a decision, insight, or conclusion into Baker's memory. Use this when a Cowork session reaches a confirmed decision that Baker should remember. Baker will use this in future briefings and context retrieval.",
        inputSchema={
            "type": "object",
            "properties": {
                "decision": {"type": "string", "description": "The decision or insight (e.g., 'Gewährleistungsfrist on Hagenauer expires March 2027')"},
                "reasoning": {"type": "string", "description": "Why this decision was made — supporting logic or evidence"},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"], "description": "How confident is this decision", "default": "high"},
                "project": {"type": "string", "description": "Project tag (e.g., 'hagenauer', 'cupial', 'rg7', 'mandarin-oriental')"},
            },
            "required": ["decision"],
        },
    ),
    Tool(
        name="baker_add_deadline",
        description="Create a deadline in Baker's deadline register. Baker will track and remind the Director. Use when analysis reveals a date that matters.",
        inputSchema={
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "What the deadline is (e.g., 'Hagenauer Gewährleistungsfrist expiry')"},
                "due_date": {"type": "string", "description": "ISO date: YYYY-MM-DD (e.g., '2027-03-15')"},
                "priority": {"type": "string", "enum": ["critical", "high", "normal", "low"], "default": "normal"},
                "source_snippet": {"type": "string", "description": "Context — quote from document or analysis that established this deadline"},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"], "default": "high"},
            },
            "required": ["description", "due_date"],
        },
    ),
    Tool(
        name="baker_upsert_vip",
        description="Add or update a VIP contact in Baker's contact register. Use when analysis identifies a key person Baker should track.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Full name"},
                "role": {"type": "string", "description": "Role or relationship (e.g., 'E+H lawyer — Cupial/Hagenauer')"},
                "email": {"type": "string", "description": "Email address"},
                "whatsapp_id": {"type": "string", "description": "WhatsApp ID (e.g., '41799605092@c.us')"},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="baker_store_analysis",
        description="Store the full output of a deep analysis into Baker's memory. Use at the end of a Cowork analytical session to preserve the work for future reference. Baker can retrieve this in future Scan queries.",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Analysis topic (e.g., 'Hagenauer damage liability analysis')"},
                "analysis_text": {"type": "string", "description": "The full analysis output — conclusions, reasoning, recommendations"},
                "source_documents": {"type": "string", "description": "Comma-separated list of source documents used"},
                "prompt": {"type": "string", "description": "The question or prompt that triggered the analysis"},
            },
            "required": ["topic", "analysis_text"],
        },
    ),
    # ------------------------------------------------------------------
    # STEP3: Onboarding tools — preferences + VIP profile enrichment
    # ------------------------------------------------------------------
    Tool(
        name="baker_upsert_preference",
        description="Store or update a Director preference. Use during onboarding to set strategic priorities, domain context, communication style, and standing orders. Categories: strategic_priority, communication, standing_order, domain_context, general. Same category+key overwrites the previous value.",
        inputSchema={
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Category: strategic_priority | communication | standing_order | domain_context | general"},
                "pref_key": {"type": "string", "description": "Key within category (e.g., 'priority_1', 'email_tone', 'chairman')"},
                "pref_value": {"type": "string", "description": "Free text value"},
            },
            "required": ["category", "pref_key", "pref_value"],
        },
    ),
    Tool(
        name="baker_update_vip_profile",
        description="Update a VIP contact's profile — tier, domain, role context, communication preference, expertise. Only provided fields are updated; others are preserved. Use during onboarding to enrich VIP profiles with Director's knowledge.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "VIP name (matched case-insensitive)"},
                "tier": {"type": "integer", "description": "1 = WhatsApp alert within 15 min, 2 = Slack within 4h"},
                "domain": {"type": "string", "description": "Primary domain: chairman | projects | network | private | travel"},
                "role_context": {"type": "string", "description": "Free text: what they do, why they matter (e.g., 'COO and board member — handles all governance')"},
                "communication_pref": {"type": "string", "description": "Preferred contact method: email | whatsapp | slack | phone"},
                "expertise": {"type": "string", "description": "Free text: areas of expertise (e.g., 'Construction law, Austrian regulatory')"},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="baker_get_preferences",
        description="Read Director preferences stored by Baker. Optionally filter by category: strategic_priority, communication, standing_order, domain_context, general. Use to review what's been stored during onboarding.",
        inputSchema={
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Optional filter: strategic_priority | communication | standing_order | domain_context | general"},
            },
        },
    ),
    Tool(
        name="baker_upsert_matter",
        description="Add or update a matter in Baker's matter registry. Matters link business issues to people, keywords, and projects for context-aware retrieval. UPSERT by matter_name (case-insensitive). Use during onboarding to expand the matter registry.",
        inputSchema={
            "type": "object",
            "properties": {
                "matter_name": {"type": "string", "description": "Short label (e.g., 'Cupial', 'Wertheimer LP'). Used as upsert key."},
                "description": {"type": "string", "description": "One-sentence description of the matter"},
                "people": {"type": "array", "items": {"type": "string"}, "description": "Key people connected to this matter (names)"},
                "keywords": {"type": "array", "items": {"type": "string"}, "description": "Terms that signal this matter in emails/messages"},
                "projects": {"type": "array", "items": {"type": "string"}, "description": "Related project tags"},
                "status": {"type": "string", "description": "active | closed | archived (default: active)", "default": "active"},
            },
            "required": ["matter_name"],
        },
    ),
    # Browser Sentinel (BROWSER-1)
    Tool(
        name="baker_browser_tasks",
        description="Browser monitoring tasks managed by Baker's Browser Sentinel. See what websites Baker is watching for changes.",
        inputSchema={
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Search task name or URL"},
                "category": {"type": "string", "description": "Filter: hotel_rates, public_records, news, bank"},
                "active_only": {"type": "boolean", "default": True},
                "limit": {"type": "integer", "default": 30},
            },
        },
    ),
    Tool(
        name="baker_browser_results",
        description="Recent results from Baker's Browser Sentinel. See what data was captured from monitored websites.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "Filter by task ID"},
                "search": {"type": "string", "description": "Search result content"},
                "days": {"type": "integer", "default": 7},
                "limit": {"type": "integer", "default": 20},
            },
        },
    ),
]


@app.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        result = _dispatch(name, arguments)
        return [TextContent(type="text", text=result)]
    except Exception as e:
        logger.error(f"Tool {name} failed: {e}")
        return [TextContent(type="text", text=f"Error: {e}")]


def _dispatch(name: str, args: dict) -> str:
    """Route tool calls to query builders."""

    if name == "baker_deadlines":
        status = args.get("status", "active")
        priority = args.get("priority")
        days = args.get("days_ahead", 30)
        limit = args.get("limit", 50)
        clauses = ["status = %s"]
        params = [status]
        if priority:
            clauses.append("priority = %s")
            params.append(priority)
        clauses.append("due_date <= NOW() + INTERVAL '%s days'")
        params.append(days)
        sql = f"SELECT * FROM deadlines WHERE {' AND '.join(clauses)} ORDER BY due_date ASC"
        rows = _query(sql, tuple(params), limit)
        return _format_results(rows, "Baker Deadlines")

    elif name == "baker_vip_contacts":
        search = args.get("search")
        limit = args.get("limit", 50)
        if search:
            sql = "SELECT * FROM vip_contacts WHERE name ILIKE %s OR role ILIKE %s OR email ILIKE %s ORDER BY name"
            pat = f"%{search}%"
            rows = _query(sql, (pat, pat, pat), limit)
        else:
            rows = _query("SELECT * FROM vip_contacts ORDER BY name", limit=limit)
        return _format_results(rows, "VIP Contacts")

    elif name == "baker_sent_emails":
        to = args.get("to")
        unreplied = args.get("unreplied_only", False)
        days = args.get("days", 7)
        limit = args.get("limit", 25)
        clauses = ["created_at >= NOW() - INTERVAL '%s days'"]
        params: list = [days]
        if to:
            clauses.append("to_address ILIKE %s")
            params.append(f"%{to}%")
        if unreplied:
            clauses.append("reply_received = FALSE")
        sql = f"SELECT * FROM sent_emails WHERE {' AND '.join(clauses)} ORDER BY created_at DESC"
        rows = _query(sql, tuple(params), limit)
        return _format_results(rows, "Sent Emails")

    elif name == "baker_actions":
        action_type = args.get("action_type")
        days = args.get("days", 7)
        limit = args.get("limit", 30)
        clauses = ["created_at >= NOW() - INTERVAL '%s days'"]
        params: list = [days]
        if action_type:
            clauses.append("action_type = %s")
            params.append(action_type)
        sql = f"SELECT * FROM baker_actions WHERE {' AND '.join(clauses)} ORDER BY created_at DESC"
        rows = _query(sql, tuple(params), limit)
        return _format_results(rows, "Baker Actions")

    elif name == "baker_clickup_tasks":
        search = args.get("search")
        status = args.get("status")
        list_name = args.get("list_name")
        limit = args.get("limit", 30)
        clauses = []
        params: list = []
        if search:
            clauses.append("(name ILIKE %s OR description ILIKE %s)")
            params.extend([f"%{search}%", f"%{search}%"])
        if status:
            clauses.append("status ILIKE %s")
            params.append(f"%{status}%")
        if list_name:
            clauses.append("list_name ILIKE %s")
            params.append(f"%{list_name}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM clickup_tasks {where} ORDER BY date_updated DESC NULLS LAST"
        rows = _query(sql, tuple(params) if params else None, limit)
        return _format_results(rows, "ClickUp Tasks")

    elif name == "baker_todoist_tasks":
        search = args.get("search")
        project = args.get("project_name")
        priority = args.get("priority")
        status = args.get("status", "active")
        limit = args.get("limit", 30)
        clauses = ["status = %s"]
        params: list = [status]
        if search:
            clauses.append("content ILIKE %s")
            params.append(f"%{search}%")
        if project:
            clauses.append("project_name ILIKE %s")
            params.append(f"%{project}%")
        if priority:
            clauses.append("priority = %s")
            params.append(priority)
        sql = f"SELECT * FROM todoist_tasks WHERE {' AND '.join(clauses)} ORDER BY due_date NULLS LAST"
        rows = _query(sql, tuple(params), limit)
        return _format_results(rows, "Todoist Tasks")

    elif name == "baker_rss_feeds":
        active_only = args.get("active_only", True)
        category = args.get("category")
        limit = args.get("limit", 50)
        clauses = []
        params: list = []
        if active_only:
            clauses.append("is_active = TRUE")
        if category:
            clauses.append("category ILIKE %s")
            params.append(f"%{category}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM rss_feeds {where} ORDER BY title"
        rows = _query(sql, tuple(params) if params else None, limit)
        return _format_results(rows, "RSS Feeds")

    elif name == "baker_rss_articles":
        search = args.get("search")
        feed_id = args.get("feed_id")
        days = args.get("days", 3)
        limit = args.get("limit", 30)
        clauses = ["ingested_at >= NOW() - INTERVAL '%s days'"]
        params: list = [days]
        if search:
            clauses.append("title ILIKE %s")
            params.append(f"%{search}%")
        if feed_id:
            clauses.append("feed_id = %s")
            params.append(feed_id)
        sql = f"SELECT * FROM rss_articles WHERE {' AND '.join(clauses)} ORDER BY published_at DESC NULLS LAST"
        rows = _query(sql, tuple(params), limit)
        return _format_results(rows, "RSS Articles")

    elif name == "baker_deep_analyses":
        search = args.get("search")
        days = args.get("days", 30)
        limit = args.get("limit", 10)
        clauses = ["created_at >= NOW() - INTERVAL '%s days'"]
        params: list = [days]
        if search:
            clauses.append("topic ILIKE %s")
            params.append(f"%{search}%")
        sql = f"SELECT * FROM deep_analyses WHERE {' AND '.join(clauses)} ORDER BY created_at DESC"
        rows = _query(sql, tuple(params), limit)
        return _format_results(rows, "Deep Analyses")

    elif name == "baker_briefing_queue":
        limit = args.get("limit", 50)
        rows = _query("SELECT * FROM briefing_queue ORDER BY created_at", limit=limit)
        return _format_results(rows, "Briefing Queue")

    elif name == "baker_watermarks":
        rows = _query("SELECT source, last_seen, updated_at FROM trigger_watermarks ORDER BY source")
        return _format_results(rows, "Trigger Watermarks")

    elif name == "baker_conversation_memory":
        search = args.get("search")
        project = args.get("project")
        days = args.get("days", 30)
        limit = args.get("limit", 20)
        clauses = ["created_at >= NOW() - INTERVAL '%s days'"]
        params: list = [days]
        if search:
            clauses.append("question ILIKE %s")
            params.append(f"%{search}%")
        if project:
            clauses.append("project = %s")
            params.append(project)
        sql = f"SELECT * FROM conversation_memory WHERE {' AND '.join(clauses)} ORDER BY created_at DESC"
        rows = _query(sql, tuple(params), limit)
        return _format_results(rows, "Conversation Memory")

    # Browser Sentinel (BROWSER-1)
    elif name == "baker_browser_tasks":
        search = args.get("search")
        category = args.get("category")
        active_only = args.get("active_only", True)
        limit = args.get("limit", 30)
        clauses = []
        params: list = []
        if active_only:
            clauses.append("is_active = TRUE")
        if search:
            clauses.append("(name ILIKE %s OR url ILIKE %s)")
            params.extend([f"%{search}%", f"%{search}%"])
        if category:
            clauses.append("category = %s")
            params.append(category)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT id, name, url, mode, category, is_active, last_polled, last_content_hash, consecutive_failures, created_at FROM browser_tasks {where} ORDER BY id"
        rows = _query(sql, tuple(params) if params else None, limit)
        return _format_results(rows, "Browser Tasks")

    elif name == "baker_browser_results":
        task_id = args.get("task_id")
        search = args.get("search")
        days = args.get("days", 7)
        limit = args.get("limit", 20)
        clauses = ["br.created_at >= NOW() - INTERVAL '%s days'"]
        params: list = [days]
        if task_id:
            clauses.append("br.task_id = %s")
            params.append(task_id)
        if search:
            clauses.append("br.content ILIKE %s")
            params.append(f"%{search}%")
        sql = f"""SELECT br.id, bt.name AS task_name, bt.url, br.content_hash,
                         LEFT(br.content, 500) AS content_preview, br.structured_data,
                         br.mode_used, br.steps_count, br.cost_usd, br.duration_ms, br.created_at
                  FROM browser_results br
                  JOIN browser_tasks bt ON br.task_id = bt.id
                  WHERE {' AND '.join(clauses)}
                  ORDER BY br.created_at DESC"""
        rows = _query(sql, tuple(params), limit)
        return _format_results(rows, "Browser Results")

    elif name == "baker_raw_query":
        sql = args.get("sql", "")
        limit = args.get("limit", 50)
        # Extra safety: reject anything that looks like a mutation
        sql_upper = sql.strip().upper()
        forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT", "REVOKE"]
        for word in forbidden:
            if sql_upper.startswith(word):
                return f"Error: {word} queries are not allowed. Use baker_raw_write for mutations."
        rows = _query(sql, limit=limit)
        return _format_results(rows, "Custom Query")

    elif name == "baker_raw_write":
        sql = args.get("sql", "")
        params = args.get("params", [])
        # Block DDL — only DML allowed (INSERT, UPDATE, DELETE)
        sql_upper = sql.strip().upper()
        blocked = ["DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT", "REVOKE"]
        for word in blocked:
            if sql_upper.startswith(word):
                return f"Error: {word} is blocked. Only INSERT, UPDATE, DELETE allowed."
        allowed = ["INSERT", "UPDATE", "DELETE"]
        if not any(sql_upper.startswith(w) for w in allowed):
            return "Error: Only INSERT, UPDATE, DELETE queries allowed. Use baker_raw_query for SELECT."
        row = _write(sql, tuple(params) if params else None)
        if row:
            return f"Write executed. Result:\n{json.dumps(dict(row), default=_json_serial, indent=2)}"
        return "Write executed (no RETURNING clause or no rows affected)."

    # ------------------------------------------------------------------
    # WRITE TOOL HANDLERS
    # ------------------------------------------------------------------

    elif name == "baker_store_decision":
        decision = args["decision"]
        reasoning = args.get("reasoning", "")
        confidence = args.get("confidence", "high")
        project = args.get("project", "")

        # CORTEX-PHASE-2B-II: Route through event bus when flag ON
        _use_cortex = False
        try:
            from memory.store_back import SentinelStoreBack
            _store = SentinelStoreBack._get_global_instance()
            _use_cortex = _store.get_cortex_config('tool_router_enabled', False)
        except Exception:
            pass

        if _use_cortex:
            from models.cortex import cortex_store_decision
            dec_id = cortex_store_decision(
                decision=decision,
                source_agent="cowork",
                reasoning=reasoning,
                confidence=confidence,
                trigger_type="cowork_session",
                project=project,
            )
            if dec_id:
                return f"Decision stored via Cortex (id={dec_id}, confidence={confidence}):\n  {decision}"
            return "Error: failed to store decision"
        else:
            # Legacy path (feature flag OFF)
            metadata = json.dumps({"source": "cowork_mcp", "project": project}) if project else json.dumps({"source": "cowork_mcp"})
            row = _write(
                """
                INSERT INTO decisions (decision, reasoning, confidence, trigger_type, metadata, created_at)
                VALUES (%s, %s, %s, 'cowork_session', %s::jsonb, NOW())
                RETURNING id, decision, confidence
                """,
                (decision, reasoning, confidence, metadata),
            )
            if row:
                return f"Decision stored (id={row['id']}, confidence={row['confidence']}):\n  {row['decision']}"
            return "Error: failed to store decision"

    elif name == "baker_add_deadline":
        description = args["description"]
        due_date = args["due_date"]
        priority = args.get("priority", "normal")
        source_snippet = args.get("source_snippet", "")
        confidence = args.get("confidence", "high")

        # CORTEX-PHASE-2B-II: Route through event bus when flag ON
        _use_cortex = False
        try:
            from memory.store_back import SentinelStoreBack
            _store = SentinelStoreBack._get_global_instance()
            _use_cortex = _store.get_cortex_config('tool_router_enabled', False)
        except Exception:
            pass

        if _use_cortex:
            from models.cortex import cortex_create_deadline
            dl_id = cortex_create_deadline(
                description=description,
                due_date=due_date,
                source_type="cowork_session",
                source_agent="cowork",
                confidence=confidence,
                priority=priority,
                source_id="mcp",
                source_snippet=source_snippet,
            )
            if dl_id:
                return f"Deadline created via Cortex (id={dl_id}, priority={priority}):\n  {description}\n  Due: {due_date}"
            return "Error: failed to create deadline"
        else:
            # Legacy path (feature flag OFF)
            row = _write(
                """
                INSERT INTO deadlines (description, due_date, source_type, source_id, source_snippet, confidence, priority, status)
                VALUES (%s, %s, 'cowork_session', 'mcp', %s, %s, %s, 'active')
                RETURNING id, description, due_date, priority
                """,
                (description, due_date, source_snippet, confidence, priority),
            )
            if row:
                return f"Deadline created (id={row['id']}, priority={row['priority']}):\n  {row['description']}\n  Due: {row['due_date']}"
            return "Error: failed to create deadline"

    elif name == "baker_upsert_vip":
        name_val = args["name"]
        role = args.get("role", "")
        email = args.get("email", "")
        whatsapp_id = args.get("whatsapp_id", "")
        # Check if contact exists (by name, case-insensitive)
        existing = _query("SELECT id FROM vip_contacts WHERE LOWER(name) = LOWER(%s)", (name_val,), limit=1)
        if existing:
            # Update existing contact — only overwrite non-empty fields
            row = _write(
                """
                UPDATE vip_contacts SET
                    role = COALESCE(NULLIF(%s, ''), role),
                    email = COALESCE(NULLIF(%s, ''), email),
                    whatsapp_id = COALESCE(NULLIF(%s, ''), whatsapp_id)
                WHERE id = %s
                RETURNING id, name, role, email
                """,
                (role, email, whatsapp_id, existing[0]["id"]),
            )
            action = "updated"
        else:
            row = _write(
                """
                INSERT INTO vip_contacts (name, role, email, whatsapp_id)
                VALUES (%s, %s, %s, %s)
                RETURNING id, name, role, email
                """,
                (name_val, role, email, whatsapp_id),
            )
            action = "created"
        if row:
            return f"VIP contact {action} (id={row['id']}):\n  {row['name']} — {row['role'] or 'no role'} ({row['email'] or 'no email'})"
        return "Error: failed to save VIP contact"

    elif name == "baker_store_analysis":
        topic = args["topic"]
        analysis_text = args["analysis_text"]
        source_docs_str = args.get("source_documents", "")
        prompt = args.get("prompt", "")
        analysis_id = f"cowork_{uuid.uuid4().hex[:12]}"
        source_documents = json.dumps([s.strip() for s in source_docs_str.split(",") if s.strip()] if source_docs_str else [])
        row = _write(
            """
            INSERT INTO deep_analyses (analysis_id, topic, source_documents, prompt, analysis_text, token_count, chunk_count, cost_usd)
            VALUES (%s, %s, %s::jsonb, %s, %s, 0, 0, 0)
            RETURNING analysis_id, topic
            """,
            (analysis_id, topic, source_documents, prompt, analysis_text),
        )
        if row:
            return f"Analysis stored (id={row['analysis_id']}):\n  Topic: {row['topic']}\n  Length: {len(analysis_text)} chars"
        return "Error: failed to store analysis"

    # ------------------------------------------------------------------
    # STEP3: Onboarding tool handlers
    # ------------------------------------------------------------------

    elif name == "baker_upsert_preference":
        category = args["category"]
        pref_key = args["pref_key"]
        pref_value = args["pref_value"]
        row = _write(
            """
            INSERT INTO director_preferences (category, pref_key, pref_value)
            VALUES (%s, %s, %s)
            ON CONFLICT (category, pref_key)
            DO UPDATE SET pref_value = EXCLUDED.pref_value, updated_at = NOW()
            RETURNING id, category, pref_key, pref_value
            """,
            (category, pref_key, pref_value),
        )
        if row:
            return f"Preference stored: [{row['category']}] {row['pref_key']} = {row['pref_value']}"
        return "Error: failed to store preference"

    elif name == "baker_update_vip_profile":
        vip_name = args["name"]
        allowed = {"tier", "domain", "role_context", "communication_pref", "expertise"}
        updates = {k: v for k, v in args.items() if k in allowed and v is not None}
        if not updates:
            return f"No profile fields provided for '{vip_name}'. Allowed: tier, domain, role_context, communication_pref, expertise."
        # Build parameterized UPDATE
        set_parts = []
        params = []
        for col, val in updates.items():
            set_parts.append(f"{col} = %s")
            params.append(val)
        params.append(vip_name.lower())
        row = _write(
            f"UPDATE vip_contacts SET {', '.join(set_parts)} WHERE LOWER(name) = %s RETURNING id, name, tier, domain, role_context, communication_pref, expertise",
            tuple(params),
        )
        if row:
            changed = ", ".join(f"{k}={v}" for k, v in updates.items())
            return f"VIP profile updated — {row['name']} (id={row['id']}): {changed}"
        return f"VIP '{vip_name}' not found. Use baker_upsert_vip to create first."

    elif name == "baker_get_preferences":
        category = args.get("category")
        if category:
            rows = _query(
                "SELECT id, category, pref_key, pref_value, updated_at FROM director_preferences WHERE category = %s ORDER BY category, pref_key",
                (category,), limit=100,
            )
        else:
            rows = _query(
                "SELECT id, category, pref_key, pref_value, updated_at FROM director_preferences ORDER BY category, pref_key",
                limit=100,
            )
        return _format_results(rows, "Director Preferences")

    elif name == "baker_upsert_matter":
        matter_name = args["matter_name"]
        description = args.get("description", "")
        people = args.get("people", [])
        keywords = args.get("keywords", [])
        projects = args.get("projects", [])
        status = args.get("status", "active")
        # Check if matter exists (case-insensitive)
        existing = _query("SELECT id FROM matter_registry WHERE LOWER(matter_name) = LOWER(%s)", (matter_name,), limit=1)
        if existing:
            row = _write(
                """UPDATE matter_registry SET
                    description = COALESCE(NULLIF(%s, ''), description),
                    people = CASE WHEN %s::text[] = '{}'::text[] THEN people ELSE %s::text[] END,
                    keywords = CASE WHEN %s::text[] = '{}'::text[] THEN keywords ELSE %s::text[] END,
                    projects = CASE WHEN %s::text[] = '{}'::text[] THEN projects ELSE %s::text[] END,
                    status = COALESCE(NULLIF(%s, ''), status),
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id, matter_name, description, people, keywords, projects, status""",
                (description, people, people, keywords, keywords, projects, projects, status, existing[0]["id"]),
            )
            action = "updated"
        else:
            row = _write(
                """INSERT INTO matter_registry (matter_name, description, people, keywords, projects, status)
                VALUES (%s, %s, %s::text[], %s::text[], %s::text[], %s)
                RETURNING id, matter_name, description, people, keywords, projects, status""",
                (matter_name, description, people, keywords, projects, status),
            )
            action = "created"
        if row:
            ppl = ", ".join(row.get("people", []) or [])
            kw = ", ".join(row.get("keywords", []) or [])
            return f"Matter {action} (id={row['id']}): {row['matter_name']}\n  Description: {row.get('description', '')}\n  People: {ppl}\n  Keywords: {kw}"
        return f"Error: failed to save matter '{matter_name}'"

    else:
        return f"Unknown tool: {name}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
