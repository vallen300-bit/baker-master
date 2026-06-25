"""M365_GRAPH_ATTACHMENT_ID_FORM_FIX_1 — conversationId-aware attachment backfill.

CORRECTED after the live Render probe (#4311) disproved the immutable-id theory:
the 6 AAQk values are CONVERSATIONIDs, not message ids. GET /messages/{id} can't
address a message by a conversation id (400 ErrorInvalidOperation), and
translateExchangeIds is 403 (app-perm gap) — so neither the Prefer header nor a
fallback could ever have worked.

Keying chain (the real defect this resolves):
- email_messages.message_id = thread_id = conversationId   (email_trigger.py:933 — all sources)
- baker_email_attachment_read(message_id=X) reads attachment_store WHERE message_id=X
- _capture_graph_attachments persisted under the REAL per-message id (m['id'])
  => attachments were keyed by a value the read tool never queries.

This backfill, per conversationId:
  1. resolve real messages:  GET /users/{u}/messages?$filter=conversationId eq '{cid}'
  2. for each message with hasAttachments: fetch by its REAL id (addressable),
  3. persist EACH attachment under the CONVERSATIONID, by REUSING the live
     _capture_graph_attachments path (which now stores under thread_id =
     conversationId-or-id, Option (a) #4317) — one code path, no divergence —
     so baker_email_attachment_read(message_id=conversationId), the id the desk
     holds from baker_email_search, finds them.

PROD WRITE — gated; dry-run by default; --execute requires a live GraphClient
(deployed baker-master env) and refuses on a dormant box. Run-path + GO owned by
lead. Keying ratified Option (a) (#4317).

Run (dry):  python3 scripts/backfill_conversation_attachments.py --ids '<cid1>,<cid2>'
Run (live): python3 scripts/backfill_conversation_attachments.py --ids-file cids.txt --execute
"""
from __future__ import annotations

import argparse
import logging
import sys
from urllib.parse import quote
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_conversation_attachments")



def _load_ids(args) -> list[str]:
    ids: list[str] = []
    if args.ids:
        ids.extend(p.strip() for p in args.ids.split(",") if p.strip())
    if args.ids_file:
        ids.extend(
            ln.strip() for ln in Path(args.ids_file).read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")
        )
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _resolve_messages(client, conv_id: str) -> list | None:
    """List ALL messages in a conversation. Returns list (maybe empty) or None on failure.

    OData string literal: single quotes wrap the value; embedded single quotes are
    doubled (none expected in a Graph conversationId). requests URL-encodes params.

    Follows @odata.nextLink to exhaustion (G2 F2): live threads exceed the 50/page
    cap, so reading only page 1 would SILENTLY miss messages -> missed attachments
    (the silent-skip class). A None mid-pagination returns None (surfaced as a
    resolve FAILURE, never a silent truncation).
    """
    safe_cid = conv_id.replace("'", "''")
    user = quote(client.cfg.mail_user, safe="")
    page = client.get(
        f"/users/{user}/messages",
        params={
            "$filter": f"conversationId eq '{safe_cid}'",
            "$select": "id,hasAttachments,subject",
            "$top": 50,
        },
    )
    if page is None:
        return None
    messages = list(page.get("value", []))
    nxt = page.get("@odata.nextLink")
    guard = 0
    while nxt and guard < 50:                 # bounded pagination
        guard += 1
        page = client.get_url(nxt)
        if page is None:                       # mid-pagination failure -> fail loud, don't truncate
            return None
        messages.extend(page.get("value", []))
        nxt = page.get("@odata.nextLink")
    return messages


# --------------------------------------------------------------------------- #
# BAKER_M365_LARGE_ATTACHMENT_FETCH_1 — message-id byte-residue backfill mode.
#
# The 2,618 byte-empty graph rows are storage='metadata_only' keyed by their
# per-message AAMk id (every one matches email_messages.message_id — prod probe
# #4447, confirmed by lead #4448). The fix is NOT the conversationId-insert path
# above (that would orphan them + the count wouldn't drop); it is an UPDATE in
# place of each existing row by its exact id:
#   load byte-empty rows -> group by message_id -> GET /messages/{mid}/attachments
#   -> match each row to a Graph attachment by filename -> /attachments/{id}/$value
#   -> route >5MiB to R2 / <=5MiB to Neon -> UPDATE that row id.
# Idempotent: only byte-empty rows are loaded, so a re-run never refetches a
# completed row. Self-limiting by --byte-budget so each Render one-off is bounded.
# --------------------------------------------------------------------------- #

def _load_byte_empty_rows(msg_ids: list[str] | None = None, limit: int | None = None) -> list[dict]:
    """Byte-empty graph rows eligible for byte recovery (UPDATE-in-place).

    storage='metadata_only', data NULL, object_key NULL, size_bytes > 0 (the 10
    true-empty size=0 rows are excluded). Optional message_id filter (chunked
    Render jobs). Read-only. Returns [] on failure (fault-tolerant)."""
    from kbl.db import get_conn
    sql = (
        "SELECT id, message_id, filename, mime_type, size_bytes "
        "FROM email_attachments "
        "WHERE source='graph' AND storage='metadata_only' "
        "AND data IS NULL AND object_key IS NULL AND size_bytes > 0"
    )
    params: list = []
    if msg_ids:
        sql += " AND message_id = ANY(%s)"
        params.append(msg_ids)
    sql += " ORDER BY message_id, size_bytes"
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params) if params else None)
                rows = cur.fetchall()
        return [
            {"id": r[0], "message_id": r[1], "filename": r[2],
             "mime_type": r[3], "size_bytes": r[4]}
            for r in rows
        ]
    except Exception as e:
        logger.error("byte-empty row load FAILED: %s", e)
        return []


def _match_attachment(atts: list[dict], row: dict) -> dict | None:
    """Match a byte-empty row to a Graph attachment by filename; disambiguate
    same-filename collisions by closest recorded size."""
    want = row.get("filename") or ""
    cands = [a for a in atts if (a.get("name") or "") == want]
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]
    target_size = row.get("size_bytes") or 0
    return min(cands, key=lambda a: abs((a.get("size") or 0) - target_size))


def run_missing(execute: bool, msg_ids: list[str] | None = None,
                byte_budget: int | None = None) -> int:
    """Recover bytes for byte-empty graph rows by UPDATE-in-place (message-id mode).

    ``byte_budget`` (bytes) bounds one invocation: stop after the planned fetch
    size crosses it (re-run drains the rest; idempotent). 0/None = unbounded.
    """
    rows = _load_byte_empty_rows(msg_ids)
    if not rows:
        logger.info("no byte-empty graph rows to recover (already drained or none).")
        return 0

    from collections import defaultdict
    by_msg: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_msg[r["message_id"]].append(r)
    logger.info("byte-residue backfill — %s — %d row(s) across %d message(s)%s",
                "EXECUTE" if execute else "DRY-RUN", len(rows), len(by_msg),
                f", byte_budget={byte_budget}" if byte_budget else "")

    if not execute:
        planned = sum(r.get("size_bytes") or 0 for r in rows)
        logger.info("[dry] would fetch ~%d byte(s) across %d row(s) via $value -> "
                    "route >5MiB R2 / <=5MiB Neon -> UPDATE in place.", planned, len(rows))
        return 0

    import triggers.graph_mail_trigger as gmt
    from kbl.graph_client import GraphClient
    from config.settings import GraphConfig
    from kbl.attachment_store import update_attachment_payload, delete_empty_attachment

    client = GraphClient(GraphConfig())
    if not client.is_ready():
        logger.error("GraphClient DORMANT (is_ready=False) — run on deployed baker-master env. Nothing attempted.")
        return 3

    updated = duplicate = skipped = failed = 0
    fetched_bytes = 0
    for mid, group in by_msg.items():
        if byte_budget and fetched_bytes >= byte_budget:
            logger.info("byte_budget %d reached (fetched %d) — stopping; re-run to continue.",
                        byte_budget, fetched_bytes)
            break
        page, _imm = gmt._fetch_attachments_page(client, mid)
        if page is None:
            failed += len(group)
            logger.error("message %s: attachment list FAILED (surfaced) — %d row(s) deferred",
                         mid[:24] + "...", len(group))
            continue
        atts = [a for a in page.get("value", []) if not a.get("isInline")]
        for row in group:
            att = _match_attachment(atts, row)
            if att is None:
                skipped += 1
                logger.warning("row id=%s (%s): no matching Graph attachment — skipped",
                               row["id"], row.get("filename"))
                continue
            raw = gmt.fetch_attachment_raw_value(client, mid, att.get("id"), max_retries=5)
            if raw is None:
                failed += 1
                logger.error("row id=%s (%s): $value fetch FAILED (surfaced)",
                             row["id"], row.get("filename"))
                continue
            payload, ct = raw
            fetched_bytes += len(payload)
            status = update_attachment_payload(
                row["id"], "graph", payload, mime_type=ct,
                provider_attachment_id=att.get("id"),
            )
            if status == "updated":
                updated += 1
            elif status == "duplicate":
                # Real bytes already on a twin row for this message — remove the
                # now-redundant empty row so residue converges to ~0.
                delete_empty_attachment(row["id"])
                duplicate += 1
            else:
                skipped += 1
                logger.warning("row id=%s: update status=%s", row["id"], status)

    logger.info("byte-residue backfill done: updated=%d duplicate-removed=%d skipped=%d failed=%d "
                "fetched~%d bytes", updated, duplicate, skipped, failed, fetched_bytes)
    return 1 if failed else 0


def run(ids: list[str], execute: bool) -> int:
    if not ids:
        logger.error("no conversationIds supplied (--ids / --ids-file)")
        return 2

    mode = "EXECUTE (persisting)" if execute else "DRY-RUN (no writes)"
    logger.info("conversationId attachment backfill — %s — %d conversation(s)", mode, len(ids))

    if not execute:
        for cid in ids:
            logger.info("[dry] would resolve conversation %s -> messages -> attachments "
                        "(stored under conversationId via live capture path)", cid[:24] + "...")
        return 0

    import triggers.graph_mail_trigger as gmt
    from kbl.graph_client import GraphClient
    from config.settings import GraphConfig

    client = GraphClient(GraphConfig())
    if not client.is_ready():
        logger.error("GraphClient DORMANT (is_ready=False) — run on deployed baker-master env. Nothing attempted.")
        return 3

    failures = 0
    for cid in ids:
        msgs = _resolve_messages(client, cid)
        if msgs is None:
            failures += 1
            logger.error("conversation %s: message resolve FAILED (surfaced)", cid[:24] + "...")
            continue
        with_att = [m for m in msgs if m.get("hasAttachments")]
        logger.info("conversation %s: %d message(s), %d with attachments",
                    cid[:24] + "...", len(msgs), len(with_att))
        conv_stored = 0
        before = gmt.attachment_fetch_failures()
        for m in with_att:
            # Reuse the live capture path: inject the conversationId so the SAME
            # thread_id keying (Option a) is applied — fetch by real id, store
            # under conversationId. No divergent fetch/decode/store logic here.
            conv_stored += gmt._capture_graph_attachments(
                client, {"id": m["id"], "conversationId": cid, "hasAttachments": True}
            )
        if gmt.attachment_fetch_failures() > before:
            failures += 1
            logger.error("conversation %s: one or more attachment fetches FAILED (surfaced above)",
                         cid[:24] + "...")
        else:
            logger.info("conversation %s: stored %d attachment(s) under conversationId key",
                        cid[:24] + "...", conv_stored)

    if failures:
        logger.error("backfill finished with %d/%d conversation failure(s)", failures, len(ids))
        return 1
    logger.info("backfill finished: %d conversation(s), 0 failures", len(ids))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Graph attachment backfill (gated prod write).")
    ap.add_argument("--ids", help="comma-separated conversationIds (conversation mode)")
    ap.add_argument("--ids-file", help="file with one conversationId per line (# comments ok)")
    ap.add_argument("--missing", action="store_true",
                    help="byte-residue mode: UPDATE-in-place all byte-empty graph rows "
                         "(message-id keyed, R2/Neon routed). Supersedes conversation mode.")
    ap.add_argument("--msg-ids-file",
                    help="restrict --missing to message_ids in this file (one/line) — chunked Render jobs")
    ap.add_argument("--byte-budget", type=int, default=0,
                    help="--missing: stop after ~N planned bytes this run (0=unbounded). "
                         "Bounds each Render one-off; re-run drains the rest (idempotent).")
    ap.add_argument("--execute", action="store_true", help="persist (default: dry-run)")
    args = ap.parse_args()
    if args.missing or args.msg_ids_file:
        msg_ids = None
        if args.msg_ids_file:
            msg_ids = [
                ln.strip() for ln in Path(args.msg_ids_file).read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.startswith("#")
            ]
        return run_missing(args.execute, msg_ids=msg_ids, byte_budget=args.byte_budget or None)
    return run(_load_ids(args), args.execute)


if __name__ == "__main__":
    raise SystemExit(main())
