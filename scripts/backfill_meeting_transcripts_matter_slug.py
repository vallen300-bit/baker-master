"""PLAUD_TRANSCRIPT_BY_MATTER_1 — retroactive matter_slug backfill for
meeting_transcripts.

Dry-run-by-default tool that proposes ``meeting_transcripts.matter_slug``
values for rows where the column is NULL, by calling the classifier
(``orchestrator.pipeline._match_matter_slug``) and resolving the matter_name
through ``kbl.slug_registry.normalize`` to a canonical slug.

Modeled on ``scripts/backfill_matter_slug.py`` (DEADLINE_MATTER_SLUG_BACKFILL_1).
CRITICAL DIFFERENCE: ``meeting_transcripts.id`` is TEXT (e.g. ``plaud_abc123``
or ``fireflies_xyz``), NOT INTEGER. The deadlines template casts ``cells[0]``
to int — that cast would drop every row here. Keep the id as ``str``.

Behavior:
  Default (no args) → DRY RUN: write proposal to
    /tmp/backfill_meeting_transcripts_proposal_<ts>.md
  ``--apply <path>``  → write mode: UPDATE rows per ratified file
    (3 safety rails + per-row SAVEPOINT, mirroring the deadlines pattern).

Safety rails on --apply:
  1. Ratified mapping file path required (positional after --apply).
  2. Mapping file must be <24h old (mtime check).
  3. Every M-section row must have non-empty proposed_slug.
  4. ``BAKER_BACKFILL_DRY_RUN_ONLY=1`` env-var override blocks --apply entirely.

Usage:
  python3 scripts/backfill_meeting_transcripts_matter_slug.py
  python3 scripts/backfill_meeting_transcripts_matter_slug.py --apply <ratified.md>

Pre-apply: AH1 verifies that baker-vault/slugs.yml has an alias mapping the
relevant matter_registry.matter_name (e.g. ``Hagenauer RG7``) to a canonical
slug (e.g. ``hagenauer-rg7``). Without the alias, Bucket M will be empty even
when the classifier matches — silent zero rows for the desk.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kbl import slug_registry  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("backfill_meeting_transcripts_matter_slug")

QUERY_LIMIT = 500
APPLY_STALENESS_SEC = 24 * 3600
DESC_TRUNCATE = 80


def _get_store():
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def _query_null_matter_slug() -> list[tuple]:
    """SELECT meeting_transcripts rows where matter_slug IS NULL.

    Returns rows of (id, title, full_transcript, source).
    """
    store = _get_store()
    conn = store._get_conn()
    if conn is None:
        raise RuntimeError("store._get_conn returned None — DB unreachable")
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT id, title, full_transcript, source
                FROM meeting_transcripts
                WHERE matter_slug IS NULL
                ORDER BY ingested_at DESC
                LIMIT %s
                """,
                (QUERY_LIMIT,),
            )
            rows = cur.fetchall()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            cur.close()
    finally:
        try:
            store._put_conn(conn)
        except Exception:
            pass
    return list(rows)


def _classify(rows: list[tuple]) -> tuple[list[dict], list[dict]]:
    """Return (bucket_M, bucket_U).

    M (Matched):   classifier returned a name + normalize resolved to canonical.
    U (Unmatched): classifier returned None OR normalize returned None.
    """
    from orchestrator.pipeline import _match_matter_slug

    store = _get_store()

    m_rows: list[dict] = []
    u_rows: list[dict] = []
    for row in rows:
        rid, title, body, src = row
        record = {
            "id": rid,  # TEXT — keep as str, do NOT cast to int
            "title": (title or "")[:DESC_TRUNCATE],
            "source_type": src or "",
            "matter_name_raw": None,
            "proposed_slug": None,
            "bucket_reason": "",
        }
        try:
            matter_name = _match_matter_slug(title or "", body or "", store)
        except Exception as e:
            record["bucket_reason"] = f"classifier raised: {e}"
            u_rows.append(record)
            continue
        record["matter_name_raw"] = matter_name
        if matter_name is None:
            record["bucket_reason"] = "classifier returned None (no match)"
            u_rows.append(record)
            continue
        canonical = slug_registry.normalize(matter_name)
        if canonical is None:
            record["bucket_reason"] = (
                f"matter_name {matter_name!r} does not resolve to a canonical "
                f"slug — check baker-vault/slugs.yml aliases"
            )
            u_rows.append(record)
            continue
        record["proposed_slug"] = canonical
        record["bucket_reason"] = f"classified → {canonical}"
        m_rows.append(record)
    return m_rows, u_rows


def _format_row(r: dict) -> str:
    raw = r["matter_name_raw"] or "—"
    prop = r["proposed_slug"] or "—"
    return (
        f"| {r['id']} | {r['title']} | {raw} → {prop} | "
        f"{r['source_type']} | {r['bucket_reason']} |"
    )


def _write_proposal(
    m_rows: list[dict],
    u_rows: list[dict],
    out_path: Path,
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    lines: list[str] = []
    lines.append(
        f"# Backfill proposal (meeting_transcripts.matter_slug) — generated {ts}"
    )
    lines.append("")
    lines.append(f"- Bucket M (Matched, auto-apply candidate): **{len(m_rows)} rows**")
    lines.append(f"- Bucket U (Unmatched, manual review):      **{len(u_rows)} rows**")
    lines.append("")
    lines.append("Director: ratify the M-section block as-is OR reply with adjustments.")
    lines.append("The ratified-mapping file is the input to `--apply`.")
    lines.append("")
    lines.append("**ID column is TEXT (e.g. plaud_abc, fireflies_xyz). Do not edit.**")
    lines.append("")
    for label, bucket in (("M (Matched)", m_rows), ("U (Unmatched)", u_rows)):
        lines.append(f"## Bucket {label} — {len(bucket)} rows")
        lines.append("")
        if not bucket:
            lines.append("_(empty)_")
            lines.append("")
            continue
        lines.append("| id | title | matter_name raw → canonical slug | source | reason |")
        lines.append("|---|---|---|---|---|")
        for r in bucket:
            lines.append(_format_row(r))
        lines.append("")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_ratified_mapping(path: Path) -> list[tuple[str, str]]:
    """Read the ratified-mapping markdown file. Pull rows from the Bucket M
    table. Return list of (id, proposed_slug). Raise on partials.

    CRITICAL: id is TEXT — do NOT cast to int. The deadlines template casts
    via ``int(cells[0])``; copying that cast would silently drop every
    transcripts row because transcript ids look like ``plaud_abc123``.
    """
    text = path.read_text(encoding="utf-8")
    out: list[tuple[str, str]] = []
    in_m_section = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## Bucket M"):
            in_m_section = True
            continue
        if line.startswith("## Bucket "):
            in_m_section = False
            continue
        if not in_m_section:
            continue
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5:
            continue
        # Skip header + separator
        if cells[0].lower() == "id" or set(cells[0]) <= {"-", ":"}:
            continue
        rid = cells[0].strip()  # TEXT id — do NOT int()
        if not rid:
            continue
        raw_arrow = cells[2]
        if "→" in raw_arrow:
            proposed = raw_arrow.split("→", 1)[1].strip()
        else:
            proposed = raw_arrow.strip()
        if not proposed or proposed == "—":
            raise RuntimeError(
                f"row id={rid!r} in ratified mapping has empty proposed_slug — "
                "every M-section row must have a canonical slug"
            )
        out.append((rid, proposed))
    return out


def _apply_updates(pairs: list[tuple[str, str]]) -> dict:
    """Run idempotent UPDATEs with per-row SAVEPOINT.

    Per-row SAVEPOINT lets the loop continue past a single mid-batch failure
    without rolling back prior successful UPDATEs (carry-forward from the
    deadlines script v3 fix).
    """
    affected = 0
    skipped = 0
    failed: list[dict] = []
    store = _get_store()
    conn = store._get_conn()
    if conn is None:
        raise RuntimeError("store._get_conn returned None — DB unreachable")
    try:
        cur = conn.cursor()
        try:
            for rid, slug in pairs:
                cur.execute("SAVEPOINT row_sp")
                try:
                    cur.execute(
                        """
                        UPDATE meeting_transcripts
                        SET matter_slug = %s
                        WHERE id = %s
                          AND matter_slug IS NULL
                        """,
                        (slug, rid),
                    )
                    if cur.rowcount > 0:
                        affected += cur.rowcount
                        cur.execute("RELEASE SAVEPOINT row_sp")
                        logger.info("UPDATE id=%s matter_slug=%s OK", rid, slug)
                    else:
                        skipped += 1
                        cur.execute("RELEASE SAVEPOINT row_sp")
                        logger.info(
                            "SKIP id=%s (already populated or row missing)", rid,
                        )
                except Exception as e:
                    cur.execute("ROLLBACK TO SAVEPOINT row_sp")
                    failed.append({"id": rid, "error": str(e)})
                    logger.warning("UPDATE id=%s FAILED: %s", rid, e)
            try:
                conn.commit()
            except Exception as e:
                logger.warning("commit failed: %s", e)
        finally:
            cur.close()
    finally:
        try:
            store._put_conn(conn)
        except Exception:
            pass
    return {"affected": affected, "skipped": skipped, "failed": failed}


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Backfill meeting_transcripts.matter_slug via classifier "
            "(dry-run by default)"
        ),
    )
    p.add_argument(
        "--apply", metavar="RATIFIED_FILE",
        help="Path to Director-ratified proposal file; runs UPDATEs. "
             "Default is DRY RUN (no --apply).",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    if args.apply:
        # Safety rail 4: env-var kill switch
        if os.environ.get("BAKER_BACKFILL_DRY_RUN_ONLY") == "1":
            logger.error("BAKER_BACKFILL_DRY_RUN_ONLY=1 — --apply blocked")
            return 2
        ratified_path = Path(args.apply)
        # Safety rail 1: ratified file must exist
        if not ratified_path.is_file():
            logger.error("ratified file not found: %s", ratified_path)
            return 2
        # Safety rail 2: 24h staleness guard
        age = time.time() - ratified_path.stat().st_mtime
        if age > APPLY_STALENESS_SEC:
            logger.error(
                "ratified file is %.1fh old (>24h staleness limit); regenerate proposal",
                age / 3600,
            )
            return 2
        # Safety rail 3: parser enforces no partial rows
        pairs = _parse_ratified_mapping(ratified_path)
        if not pairs:
            logger.error(
                "no rows found in Bucket M of %s — nothing to apply",
                ratified_path,
            )
            return 2
        logger.info("APPLY mode: %d rows from %s", len(pairs), ratified_path)
        summary = _apply_updates(pairs)
        logger.info(
            "APPLY summary: affected=%d skipped=%d failed=%d",
            summary["affected"], summary["skipped"], len(summary["failed"]),
        )
        return 0 if not summary["failed"] else 1

    # DRY RUN
    rows = _query_null_matter_slug()
    m_rows, u_rows = _classify(rows)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(f"/tmp/backfill_meeting_transcripts_proposal_{ts}.md")
    _write_proposal(m_rows, u_rows, out_path)
    logger.info(
        "DRY RUN complete: %d total | M=%d U=%d → %s",
        len(rows), len(m_rows), len(u_rows), out_path,
    )
    print(str(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
