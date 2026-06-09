"""Email MCP tool surface — provider-aware search/read over the MERGED mail store.

`baker_email_search` / `baker_email_read` expose the unified `email_messages`
store, which holds BOTH Gmail- and Outlook/M365-Graph-ingested mail (both sources
land via `triggers.email_trigger._process_email_threads`). This is the surface
that sees Director's `dvallen@brisengroup.com` mail AFTER the ~2026-06-03 M365
migration.

Why this exists (M365_MAIL_BLINDSPOT_DIAGNOSE_FIX_1): `baker_gmail_*` is
Gmail-OAuth-only — it queries the legacy Gmail account and is STRUCTURALLY BLIND
to brisengroup mail post-migration, returning a silent empty. graph_mail ingests
M365 mail into `email_messages`, but Qdrant/`baker_search` did not reliably
surface it. The reliable surface is this Postgres-backed store search.

Providers:
  store (default) — `email_messages` (merged Gmail + Graph ingested mail). Reliable, complete.
  graph           — live Microsoft Graph inbox (freshest, pre-ingestion).
  all             — store + graph merged.

Search shape (M365_MAIL_BLINDSPOT build-detail, lead #2631 / codex #2627): the
match is TOKENIZED and field-aware — each whitespace term must match (AND) across
subject/sender/body (OR within a term). The pre-existing
`retriever.get_email_messages` is a WHOLE-QUERY ILIKE, so a multi-term/literal
query ('M.Spanyi@eh.at court hearing') silently returns 0 even though 'Spanyi'
alone returns dozens — inheriting that would re-create the blindspot. We run our
own tokenized query against `email_messages` via the shared retriever connection
(reusing the store + its SearchBackendUnavailable outage signal), and expose a
`source` filter (gmail|graph|exchange) now that email_messages carries a source.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from mcp.types import Tool  # type: ignore[import-not-found]

logger = logging.getLogger("baker.tools.email")

_PROVIDERS = ("store", "graph", "all")
_DEFAULT_PROVIDER = "store"
_MAX_RESULTS_HARD_CAP = 50
_SNIPPET_CAP = 8_000
_BODY_CAP = 50_000

# Fields each query token is matched against (OR within a token; AND across tokens).
_MATCH_FIELDS = ("subject", "sender_name", "sender_email", "full_body")


EMAIL_TOOLS: list[Tool] = [
    Tool(
        name="baker_email_search",
        description=(
            "Search Director's MERGED mailbox store (email_messages) — Gmail AND "
            "Outlook/Microsoft 365 mail in ONE surface. THIS is the tool for "
            "dvallen@brisengroup.com / Outlook / M365 mail (migrated ~2026-06-03); "
            "baker_gmail_search is Gmail-OAuth-only and is BLIND to brisengroup "
            "mail. Keyword match on subject / sender / body, newest first. "
            "Empty query returns the most recent emails. provider=store (default, "
            "reliable Postgres store), graph (live M365 inbox), or all (merged). "
            "A backend outage is surfaced as backend_unavailable=true — never read "
            "an empty result as 'no mail' without checking that flag."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Keyword(s) — matched against subject, sender name, sender "
                        "email, and body (case-insensitive). Empty/omitted returns "
                        "the most recent emails. This is NOT Gmail query syntax: "
                        "pass a plain name/term (e.g. 'Spanyi' or 'hearing'), not "
                        "'from:...'."
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Cap on matches. Default 10, hard max 50.",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50,
                },
                "provider": {
                    "type": "string",
                    "enum": list(_PROVIDERS),
                    "description": (
                        "store = merged email_messages (default, reliable); "
                        "graph = live M365 inbox; all = store + graph merged."
                    ),
                    "default": _DEFAULT_PROVIDER,
                },
                "source": {
                    "type": "string",
                    "description": (
                        "Optional store filter on the ingest source: 'graph' "
                        "(Outlook/M365), 'email' (Gmail), 'exchange'. Omit for all "
                        "sources. Only applies to provider=store/all."
                    ),
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="baker_email_read",
        description=(
            "Read one email's full body + headers by message_id from the merged "
            "store (email_messages). Use the message_id returned by "
            "baker_email_search. provider=store (default) reads the ingested store; "
            "provider=graph reads live from the M365 inbox."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "message_id from a baker_email_search result.",
                },
                "provider": {
                    "type": "string",
                    "enum": ["store", "graph"],
                    "description": "store = email_messages (default); graph = live M365.",
                    "default": "store",
                },
            },
            "required": ["message_id"],
        },
    ),
]

EMAIL_TOOL_NAMES = frozenset(t.name for t in EMAIL_TOOLS)


# ── helpers ────────────────────────────────────────────────────────────────

def _clamp_max(value: Any, default: int = 10) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return default
    return min(value, _MAX_RESULTS_HARD_CAP)


# Gmail search operators a caller may paste in by habit (this is a plain-text
# store, NOT Gmail). VALUE operators keep their value (from:x@y -> x@y); DATE /
# BOOLEAN operators are dropped — they don't belong in an ILIKE and an undropped
# 'after:2026/06/05' token would AND-match nothing, re-creating a false-empty
# (codex #2639: pasted 'from:M.Spanyi@eh.at after:2026/06/05' matched 0 rows).
_GMAIL_VALUE_OPS = ("from:", "to:", "cc:", "bcc:", "subject:", "label:")
_GMAIL_DROP_OPS = (
    "after:", "before:", "older:", "newer:", "older_than:", "newer_than:",
    "has:", "is:", "in:", "category:", "filename:",
)


def _tokenize(query: str) -> list[str]:
    """Split a query into match terms, normalizing pasted Gmail operators.

    Whole-query ILIKE is the blindspot we are fixing (lead #2631) — each term
    matches independently. Gmail operators are normalized so a caller who copies
    a Gmail-syntax query still hits (codex #2639)."""
    out: list[str] = []
    for raw in (query or "").split():
        tok = raw.strip().strip('"').strip("'")
        if not tok:
            continue
        low = tok.lower()
        if any(low.startswith(op) for op in _GMAIL_DROP_OPS):
            continue  # date/boolean operator — not a text term
        for op in _GMAIL_VALUE_OPS:
            if low.startswith(op):
                tok = tok[len(op):].strip().strip('"').strip("'")
                break
        if tok:
            out.append(tok)
    return out


def _build_email_search_sql(query: str, source: str | None, limit: int) -> tuple[str, list[Any]]:
    """Build a TOKENIZED, field-aware query over email_messages.

    Each token must match (AND across tokens) at least one of subject / sender_name
    / sender_email / full_body (OR within a token). Optional exact source filter.
    Returns (sql, params). Pure — unit-testable without a DB.
    """
    tokens = _tokenize(query)
    where: list[str] = []
    params: list[Any] = []
    for tok in tokens:
        ors = " OR ".join(f"{f} ILIKE %s" for f in _MATCH_FIELDS)
        where.append(f"({ors})")
        params.extend([f"%{tok}%"] * len(_MATCH_FIELDS))
    if source:
        where.append("source = %s")
        params.append(source)
    where_sql = " AND ".join(where) if where else "TRUE"
    sql = (
        "SELECT message_id, thread_id, sender_name, sender_email, subject, "
        f"LEFT(full_body, {_SNIPPET_CAP}) AS snippet, received_date, source "
        "FROM email_messages "
        f"WHERE {where_sql} "
        "ORDER BY received_date DESC NULLS LAST, ingested_at DESC NULLS LAST "
        "LIMIT %s"
    )
    params.append(limit)
    return sql, params


_ROW_COLS = ("message_id", "thread_id", "sender_name", "sender_email",
             "subject", "snippet", "received_date", "source")


def _row_to_match(row: Any) -> dict[str, Any]:
    data = {c: row[i] for i, c in enumerate(_ROW_COLS)}
    return {
        "message_id": data.get("message_id"),
        "sender": data.get("sender_name") or data.get("sender_email"),
        "sender_email": data.get("sender_email"),
        "subject": data.get("subject"),
        "date": str(data.get("received_date"))[:19] if data.get("received_date") else None,
        "source": data.get("source"),
        "snippet": (data.get("snippet") or "")[:_SNIPPET_CAP],
    }


def _run_email_query(sql: str, params: list[Any]) -> list[Any]:
    """Execute a read against email_messages via the shared retriever connection.

    Raises SearchBackendUnavailable on a genuine backend outage (so callers do
    not read it as 'no mail'); rolls back + resets the pooled conn on any error.
    """
    from memory.retriever import SentinelRetriever, SearchBackendUnavailable
    try:
        from memory.retriever import _is_backend_unavailable_error
    except Exception:  # pragma: no cover
        def _is_backend_unavailable_error(_e):  # type: ignore[misc]
            return False

    conn = None
    try:
        retriever = SentinelRetriever._get_global_instance()
        conn = retriever._get_pg_conn()
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return rows
    except Exception as e:
        try:
            if conn is not None:
                conn.rollback()
        except Exception:
            pass
        try:
            SentinelRetriever._get_global_instance()._reset_pg_conn()
        except Exception:
            pass
        if _is_backend_unavailable_error(e):
            raise SearchBackendUnavailable(str(e)) from e
        raise


def _store_search(query: str, max_results: int, source: str | None = None) -> dict[str, Any]:
    """Tokenized, field-aware search of the merged email_messages store.

    Surfaces a backend OUTAGE loudly (backend_unavailable) so an empty result is
    never silently read as 'no mail'."""
    from memory.retriever import SearchBackendUnavailable

    sql, params = _build_email_search_sql(query, source, max_results)
    try:
        rows = _run_email_query(sql, params)
    except SearchBackendUnavailable as e:
        logger.warning(f"email store backend unavailable: {e}")
        return {
            "provider": "store",
            "query": query,
            "source": source,
            "backend_unavailable": True,
            "error": str(e),
            "match_count": 0,
            "matches": [],
            "notice": "search backend unavailable — retry; do NOT read as 'no mail'.",
        }
    except Exception as e:
        logger.warning(f"email store search failed (non-fatal): {e}")
        return {
            "provider": "store",
            "query": query,
            "source": source,
            "error": str(e),
            "match_count": 0,
            "matches": [],
        }

    matches = [_row_to_match(r) for r in rows]
    out: dict[str, Any] = {
        "provider": "store",
        "query": query,
        "match_count": len(matches),
        "matches": matches,
    }
    if source:
        out["source"] = source
    return out


def _graph_search(query: str, max_results: int) -> dict[str, Any]:
    """Live Microsoft Graph inbox search (freshest, pre-ingestion)."""
    try:
        from kbl.graph_client import GraphClient
        from config.settings import GraphConfig
    except Exception as e:  # pragma: no cover
        return {"provider": "graph", "error": f"graph import failed: {e}",
                "match_count": 0, "matches": []}

    try:
        client = GraphClient(GraphConfig())
        if not client.is_ready():
            return {
                "provider": "graph",
                "error": "graph mailbox not ready (BAKER_USE_GRAPH off or creds missing)",
                "match_count": 0,
                "matches": [],
            }
        page = client.get(
            f"/users/{client.cfg.mail_user}/mailFolders/Inbox/messages",
            params={
                "$select": "id,conversationId,subject,from,receivedDateTime,bodyPreview",
                "$top": max_results,
            },
        )
        if page is None:
            return {"provider": "graph", "error": "graph search failed (auth/HTTP)",
                    "match_count": 0, "matches": []}
        q = (query or "").lower()
        matches: list[dict[str, Any]] = []
        for msg in page.get("value", []):
            sender = ((msg.get("from") or {}).get("emailAddress") or {})
            hay = " ".join([
                str(msg.get("subject", "")),
                str(msg.get("bodyPreview", "")),
                str(sender.get("address", "")),
                str(sender.get("name", "")),
            ]).lower()
            if not q or q in hay:
                matches.append({
                    "message_id": msg.get("id"),
                    "sender": sender.get("name") or sender.get("address"),
                    "subject": msg.get("subject"),
                    "date": msg.get("receivedDateTime"),
                    "snippet": str(msg.get("bodyPreview", ""))[:_SNIPPET_CAP],
                })
        return {"provider": "graph", "query": query,
                "match_count": len(matches), "matches": matches[:max_results]}
    except Exception as e:
        logger.warning(f"graph search failed (non-fatal): {e}")
        return {"provider": "graph", "error": str(e), "match_count": 0, "matches": []}


def _search(args: dict) -> str:
    query = str(args.get("query", "") or "").strip()
    max_results = _clamp_max(args.get("max_results"), default=10)
    provider = str(args.get("provider") or _DEFAULT_PROVIDER).strip().lower()
    if provider not in _PROVIDERS:
        provider = _DEFAULT_PROVIDER
    source = str(args.get("source") or "").strip().lower() or None

    if provider == "store":
        return json.dumps(_store_search(query, max_results, source))
    if provider == "graph":
        return json.dumps(_graph_search(query, max_results))

    # provider == "all": merge store + graph, surface per-provider errors.
    store = _store_search(query, max_results, source)
    graph = _graph_search(query, max_results)
    errors: dict[str, str] = {}
    if store.get("error"):
        errors["store"] = store["error"]
    if graph.get("error"):
        errors["graph"] = graph["error"]
    out: dict[str, Any] = {
        "provider": "all",
        "query": query,
        "match_count": int(store.get("match_count", 0)) + int(graph.get("match_count", 0)),
        "results": {"store": store, "graph": graph},
    }
    if errors:
        out["errors"] = errors
    # A store outage makes a 0 count untrustworthy — propagate the loud flag.
    if store.get("backend_unavailable"):
        out["backend_unavailable"] = True
        out["notice"] = "store backend unavailable — retry; do NOT read as 'no mail'."
    return json.dumps(out)


def _read(args: dict) -> str:
    message_id = str(args.get("message_id", "") or "").strip()
    provider = str(args.get("provider") or "store").strip().lower()
    if not message_id:
        return json.dumps({"error": "message_id is required"})

    if provider == "graph":
        try:
            from kbl.graph_client import GraphClient
            from config.settings import GraphConfig
            client = GraphClient(GraphConfig())
            if not client.is_ready():
                return json.dumps({"error": "graph mailbox not ready"})
            msg = client.get(
                f"/users/{client.cfg.mail_user}/messages/{message_id}",
                params={"$select": "id,conversationId,subject,from,receivedDateTime,body,bodyPreview"},
            )
            if msg is None:
                return json.dumps({"error": "graph read failed", "message_id": message_id})
            sender = ((msg.get("from") or {}).get("emailAddress") or {})
            body = (msg.get("body") or {}).get("content", "") or msg.get("bodyPreview", "")
            return json.dumps({
                "provider": "graph",
                "message_id": msg.get("id"),
                "sender": sender.get("name") or sender.get("address"),
                "subject": msg.get("subject"),
                "date": msg.get("receivedDateTime"),
                "body": str(body)[:_BODY_CAP],
            })
        except Exception as e:
            logger.warning(f"graph read failed (non-fatal): {e}")
            return json.dumps({"error": str(e), "message_id": message_id})

    # provider == "store": read the merged store by message_id.
    from memory.retriever import SentinelRetriever

    conn = None
    try:
        retriever = SentinelRetriever._get_global_instance()
        conn = retriever._get_pg_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT message_id, thread_id, sender_name, sender_email, subject,
                   full_body, received_date, priority, ingested_at, source
            FROM email_messages
            WHERE message_id = %s
            LIMIT 1
            """,
            (message_id,),
        )
        row = cur.fetchone()
        cur.close()
    except Exception as e:
        logger.warning(f"email store read failed (non-fatal): {e}")
        try:
            if conn is not None:
                conn.rollback()
        except Exception:
            pass
        try:
            SentinelRetriever._get_global_instance()._reset_pg_conn()
        except Exception:
            pass
        return json.dumps({"error": str(e), "message_id": message_id})

    if not row:
        return json.dumps({
            "error": "email not found in email_messages",
            "message_id": message_id,
            "hint": "try provider=graph for a very recent message not yet ingested.",
        })
    cols = ["message_id", "thread_id", "sender_name", "sender_email", "subject",
            "full_body", "received_date", "priority", "ingested_at", "source"]
    data = {c: (str(v) if v is not None else None) for c, v in zip(cols, row)}
    if data.get("full_body"):
        data["full_body"] = data["full_body"][:_BODY_CAP]
    return json.dumps({"provider": "store", "message": data})


def dispatch_email(name: str, args: dict) -> str:
    """Route an MCP email tool call. Returns a JSON string."""
    try:
        if name == "baker_email_search":
            return _search(args)
        if name == "baker_email_read":
            return _read(args)
        return json.dumps({"error": f"unknown email tool: {name}"})
    except Exception as e:  # fault-tolerant: never raise to the MCP layer
        logger.error(f"dispatch_email({name}) failed: {e}")
        return json.dumps({"error": f"email tool failed: {e}"})
