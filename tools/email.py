"""Email MCP tool surface — provider-aware search/read over the MERGED mail store.

`baker_email_search` / `baker_email_read` expose the unified `email_messages`
store, which holds BOTH Gmail- and Outlook/M365-Graph-ingested mail (both sources
land via `triggers.email_trigger._process_email_threads`). This is the surface
that sees Director's `dvallen@brisengroup.com` mail AFTER the ~2026-06-03 M365
migration.

`baker_email_attachment_read` (BAKER_M365_ATTACHMENT_READ_SURFACE_1) exposes the
attachment BYTES that the Graph mail trigger already persists into the
`email_attachments` store (kbl/attachment_store.py) but which had no read surface
— so the desk could read M365 mail bodies yet not pull attachment bytes. It lists
attachments for a message_id and returns extracted text (+ optional base64 bytes)
for a named/indexed attachment. Source-aware (graph | bluewin | email). It does
NOT re-fetch from Graph — read-only over the durable store. Auth is the same
transport-level X-Baker-Key gate as every MCP tool (POST /mcp -> _mcp_verify_key,
fail-closed 401); there is no separate unauthenticated path.

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

import base64
import json
import logging
import mimetypes
import re
from typing import Any

from mcp.types import Tool  # type: ignore[import-not-found]

logger = logging.getLogger("baker.tools.email")

_PROVIDERS = ("store", "graph", "all")
_DEFAULT_PROVIDER = "store"
_MAX_RESULTS_HARD_CAP = 50
_SNIPPET_CAP = 8_000
_BODY_CAP = 50_000

# Extensions the gmail attachment pipeline can extract text from. Mirrors
# scripts.extract_gmail._ATTACHMENT_EXTENSIONS; declared locally so importing
# this module stays light (the extractor pulls heavy google/office deps and is
# imported lazily only when a text-bearing attachment is actually fetched).
_ATTACH_TEXT_EXTS = {".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md", ".json"}

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
    Tool(
        name="baker_email_attachment_read",
        description=(
            "Read attachment BYTES/TEXT for a stored email (Gmail OR Outlook/M365 "
            "Graph), from the durable email_attachments store. THIS is how you pull "
            "attachment bytes for dvallen@brisengroup.com / M365 mail — "
            "baker_email_read returns only the body, and baker_gmail_attachment_read "
            "is Gmail-OAuth-only (blind to M365). Two modes: (1) LIST — omit both "
            "filename and attachment_index to enumerate a message's attachments "
            "(filename/mime/size/index); (2) FETCH — give filename (exact, "
            "case-sensitive; attachment_index disambiguates duplicates) OR "
            "attachment_index alone (1-based position) to get extracted text, plus "
            "base64 bytes when include_bytes=true. Read-only over the store — does "
            "NOT re-fetch from Graph. Payloads >5MB are metadata-only (bytes "
            "unavailable). Use the message_id from baker_email_search/baker_email_read."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": (
                        "message_id from baker_email_search / baker_email_read "
                        "(the stored mail's id; same id the attachment rows are "
                        "keyed by)."
                    ),
                },
                "filename": {
                    "type": "string",
                    "description": (
                        "Attachment filename, exact case-sensitive match. Omit "
                        "(with no attachment_index) to LIST the message's "
                        "attachments instead of fetching one."
                    ),
                },
                "attachment_index": {
                    "type": "integer",
                    "description": (
                        "1-based index. With filename: tiebreaker among duplicates "
                        "(default 1). Without filename: selects the Nth attachment "
                        "in the message (id order). Omit entirely (with no filename) "
                        "for LIST mode."
                    ),
                    "minimum": 1,
                },
                "source": {
                    "type": "string",
                    "description": (
                        "Optional ingest-source filter: 'graph' (Outlook/M365), "
                        "'bluewin', 'email' (Gmail), 'exchange'. Omit for all sources."
                    ),
                },
                "include_bytes": {
                    "type": "boolean",
                    "description": (
                        "If true, include base64-encoded raw bytes alongside "
                        "extracted text. Default false (text only)."
                    ),
                    "default": False,
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
# store, NOT Gmail). VALUE operators keep their value (from:x@y -> x@y); DATE
# operators (after:/before:) are TRANSLATED into received_date bounds; other
# boolean operators are dropped — none of them belong in an ILIKE, and an
# unhandled 'after:2026/06/05' token would AND-match nothing, re-creating the
# false-empty (lead #2640 / codex #2639: pasted Gmail syntax matched 0 rows).
_GMAIL_VALUE_OPS = ("from:", "to:", "cc:", "bcc:", "subject:", "label:")
_GMAIL_AFTER_OPS = ("after:", "newer:")
_GMAIL_BEFORE_OPS = ("before:", "older:")
_GMAIL_DROP_OPS = ("older_than:", "newer_than:", "has:", "is:", "in:",
                   "category:", "filename:")

_DATE_RE = re.compile(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$")


def _parse_date(value: str) -> str | None:
    """Parse a Gmail-style YYYY/MM/DD (or YYYY-MM-DD) date to an ISO string."""
    m = _DATE_RE.match((value or "").strip())
    if not m:
        return None
    y, mo, d = (int(g) for g in m.groups())
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _parse_query(query: str) -> tuple[list[str], str | None, str | None]:
    """Normalize a query into (text_tokens, after_date, before_date).

    Each text token matches independently (AND across tokens); after/before are
    translated into received_date bounds. Pasted Gmail operators are handled so a
    copied Gmail-syntax query still hits (lead #2640)."""
    tokens: list[str] = []
    after: str | None = None
    before: str | None = None
    for raw in (query or "").split():
        tok = raw.strip().strip('"').strip("'")
        if not tok:
            continue
        low = tok.lower()
        matched_date = False
        for op in _GMAIL_AFTER_OPS:
            if low.startswith(op):
                after = _parse_date(tok.split(":", 1)[1]) or after
                matched_date = True
                break
        if matched_date:
            continue
        for op in _GMAIL_BEFORE_OPS:
            if low.startswith(op):
                before = _parse_date(tok.split(":", 1)[1]) or before
                matched_date = True
                break
        if matched_date:
            continue
        if any(low.startswith(op) for op in _GMAIL_DROP_OPS):
            continue  # boolean operator — not a text term
        for op in _GMAIL_VALUE_OPS:
            if low.startswith(op):
                tok = tok[len(op):].strip().strip('"').strip("'")
                break
        if tok:
            tokens.append(tok)
    return tokens, after, before


def _tokenize(query: str) -> list[str]:
    """Text match-terms only (Gmail operators normalized). See _parse_query."""
    return _parse_query(query)[0]


def _build_email_search_sql(query: str, source: str | None, limit: int) -> tuple[str, list[Any]]:
    """Build a TOKENIZED, field-aware query over email_messages.

    Each token must match (AND across tokens) at least one of subject / sender_name
    / sender_email / full_body (OR within a token). after:/before: become
    received_date bounds. Optional exact source filter. Returns (sql, params).
    Pure — unit-testable without a DB.
    """
    tokens, after, before = _parse_query(query)
    where: list[str] = []
    params: list[Any] = []
    for tok in tokens:
        ors = " OR ".join(f"{f} ILIKE %s" for f in _MATCH_FIELDS)
        where.append(f"({ors})")
        params.extend([f"%{tok}%"] * len(_MATCH_FIELDS))
    if after:
        where.append("received_date >= %s")
        params.append(after)
    if before:
        where.append("received_date < %s")
        params.append(before)
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


def _attachment_read(args: dict) -> str:
    """Read attachment bytes/text from the email_attachments store.

    Two modes (see the tool description): LIST when neither filename nor
    attachment_index is given; FETCH otherwise. Fault-tolerant — every store
    call already returns []/None on failure, and this wrapper never raises.
    """
    message_id = str(args.get("message_id", "") or "").strip()
    filename = str(args.get("filename", "") or "").strip()
    raw_index = args.get("attachment_index")
    source = str(args.get("source") or "").strip().lower() or None
    include_bytes = bool(args.get("include_bytes", False))

    if not message_id:
        return json.dumps({"error": "message_id is required"})

    index_provided = raw_index is not None
    if index_provided:
        if not isinstance(raw_index, int) or isinstance(raw_index, bool) or raw_index < 1:
            return json.dumps({
                "error": f"attachment_index must be a positive integer (got {raw_index!r})",
            })
        index = raw_index
    else:
        index = 1

    from kbl.attachment_store import (
        list_attachments,
        get_attachment_read,
        AttachmentStoreUnavailable,
    )

    def _outage(e):
        logger.warning(f"attachment store backend unavailable: {e}")
        return json.dumps({
            "message_id": message_id,
            "source": source,
            "backend_unavailable": True,
            "error": str(e),
            "notice": "attachment store unavailable — retry; do NOT read as 'no attachments'.",
        })

    # Store OUTAGE on the LIST read — never report as attachment_count:0 /
    # 'no attachments found' (mirrors baker_email_search's backend_unavailable).
    try:
        rows = list_attachments(message_id, source)
    except AttachmentStoreUnavailable as e:
        return _outage(e)

    # LIST mode — enumerate the message's attachments (metadata only).
    if not filename and not index_provided:
        return json.dumps({
            "message_id": message_id,
            "source": source,
            "attachment_count": len(rows),
            "attachments": [
                {
                    "index": i + 1,
                    "filename": r.get("filename"),
                    "mime_type": r.get("mime_type"),
                    "size_bytes": r.get("size_bytes"),
                    "storage": r.get("storage"),
                    "source": r.get("source"),
                }
                for i, r in enumerate(rows)
            ],
        })

    if not rows:
        return json.dumps({
            "error": "no attachments found for message_id",
            "message_id": message_id,
            "source": source,
        })

    # FETCH mode — select the target row.
    if filename:
        matches = [r for r in rows if (r.get("filename") or "") == filename]
        if not matches:
            return json.dumps({
                "error": f"filename not found in message: {filename}",
                "message_id": message_id,
                "available_filenames": sorted(
                    {r.get("filename") for r in rows if r.get("filename")}
                ),
            })
        if index > len(matches):
            return json.dumps({
                "error": (
                    f"attachment_index {index} out of range "
                    f"({len(matches)} attachment(s) named {filename!r})"
                ),
                "filename": filename,
                "match_count": len(matches),
            })
        target = matches[index - 1]
        match_count = len(matches)
    else:
        if index > len(rows):
            return json.dumps({
                "error": (
                    f"attachment_index {index} out of range "
                    f"({len(rows)} attachment(s) on message)"
                ),
                "message_id": message_id,
                "attachment_count": len(rows),
            })
        target = rows[index - 1]
        match_count = len(rows)

    # Payloads >5MB persist metadata-only (data=NULL) — bytes are not available.
    if target.get("storage") == "metadata_only":
        return json.dumps({
            "error": "attachment stored metadata-only (payload >5MB not persisted); bytes unavailable",
            "message_id": message_id,
            "filename": target.get("filename"),
            "size_bytes": target.get("size_bytes"),
            "storage": "metadata_only",
        })

    # Byte fetch — distinguish a store OUTAGE (backend_unavailable) from a
    # genuine miss/NULL payload (true 'unavailable'). get_attachment_read RAISES
    # on outage; None means the row genuinely isn't there.
    try:
        full = get_attachment_read(target["id"])
    except AttachmentStoreUnavailable as e:
        return _outage(e)
    if full is None or full.get("data") is None:
        return json.dumps({
            "error": "attachment payload unavailable (store miss or NULL data)",
            "message_id": message_id,
            "filename": target.get("filename"),
        })

    file_bytes = full["data"]
    filename_out = full.get("filename") or filename or f"attachment_{target['id']}"

    # Extract text via the SAME pipeline baker_gmail_attachment_read uses.
    from pathlib import Path
    ext = Path(filename_out).suffix.lower()
    text = ""
    text_error = None
    if ext in _ATTACH_TEXT_EXTS:
        try:
            from scripts.extract_gmail import _extract_text_from_bytes
            text = _extract_text_from_bytes(file_bytes, filename_out, ext) or ""
        except Exception as e:
            text_error = str(e)
            logger.warning(f"attachment text extraction failed ({filename_out}): {e}")

    mime_type = full.get("mime_type")
    if not mime_type:
        guessed, _ = mimetypes.guess_type(filename_out)
        mime_type = guessed or "application/octet-stream"

    result: dict[str, Any] = {
        "message_id": message_id,
        "source": full.get("source"),
        "filename": filename_out,
        "mime_type": mime_type,
        "size_bytes": full.get("size_bytes"),
        "content_sha256": full.get("content_sha256"),
        "storage": full.get("storage"),
        "attachment_index": index,
        "match_count": match_count,
        "text": text,
        "text_extracted": bool(text),
    }
    if text_error:
        result["text_error"] = text_error
    if include_bytes:
        result["bytes_base64"] = base64.standard_b64encode(file_bytes).decode("ascii")
    return json.dumps(result)


def dispatch_email(name: str, args: dict) -> str:
    """Route an MCP email tool call. Returns a JSON string."""
    try:
        if name == "baker_email_search":
            return _search(args)
        if name == "baker_email_read":
            return _read(args)
        if name == "baker_email_attachment_read":
            return _attachment_read(args)
        return json.dumps({"error": f"unknown email tool: {name}"})
    except Exception as e:  # fault-tolerant: never raise to the MCP layer
        logger.error(f"dispatch_email({name}) failed: {e}")
        return json.dumps({"error": f"email tool failed: {e}"})
