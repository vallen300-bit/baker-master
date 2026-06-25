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
    """List messages in a conversation. Returns list (maybe empty) or None on fetch failure.

    OData string literal: single quotes wrap the value; embedded single quotes are
    doubled (none expected in a Graph conversationId). requests URL-encodes params.
    """
    safe_cid = conv_id.replace("'", "''")
    page = client.get(
        f"/users/{client.cfg.mail_user}/messages",
        params={
            "$filter": f"conversationId eq '{safe_cid}'",
            "$select": "id,hasAttachments,subject",
            "$top": 50,
        },
    )
    if page is None:
        return None
    return page.get("value", [])


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
    ap = argparse.ArgumentParser(description="conversationId-aware attachment backfill (gated prod write).")
    ap.add_argument("--ids", help="comma-separated conversationIds")
    ap.add_argument("--ids-file", help="file with one conversationId per line (# comments ok)")
    ap.add_argument("--execute", action="store_true", help="persist (default: dry-run)")
    args = ap.parse_args()
    return run(_load_ids(args), args.execute)


if __name__ == "__main__":
    raise SystemExit(main())
