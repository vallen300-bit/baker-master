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
import pathlib
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse, parse_qs

import httpx
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
    """Execute a read-only query. Returns list of dicts.

    Read-only enforcement happens at the SQL-parse level in _dispatch
    (forbidden keyword list). We deliberately do NOT call
    `set_session(readonly=True)` here — Neon's pgbouncer transaction-mode
    pool does not reset session state by default, so a SET issued on one
    backend connection leaks to subsequent unrelated callers and forces
    the entire app into read-only mode (RCA 2026-04-29).
    """
    conn = psycopg2.connect(**_get_conn_params())
    conn.autocommit = True
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchmany(limit)
            return [dict(r) for r in rows]
    finally:
        # Best-effort: reset any session GUCs we might have inherited from a
        # poisoned pooler backend (e.g. default_transaction_read_only=on
        # leaked from a pre-fix instance) before returning the connection.
        try:
            with conn.cursor() as c:
                c.execute("DISCARD ALL")
        except Exception:
            pass
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
# Vault-write audit helpers (BAKER_VAULT_WRITE_1)
# ---------------------------------------------------------------------------
# Schema verified 2026-04-30 against information_schema.columns:
#   action_type, target_task_id, target_space_id, payload, trigger_source,
#   created_at, success, error_message.
# Re-verify if the brief's reference date drifts more than ~1 month.

def _emit_vault_write_audit(
    path: str,
    mode: str,
    commit_message: str,
) -> int | None:
    """INSERT initial audit row in attempt state. Returns row id or None on failure.

    success is set explicitly to NULL to mark "attempt in flight" — the table's
    DEFAULT TRUE would otherwise mask crashes between INSERT and UPDATE.
    """
    try:
        payload = {"mode": mode, "commit_message": commit_message[:200]}
        row = _write(
            """INSERT INTO baker_actions
                   (action_type, target_task_id, payload, trigger_source,
                    created_at, success)
               VALUES (%s, %s, %s::jsonb, %s, NOW(), %s)
               RETURNING id""",
            ("vault_write", path, json.dumps(payload), "mcp", None),
        )
        return row["id"] if row else None
    except Exception as e:  # pragma: no cover — DB outage is best-effort logged
        logger.warning("vault_write audit emit failed: %s", e)
        return None


def _update_vault_write_audit(
    audit_id: int | None,
    success: bool,
    payload_extra: dict | None = None,
    error_message: str | None = None,
) -> None:
    """UPDATE the audit row with terminal state.

    payload_extra (success path): merges into existing payload — adds klass,
    commit_sha, content_sha, html_url, bytes_written. target_space_id is set
    to klass for downstream filtering.
    error_message (failure path): MUST already be _redact()-ed by caller.
    """
    if not audit_id:
        return
    try:
        if payload_extra:
            extra_json = json.dumps(payload_extra, default=str)[:8000]
            _write(
                """UPDATE baker_actions
                   SET success = %s,
                       payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb,
                       target_space_id = %s,
                       error_message = %s
                   WHERE id = %s""",
                (
                    success,
                    extra_json,
                    payload_extra.get("klass"),
                    error_message,
                    audit_id,
                ),
            )
        else:
            _write(
                """UPDATE baker_actions
                   SET success = %s,
                       error_message = %s
                   WHERE id = %s""",
                (success, error_message, audit_id),
            )
    except Exception as e:  # pragma: no cover — DB outage is best-effort logged
        logger.warning("vault_write audit update failed: %s", e)


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
        description=(
            "List Baker's VIP contacts — key people tracked by the system. "
            "Returns full provenance fields including linkedin_url + source_of_introduction "
            "(both stored on vip_contacts table). Search matches name / role / email / "
            "linkedin_url / source_of_introduction."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "search": {
                    "type": "string",
                    "description": (
                        "Search by name, role, email, linkedin_url, or "
                        "source_of_introduction (case-insensitive substring match)"
                    ),
                },
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
    # ------------------------------------------------------------------
    # VAULT-READ TOOLS (SOT_OBSIDIAN_1_PHASE_D + BAKER_VAULT_READ_WIKI_SCOPE_1)
    # Cowork reads her own canonical skill + memory files plus per-matter
    # dossiers from the Render-side baker-vault mirror. Read-only; scoped
    # to `_ops/` and `wiki/` subtrees only.
    # ------------------------------------------------------------------
    Tool(
        name="baker_vault_list",
        description="List files in the baker-vault mirror under a given prefix. Allowed prefixes: `_ops/` (skills, agents, processes, briefs, registries) and `wiki/` (matter dossiers, curated knowledge, ratified priorities). Use this to discover what canonical files are available. Returns sorted relative paths for `.md`, `.yml`, `.yaml`, `.txt`, `.html`, `.htm` files only.",
        inputSchema={
            "type": "object",
            "properties": {
                "prefix": {
                    "type": "string",
                    "description": "Path prefix to list under. Must start with `_ops/` or `wiki/`. Default `_ops/`.",
                    "default": "_ops/",
                },
            },
        },
    ),
    Tool(
        name="baker_vault_read",
        description="Read a canonical file from the baker-vault mirror — single source of truth for AI Dennis's skill + memory, write-brief skill, bank-model (`_ops/`) plus per-matter dossiers like `wiki/matters/<slug>/cortex-config.md`, `gold.md`, `curated/*`, and `wiki/hot.md` (`wiki/`). Scoped to `_ops/**` and `wiki/**` with path-traversal protection. 128 KB cap — oversize files return metadata only. Returns `{path, content_utf8, sha256, bytes, last_commit_sha, truncated}`.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path, e.g. `_ops/skills/it-manager/SKILL.md` or `wiki/matters/oskolkov/cortex-config.md`. Must start with `_ops/` or `wiki/`. Only .md / .yml / .yaml / .txt / .html / .htm allowed. HTML is returned as text/source, not rendered.",
                },
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="baker_vault_write",
        description=(
            "Write a curated knowledge file to the baker-vault via GitHub Contents API. "
            "STRICT path whitelist (6 path classes), append-only except _session-state.md, "
            "frontmatter required for curated/ and proposed-gold.md. "
            "Allowed path classes: "
            "wiki/matters/<slug>/_session-state.md (overwrite OK), "
            "wiki/matters/<slug>/curated/<YYYY-MM-DD>-<topic>.md (append-only, frontmatter req'd), "
            "wiki/_inbox/handoff-<date>-<src>-to-<tgt>.md (append-only), "
            "wiki/matters/<slug>/proposed-gold.md (append-only, frontmatter req'd), "
            "wiki/matters/<slug>/decisions/<YYYY-MM-DD>-<topic>.md (append-only), "
            "wiki/matters/<slug>/red-flags.md (append-only). "
            "Returns commit SHA + content SHA + GitHub URL."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative vault path. Must match one of the 6 allowed patterns.",
                    "minLength": 1,
                    "maxLength": 500,
                },
                "content": {
                    "type": "string",
                    "description": "UTF-8 file content. For append mode, the segment to append.",
                    "minLength": 1,
                    "maxLength": 100000,
                },
                "mode": {
                    "type": "string",
                    "enum": ["append", "overwrite"],
                    "description": "append (default for all paths) or overwrite (only allowed for _session-state.md).",
                    "default": "append",
                },
                "commit_message": {
                    "type": "string",
                    "description": "Git commit message. Required. Format: '<Desk> — <topic>'.",
                    "minLength": 1,
                    "maxLength": 200,
                },
            },
            "required": ["path", "content", "commit_message"],
        },
    ),
    Tool(
        name="baker_scan",
        description=(
            "Run a Baker Scan — interactive Q&A across Baker's memory (emails, meetings, "
            "WhatsApp, ClickUp, contacts, deadlines). If `capability_slug` is provided, "
            "routes to the named client-PM or domain capability (e.g. `ao_pm` for "
            "Andrey Oskolkov, `movie_am` for Mandarin Vienna asset management); "
            "otherwise auto-routes via Baker's intent classifier. Returns the final "
            "answer text (SSE stream collected into one string)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The question to ask Baker.",
                    "minLength": 1,
                    "maxLength": 4000,
                },
                "capability_slug": {
                    "type": "string",
                    "description": (
                        "Optional. Route to a specific capability instead of auto-classify. "
                        "Examples: ao_pm, movie_am, finance, legal, sales, asset_management."
                    ),
                },
                "history": {
                    "type": "array",
                    "description": "Optional prior turns: [{role, content}, ...]",
                    "default": [],
                },
                "project": {
                    "type": "string",
                    "description": "Optional scope: rg7, hagenauer, movie-hotel-asset-management.",
                },
                "role": {
                    "type": "string",
                    "description": "Optional scope: chairman, network, private, travel.",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="baker_search",
        description=(
            "Semantic search across all Baker memory (emails, meetings, WhatsApp, "
            "documents, contacts, deadlines). Returns top-N matching items with "
            "relevance scores. Use for fact-finding queries; use baker_scan for "
            "conversational answers."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language search query.",
                    "minLength": 1,
                    "maxLength": 500,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 20, max 50).",
                    "default": 20,
                    "maximum": 50,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="baker_substack_search",
        description=(
            "Semantic search across ingested Substack archives. Use when an agent "
            "needs to query a known Substack publication's content by topic. "
            "Returns top-k matching posts with title, URL, post date, audience tier, "
            "and a body excerpt. Today's seeded publications: 'natesnewsletter' "
            "(Nate Jones — Director paid sub). To add a new publication, run "
            "scripts/backfill_substack_archive.py --publication <slug> --apply "
            "after Director provides the session cookie via 1Password."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "publication": {
                    "type": "string",
                    "description": (
                        "Substack publication subdomain. Today supports: natesnewsletter."
                    ),
                    "minLength": 1,
                    "maxLength": 100,
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Natural-language query. Embedded via Voyage; matched against post bodies."
                    ),
                    "minLength": 1,
                    "maxLength": 500,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max posts to return (1-20).",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
                },
            },
            "required": ["publication", "query"],
        },
    ),
    Tool(
        name="baker_ingest_text",
        description=(
            "Ingest a text document into Baker's knowledge base. Use for memos, "
            "notes, transcripts, or any text content. For binary files (PDFs, "
            "images), upload via the dashboard UI instead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Filename for the document (e.g. 'it-memo-2026-04-26.md').",
                    "minLength": 1,
                    "maxLength": 200,
                },
                "content": {
                    "type": "string",
                    "description": "Text body to ingest.",
                    "minLength": 1,
                    "maxLength": 100000,
                },
                "collection": {
                    "type": "string",
                    "description": "Optional Qdrant collection override.",
                },
                "project": {
                    "type": "string",
                    "description": "Optional project tag: rg7, hagenauer, movie-hotel-asset-management.",
                },
                "role": {
                    "type": "string",
                    "description": "Optional role tag: chairman, network, private, travel.",
                },
            },
            "required": ["title", "content"],
        },
    ),
    Tool(
        name="baker_health",
        description=(
            "Get Baker system health: database connectivity, scheduler status, "
            "active sentinels, vault mirror state, last update timestamps. Returns "
            "a structured health summary for monitoring or pre-flight checks."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    # ----------------------------------------------------------------------
    # Brisen Lab V2 bridge — message bus consumer-side tools (BRISEN_LAB_V2_BRIDGE_1)
    # Brief: briefs/BRIEF_BRISEN_LAB_V2_BRIDGE_1.md §A7
    # Daemon: brisen-lab.onrender.com (paired repo `vallen300-bit/brisen-lab`)
    # Auth: X-Terminal-Key header from BRISEN_LAB_TERMINAL_KEY env (per-worker scoped)
    # Fail-open: when V2 endpoints return 503 (BRISEN_LAB_V2_ENABLED=false on daemon),
    # tools return a paste-block fallback marker per AC6 instead of raising.
    # ----------------------------------------------------------------------
    Tool(
        name="baker_inbox_post",
        description=(
            "Post a message to the Brisen Lab V2 message bus. "
            "The sender is derived server-side from the X-Terminal-Key (the "
            "caller's terminal slug); you do not set it. "
            "Recipients are the `to` array; `kind` is one of dispatch / broadcast / "
            "ratify_required / ratify_decision. For `ratify_required`, set "
            "`tier_required` (B / A / director_only); the daemon validates it against "
            "the topic→tier classification and rejects HTTP 400 if downgraded. "
            "For `ratify_decision`, supply `parent_id` (the ratify_required msg id) AND "
            "`human_confirmation_token` (JWT from /auth/human-confirmation). "
            "Returns the daemon's response (msg_id, thread_id, etc.) or a paste-block "
            "fallback marker when V2 is disabled."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "to": {
                    "anyOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "string"},
                    ],
                    "description": "Recipient terminal slug(s). Single string coerced to 1-element list.",
                },
                "kind": {
                    "type": "string",
                    "enum": ["dispatch", "broadcast", "ratify_required", "ratify_decision"],
                    "description": "Message kind per brief §3 schema.",
                },
                "topic": {
                    "type": "string",
                    "description": "Optional topic prefix, e.g. 'cortex/aukera/cycle-f7795012'.",
                },
                "body": {
                    "type": "string",
                    "description": "Message body (string; structured payloads serialized by caller).",
                },
                "parent_id": {
                    "type": "integer",
                    "description": "Parent message id (required for kind=ratify_decision; otherwise reply linkage).",
                },
                "thread_id": {
                    "type": "string",
                    "description": "Optional thread UUID (daemon assigns if omitted).",
                },
                "tier_required": {
                    "type": "string",
                    "enum": ["B", "A", "director_only"],
                    "description": "Required only for kind=ratify_required (defaults to B; daemon-validated against topic classification).",
                },
                "human_confirmation_token": {
                    "type": "string",
                    "description": "JWT from POST /auth/human-confirmation (required for kind=ratify_decision).",
                },
                "from_terminal": {
                    "type": "string",
                    "description": "Deprecated / no-op. The sender is derived server-side from the X-Terminal-Key; this field does not affect routing or sender attribution. Kept for backward compatibility only.",
                },
            },
            "required": ["to", "kind", "body"],
        },
    ),
    Tool(
        name="baker_inbox_read",
        description=(
            "Read the caller's inbox from the Brisen Lab V2 message bus. "
            "Returns messages where the caller's terminal slug is in `to_terminals` "
            "and `acknowledged_at IS NULL`. Does NOT ack — call `baker_inbox_ack` "
            "after processing each consumed message (NM3: workers cannot write the "
            "DB directly). Filters: `since` (ISO timestamp), `kind`, `topic` "
            "(prefix LIKE), `exclude_self` (drop messages from this terminal). "
            "Unacked-only by default (client-filters acknowledged_at IS NULL even if "
            "the daemon returns acked rows); pass include_acked=true for the full set. "
            "Fail-open: returns empty list with a fallback notice when V2 disabled."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "terminal": {
                    "type": "string",
                    "description": "Terminal slug to read inbox for (defaults to $BAKER_ROLE lower-cased).",
                },
                "since": {
                    "type": "string",
                    "description": "Optional ISO timestamp filter (created_at > since).",
                },
                "kind": {
                    "type": "string",
                    "description": "Optional kind filter.",
                },
                "topic": {
                    "type": "string",
                    "description": "Optional topic prefix filter.",
                },
                "exclude_self": {
                    "type": "boolean",
                    "description": "If true, drop messages where from_terminal == this terminal (Cortex peer/self-read filter).",
                    "default": False,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max rows (default 50; daemon caps preview at 8K bytes per row).",
                    "default": 50,
                },
                "include_acked": {
                    "type": "boolean",
                    "description": "If true, return acked messages too (default false = unacked only).",
                    "default": False,
                },
            },
        },
    ),
    Tool(
        name="baker_inbox_ack",
        description=(
            "Ack a consumed inbox message via POST /msg/<id>/ack. NM3: this is the "
            "sole authoritative path to set `acknowledged_at`; workers do NOT have "
            "direct DB write access. Call once per message id after processing. "
            "Idempotent on the daemon side (re-ack returns 200). Fail-open: silent "
            "no-op when V2 disabled (drain side stays cheap)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "msg_id": {
                    "type": "integer",
                    "description": "Message id from baker_inbox_read.",
                },
                "msg_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Bulk ack: list of message ids (alternative to msg_id; both NOT both).",
                },
            },
        },
    ),
]

# ClaimsMax v1 REST surface — imported separately to keep the existing 24-tool
# block stable. Tools live in tools/claimsmax.py; dispatch routes there too.
try:
    from tools.claimsmax import CLAIMSMAX_TOOLS, CLAIMSMAX_TOOL_NAMES, dispatch_claimsmax
    TOOLS.extend(CLAIMSMAX_TOOLS)
except Exception as _claimsmax_import_err:  # pragma: no cover — defensive import
    logger.warning("ClaimsMax tools unavailable: %s", _claimsmax_import_err)
    CLAIMSMAX_TOOL_NAMES = frozenset()

    def dispatch_claimsmax(name: str, args: dict) -> str:  # type: ignore[no-redef]
        return f"Error: ClaimsMax tools failed to load: {_claimsmax_import_err}"


# xAI Grok Responses API + Live Search — defensive import mirroring ClaimsMax.
try:
    from tools.grok import GROK_TOOLS, GROK_TOOL_NAMES, dispatch_grok
    TOOLS.extend(GROK_TOOLS)
except Exception as _grok_import_err:  # pragma: no cover — defensive import
    logger.warning("Grok tools unavailable: %s", _grok_import_err)
    GROK_TOOL_NAMES = frozenset()

    def dispatch_grok(name: str, args: dict) -> str:  # type: ignore[no-redef]
        return f"Error: Grok tools failed to load: {_grok_import_err}"


# Perplexity Sonar cited ask — defensive import mirroring ClaimsMax + Grok.
try:
    from tools.perplexity import PERPLEXITY_TOOLS, PERPLEXITY_TOOL_NAMES, dispatch_perplexity
    TOOLS.extend(PERPLEXITY_TOOLS)
except Exception as _perplexity_import_err:  # pragma: no cover — defensive import
    logger.warning("Perplexity tools unavailable: %s", _perplexity_import_err)
    PERPLEXITY_TOOL_NAMES = frozenset()

    def dispatch_perplexity(name: str, args: dict) -> str:  # type: ignore[no-redef]
        return f"Error: Perplexity tools failed to load: {_perplexity_import_err}"


# Gmail on-demand attachment read — defensive import mirroring ClaimsMax + Grok.
try:
    from tools.gmail import GMAIL_TOOLS, GMAIL_TOOL_NAMES, dispatch_gmail
    TOOLS.extend(GMAIL_TOOLS)
except Exception as _gmail_import_err:  # pragma: no cover — defensive import
    logger.warning("Gmail tools unavailable: %s", _gmail_import_err)
    GMAIL_TOOL_NAMES = frozenset()

    def dispatch_gmail(name: str, args: dict) -> str:  # type: ignore[no-redef]
        return f"Error: Gmail tools failed to load: {_gmail_import_err}"


# Email merged-store surface (M365_MAIL_BLINDSPOT_DIAGNOSE_FIX_1) — the surface
# that sees Director's brisengroup.com / Outlook / M365 mail. Defensive import.
try:
    from tools.email import EMAIL_TOOLS, EMAIL_TOOL_NAMES, dispatch_email
    TOOLS.extend(EMAIL_TOOLS)
except Exception as _email_import_err:  # pragma: no cover — defensive import
    logger.warning("Email tools unavailable: %s", _email_import_err)
    EMAIL_TOOL_NAMES = frozenset()

    def dispatch_email(name: str, args: dict) -> str:  # type: ignore[no-redef]
        return f"Error: Email tools failed to load: {_email_import_err}"


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


# ---------------------------------------------------------------------------
# Loopback helpers for live REST endpoints (BAKER_MCP_EXTENSION_1)
# ---------------------------------------------------------------------------

def _internal_base_url() -> str:
    """Loopback URL for in-process MCP calls; override via BAKER_INTERNAL_URL env."""
    return os.getenv("BAKER_INTERNAL_URL", "http://localhost:8080")


def _internal_api_key() -> str:
    """API key for X-Baker-Key header (same as dashboard)."""
    return os.getenv("BAKER_API_KEY", "")


def _baker_scan_via_loopback(args: dict) -> str:
    """Route to /api/scan or /api/scan/client-pm based on capability_slug presence.

    Collects the SSE stream into a single text string. Canonical content key is
    `token` (verified at outputs/dashboard.py:8240 for the capability path and
    :7441/8343 elsewhere). Other event types — status / capabilities / tool_call /
    screenshot / task_id / error / __citations__ prefix — are metadata and skipped.
    """
    query = (args.get("query") or "").strip()
    if not query:
        return "Error: query is required"
    capability_slug = args.get("capability_slug")
    history = args.get("history") or []

    base = _internal_base_url()
    headers = {"X-Baker-Key": _internal_api_key(), "Accept": "text/event-stream"}

    if capability_slug:
        url = f"{base}/api/scan/client-pm"
        payload = {"question": query, "capability_slug": capability_slug, "history": history}
    else:
        url = f"{base}/api/scan"
        payload = {
            "question": query,
            "history": history,
            "project": args.get("project"),
            "role": args.get("role"),
        }

    chunks: list[str] = []
    try:
        with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            with client.stream(
                "POST",
                url,
                json={k: v for k, v in payload.items() if v is not None},
                headers=headers,
            ) as resp:
                if resp.status_code != 200:
                    body = resp.read().decode("utf-8", errors="replace")
                    return f"Error: scan returned HTTP {resp.status_code}: {body[:300]}"
                for line in resp.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    payload_str = line[6:]
                    # [DONE] sentinel and __citations__ markers are not JSON.
                    if payload_str.startswith("__citations__") or payload_str == "[DONE]":
                        continue
                    try:
                        evt = json.loads(payload_str)
                    except Exception:
                        continue
                    if isinstance(evt, dict):
                        token = evt.get("token")
                        if token and isinstance(token, str):
                            chunks.append(token)
                        err = evt.get("error")
                        if err and isinstance(err, str):
                            return f"Error from scan: {err}"
    except httpx.TimeoutException:
        return "Error: scan timed out after 60s"
    except Exception as e:
        return f"Error: scan failed: {e}"

    if not chunks:
        return "(empty response — check capability_slug or query)"
    return "".join(chunks).strip()


def _baker_search_via_loopback(args: dict) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "Error: query is required"
    try:
        limit = int(args.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 50))

    url = f"{_internal_base_url()}/api/search/unified"
    headers = {"X-Baker-Key": _internal_api_key()}
    params = {"q": query, "limit": limit}

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, params=params, headers=headers)
            if resp.status_code != 200:
                return f"Error: search returned HTTP {resp.status_code}: {resp.text[:300]}"
            data = resp.json()
    except httpx.TimeoutException:
        return "Error: search timed out after 15s"
    except Exception as e:
        return f"Error: search failed: {e}"

    items = data.get("results") or data.get("items") or []
    if not items:
        return f"No results for: {query}"
    total = data.get("total", len(items))
    lines = [f"Search results for: {query} ({len(items)} of {total} hits)\n{'=' * 60}"]
    for r in items:
        if isinstance(r, dict):
            parts = [f"  {k}: {v}" for k, v in r.items() if v is not None]
            lines.append("\n".join(parts))
        else:
            lines.append(f"  {r}")
    return "\n---\n".join(lines)


def _baker_substack_search(args: dict) -> str:
    """Semantic search against baker-substack-<publication> Qdrant collection.

    Direct Qdrant call (no /api/* loopback) — the substack collection isn't
    surfaced through any existing baker-master REST endpoint. Voyage embed
    matches the indexing path in scripts/backfill_substack_archive.py +
    triggers/substack_ingest.py._index_to_qdrant.
    """
    publication = (args.get("publication") or "").strip()
    query = (args.get("query") or "").strip()
    if not publication or not query:
        return "Error: both 'publication' and 'query' are required"

    try:
        limit = int(args.get("limit", 5))
    except (TypeError, ValueError):
        limit = 5
    limit = max(1, min(limit, 20))

    qdrant_url = os.environ.get("QDRANT_URL")
    qdrant_key = os.environ.get("QDRANT_API_KEY") or os.environ.get("QDRANT_KEY")
    if not qdrant_url:
        return "Error: QDRANT_URL not configured"
    if not os.environ.get("VOYAGE_API_KEY"):
        return "Error: VOYAGE_API_KEY not configured"

    try:
        from kbl.voyage_client import embed as voyage_embed
        from qdrant_client import QdrantClient
    except ImportError as e:
        return f"Error: dependency missing ({e})"

    collection_name = f"baker-substack-{publication}"
    try:
        qdrant = QdrantClient(url=qdrant_url, api_key=qdrant_key)
    except Exception as e:
        return f"Error: Qdrant client init failed: {e}"

    try:
        qdrant.get_collection(collection_name)
    except Exception:
        return (
            f"Error: no Substack archive for '{publication}'. "
            f"Run `python scripts/backfill_substack_archive.py "
            f"--publication {publication} --apply` after Director provides "
            f"the session cookie in 1Password."
        )

    try:
        query_vec = voyage_embed(query)
    except Exception as e:
        return f"Error: Voyage embed failed: {e}"

    try:
        hits = qdrant.search(
            collection_name=collection_name,
            query_vector=query_vec,
            limit=limit,
            with_payload=True,
        )
    except Exception as e:
        return f"Error: Qdrant search failed: {e}"

    if not hits:
        return f"No matches for '{query}' in {publication} archive."

    lines = [f"Top {len(hits)} matches for '{query}' in {publication}:", ""]
    for i, h in enumerate(hits, 1):
        p = h.payload or {}
        post_date = (p.get("post_date") or "")[:10]
        preview = (p.get("preview") or p.get("body_text") or "")[:400]
        lines.append(f"{i}. {p.get('title') or '(untitled)'}")
        lines.append(f"   URL: {p.get('canonical_url', '')}")
        lines.append(
            f"   Date: {post_date} | Audience: {p.get('audience', '')} | "
            f"Type: {p.get('type', '')}"
        )
        lines.append(f"   Match score: {h.score:.3f}")
        lines.append(f"   Preview: {preview}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _baker_ingest_text_via_loopback(args: dict) -> str:
    title = (args.get("title") or "").strip()
    content = args.get("content") or ""
    if not title or not content:
        return "Error: title and content are required"

    if not any(title.lower().endswith(ext) for ext in (".md", ".txt", ".markdown")):
        title = title + ".md"

    url = f"{_internal_base_url()}/api/ingest"
    headers = {"X-Baker-Key": _internal_api_key()}

    form_data: dict = {}
    if args.get("project"):
        form_data["project"] = args["project"]
    if args.get("role"):
        form_data["role"] = args["role"]
    params: dict = {}
    if args.get("collection"):
        params["collection"] = args["collection"]

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=pathlib.Path(title).suffix,
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as fh:
            files = {"file": (title, fh, "text/plain")}
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    url, headers=headers, params=params, data=form_data, files=files,
                )
                if resp.status_code != 200:
                    return (
                        f"Error: ingest returned HTTP {resp.status_code}: "
                        f"{resp.text[:300]}"
                    )
                result = resp.json()
                return (
                    f"Ingested: {result.get('filename', title)}\n"
                    f"Status: {result.get('status', 'unknown')}\n"
                    f"Collection: {result.get('collection', '')}\n"
                    f"Chunks: {result.get('chunks', 0)}\n"
                    f"Dedup: {result.get('dedup', False)}"
                )
    except httpx.TimeoutException:
        return "Error: ingest timed out after 60s"
    except Exception as e:
        return f"Error: ingest failed: {e}"
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _baker_health_via_loopback() -> str:
    url = f"{_internal_base_url()}/health"  # public path; no auth required
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return f"Error: health returned HTTP {resp.status_code}: {resp.text[:300]}"
            data = resp.json()
    except httpx.TimeoutException:
        return "Error: health probe timed out after 10s"
    except Exception as e:
        return f"Error: health probe failed: {e}"

    parts = [
        f"Status: {data.get('status', 'unknown')}",
        f"Database: {data.get('database', '?')}",
        f"Scheduler: {data.get('scheduler', '?')}",
        f"Scheduled jobs: {data.get('scheduled_jobs', '?')}",
        f"Sentinels healthy: {data.get('sentinels_healthy', '?')}",
        f"Sentinels down: {data.get('sentinels_down', 0)}",
    ]
    if data.get("sentinels_down_list"):
        parts.append(f"  ↳ down: {', '.join(data['sentinels_down_list'])}")
    if data.get("vault_mirror_last_pull"):
        parts.append(f"Vault mirror last pull: {data['vault_mirror_last_pull']}")
    if data.get("vault_mirror_commit_sha"):
        parts.append(f"Vault mirror sha: {str(data['vault_mirror_commit_sha'])[:12]}")
    parts.append(f"Timestamp: {data.get('timestamp', '?')}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Brisen Lab V2 bridge helpers — message bus consumer-side (BRISEN_LAB_V2_BRIDGE_1)
# ---------------------------------------------------------------------------

def _brisen_lab_url() -> str:
    """Brisen Lab daemon base URL; override via BRISEN_LAB_URL env."""
    return os.getenv("BRISEN_LAB_URL", "https://brisen-lab.onrender.com").rstrip("/")


def _brisen_lab_terminal_key() -> str:
    """Per-worker terminal-key for X-Terminal-Key header.

    Lookup order:
      1. BRISEN_LAB_TERMINAL_KEY (preferred — set by 1Password run wrapper)
      2. empty string (caller will get 401 from daemon — surface clearly)
    """
    return os.getenv("BRISEN_LAB_TERMINAL_KEY", "")


def _brisen_lab_caller_terminal() -> str:
    """Caller's terminal slug for from_terminal / inbox-read paths.

    Lookup order:
      1. BAKER_ROLE env (lower-cased; matches role-context filenames)
      2. "cowork" fallback (Cowork Claude.ai App default — no terminal harness)
    """
    role = os.getenv("BAKER_ROLE", "").strip().lower()
    return role or "cowork"


def _brisen_lab_extract_error(resp) -> str:
    """Surface only the daemon's structured `error` field, never raw body.

    Daemon errors are JSON-structured today (`{"error": "...", ...}`). If the
    daemon ever logs request context (session_id, worker_slug fragments,
    headers) into the error body, raw `resp.text` would surface it to the LLM
    via the MCP tool response. This helper parses JSON and surfaces only the
    `error` field; on non-JSON or missing-error-field, falls back to a short
    truncated raw-text slice (80 chars) — enough to debug without leaking
    full request context.
    """
    try:
        body = resp.json()
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, str) and err:
                return err
    except (ValueError, TypeError):
        pass
    try:
        return resp.text[:80]
    except Exception:
        return ""


def _brisen_lab_paste_block_fallback(operation: str, payload: dict) -> str:
    """AC6 fallback marker — when V2 endpoints return 503 (BRISEN_LAB_V2_ENABLED=false).

    Returns a paste-block-shaped string the caller can copy to Director for manual
    relay. Per brief §AC6: paste-block-via-Director fallback works when flag OFF or
    worker unreachable.
    """
    return (
        f"[brisen-lab v2 disabled — paste-block fallback]\n"
        f"operation: {operation}\n"
        f"from_terminal: {_brisen_lab_caller_terminal()}\n"
        f"payload: {json.dumps(payload, default=_json_serial, indent=2)}\n"
        f"# Director: relay this manually until BRISEN_LAB_V2_ENABLED=true on daemon."
    )


def _brisen_lab_post_via_http(args: dict) -> str:
    """POST /msg/<recipient> on the Brisen Lab daemon.

    Wire contract — matches ``scripts/bus_post.py`` (the canonical correct
    client) exactly:
      - Recipients live in the body key ``to`` (a list). The daemon reads
        ``body["to"]`` for delivery; ``body.get("to") or [terminal]`` makes the
        URL path only a fallback.
      - The URL path is the FIRST recipient (``POST /msg/{recipient}``).
      - The SENDER is derived server-side from the ``X-Terminal-Key`` — never
        from the URL path or any body field.
    A prior drift sent body key ``to_terminals`` (which the daemon ignores) and
    addressed the URL to the SENDER, so every message fell back to being
    delivered to its own sender and never reached the recipient (Lesson #8:
    the unit tests encoded the drift and stayed green).

    Fail-open semantics:
      - HTTP 503 → paste-block fallback marker (V2 disabled state)
      - HTTP 4xx → loud error string (caller's bug; surface)
      - Network/timeout → loud error string
      - HTTP 200 → daemon JSON response stringified
    """
    to = args.get("to")
    kind = args.get("kind")
    body = args.get("body")
    if not to or not kind or body is None:
        return "Error: to, kind, body are required"
    if isinstance(to, str):
        to = [to]
    if not isinstance(to, list) or not all(isinstance(x, str) for x in to):
        return "Error: to must be a string or list of strings"

    payload: dict = {
        "to": to,
        "kind": kind,
        "body": body,
    }
    if args.get("topic"):
        payload["topic"] = args["topic"]
    if args.get("parent_id") is not None:
        payload["parent_id"] = args["parent_id"]
    if args.get("thread_id"):
        payload["thread_id"] = args["thread_id"]
    if args.get("tier_required"):
        payload["tier_required"] = args["tier_required"]

    # POST to the first recipient with the full `to` list in the body; the
    # daemon fans out to every slug in body["to"]. Mirrors bus_post.py._post.
    url = f"{_brisen_lab_url()}/msg/{to[0]}"
    headers = {
        "X-Terminal-Key": _brisen_lab_terminal_key(),
        "Content-Type": "application/json",
    }
    if args.get("human_confirmation_token"):
        headers["X-Human-Confirmation-Token"] = args["human_confirmation_token"]

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException:
        return f"Error: brisen-lab POST timed out after 15s ({url})"
    except Exception as e:
        return f"Error: brisen-lab POST failed: {e}"

    if resp.status_code == 503:
        return _brisen_lab_paste_block_fallback("post", payload)
    if resp.status_code >= 400:
        err = _brisen_lab_extract_error(resp)
        return f"Error: brisen-lab POST returned HTTP {resp.status_code}: {err}"
    try:
        data = resp.json()
    except Exception:
        return f"OK (non-JSON response): {resp.text[:200]}"
    return json.dumps(data, default=_json_serial, indent=2)


def _brisen_lab_read_via_http(args: dict) -> str:
    """GET /msg/<terminal> on the Brisen Lab daemon.

    Fail-open: 503 returns empty list with fallback notice; loud on other errors.
    """
    terminal = args.get("terminal") or _brisen_lab_caller_terminal()
    params: dict = {}
    if args.get("since"):
        params["since"] = args["since"]
    if args.get("kind"):
        params["kind"] = args["kind"]
    if args.get("topic"):
        params["topic"] = args["topic"]
    if args.get("exclude_self"):
        params["exclude_self"] = "true"
    # User-facing display limit (what the caller asked to SEE).
    try:
        display_limit = int(args.get("limit", 50))
    except (TypeError, ValueError):
        display_limit = 50
    display_limit = max(1, min(display_limit, 200))

    include_acked = bool(args.get("include_acked", False))

    # Fetch wide so unacked rows aren't buried behind acked ones in a small page.
    # Daemon hard-caps ~200; fetch the max when we intend to client-filter.
    params["limit"] = 200 if not include_acked else display_limit
    # Hint the daemon too (harmless if it ignores the param — contract says it might).
    if not include_acked:
        params["unread"] = "true"

    url = f"{_brisen_lab_url()}/msg/{terminal}"
    headers = {"X-Terminal-Key": _brisen_lab_terminal_key()}

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, params=params, headers=headers)
    except httpx.TimeoutException:
        return f"Error: brisen-lab GET timed out after 15s ({url})"
    except Exception as e:
        return f"Error: brisen-lab GET failed: {e}"

    if resp.status_code == 503:
        return f"[brisen-lab v2 disabled — empty inbox returned for {terminal}]"
    if resp.status_code >= 400:
        err = _brisen_lab_extract_error(resp)
        return f"Error: brisen-lab GET returned HTTP {resp.status_code}: {err}"
    try:
        data = resp.json()
    except Exception:
        err = _brisen_lab_extract_error(resp)
        return f"Error: brisen-lab GET non-JSON response: {err}"

    rows = data if isinstance(data, list) else data.get("messages") or data.get("rows") or []

    if not include_acked:
        # Load-bearing: filter regardless of whether the daemon honored `unread`.
        rows = [r for r in rows if not r.get("acknowledged_at")]

    rows = rows[:display_limit]

    if not rows:
        shown = {k: v for k, v in params.items() if k not in ("limit", "unread")}
        suffix = "" if include_acked else " (unacked only; pass include_acked=true to see acked)"
        return f"Inbox empty for {terminal} (filters: {json.dumps(shown)}){suffix}"
    return json.dumps(rows, default=_json_serial, indent=2)


def _brisen_lab_ack_via_http(args: dict) -> str:
    """POST /msg/<id>/ack for one or many message ids (NM3: sole authoritative ack path)."""
    msg_id = args.get("msg_id")
    msg_ids = args.get("msg_ids") or []
    if msg_id is not None:
        msg_ids = [msg_id]
    if not msg_ids:
        return "Error: msg_id or msg_ids is required"
    if not all(isinstance(x, int) for x in msg_ids):
        return "Error: msg_ids must be integers"

    headers = {"X-Terminal-Key": _brisen_lab_terminal_key()}
    base = _brisen_lab_url()

    results: list[dict] = []
    try:
        with httpx.Client(timeout=15.0) as client:
            for mid in msg_ids:
                url = f"{base}/msg/{mid}/ack"
                try:
                    resp = client.post(url, headers=headers)
                except httpx.TimeoutException:
                    results.append({"msg_id": mid, "status": "timeout"})
                    continue
                except Exception as e:
                    results.append({"msg_id": mid, "status": "error", "error": str(e)[:120]})
                    continue
                if resp.status_code == 503:
                    # Drain side fail-open: silent no-op + record
                    results.append({"msg_id": mid, "status": "v2_disabled"})
                    continue
                results.append({"msg_id": mid, "status": resp.status_code})
    except Exception as e:
        return f"Error: brisen-lab ack loop failed: {e}"

    return json.dumps({"acked": results}, default=_json_serial, indent=2)


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
            # Match name / role / email + provenance fields (linkedin_url,
            # source_of_introduction). Surface refinement
            # BAKER_VIP_MCP_EXPOSE_PROVENANCE_FIELDS_1 (2026-05-23).
            sql = (
                "SELECT * FROM vip_contacts "
                "WHERE name ILIKE %s "
                "   OR role ILIKE %s "
                "   OR email ILIKE %s "
                "   OR linkedin_url ILIKE %s "
                "   OR source_of_introduction ILIKE %s "
                "ORDER BY name"
            )
            pat = f"%{search}%"
            rows = _query(sql, (pat, pat, pat, pat, pat), limit)
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
        _store = None
        try:
            from memory.store_back import SentinelStoreBack
            _store = SentinelStoreBack._get_global_instance()
            _use_cortex = _store.get_cortex_config('tool_router_enabled', False)
        except Exception:
            pass

        # DEADLINE_MATTER_SLUG_BACKFILL_1 Scope A3: classify before write so
        # the MCP-tool door no longer bypasses the slug classifier.
        _matter_slug = None
        try:
            from orchestrator.pipeline import _match_matter_slug
            from kbl import slug_registry
            if _store is None:
                from memory.store_back import SentinelStoreBack
                _store = SentinelStoreBack._get_global_instance()
            _matter_name = _match_matter_slug(description, source_snippet or "", _store)
            _matter_slug = slug_registry.normalize(_matter_name)
        except Exception:
            _matter_slug = None

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
                matter_slug=_matter_slug,
            )
            if dl_id:
                return f"Deadline created via Cortex (id={dl_id}, priority={priority}):\n  {description}\n  Due: {due_date}"
            return "Error: failed to create deadline"
        else:
            # Legacy path (feature flag OFF)
            row = _write(
                """
                INSERT INTO deadlines (description, due_date, source_type, source_id, source_snippet, confidence, priority, status, matter_slug)
                VALUES (%s, %s, 'cowork_session', 'mcp', %s, %s, %s, 'active', %s)
                RETURNING id, description, due_date, priority
                """,
                (description, due_date, source_snippet, confidence, priority, _matter_slug),
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

    # ------------------------------------------------------------------
    # VAULT-READ TOOL HANDLERS (SOT_OBSIDIAN_1_PHASE_D)
    # ------------------------------------------------------------------

    elif name == "baker_vault_list":
        from vault_mirror import list_ops_files, VaultPathError

        prefix = args.get("prefix", "_ops/")
        try:
            paths = list_ops_files(prefix)
        except VaultPathError as e:
            return f"Error: {e}"
        if not paths:
            return f"No files found under prefix: {prefix}"
        return json.dumps({"prefix": prefix, "paths": paths}, indent=2)

    elif name == "baker_vault_read":
        from vault_mirror import read_ops_file, VaultPathError

        path = args.get("path")
        if not path:
            return "Error: 'path' argument is required"
        try:
            result = read_ops_file(path)
        except VaultPathError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2)

    elif name == "baker_vault_write":
        from baker_mcp.vault_write import (
            write_vault_file,
            VaultWriteError,
            _redact,
        )

        path = args.get("path")
        content = args.get("content")
        mode = args.get("mode", "append")
        commit_message = args.get("commit_message")

        if not path or not content or not commit_message:
            return "Error: 'path', 'content', and 'commit_message' are required"

        token = os.getenv("GITHUB_TOKEN", "")
        if not token:
            return "Error: GITHUB_TOKEN env var not set on Render"

        # Audit BEFORE attempt — captures intent even on hard crashes between
        # INSERT and the GitHub round-trip. success=NULL marks "in flight";
        # the daily sweeper detects rows still NULL after 5 minutes.
        audit_id = _emit_vault_write_audit(path, mode, commit_message)

        try:
            result = write_vault_file(path, content, mode, commit_message, token)
            _update_vault_write_audit(audit_id, success=True, payload_extra=result)
            return json.dumps(result, indent=2)
        except VaultWriteError as e:
            # Validation rejection — should never contain tokens, but redact anyway.
            _update_vault_write_audit(
                audit_id, success=False, error_message=_redact(str(e))
            )
            return f"Error: {_redact(str(e))}"
        except httpx.HTTPStatusError as e:
            # GitHub error response body could echo Authorization header — MUST
            # redact before audit + caller. Lesson #18 + vault_mirror._redact.
            body = _redact(f"{e.response.status_code}: {e.response.text[:200]}")
            _update_vault_write_audit(
                audit_id, success=False, error_message=body
            )
            return f"Error: GitHub API rejected write — {e.response.status_code}"
        except Exception as e:
            _update_vault_write_audit(
                audit_id, success=False, error_message=_redact(str(e))
            )
            return f"Error: {_redact(str(e))}"

    elif name == "baker_scan":
        return _baker_scan_via_loopback(args)

    elif name == "baker_search":
        return _baker_search_via_loopback(args)

    elif name == "baker_substack_search":
        return _baker_substack_search(args)

    elif name == "baker_ingest_text":
        return _baker_ingest_text_via_loopback(args)

    elif name == "baker_health":
        return _baker_health_via_loopback()

    elif name == "baker_inbox_post":
        return _brisen_lab_post_via_http(args)

    elif name == "baker_inbox_read":
        return _brisen_lab_read_via_http(args)

    elif name == "baker_inbox_ack":
        return _brisen_lab_ack_via_http(args)

    elif name in CLAIMSMAX_TOOL_NAMES:
        return dispatch_claimsmax(name, args)

    elif name in GROK_TOOL_NAMES:
        return dispatch_grok(name, args)

    elif name in PERPLEXITY_TOOL_NAMES:
        return dispatch_perplexity(name, args)

    elif name in GMAIL_TOOL_NAMES:
        return dispatch_gmail(name, args)

    elif name in EMAIL_TOOL_NAMES:
        return dispatch_email(name, args)

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
