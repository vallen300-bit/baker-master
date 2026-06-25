"""M365_GRAPH_ATTACHMENT_ID_FORM_FIX_1 — targeted attachment backfill.

Re-fetches and persists attachments for a known list of Graph message ids whose
attachments were silently dropped at ingest because the message id is in
immutable (AAQk / base64url) form and the by-id attachment fetch was issued
WITHOUT Prefer: IdType="ImmutableId" (now fixed in triggers/graph_mail_trigger).

Reuses the FIXED ``_capture_graph_attachments`` path verbatim, so the backfill
and the live poller can never diverge. Auth reuses the working Graph app-token
path (GraphClient.is_ready() is the gate) — so this MUST run on the deployed
env that holds the M365 app cert; on a B-code box GraphClient is dormant and the
script refuses to run (fail-loud, no silent no-op).

PROD WRITE — gated. Dry-run by default; pass --execute to persist. The 6
load-bearing lilienmatt/financing-aukera docs (n39 n42 n44 n46 n54 n55) are
supplied by lead at G4 (full ids relayed on the bus); pass them via --ids or
--ids-file. Nothing is written without BOTH --execute AND lead's explicit go.

Run (dry):  python3 scripts/backfill_aaqk_attachments.py --ids "<id1>,<id2>,..."
Run (live): python3 scripts/backfill_aaqk_attachments.py --ids-file ids.txt --execute
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
logger = logging.getLogger("backfill_aaqk_attachments")


def _load_ids(args) -> list[str]:
    ids: list[str] = []
    if args.ids:
        ids.extend(p.strip() for p in args.ids.split(",") if p.strip())
    if args.ids_file:
        text = Path(args.ids_file).read_text(encoding="utf-8")
        ids.extend(line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#"))
    # de-dup, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def run(ids: list[str], execute: bool) -> int:
    """Returns process exit code (0 ok, non-zero on any per-id failure)."""
    if not ids:
        logger.error("no message ids supplied (use --ids or --ids-file)")
        return 2

    import triggers.graph_mail_trigger as gmt

    mode = "EXECUTE (persisting)" if execute else "DRY-RUN (no writes)"
    logger.info("AAQk attachment backfill — %s — %d message id(s)", mode, len(ids))

    # Dry-run is read-only and needs no live client — preview id forms anywhere.
    if not execute:
        for mid in ids:
            form = "immutable" if gmt._is_immutable_message_id(mid) else "standard"
            logger.info("[dry] id_form=%s would re-capture attachments for %s", form, mid[:24] + "...")
        return 0

    from kbl.graph_client import GraphClient
    from config.settings import GraphConfig

    client = GraphClient(GraphConfig())
    if not client.is_ready():
        # Fail-loud: the cert lives on the deployed env. Never pretend success.
        logger.error(
            "GraphClient is DORMANT here (is_ready=False) — the M365 app cert is "
            "deployed-env only. Run this backfill on the deployed env, not a "
            "B-code box. Nothing attempted."
        )
        return 3

    failures = 0
    for mid in ids:
        form = "immutable" if gmt._is_immutable_message_id(mid) else "standard"
        before = gmt.attachment_fetch_failures()
        # hasAttachments=True forces the capture path; a true-empty doc simply
        # stores 0 and is surfaced as benign by the capture helper.
        stored = gmt._capture_graph_attachments(client, {"id": mid, "hasAttachments": True})
        after = gmt.attachment_fetch_failures()
        if after > before:
            failures += 1
            logger.error("id_form=%s FETCH FAILED for %s — see surfaced ERROR above", form, mid[:24] + "...")
        else:
            logger.info("id_form=%s stored=%d for %s", form, stored, mid[:24] + "...")

    if failures:
        logger.error("backfill finished with %d/%d failure(s)", failures, len(ids))
        return 1
    logger.info("backfill finished: %d id(s) processed, 0 failures", len(ids))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Targeted AAQk attachment backfill (gated prod write).")
    ap.add_argument("--ids", help="comma-separated Graph message ids")
    ap.add_argument("--ids-file", help="file with one Graph message id per line (# comments ok)")
    ap.add_argument("--execute", action="store_true", help="persist (default: dry-run)")
    args = ap.parse_args()
    return run(_load_ids(args), args.execute)


if __name__ == "__main__":
    raise SystemExit(main())
